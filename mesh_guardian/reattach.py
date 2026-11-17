# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Parent search on request, for the end devices whose parent link is poor.

A Thread end device picks its parent when it attaches and many firmwares keep
it as long as the link holds, even when a much better router is in range.
Matter has no "find a better parent" command, but a node accepts to be told to
connect to a Thread network. Asked to connect to the network it is already on,
the node restarts its Thread interface and attaches again, which makes it
choose a parent among the routers it hears now. It does not reboot and its
configuration is unchanged.

Sequence, on endpoint 0, under the fail-safe of General Commissioning:
  ArmFailSafe -> ConnectNetwork (Network Commissioning, same network id)
  -> CommissioningComplete.
If the node does not confirm, the fail-safe is disarmed (or expires on its
own) and the node keeps the network configuration it had.

Only end devices are concerned (a router has no parent), and only those whose
link is weak when read just before (same rule as the table and the advice: link
quality 1): a node with a good link can end up on a weaker parent, and there is
no way back to the previous one. Nothing is sent
until the "Find better parents" button is pressed.

Recovery attempt (recover_node): the same connect command, sent to a Thread node
that is unavailable, router or end device. Its last known network id is used
(it cannot be read). Nothing to lose: the node is already out.
"""
import base64
import logging
import threading
import time

from i18n import t, tn
from store import load_json, save_json
from nodetable import heard_map, heard_of, nb_rssi
from advice import weak_link

LOG = logging.getLogger("mg.reattach")
GOOD_GAIN = 6         # dB: gain from which the new link counts as better (same as the advice)
FAILSAFE_S = 120      # s: the node goes back to its configuration by itself after this time
SETTLE_S = 25         # s: time left to the node to attach before its new link is read
FOLLOW_EVERY_S = 30   # s: result not known yet: the node and its parent are read again this often...
FOLLOW_FOR_S = 300    # s: ...for this long
RECOVER_WAIT_S = 120  # s: recovery attempt: time left to the Matter Server to reach an unavailable node
CLOSE_TRIES = 3       # recovery attempt: tries to close the fail-safe of a node that is back...
CLOSE_EVERY_S = 10    # s: ...this far apart
FABRIC_VENDORS = {4937: "Apple Home", 24582: "Google Home", 4362: "SmartThings", 4631: "Amazon Alexa"}   # fabric vendor id -> name shown
RESETS_FILE = "/data/reset_nodes.json"
RESETS_KEEP_S = 7 * 86400   # s: the old identity of a reset node is not reported as unknown for this long
RESULT_KEEP_S = 900   # s: a result stays in the table this long (the page shows it when it arrives)
END_DEVICE_ROLES = (2, 3, 4)   # sleepy end device, end device, REED (a full end device attached as a child)
CONNECT_NETWORK = 6   # Network Commissioning command id
# PROVISIONAL (2.12.0, trial asked by the user): the same command on a router. A router has no
# parent and picks its routes by itself, so no better link is expected; the trial is to see what
# it does on a router that answers badly. To go back, remove:
# - here: ROUTER_ROLES, ROUTER_SETTLE_S, ROUTER_POLL_S, _row, _first_link, _link_text, _router,
#   _follow_router and the "if row is None" block of run_node;
# - i18n.py: the FR texts "{node}: Thread restart of a router (trial)…", "…of the leader (trial)…",
#   "{node}: Thread restarted, waiting for the result…", "…router again…", "…still an end device…";
# - web/index.html: canParent back to `net(r) === "thread" && !isRouter(r) && r.role !== "leader"`,
#   the "restarted" branches of runAction, the texts a_parent_confirm_router, a_parent_confirm_leader
#   (EN and FR) and their use in runAction;
# - DOCS.md: the trial in "Actions on one node" and in "Find better parents"; README: "on a router
#   it restarts its Thread interface, a trial"; CHANGELOG: an entry saying it was removed.
ROUTER_ROLES = (5, 6)  # Thread routing roles "router" and "leader" (the leader too, asked by the user: the page warns)
ROUTER_SETTLE_S = 180  # s: a router attaches as a child first and becomes a router again within 2 minutes
ROUTER_POLL_S = 20     # s: its role is read this often meanwhile, the result is given as soon as it is a router again
PATHS = ["0/53/1", "0/53/7", "0/51/0", "0/49/1", "0/49/65529"]   # table and addresses read together: same moment


PROXY_SETTLE_S = 5    # s: time left to the Matter Server to hear the announcement made in a node's place
BACK_WAIT_S = 60      # s: announced in its place on its current address: time left to come back before anything else
AUTO_EVERY_S = 60     # s: automatic recovery by the Thread diagnostic: candidates looked for this often
AUTO_NODE_S = 1800    # s: at most one automatic diagnostic per node in this time
AUTO_PER_HOUR = 5     # nodes at most per hour (automatic)
AUTO_HEARD_S = 900    # s: only for a node a neighbor heard this recently


def _ago(s):
    s = max(0, int(s))
    return f"{s} s" if s < 90 else f"{round(s / 60)} min"


def ext_of(attrs):
    """Extended address (radio address) of a Thread node from its network interfaces (0/51/0)."""
    for itf in attrs.get("0/51/0") or []:
        if isinstance(itf, dict) and itf.get("7") == 4 and itf.get("4"):
            try:
                raw = base64.b64decode(itf["4"])
            except Exception:  # noqa: BLE001
                continue
            if len(raw) == 8:
                return int.from_bytes(raw, "big")
    return None


def mleid_of(attrs):
    """Mesh-local EID of a Thread node (its stable address inside the mesh, whatever the OMR prefix):
    the address of its Thread interface (0/51/0, field 6) in the mesh-local prefix (0/53/5), not an
    RLOC/ALOC (interface id 0000:00ff:fe00:xxxx). Known from the last values of the node, also
    when it is unavailable. None when not found."""
    import ipaddress   # noqa: PLC0415
    raw = attrs.get("0/53/5")
    try:
        pre = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw or b"")
    except Exception:  # noqa: BLE001
        return None
    pre = pre[1:9] if len(pre) == 9 else pre[:8]   # ipv6pre: [length in bits] + prefix, or the 8 bytes alone
    if len(pre) != 8:
        return None
    for itf in attrs.get("0/51/0") or []:
        if not isinstance(itf, dict) or itf.get("7") != 4:
            continue
        for a in itf.get("6") or []:
            try:
                b = base64.b64decode(a)
            except Exception:  # noqa: BLE001
                continue
            if len(b) == 16 and b[:8] == pre and b[8:14] != bytes.fromhex("000000fffe00"):
                return str(ipaddress.IPv6Address(b))
    return None


def _field(res, name, key):
    """Field of a command answer: by name (Matter Server) or by numeric id."""
    if not isinstance(res, dict):
        return None
    return res.get(name, res.get(key))


def parent_link(table):
    """Link of an end device with its parent in a neighbor table (0/53/7):
    {"rloc", "lqi", "rssi"}, or None. Entries only overheard (LQI 0) are ignored, except
    the only entry of the table: an end device that keeps one neighbor keeps its parent,
    and its link quality 0 is a measure (no margin above the noise)."""
    entries = [nb for nb in table or [] if isinstance(nb, dict) and nb.get("13") is not True
               and nb_rssi(nb) is not None]
    for nb in entries:
        if nb.get("5"):
            return {"rloc": nb.get("2"), "lqi": nb["5"], "rssi": nb_rssi(nb)}
    if len(entries) == 1 and entries[0].get("5") is not None:
        nb = entries[0]
        return {"rloc": nb.get("2"), "lqi": nb["5"], "rssi": nb_rssi(nb)}
    return None


def is_poor(link):
    return bool(link) and weak_link(link["rssi"], link["lqi"])


def connected_network(networks):
    """Id of the only network the node knows and is connected to, or None."""
    if not isinstance(networks, list) or len(networks) != 1 or not isinstance(networks[0], dict):
        return None
    net = networks[0]
    connected = net.get("1", net.get("connected"))
    return net.get("0", net.get("networkID")) if connected is True else None


def verdict(before, after):
    """better / worse / similar, from the link shown in the table before and after:
    (rssi, lqi). The link quality decides first, then the RSSI."""
    (rssi_b, lqi_b), (rssi_a, lqi_a) = before, after
    if lqi_a is not None and lqi_b is not None and lqi_a != lqi_b:
        return "better" if lqi_a > lqi_b else "worse"
    if rssi_a is not None and rssi_b is not None:
        gain = rssi_a - rssi_b
        return "better" if gain >= GOOD_GAIN else "worse" if gain <= -GOOD_GAIN else "similar"
    return "similar"



class NoAnswer(Exception):
    """The node did not answer the connect command (not a refusal)."""

class Reattach:
    def __init__(self, watch, healer):
        self.w = watch
        self.h = healer
        self.live = None          # live copy of the Matter Server cache, plugged in by watcher
        self.advisor = None       # radio advice: told which nodes were asked to move
        self.table = None         # node table: the link shown to the user (weakest direction)
        self.busy = threading.Lock()
        self.last = {"date": None, "checked": 0, "poor": 0, "better": 0, "nodes": []}
        self.results = {}         # node hex -> {"state": "pending" | "done", "text", "at"} of the last search
        self.recovering = set()   # node hex of the recovery attempts still followed
        self.resets = {}          # node hex -> time of its reset with the Reset button (its old identity is announced a while)
        data = load_json(RESETS_FILE, {})
        self.resets = {k: v for k, v in data.items() if time.time() - v < RESETS_KEEP_S} if isinstance(data, dict) else {}

    def was_reset(self, node_id):
        """True for the id (int) of a node reset with the Reset button in the last days."""
        at = self.resets.get(f"{node_id:016X}") if isinstance(node_id, int) else None
        return bool(at) and time.time() - at < RESETS_KEEP_S

    def result_of(self, nid):
        """Last parent search of a node for the table, while it is recent."""
        r = self.results.get(nid)
        return r if r and time.time() - r["at"] < RESULT_KEEP_S else None

    # ------------------------------------------------------------ Matter Server
    def _read(self, node_id):
        res = self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": PATHS}, timeout=60)
        return res if isinstance(res, dict) else {}

    def _command(self, node_id, cluster, name, payload, timeout=90):
        return self.h.matter_command("device_command", {"node_id": node_id, "endpoint_id": 0, "cluster_id": cluster,
                                                        "command_name": name, "payload": payload}, timeout=timeout)

    def _reattach(self, node_id, network):
        """Ask the node to connect again to its own network. Raises if it refuses; raises
        NoAnswer if it does not answer the connect command (it is attaching again: no answer
        until it is attached, longer than the Matter Server waits for some nodes)."""
        res = self._command(node_id, 48, "ArmFailSafe", {"expiryLengthSeconds": FAILSAFE_S, "breadcrumb": 1})
        if _field(res, "errorCode", "0") != 0:
            raise RuntimeError(f"ArmFailSafe: {res}")
        try:
            try:
                res = self._command(node_id, 49, "ConnectNetwork", {"networkID": network, "breadcrumb": 2})
            except Exception as err:  # noqa: BLE001
                if isinstance(err, TimeoutError) or any(w in str(err).lower() for w in ("abort", "timeout", "timed out")):
                    # silence is not a refusal: the node may be attaching. The fail-safe is
                    # left armed (it brings the node back by itself if it fails)
                    raise NoAnswer(str(err)) from err
                raise
            if _field(res, "networkingStatus", "0") != 0:
                raise RuntimeError(f"ConnectNetwork: {res}")
            res = self._command(node_id, 48, "CommissioningComplete", {})
            if _field(res, "errorCode", "0") != 0:
                raise RuntimeError(f"CommissioningComplete: {res}")
        except NoAnswer:
            raise
        except Exception:
            try:   # disarm now rather than leave the node 2 minutes under fail-safe
                self._command(node_id, 48, "ArmFailSafe", {"expiryLengthSeconds": 0, "breadcrumb": 0}, timeout=30)
            except Exception as err:  # noqa: BLE001
                LOG.debug("disarm fail-safe of %s: %s", node_id, err)
            raise

    # ------------------------------------------------------------ campaign
    def _targets(self):
        """Available Thread end devices: [(node hex, name, area)]. Roles come from the values
        already received; the link itself is read from the node just before acting."""
        if self.live and self.live.connected:
            nodes = self.live.snapshot()
        else:
            nodes = self.h.matter_command("get_nodes", {}, timeout=120)
        if not isinstance(nodes, list):
            raise RuntimeError("unexpected get_nodes answer")
        with self.h.lock:
            ha = {k: dict(v) for k, v in self.h.nodes.items()}
        out = []
        for node in nodes:
            nid = f"{int(node.get('node_id', 0)):016X}"
            if (node.get("attributes") or {}).get("0/53/1") not in END_DEVICE_ROLES or node.get("available") is False:
                continue
            n = ha.get(nid) or {}
            if n and not n.get("available", True):
                continue
            out.append((nid, n.get("name") or f"0x{nid.lstrip('0')}", n.get("area", "?")))
        return sorted(out, key=lambda x: x[1])

    def _view(self, nid, read_parent=False):
        """(parent name, rssi, lqi) of a node as the table shows them (weakest direction of
        the link). read_parent: read the neighbor table of the parent first (just after a move)."""
        if not self.table:
            return None, None, None
        rid = f"0x{nid.lstrip('0') or '0'}"
        try:
            self.table.cache_t = 0
            rows = self.table.get(force=True).get("rows") or []
            row = next((r for r in rows if r.get("id") == rid), {})
            if read_parent and row.get("parent"):
                par = next((r for r in rows if r.get("name") == row["parent"]), None)
                if par:
                    pid = f"{int(par['id'], 16):016X}"
                    res = self.h.matter_command("read_attribute", {"node_id": int(pid, 16), "attribute_path": "0/53/7"}, timeout=30)
                    table = res.get("0/53/7") if isinstance(res, dict) else None
                    if isinstance(table, list) and self.live:
                        self.live.set_attribute(pid, "0/53/7", table)
                    self.table.cache_t = 0
                    row = next((r for r in self.table.get(force=True).get("rows") or [] if r.get("id") == rid), row)
            return row.get("parent"), row.get("rssi"), row.get("lqi")
        except Exception as err:  # noqa: BLE001
            LOG.debug("table view of %s: %s", nid, err)
            return None, None, None

    def _one(self, nid, name, area, force=False):
        """Read the link of one node and, if it is poor, make it look for a parent.
        Returns None (nothing to do) or the result (dict)."""
        node_id = int(nid, 16)
        attrs = self._read(node_id)
        before = parent_link(attrs.get("0/53/7"))
        if self.live and isinstance(attrs.get("0/53/7"), list):
            self.live.set_attribute(nid, "0/53/7", attrs["0/53/7"])
            if isinstance(attrs.get("0/51/0"), list):   # its RLOC16, so its parent: from the same moment
                self.live.set_attribute(nid, "0/51/0", attrs["0/51/0"])
            self.live.note_contact(nid, src="read")
        parent_before, rssi_before, lqi_before = self._view(nid)
        # same rule as the table and the advice, on the link the table shows
        poor = weak_link(rssi_before, lqi_before) if (rssi_before is not None or lqi_before is not None) else is_poor(before)
        if attrs.get("0/53/1") not in END_DEVICE_ROLES or not before or not (force or poor):
            return None
        if not force and not parent_before:
            return None   # no parent in the table (a router, whatever its reported role): nothing to search
        if rssi_before is None and lqi_before is None:   # not in the table yet: the link read on the node
            rssi_before, lqi_before = before["rssi"], before["lqi"]
        row = {"node": name, "area": area, "rssi_before": rssi_before, "lqi_before": lqi_before,
               "rloc_before": before["rloc"], "parent_before": parent_before}
        network = connected_network(attrs.get("0/49/1"))
        if network is None or CONNECT_NETWORK not in (attrs.get("0/49/65529") or []):
            return row | {"result": "unsupported"}
        self.w.emit("reattach_node", t("{node}: looking for a better parent", node=name, area=area),
                    node=name, rssi=before["rssi"], lqi=before["lqi"])
        if self.advisor:
            self.advisor.forced[name] = time.time()
        try:
            self._reattach(node_id, network)
        except NoAnswer as err:
            LOG.debug("parent search of %s: no answer to the connect command (%s)", name, err)
            if not self.w.stop.wait(SETTLE_S):
                try:   # attached again: close the fail-safe as after an answer (it reverts by itself otherwise)
                    self._command(node_id, 48, "CommissioningComplete", {}, timeout=30)
                except Exception as err2:  # noqa: BLE001
                    LOG.debug("commissioning complete of %s after no answer: %s", name, err2)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("{node}: parent search refused: {err}", node=name, area=area, err=err))
            LOG.debug("parent search of %s refused: %s", name, err)
            return row | {"result": "failed"}
        else:
            if self.w.stop.wait(SETTLE_S):
                return row | {"result": "unknown"}
        after = None
        try:
            table = self._read(node_id).get("0/53/7")
            after = parent_link(table)
            if self.live and isinstance(table, list):
                self.live.set_attribute(nid, "0/53/7", table)
                self.live.note_contact(nid, src="read")
        except Exception as err:  # noqa: BLE001
            LOG.debug("read after parent search of %s: %s", name, err)
        try:   # addresses of the node: its RLOC16 (and so its parent) can have changed
            res_a = self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": "0/51/0"}, timeout=30)
            addrs = res_a.get("0/51/0") if isinstance(res_a, dict) else None
            if isinstance(addrs, list) and self.live:
                self.live.set_attribute(nid, "0/51/0", addrs)
        except Exception as err:  # noqa: BLE001
            LOG.debug("addresses of %s: %s", name, err)
        if after:
            row["rloc"] = after["rloc"]
        before = (parent_before, rssi_before, lqi_before)
        if not self._conclude(nid, name, before, row, read=False, known=bool(after)):
            # not known yet (a sleepy node answers at its next wake-up): followed in the background
            threading.Thread(target=self._follow, args=(nid, name, before), daemon=True, name="reattach-follow").start()
        return row

    def _conclude(self, nid, name, before, row, read=True, known=True):
        """Read the node and its parent, and if the parent is known, give the result: the
        parent (new or same) and its link now, as the table shows them. Returns True when done."""
        node_id = int(nid, 16)
        if read:
            for path in ("0/53/7", "0/51/0"):   # its table and its addresses (RLOC16, so its parent)
                try:
                    res_r = self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": path}, timeout=30)
                    value = res_r.get(path) if isinstance(res_r, dict) else None
                    if isinstance(value, list) and self.live:
                        self.live.set_attribute(nid, path, value)
                        self.live.note_contact(nid, src="read")
                except Exception as err:  # noqa: BLE001 - asleep: next try
                    LOG.debug("follow-up read of %s %s: %s", name, path, err)
                    return False
        parent, rssi, lqi = self._view(nid, read_parent=True)   # only the values of the table: no other source
        if not known or not parent:
            row.update({"result": "unknown", "text": t("{node}: new parent not known yet", node=name)})
            self.results[nid] = {"state": "pending", "text": row["text"], "at": time.time()}
            return False
        parent_before, rssi_before, lqi_before = before
        res = "same" if parent == parent_before else verdict((rssi_before, lqi_before), (rssi, lqi))
        link = " · ".join(x for x in (parent, f"LQI {lqi}" if lqi is not None else None, f"{rssi} dBm" if rssi is not None else None) if x)
        text = t("{node}: same parent {link}", node=name, link=link) if res == "same" else \
            t("{node}: new parent {link}", node=name, link=link)
        row.update({"result": res, "parent": parent, "rssi": rssi, "lqi": lqi, "text": text})
        self._done(nid, name, res, text)
        self.w.emit("reattach_result", text, node=name, result=res, rssi_before=rssi_before, rssi=rssi, lqi=lqi, parent=parent)
        return True

    def _done(self, nid, name, res, text):
        self.results[nid] = {"state": "done", "result": res, "text": text, "at": time.time()}
        if self.advisor:
            self.advisor.tried[name] = (time.time(), res)   # kept on disk: the advice follows it
            self.advisor.save()
        if res not in ("noanswer", "unknown") and getattr(self.w, "history", None):
            try:
                self.w.history.sample_one(nid)   # the parent change shows in the node panel at once
            except Exception as err:  # noqa: BLE001
                LOG.debug("history point of %s: %s", name, err)
        if self.table:
            self.table.cache_t = 0   # the page shows the new link at its next request

    def _follow(self, nid, name, before):
        """Result not known right after the search: read the node and its parent again every
        FOLLOW_EVERY_S for FOLLOW_FOR_S, then give the result (or say the node did not answer)."""
        end = time.time() + FOLLOW_FOR_S
        while time.time() < end:
            if self.w.stop.wait(FOLLOW_EVERY_S):
                return
            try:
                if self._conclude(nid, name, before, {}):
                    return
            except Exception as err:  # noqa: BLE001
                LOG.debug("follow-up of %s: %s", name, err)
        text = t("{node}: no answer from the node", node=name)
        self._done(nid, name, "noanswer", text)
        self.w.emit("reattach_result", text, node=name, result="noanswer")

    # ------------------------------------------------------------ router (provisional, see top)
    def _row(self, nid):
        """Row of the node in the table, read again."""
        if not self.table:
            return {}
        rid = f"0x{nid.lstrip('0') or '0'}"
        try:
            self.table.cache_t = 0
            return next((r for r in self.table.get(force=True).get("rows") or [] if r.get("id") == rid), {})
        except Exception as err:  # noqa: BLE001
            LOG.debug("table row of %s: %s", nid, err)
            return {}

    @staticmethod
    def _first_link(row):
        """(name, rssi, lqi) of the first link of a node: its parent, or the first hop of a router."""
        if row.get("parent"):
            return row.get("parent"), row.get("rssi"), row.get("lqi")
        return row.get("best_link"), row.get("best_rssi"), row.get("best_lqi")

    @staticmethod
    def _link_text(link):
        name, rssi, lqi = link
        return " · ".join(x for x in (name, f"LQI {lqi}" if lqi is not None else None,
                                      f"{rssi} dBm" if rssi is not None else None) if x) or "?"

    def _router(self, nid, name, area):
        """Restart the Thread interface of a router. Returns None when the node is not a router."""
        node_id = int(nid, 16)
        attrs = self._read(node_id)
        if attrs.get("0/53/1") not in ROUTER_ROLES:
            return None
        before = self._first_link(self._row(nid))
        network = connected_network(attrs.get("0/49/1"))
        if network is None or CONNECT_NETWORK not in (attrs.get("0/49/65529") or []):
            return {"result": "unsupported"}
        leader = attrs.get("0/53/1") == 6
        self.w.emit("reattach_node", (t("{node}: Thread restart of the leader (trial), first link {link}", node=name, area=area,
                                        link=self._link_text(before)) if leader else
                                      t("{node}: Thread restart of a router (trial), first link {link}", node=name, area=area,
                                        link=self._link_text(before))), node=name)
        try:
            self._reattach(node_id, network)
        except NoAnswer as err:
            LOG.debug("thread restart of %s: no answer to the connect command (%s)", name, err)
            if not self.w.stop.wait(SETTLE_S):
                try:
                    self._command(node_id, 48, "CommissioningComplete", {}, timeout=30)
                except Exception as err2:  # noqa: BLE001
                    LOG.debug("commissioning complete of %s after no answer: %s", name, err2)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("{node}: parent search refused: {err}", node=name, area=area, err=err))
            return {"result": "failed"}
        text = t("{node}: Thread restarted, waiting for the result…", node=name)
        self.results[nid] = {"state": "pending", "text": text, "at": time.time()}
        threading.Thread(target=self._follow_router, args=(nid, name, before), daemon=True, name="reattach-router").start()
        return {"result": "restarted", "text": text}

    def _follow_router(self, nid, name, before):
        """Role and first link of the router as soon as it is a router again: its role is
        read every ROUTER_POLL_S, and after ROUTER_SETTLE_S the result is given as it is."""
        node_id = int(nid, 16)
        end = time.time() + ROUTER_SETTLE_S
        while time.time() < end:
            if self.w.stop.wait(min(ROUTER_POLL_S, max(0.0, end - time.time()))):
                return
            try:   # a node that is attaching again may not answer: next try
                res = self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": "0/53/1"}, timeout=15)
                if isinstance(res, dict) and res.get("0/53/1") in ROUTER_ROLES:
                    break
            except Exception as err:  # noqa: BLE001
                LOG.debug("role of %s after thread restart: %s", name, err)
        try:
            res = self.h.matter_command("read_attribute", {"node_id": node_id,
                                                           "attribute_path": ["0/53/1", "0/53/7", "0/53/8", "0/51/0"]}, timeout=60)
            if not isinstance(res, dict) or res.get("0/53/1") is None:
                raise RuntimeError("no value")
            if self.live:
                for path, value in res.items():
                    self.live.set_attribute(nid, path, value)
                self.live.note_contact(nid, src="read")
            row = self._row(nid)
            again = row.get("role") in ("router", "leader")
            text = (t("{node}: Thread restarted, router again, first link {link} (before: {before})", node=name,
                      link=self._link_text(self._first_link(row)), before=self._link_text(before)) if again else
                    t("{node}: Thread restarted, still an end device, first link {link} (before: {before})", node=name,
                      link=self._link_text(self._first_link(row)), before=self._link_text(before)))
            result = "restarted"
        except Exception as err:  # noqa: BLE001
            LOG.debug("read after thread restart of %s: %s", name, err)
            text, result = t("{node}: no answer from the node", node=name), "noanswer"
        self.results[nid] = {"state": "done", "result": result, "text": text, "at": time.time()}
        if self.table:
            self.table.cache_t = 0
        self.w.emit("reattach_result", text, node=name, result=result)

    def run_node(self, nid):
        """Parent search for one node, asked from the node table: done even when its link is
        not poor (the user chose). Returns the result dict, or {"result": "router"} when
        the node is not an end device."""
        if not self.busy.acquire(timeout=1):
            return {"result": "busy"}
        try:
            with self.h.lock:
                n = dict(self.h.nodes.get(nid) or {})
            try:
                row = self._one(nid, n.get("name") or f"0x{nid.lstrip('0')}", n.get("area", "?"), force=True)
            except Exception as err:  # noqa: BLE001 - asleep or out of reach
                LOG.debug("parent search of %s: %s", nid, err)
                return {"result": "noanswer"}
            if row is None:   # not an end device: a router (provisional trial), or nothing to do
                try:
                    row = self._router(nid, n.get("name") or f"0x{nid.lstrip('0')}", n.get("area", "?"))
                except Exception as err:  # noqa: BLE001
                    LOG.debug("thread restart of %s: %s", nid, err)
                    return {"result": "noanswer"}
            return row or {"result": "router"}
        finally:
            self.busy.release()

    # ------------------------------------------------------------ recovery attempt (unavailable node)
    def _cached(self, nid):
        """Attributes of a node as last known (it cannot be read: it is unavailable)."""
        if self.live:
            with self.live.lock:
                n = self.live.nodes.get(nid)
                if n:
                    return dict(n["attributes"])
        res = self.h.matter_command("get_node", {"node_id": int(nid, 16)}, timeout=60)
        return (res.get("attributes") or {}) if isinstance(res, dict) else {}

    def _is_back(self, nid):
        if self.live and self.live.connected:
            with self.live.lock:
                n = self.live.nodes.get(nid)
            return bool(n) and n.get("available") is True
        with self.h.lock:
            return bool((self.h.nodes.get(nid) or {}).get("available"))

    def _recover_result(self, nid, name, res, text, state="done"):
        self.results[nid] = {"state": state, "result": res, "text": text, "at": time.time()}
        if self.table:
            self.table.cache_t = 0
        if state == "done":
            self.w.emit("recover_result", text, node=name, result=res)

    def recover_node(self, nid):
        """Recovery attempt for an unavailable Thread node, asked from the node table: the
        connect command of the parent search is sent although the node is unavailable.
        "Unavailable" means the Matter Server could not set up its subscription again (a long
        exchange); one command only needs a session and one answer, which can get through a
        link that loses most messages. The node then restarts its Thread interface and picks
        its neighbors again. Returns at once ({"result": "pending" | "unsupported" | "busy"});
        the result comes in the table (results) and in the recover_result event."""
        if nid in self.recovering or not self.busy.acquire(timeout=1):
            return {"result": "busy"}
        started = False
        try:
            with self.h.lock:
                n = dict(self.h.nodes.get(nid) or {})
            name, area = n.get("name") or f"0x{nid.lstrip('0')}", n.get("area", "?")
            try:
                attrs = self._cached(nid)
            except Exception as err:  # noqa: BLE001
                LOG.debug("recovery of %s, last known values: %s", name, err)
                attrs = {}
            network = connected_network(attrs.get("0/49/1"))
            if network is None or CONNECT_NETWORK not in (attrs.get("0/49/65529") or []):
                return {"result": "unsupported"}
            # the thread is created first: when it cannot start (no thread left), the node is not
            # left marked "recovering" for good, with a result "pending" that never ends
            th = threading.Thread(target=self._recover, args=(nid, name, area, network, ext_of(attrs)),
                                  daemon=True, name="recover")
            self.recovering.add(nid)
            self.results[nid] = {"state": "pending", "text": t("{node}: recovery attempt", node=name, area=area),
                                 "at": time.time()}
            try:
                th.start()
            except RuntimeError as err:
                self.recovering.discard(nid)
                self.results.pop(nid, None)
                LOG.warning(t("{node}: recovery attempt not started ({err})", node=name, err=err))
                return {"result": "failed"}
            started = True
            return {"result": "pending"}
        finally:
            if not started:
                self.busy.release()

    def _alive(self, nid, node_id, ext):
        """Is the node alive? Two tests that do not need it to answer Matter:
        - radio: the neighbor tables of the routers that know it, read now (it can be alive on
          the radio with an address nobody can reach);
        - network: the ping of the Matter Server on its known addresses ({ip: answered}).
        Returns {"ok": [ip], "ko": [ip], "heard": [(name, seconds, rssi)], "radio_known": bool}."""
        try:
            res = self.h.matter_command("ping_node", {"node_id": node_id}, timeout=60)
        except Exception as err:  # noqa: BLE001
            LOG.debug("ping of %s before recovery: %s", nid, err)
            res = None
        res = res if isinstance(res, dict) else {}
        heard = []
        if ext is not None and self.live and hasattr(self.live, "heard_by"):
            try:
                with self.h.lock:
                    names = {k: v.get("name") or k for k, v in self.h.nodes.items()}
                heard = [(names.get(k, f"0x{k.lstrip('0')}"), s, r) for k, s, r in self.live.heard_by(ext)]
            except Exception as err:  # noqa: BLE001
                LOG.debug("radio test of %s: %s", nid, err)
        return {"ok": sorted(ip for ip, v in res.items() if v), "ko": sorted(ip for ip, v in res.items() if not v),
                "heard": heard, "radio_known": ext is not None}

    def announce_current(self, nid, name, ips):
        """Announces the node in its place on the addresses the Thread diagnostic found, and keeps
        that announcement until the node announces itself again on the prefix of the network."""
        if not hasattr(self.w, "proxy_announce") or not self.w.proxy_announce(nid, ips):
            return False
        if hasattr(self.w, "proxy_hold"):
            self.w.proxy_hold(nid, ips, name)
        self.w.emit("recover_proxy", t("{node}: announced in its place on {ip} (address given by the Thread diagnostic)",
                                       node=name, ip=", ".join(ips)), node=name, ip=list(ips))
        self.w.stop.wait(PROXY_SETTLE_S)
        return True

    def _hearing(self, nid, ext, recent):
        """Most recent hearing of the node in the neighbor tables of the other nodes (nodetable.heard_map)."""
        if ext is None or not self.live:
            return None
        with self.h.lock:
            names = {k: v.get("name") or k for k, v in self.h.nodes.items()}
        with self.live.lock:
            snap = {k: {"attrs": dict(n.get("attributes") or {}), "meta": {"available": n.get("available")},
                        "node": {}, "name": names.get(k, k)} for k, n in self.live.nodes.items() if k != nid}
        return heard_of(heard_map(snap, self.live, time.time(), recent=recent), ext)

    # ------------------------------------------------------------ automatic recovery by the Thread diagnostic
    def run_auto(self):
        """Every AUTO_EVERY_S: one unavailable mains node that a neighbor hears and whose address is
        not known (or on an old prefix) gets the gentle way: Thread diagnostic, then the announcement
        in its place on its current address. Never the restart of its radio (ConnectNetwork)."""
        if self.w.stop.wait(300):   # after a start, Home Assistant and the tables settle first
            return
        while True:
            try:
                self.auto_pass()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Automatic Thread diagnostic failed: {err}", err=err))
            if self.w.stop.wait(AUTO_EVERY_S):
                return

    def auto_pass(self, now=None):
        """One candidate at most per pass. Returns the node hex handled, or None."""
        now = time.time() if now is None else now
        if not getattr(self, "auto_diag", True):
            return None
        anchor = getattr(self.w, "anchor", None)
        storm = getattr(self.h, "storm", None)
        if anchor is None or not anchor.diag_ready() or anchor.blocked() or (storm and storm.active):
            return None
        last = self.__dict__.setdefault("auto_last", {})
        done = self.__dict__["auto_done"] = [x for x in self.__dict__.get("auto_done", []) if now - x < 3600]
        if len(done) >= AUTO_PER_HOUR:
            return None
        with self.h.lock:
            down = sorted(((k, n) for k, n in self.h.nodes.items() if not n.get("available") and not n.get("battery")),
                          key=lambda x: x[1].get("since") or 0)
        holds = getattr(self.w, "proxy_holds", None) or {}
        for nid, n in down:
            if nid in self.recovering or nid in holds or (nid in last and now - last[nid] < AUTO_NODE_S):
                continue
            st = self.w.stale_prefix(nid, thread=True) if hasattr(self.w, "stale_prefix") else None
            announced = (self.w.matter.get(nid) or {}).get("online") if hasattr(self.w, "matter") else None
            if not st and announced is not False:
                continue   # announced on a current address: the diagnostic would not change anything
            try:
                ext = ext_of(self._cached(nid))
            except Exception:  # noqa: BLE001
                continue
            if not self._hearing(nid, ext, AUTO_HEARD_S):
                continue   # nobody hears it: not this way (the pings of the recovery go on)
            if not self.busy.acquire(blocking=False):
                return None
            try:
                last[nid] = now
                done.append(now)
                name = n.get("name") or f"0x{nid.lstrip('0')}"
                d = self._thread_diag(nid, name, ext)
                if d is None:
                    return nid
                self.w.emit("auto_diag", t("{node}: automatic Thread diagnostic: {diag}", node=name, diag=d["text"]),
                            node=name, result=d["result"])
                if d["omr"] and self.announce_current(nid, name, d["omr"]):
                    if self._wait_back(nid, BACK_WAIT_S):
                        self._recover_result(nid, name, "back_announce", t(
                            "{node}: back once announced in its place on its current address", node=name) + " · " + d["text"])
                elif d["result"] in ("old_prefix_only", "frozen"):
                    self._recover_result(nid, name, d["result"], d["outcome"] + " · " + d["text"])
                return nid
            finally:
                self.busy.release()
        return None

    def _wait_back(self, nid, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self._is_back(nid):
                return True
            if self.w.stop.wait(3):
                return False
        return self._is_back(nid)

    def _thread_diag(self, nid, name, ext):
        """Thread diagnostic of a node by Thread Anchor (its RLOC16 read in the neighbor tables of the
        nodes that hear it). None when it cannot be asked (no Thread Anchor, RLOC16 not known).
        Else {"text", "omr": [addresses on the network prefix], "result": "omr" | "old_prefix_only" |
        "frozen" | "unknown", "outcome": text of the result when the attempt stops there}."""
        anchor = getattr(self.w, "anchor", None)
        if anchor is None or not anchor.diag_ready() or ext is None or not self.live:
            return None
        hb = self._hearing(nid, ext, 3600)
        try:
            mleid = mleid_of(self._cached(nid))
        except Exception:  # noqa: BLE001
            mleid = None
        rloc = hb.get("rloc16") if hb else None
        if rloc is None and mleid is None:
            return None   # nothing Thread Anchor can reach it by
        res = anchor.diag(rloc, ext, mleid=mleid)
        where = f"RLOC 0x{rloc:04X}" if rloc is not None else f"ML-EID {mleid}"
        if not isinstance(res, dict):
            return {"text": t("Thread diagnostic ({where}) failed: {why}", where=where, why=t("no answer from Thread Anchor")),
                    "omr": [], "result": "unknown", "outcome": ""}
        ping = res.get("ping") or {}
        err = str(res.get("error") or "")
        pinged = (t("answers through the mesh ({ms} ms)", ms=ping.get("rtt_ms")) if ping.get("ok")
                  else t("no answer through the mesh") if ping else t("not pinged"))
        if err:
            text = t("Thread diagnostic ({where}) failed: {why}", where=where, why=err) + (f" ({pinged})" if ping else "")
            # neither the diagnostic nor the ping answers while a neighbor hears it: its network stack
            # is stuck. Any other error (busy, too soon, another node at this RLOC16…) proves nothing
            if err.startswith("no answer to the network diagnostic") and not ping.get("ok") and hb:
                return {"text": text, "omr": [], "result": "frozen", "outcome": t(
                    "{node}: heard by {who} but no answer through the mesh: its network stack is stuck. No remote way "
                    "is left: cutting its power for 10 s is the last resort, your call", node=name, who=hb["by"])}
            return {"text": text, "omr": [], "result": "unknown", "outcome": ""}
        # the diagnostic answered (the ping may not: some nodes answer one and not the other)
        omr = [str(x) for x in res.get("omr_addresses") or []]
        old = [str(x) for x in res.get("other_prefix_addresses") or []]
        addrs = ", ".join(omr + old) or t("no routable address")
        text = t("Thread diagnostic ({where}): {ping}; addresses: {addrs}", where=where, ping=pinged, addrs=addrs)
        if omr:
            return {"text": text, "omr": omr, "result": "omr", "outcome": ""}
        if old:
            return {"text": text, "omr": [], "result": "old_prefix_only", "outcome": t(
                "{node}: only has the old prefix ({addrs}): it did not take the prefix of the network. A remedy on the "
                "border router of Home Assistant is possible (a route to the old prefix for a while), with your agreement",
                node=name, addrs=", ".join(old))}
        return {"text": text, "omr": [], "result": "unknown", "outcome": ""}

    @staticmethod
    def _alive_text(name, a):
        if a["heard"]:
            who, s, rssi = a["heard"][0]
            radio = t("heard on the radio by {who} {ago} ago", who=f"{who} ({rssi} dBm)" if rssi is not None else who,
                      ago=_ago(s))
        elif a["radio_known"]:
            radio = t("not heard on the radio by its neighbors")
        else:
            radio = t("radio not checked (address of its radio not known)")
        if a["ok"]:
            net = t("answers the network ping on {ip}", ip=", ".join(a["ok"]))
        elif a["ko"]:
            net = t("no answer to the network ping ({ips})", ips=", ".join(a["ko"]))
        else:
            net = t("no address to ping")
        return t("{node}: alive test: {radio}; {ping}", node=name, radio=radio, ping=net)

    def _recover(self, nid, name, area, network, ext=None):
        node_id = int(nid, 16)
        proxied = False
        try:
            try:
                self.w.emit("recover_node", t("{node}: recovery attempt", node=name, area=area), node=name)
                alive = self._alive(nid, node_id, ext)
                alive_txt = self._alive_text(name, alive)
                self.w.emit("recover_alive", alive_txt, node=name, ping_ok=alive["ok"], ping_ko=alive["ko"],
                            heard=[[w, round(s), r] for w, s, r in alive["heard"]])
                st = self.w.stale_prefix(nid, thread=True) if hasattr(self.w, "stale_prefix") else None
                announced = (self.w.matter.get(nid) or {}).get("online") if hasattr(self.w, "matter") else None
                if (st or (announced is False and not alive["ok"])) and alive["heard"]:
                    # address not known or on an old prefix, but its neighbors hear it: Thread Anchor
                    # reaches it through the mesh (RLOC16) and tells its current addresses
                    d = self._thread_diag(nid, name, ext)
                    if d is not None:
                        alive_txt += " · " + d["text"]
                        if d["omr"] and self.announce_current(nid, name, d["omr"]):
                            # the gentle way first: often the Matter Server only needed its address
                            # (17/11, Miele: back 6 s later). The radio of the node is not restarted
                            if self._wait_back(nid, BACK_WAIT_S):
                                self._recover_result(nid, name, "back_announce", t(
                                    "{node}: back once announced in its place on its current address", node=name)
                                    + " · " + alive_txt)
                                return
                            st = None   # its current address is announced: the command can leave
                        elif d["result"] in ("old_prefix_only", "frozen"):
                            self._recover_result(nid, name, d["result"], d["outcome"] + " · " + alive_txt)
                            return
                if st:
                    # still on a prefix the border routers left: its address is not known, the
                    # command cannot leave (the Matter Server gives up at once)
                    self._recover_result(nid, name, "stale", (t(
                        "{node}: recovery attempt not sent: stayed on the old prefix {prefix} after {br} changed it at {at}, "
                        "its new address is not known", node=name, prefix=st["prefix"], br=st["br"], at=st["at"]) if st.get("br")
                        else t("{node}: recovery attempt not sent: stayed on the old prefix {prefix}, its new address is not known",
                               node=name, prefix=st["prefix"]))
                        + " · " + alive_txt)
                    return
                if not proxied and alive["ok"] and announced is False and hasattr(self.w, "proxy_announce"):
                    # TRIAL: it answers on an address but no longer announces itself: announced in
                    # its place, the Matter Server can find it again and the command can leave
                    proxied = self.w.proxy_announce(nid, alive["ok"])
                    if proxied:
                        self.w.emit("recover_proxy", t("{node}: announced in its place on {ip} (trial), for the recovery attempt",
                                                       node=name, ip=", ".join(alive["ok"])), node=name, ip=alive["ok"])
                        self.w.stop.wait(PROXY_SETTLE_S)
                sent = self._recover_send(node_id, name, area, network, alive_txt)
            finally:
                if proxied:
                    # withdrawn as soon as the commands are sent: the node announces itself again
                    # when it attaches, and two announcements of one name would conflict
                    self.w.proxy_withdraw(nid)
                    proxied = False
                self.busy.release()
            if not sent:
                return
            self._recover_result(nid, name, "sent", t("{node}: Thread restarted, waiting for it to come back", node=name),
                                 state="pending")
            closed = False
            end = time.time() + FOLLOW_FOR_S
            wait = SETTLE_S
            while time.time() < end:
                if self.w.stop.wait(wait):
                    return
                wait = FOLLOW_EVERY_S
                if not closed:
                    try:   # attached again: close the fail-safe (it reverts by itself otherwise)
                        self._command(node_id, 48, "CommissioningComplete", {}, timeout=60)
                        closed = True
                    except Exception as err:  # noqa: BLE001
                        LOG.debug("commissioning complete of %s after recovery: %s", name, err)
                if self._is_back(nid):
                    # back but the fail-safe is still armed: when it expires the node reverts its
                    # configuration and may restart Thread once more. It answers now: close it
                    for _ in range(CLOSE_TRIES):
                        if closed or self.w.stop.wait(CLOSE_EVERY_S):
                            break
                        try:
                            self._command(node_id, 48, "CommissioningComplete", {}, timeout=60)
                            closed = True
                        except Exception as err:  # noqa: BLE001
                            LOG.debug("commissioning complete of %s, back: %s", name, err)
                    if not closed:
                        LOG.info("recovery of %s: back, fail-safe not closed (it expires by itself)", name)
                    self._recover_result(nid, name, "back", t("{node}: back after the recovery attempt", node=name))
                    return
            self._recover_result(nid, name, "noanswer", t("{node}: still unavailable after the recovery attempt", node=name))
        except Exception as err:  # noqa: BLE001
            LOG.warning("recovery of %s: %s", name, err)
            self._recover_result(nid, name, "noanswer", t("{node}: still unavailable after the recovery attempt", node=name))
        finally:
            self.recovering.discard(nid)
            if proxied:
                self.w.proxy_withdraw(nid)

    def _recover_send(self, node_id, name, area, network, alive_txt=""):
        """ArmFailSafe and ConnectNetwork (the ping of the alive test, just before, made the
        Matter Server look for the address of the node again). True when the connect command
        left under an armed fail-safe (answered or not: a node that attaches again may not answer)."""
        nid = f"{node_id:016X}"
        try:
            res = self._command(node_id, 48, "ArmFailSafe", {"expiryLengthSeconds": FAILSAFE_S, "breadcrumb": 1},
                                timeout=RECOVER_WAIT_S)
        except Exception as err:  # noqa: BLE001 - no session: nothing reaches the node
            LOG.info("recovery of %s, no answer to ArmFailSafe: %s", name, err)
            announced = (self.w.matter.get(nid) or {}).get("online") if hasattr(self.w, "matter") else None
            self._recover_result(nid, name, "unreachable",
                                 (t("{node}: no longer announced on the network, its address is not known: "
                                    "the recovery attempt could not be sent", node=name) if announced is False
                                  else t("{node}: out of reach, the recovery attempt could not be sent", node=name))
                                 + (" · " + alive_txt if alive_txt else ""))
            return False
        if _field(res, "errorCode", "0") != 0:
            LOG.info("recovery of %s, ArmFailSafe refused: %s", name, res)
            self._recover_result(nid, name, "failed", t("{node}: recovery attempt refused", node=name))
            return False
        try:
            res = self._command(node_id, 49, "ConnectNetwork", {"networkID": network, "breadcrumb": 2})
        except Exception as err:  # noqa: BLE001 - silence is not a refusal: the node may be attaching
            LOG.debug("recovery of %s, no answer to ConnectNetwork: %s", name, err)
            return True
        if _field(res, "networkingStatus", "0") != 0:
            LOG.info("recovery of %s, ConnectNetwork refused: %s", name, res)
            try:
                self._command(node_id, 48, "ArmFailSafe", {"expiryLengthSeconds": 0, "breadcrumb": 0}, timeout=30)
            except Exception as err:  # noqa: BLE001
                LOG.debug("disarm fail-safe of %s: %s", name, err)
            self._recover_result(nid, name, "failed", t("{node}: recovery attempt refused", node=name))
            return False
        return True

    # ------------------------------------------------------------ factory reset from a distance
    # Matter has no reset command, but a node that leaves its last fabric erases what it
    # learnt since it was paired (the SDK of most devices then restarts it, ready to be paired
    # again). An administrator may remove any fabric of a node, not only its own: the others
    # are removed first, then the Matter Server removes the node, which removes its own.
    def fabrics(self, nid):
        """(index of the fabric of Home Assistant, [{"index", "name", "own"}] of every fabric)."""
        res = self.h.matter_command("read_attribute", {"node_id": int(nid, 16), "attribute_path": ["0/62/1", "0/62/5"]},
                                    timeout=60)
        own, listed = (res or {}).get("0/62/5"), (res or {}).get("0/62/1")
        if own is None or not isinstance(listed, list) or not listed:
            raise RuntimeError("fabrics not read")
        out = []
        for f in listed:
            index, vendor, label = _field(f, "fabricIndex", "254"), _field(f, "vendorID", "2"), _field(f, "label", "5")
            if index is None:
                raise RuntimeError("fabric without index")
            name = "Home Assistant" if index == own else FABRIC_VENDORS.get(vendor) or label or f"vendor {vendor}"
            out.append({"index": index, "name": name, "own": index == own})
        if not any(f["own"] for f in out):
            raise RuntimeError("own fabric not listed")
        return own, out

    def _leave_own(self, node_id, own):
        """Ask the node to leave the fabric of Home Assistant. "left" (it confirmed), "unsure"
        (no answer, and it can no longer be reached: it most likely left, the answer was lost
        with the session it closed). Raises when it refused or when it still answers on it."""
        try:
            res = self._command(node_id, 62, "RemoveFabric", {"fabricIndex": own}, timeout=60)
        except Exception as err:  # noqa: BLE001
            LOG.debug("leaving the fabric, no answer from %s: %s", node_id, err)
            try:   # still reachable on the fabric: it did not leave
                self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": "0/62/5"}, timeout=30)
            except Exception:  # noqa: BLE001
                return "unsure"
            raise RuntimeError("still on the fabric of Home Assistant") from err
        if _field(res, "statusCode", "0") != 0:
            raise RuntimeError(f"RemoveFabric {own}: {res}")
        return "left"

    def reset_node(self, nid):
        """Remove the node from every fabric, its own last. Returns {"result": "reset" |
        "unsure" (it did not confirm leaving the last one, but no longer answers) | "noanswer"
        (nothing was removed) | "partial" (it left other fabrics but is still in Home Assistant)
        | "busy", "fabrics": names removed, "listed": still in the list of the Matter Server}.

        The fabric of Home Assistant is removed here rather than left to remove_node: the
        Matter Server removes the node from its list even when the device refuses to leave (it
        only writes it in its log), and the device would then keep a fabric nobody can use,
        out of reach of any reset from a distance."""
        if not self.busy.acquire(timeout=1):
            return {"result": "busy"}
        removed = []
        try:
            node_id = int(nid, 16)
            with self.h.lock:
                name = (self.h.nodes.get(nid) or {}).get("name") or f"0x{nid.lstrip('0')}"
            try:
                own, fabs = self.fabrics(nid)
                for f in fabs:
                    if f["own"]:
                        continue
                    res = self._command(node_id, 62, "RemoveFabric", {"fabricIndex": f["index"]}, timeout=60)
                    if _field(res, "statusCode", "0") != 0:
                        raise RuntimeError(f"RemoveFabric {f['index']}: {res}")
                    removed.append(f["name"])
                result = "reset" if self._leave_own(node_id, own) == "left" else "unsure"
            except Exception as err:  # noqa: BLE001
                LOG.warning("reset of %s stopped after %d fabric(s): %s", name, len(removed), err)
                return {"result": "partial" if removed else "noanswer", "fabrics": removed}
            removed.append("Home Assistant")
            listed = False
            try:   # the device has left: the Matter Server forgets it (it cannot reach it any more)
                self.h.matter_command("remove_node", {"node_id": node_id}, timeout=180)
            except Exception as err:  # noqa: BLE001
                listed = "does not exist" not in str(err).lower()
                LOG.warning("reset of %s: left its fabrics, but the Matter Server did not remove it: %s", name, err)
            self.resets[nid] = time.time()
            try:
                save_json(RESETS_FILE, self.resets)
            except OSError as err:
                LOG.debug("cannot write %s: %s", RESETS_FILE, err)
            self.w.emit("node_reset", t("{node}: reset from a distance, to pair again", node=name), node=name,
                        fabrics=removed, result=result)
            if self.table:
                self.table.cache_t = 0
            return {"result": result, "fabrics": removed, "listed": listed}
        finally:
            self.busy.release()

    def run_now(self, origin):
        """Read the parent link of every end device and move those whose link is poor (button)."""
        if not self.busy.acquire(blocking=False):
            LOG.info(t("Parent search already running"))
            return
        try:
            if self.h.storm and self.h.storm.active or time.time() < self.h.mass_until:
                self.w.emit("reattach_done", t("Parent search skipped: the network is re-forming, try again later",
                                               origin=origin), checked=0, poor=0, origin=origin)
                return
            try:
                targets = self._targets()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Parent search interrupted: {err}", err=err))
                return
            self.w.emit("reattach", t("Parent search: checking the link of {n} end devices",
                                      origin=origin, n=len(targets)), total=len(targets), origin=origin)
            rows, checked = [], 0
            for nid, name, area in targets:
                if self.w.stop.is_set():
                    return
                try:
                    row = self._one(nid, name, area)
                except ConnectionError as err:
                    LOG.warning(t("Parent search interrupted: {err}", err=err))
                    break
                except Exception as err:  # noqa: BLE001
                    LOG.debug("parent search, %s not read: %s", name, err)   # asleep or out of reach
                    continue
                checked += 1
                if row:
                    rows.append(row)
            better = sum(1 for r in rows if r["result"] == "better")
            self.last = {"date": time.strftime("%d/%m %H:%M"), "checked": checked, "poor": len(rows), "better": better,
                         "nodes": [r.get("text") or r["node"] for r in rows][:60]}
            if rows:
                text = tn("Parent search: {n} poor link, {better} better now",
                          "Parent search: {n} poor links, {better} better now", len(rows), better=better, origin=origin)
            else:
                text = t("Parent search: no poor link among {n} end devices", n=checked, origin=origin)
            self.w.emit("reattach_done", text, checked=checked, poor=len(rows), better=better,
                        nodes=rows, origin=origin)
            self.w.dirty = True
        finally:
            self.busy.release()

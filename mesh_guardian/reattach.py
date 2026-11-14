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
link is poor when read just before: a node with a good link can end up on a
weaker parent, and there is no way back to the previous one. Nothing is sent
until the "Find better parents" button is pressed.
"""
import logging
import threading
import time

from i18n import t, tn

LOG = logging.getLogger("mg.reattach")
POOR_LQI = 2          # link quality (1-3) from which a new parent is worth looking for
POOR_RSSI = -80       # dBm: same, whatever the link quality
GOOD_GAIN = 6         # dB: gain from which the new link counts as better (same as the advice)
FAILSAFE_S = 120      # s: the node goes back to its configuration by itself after this time
SETTLE_S = 25         # s: time left to the node to attach before its new link is read
END_DEVICE_ROLES = (2, 3)   # sleepy end device, end device
CONNECT_NETWORK = 6   # Network Commissioning command id
PATHS = ["0/53/1", "0/53/7", "0/49/1", "0/49/65529"]


def _field(res, name, key):
    """Field of a command answer: by name (Matter Server) or by numeric id."""
    if not isinstance(res, dict):
        return None
    return res.get(name, res.get(key))


def parent_link(table):
    """Link of an end device with its parent in a neighbor table (0/53/7):
    {"rloc", "lqi", "rssi"}, or None. Entries only overheard (LQI 0) are ignored."""
    for nb in table or []:
        if not isinstance(nb, dict) or nb.get("13") is True:
            continue
        lqi, rssi = nb.get("5"), nb.get("6")
        if not lqi or rssi is None:
            continue
        return {"rloc": nb.get("2"), "lqi": lqi, "rssi": rssi}
    return None


def is_poor(link):
    return bool(link) and (link["lqi"] <= POOR_LQI or link["rssi"] <= POOR_RSSI)


def connected_network(networks):
    """Id of the only network the node knows and is connected to, or None."""
    if not isinstance(networks, list) or len(networks) != 1 or not isinstance(networks[0], dict):
        return None
    net = networks[0]
    connected = net.get("1", net.get("connected"))
    return net.get("0", net.get("networkID")) if connected is True else None


def verdict(before, after):
    """better / worse / similar / same (no parent change) / unknown."""
    if not after:
        return "unknown"
    if after["rloc"] == before["rloc"]:
        return "same"
    gain = after["rssi"] - before["rssi"]
    if after["lqi"] > before["lqi"] or gain >= GOOD_GAIN:
        return "better"
    if after["lqi"] < before["lqi"] or gain <= -GOOD_GAIN:
        return "worse"
    return "similar"


class Reattach:
    def __init__(self, watch, healer):
        self.w = watch
        self.h = healer
        self.live = None          # live copy of the Matter Server cache, plugged in by watcher
        self.advisor = None       # radio advice: told which nodes were asked to move
        self.busy = threading.Lock()
        self.last = {"date": None, "checked": 0, "poor": 0, "better": 0, "nodes": []}

    # ------------------------------------------------------------ Matter Server
    def _read(self, node_id):
        res = self.h.matter_command("read_attribute", {"node_id": node_id, "attribute_path": PATHS}, timeout=60)
        return res if isinstance(res, dict) else {}

    def _command(self, node_id, cluster, name, payload, timeout=90):
        return self.h.matter_command("device_command", {"node_id": node_id, "endpoint_id": 0, "cluster_id": cluster,
                                                        "command_name": name, "payload": payload}, timeout=timeout)

    def _reattach(self, node_id, network):
        """Ask the node to connect again to its own network. Raises if it refuses."""
        res = self._command(node_id, 48, "ArmFailSafe", {"expiryLengthSeconds": FAILSAFE_S, "breadcrumb": 1})
        if _field(res, "errorCode", "0") != 0:
            raise RuntimeError(f"ArmFailSafe: {res}")
        try:
            res = self._command(node_id, 49, "ConnectNetwork", {"networkID": network, "breadcrumb": 2})
            if _field(res, "networkingStatus", "0") != 0:
                raise RuntimeError(f"ConnectNetwork: {res}")
            res = self._command(node_id, 48, "CommissioningComplete", {})
            if _field(res, "errorCode", "0") != 0:
                raise RuntimeError(f"CommissioningComplete: {res}")
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

    def _one(self, nid, name, area):
        """Read the link of one node and, if it is poor, make it look for a parent.
        Returns None (nothing to do) or the result (dict)."""
        node_id = int(nid, 16)
        attrs = self._read(node_id)
        before = parent_link(attrs.get("0/53/7"))
        if self.live and isinstance(attrs.get("0/53/7"), list):
            self.live.set_attribute(nid, "0/53/7", attrs["0/53/7"])
            self.live.note_contact(nid, src="read")
        if attrs.get("0/53/1") not in END_DEVICE_ROLES or not is_poor(before):
            return None
        row = {"node": name, "area": area, "rssi_before": before["rssi"], "lqi_before": before["lqi"]}
        network = connected_network(attrs.get("0/49/1"))
        if network is None or CONNECT_NETWORK not in (attrs.get("0/49/65529") or []):
            return row | {"result": "unsupported"}
        self.w.emit("reattach_node", t("{node}: looking for a better parent (now {rssi}dBm, LQI {lqi})",
                                       node=name, area=area, rssi=before["rssi"], lqi=before["lqi"]),
                    node=name, rssi=before["rssi"], lqi=before["lqi"])
        if self.advisor:
            self.advisor.forced[name] = time.time()
        try:
            self._reattach(node_id, network)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("{node}: parent search refused: {err}", node=name, area=area, err=err))
            return row | {"result": "failed"}
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
        res = verdict(before, after)
        row["result"] = res
        if after:
            row |= {"rssi": after["rssi"], "lqi": after["lqi"]}
        texts = {
            "better": t("{node}: better parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})"),
            "worse": t("{node}: weaker parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})"),
            "similar": t("{node}: similar parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})"),
            "same": t("{node}: same parent kept, {after}dBm (LQI {lqi}): no better router in range"),
            "unknown": t("{node}: parent search sent, new link not read yet"),
        }
        self.w.emit("reattach_result", texts[res].format(
            node=name, before=before["rssi"], lqi_before=before["lqi"],
            after=after["rssi"] if after else "?", lqi=after["lqi"] if after else "?"),
            node=name, result=res, rssi_before=before["rssi"], lqi_before=before["lqi"],
            rssi=after["rssi"] if after else None, lqi=after["lqi"] if after else None)
        return row

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
                         "nodes": [f"{r['node']}: {r['result']}, {r['rssi_before']}dBm → {r.get('rssi', '?')}dBm"
                                   for r in rows][:60]}
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

# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Live copy of the Matter Server node cache.

One WebSocket connection with "start_listening": the Matter Server sends the
full list of nodes once, then every attribute report of every node
(attribute_updated) as it arrives. Nothing is sent to the nodes: these are the
reports the Matter Server receives anyway through its own subscriptions.

This keeps current values (neighbor tables, counters, roles) without polling,
and gives the time of the last report of every node.
"""

import base64
import json
import logging
import threading
import time
import uuid

import websocket  # websocket-client

from i18n import t
from nodetable import ext_of

LOG = logging.getLogger("mg.live")
CONTACTS_FILE = "/data/last_contact.json"
SOURCES_FILE = "/data/contact_sources.json"


def node_hex(node_id):
    return f"{int(node_id):016X}"


FRESH_KEEP_S = 2 * 3600   # a value read from a node wins over the Matter Server cache this long
RHYTHM_MIN_GAP_S = 30     # shorter silences are bursts of traffic, not the rhythm of the node
RHYTHM_KEEP = 40          # silences kept per node
RHYTHM_MIN_SAMPLES = 8    # silences needed before the rhythm is trusted


class MatterLive:
    def __init__(self, watch, healer):
        self.w = watch
        self.h = healer
        self.lock = threading.RLock()
        self.nodes = {}       # node hex -> {"available", "attributes", "last": ts, "radio": ts}
        self.connected = False
        self.since = None     # time of the current connection
        self.contacts = {}    # node hex -> time of the last contact, kept in /data
        self._saved = 0
        self.t0 = time.time()   # start of the add-on: silences across a restart are not the node's
        try:
            with open(CONTACTS_FILE) as f:
                self.contacts = {k: float(v) for k, v in json.load(f).items()}
        except Exception:  # noqa: BLE001
            self.contacts = {}
        self.sources = {}     # node hex -> {"src", "active": ts, "gap": s, "since": ts}
        try:
            with open(SOURCES_FILE) as f:
                self.sources = json.load(f)
            for s in self.sources.values():
                s["active"] = None   # the add-on was stopped: that gap is not the node's
        except Exception:  # noqa: BLE001
            self.sources = {}

    def _save_contacts(self):
        try:
            with open(CONTACTS_FILE, "w") as f:
                json.dump(self.contacts, f)
        except OSError as err:
            LOG.warning(t("Cannot write {file}: {err}", file=CONTACTS_FILE, err=err))

    def reset_contacts(self):
        with self.lock:
            self.contacts = {}
            self.sources = {}
            for n in self.nodes.values():
                n["last"] = None
            self._save_contacts()
            self._save_sources()

    def prune(self, ids):
        """Forget the contacts of nodes that no longer exist (ids: set of int node ids)."""
        with self.lock:
            gone = [k for k in self.contacts if int(k, 16) not in ids]
            for k in gone:
                del self.contacts[k]
            if gone:
                self._save_contacts()
        return len(gone)

    def node_ids(self):
        with self.lock:
            return {int(k, 16) for k in self.nodes}

    def note_contact(self, nid, now=None, src="report"):
        """The node answered or reported something: remember when (survives restarts).
        src: report, event, read, ping or passive. For each node the longest gap between
        two contacts that are not passive is kept: it tells whether passive contact is
        needed to keep "Last contact" fresh."""
        now = now or time.time()
        with self.lock:
            s = self.sources.setdefault(nid, {"src": None, "active": None, "gap": 0, "since": now})
            s["src"] = src
            # rhythm of the node: its silences of 30 s or more between two contacts (any source)
            prev = self.contacts.get(nid)
            if prev and prev >= self.t0 and now - prev >= RHYTHM_MIN_GAP_S:
                s["gaps"] = (s.get("gaps") or [])[-(RHYTHM_KEEP - 1):] + [round(now - prev)]
            if src != "passive":
                if s["active"]:
                    s["gap"] = max(s["gap"], now - s["active"])
                s["active"] = now
            self.contacts[nid] = now
            if nid in self.nodes:
                self.nodes[nid]["last"] = now
            if now - self._saved >= 300:
                self._saved = now
                self._save_contacts()
                self._save_sources()

    def _save_sources(self):
        try:
            with open(SOURCES_FILE, "w") as f:
                json.dump(self.sources, f)
        except OSError as err:
            LOG.warning(t("Cannot write {file}: {err}", file=SOURCES_FILE, err=err))

    def rhythm(self, nid):
        """(usual silence between two signs of life in s, or None while unknown; seconds since
        the last contact). The usual silence is a high percentile of the silences seen, so a
        few outages do not count; with passive contact it is close to the liveness interval
        of the Matter subscription."""
        with self.lock:
            gaps = sorted((self.sources.get(nid) or {}).get("gaps") or [])
            last = self.contacts.get(nid)
        usual = gaps[int(len(gaps) * 0.8)] if len(gaps) >= RHYTHM_MIN_SAMPLES else None
        return usual, (time.time() - last if last else None)

    def source(self, nid):
        """(source of the last contact, longest gap in s between two non-passive contacts,
        seconds since the last non-passive contact, observed since)."""
        with self.lock:
            s = self.sources.get(nid)
            if not s:
                return None, None, None, None
            since_active = time.time() - s["active"] if s.get("active") else None
            gap = max(s.get("gap") or 0, since_active or 0)
            return s.get("src"), round(gap), round(since_active) if since_active is not None else None, s.get("since")

    # ------------------------------------------------------------ cache
    def _set_node(self, data):
        nid = node_hex(data.get("node_id", 0))
        with self.lock:
            old = self.nodes.get(nid, {})
            attrs = dict(data.get("attributes") or {})
            # a value read directly from the node is newer than the cache of the Matter Server,
            # which can hold an old one for hours: keep it until the node reports that attribute
            for (k, path), (t0, value) in list(getattr(self, "fresh", {}).items()):
                if k == nid and time.time() - t0 < FRESH_KEEP_S:
                    attrs[path] = value
            self.nodes[nid] = {"available": data.get("available"), "attributes": attrs,
                               "last": old.get("last") or self.contacts.get(nid), "radio": old.get("radio"),
                               "date_commissioned": data.get("date_commissioned")}

    def _event(self, msg):
        ev, data = msg.get("event"), msg.get("data")
        now = time.time()
        if ev == "attribute_updated" and isinstance(data, list) and len(data) == 3:
            nid = node_hex(data[0])
            with self.lock:
                n = self.nodes.setdefault(nid, {"available": None, "attributes": {}, "last": None, "radio": None})
                n["attributes"][data[1]] = data[2]
                getattr(self, "fresh", {}).pop((nid, data[1]), None)   # a real report: it is the current value
                if str(data[1]).startswith("0/53/"):
                    n["radio"] = now
            self.note_contact(nid, now, src="report")
        elif ev in ("node_added", "node_updated") and isinstance(data, dict):
            self._set_node(data)
            self.note_contact(node_hex(data.get("node_id", 0)), now, src="report")
        elif ev == "node_event" and isinstance(data, dict) and data.get("node_id") is not None:
            self.note_contact(node_hex(data["node_id"]), now, src="event")
        elif ev == "node_removed":
            with self.lock:
                self.nodes.pop(node_hex(data or 0), None)
                if self.contacts.pop(node_hex(data or 0), None) is not None:
                    self._save_contacts()

    def set_attribute(self, nid, path, value):
        """Value read directly from a node (kept in the live copy)."""
        with self.lock:
            if nid in self.nodes:
                self.nodes[nid]["attributes"][path] = value
            self.__dict__.setdefault("fresh", {})[(nid, path)] = (time.time(), value)

    def addresses(self):
        """node hex -> IPv6 addresses (16 bytes) the node reports (General Diagnostics)."""
        out = {}
        with self.lock:
            for k, n in self.nodes.items():
                for itf in n["attributes"].get("0/51/0") or []:
                    if not isinstance(itf, dict):
                        continue
                    for addr in itf.get("6") or []:
                        try:
                            raw = base64.b64decode(addr)
                        except Exception:  # noqa: BLE001
                            continue
                        if len(raw) == 16 and raw[0] != 0xFE:   # link-local addresses are not routed
                            out.setdefault(k, set()).add(raw)
        return out

    def snapshot(self):
        """Nodes in the get_nodes format (for the radio survey and the table)."""
        with self.lock:
            return [{"node_id": int(k, 16), "available": n["available"], "attributes": dict(n["attributes"]),
                     "last": n["last"], "radio": n["radio"]} for k, n in self.nodes.items()]

    def leaders(self):
        """Hex ids of the available nodes whose Thread role is leader (cheap: no copy)."""
        with self.lock:
            return [k for k, n in self.nodes.items()
                    if n["attributes"].get("0/53/1") == 6 and n.get("available") is not False]

    def last_heard(self, ext):
        """Seconds since a node last heard the device with this extended address (neighbor
        tables: time of the report minus the age of the entry), or None if unknown."""
        now, best = time.time(), None
        with self.lock:
            for n in self.nodes.values():
                if not n.get("radio"):
                    continue
                for nb in n["attributes"].get("0/53/7") or []:
                    if not isinstance(nb, dict) or nb.get("0") is None or abs(nb["0"] - ext) > 4096:
                        continue
                    ago = now - (n["radio"] - (nb.get("1") or 0))
                    best = ago if best is None else min(best, ago)
        return best

    def check_heard(self, ext, max_nodes=2):
        """Read now the neighbor table of up to two mains-powered routers that know this
        device (a small read, only when its presence is in doubt). Returns the seconds
        since one of them last heard it, or None."""
        with self.lock:
            cands = []
            for k, n in self.nodes.items():
                a = n["attributes"]
                if n.get("available") is False or a.get("0/53/1") not in (5, 6):
                    continue
                for nb in a.get("0/53/7") or []:
                    if isinstance(nb, dict) and nb.get("0") is not None and abs(nb["0"] - ext) <= 4096:
                        cands.append((nb.get("6") if nb.get("6") is not None else -127, k))
        best = None
        for _, k in sorted(cands, reverse=True)[:max_nodes]:
            try:
                res = self.h.matter_command("read_attribute", {"node_id": int(k, 16), "attribute_path": "0/53/7"},
                                            timeout=30)
            except Exception as err:  # noqa: BLE001
                LOG.debug("read neighbor table of %s: %s", k, err)
                continue
            table = res.get("0/53/7") if isinstance(res, dict) else res
            if not isinstance(table, list):
                continue
            now = time.time()
            with self.lock:
                if k in self.nodes:
                    self.nodes[k]["attributes"]["0/53/7"] = table
                    self.nodes[k]["radio"] = now
            for nb in table:
                if isinstance(nb, dict) and nb.get("0") is not None and abs(nb["0"] - ext) <= 4096:
                    age = nb.get("1") or 0
                    best = age if best is None else min(best, age)
            if best is not None and best <= 120:
                break
        return best

    def _read(self, nid_hex, path):
        res = self.h.matter_command("read_attribute", {"node_id": int(nid_hex, 16), "attribute_path": path}, timeout=30)
        return res.get(path) if isinstance(res, dict) else res

    def resolve_leader(self, names):
        """Find the Thread leader by asking a router: Leader Router ID (0/53/13), then its
        extended address in the router's route table (0/53/8). The Matter Server does not
        forward role changes, so the cached roles cannot tell it. Two small reads.
        names: extended address -> name (Matter nodes and border routers)."""
        with self.lock:
            routers = [k for k, n in self.nodes.items()
                       if n.get("available") is not False and n["attributes"].get("0/53/1") in (5, 6)
                       and n["attributes"].get("0/53/8")]
        for k in routers[:10]:
            try:
                rid = self._read(k, "0/53/13")
                routes = self._read(k, "0/53/8")
            except Exception as err:  # noqa: BLE001
                LOG.debug("leader read on %s: %s", k, err)
                continue
            if not isinstance(rid, int) or not isinstance(routes, list):
                continue
            if not any(isinstance(rt, dict) and rt.get("2") == rid for rt in routes):
                # no route to the leader: the router asked is the leader itself
                try:
                    role = self._read(k, "0/53/1")
                except Exception:  # noqa: BLE001
                    role = None
                if role == 6:
                    with self.lock:
                        own = self.nodes.get(k, {}).get("attributes", {})
                        if k in self.nodes:
                            self.nodes[k]["attributes"]["0/53/1"] = 6
                    ext = ext_of(own)
                    for e, name in names.items():
                        if ext is not None and abs(e - ext) <= 4096:
                            return name
                continue
            with self.lock:
                if k in self.nodes:
                    self.nodes[k]["attributes"]["0/53/8"] = routes
            for rt in routes:
                if isinstance(rt, dict) and rt.get("2") == rid:
                    ext = rt.get("0")
                    if not ext:   # the router asked is the leader itself
                        with self.lock:
                            own = self.nodes.get(k, {}).get("attributes", {})
                        ext = ext_of(own)
                    for e, name in names.items():
                        if ext is not None and abs(e - ext) <= 4096:
                            return name
                    return f"router {rid} (0x{rid << 10:04x})"
        return None

    def resync(self):
        """Full reload with get_nodes (used when the live link is down)."""
        nodes = self.h.matter_command("get_nodes", {}, timeout=120)
        if isinstance(nodes, list):
            for n in nodes:
                self._set_node(n)

    # ------------------------------------------------------------ loop
    def _listen(self, url):
        ws = websocket.create_connection(url, timeout=15)
        try:
            ws.recv()  # server info
            mid = uuid.uuid4().hex[:8]
            ws.send(json.dumps({"message_id": mid, "command": "start_listening"}))
            ws.settimeout(60)
            while not self.w.stop.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    ws.ping()
                    continue
                if not raw:
                    raise ConnectionError("closed")
                msg = json.loads(raw)
                if msg.get("message_id") == mid:
                    if "error_code" in msg:
                        raise RuntimeError(f"{msg.get('error_code')} {msg.get('details')}")
                    with self.lock:
                        self.nodes = {}
                    for n in msg.get("result") or []:
                        self._set_node(n)
                    self.connected, self.since = True, time.time()
                    LOG.info(t("Live link to the Matter Server: {n} nodes", n=len(self.nodes)))
                elif "event" in msg:
                    if msg["event"] == "server_shutdown":
                        raise ConnectionError("server shutdown")
                    self._event(msg)
        finally:
            self.connected = False
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def run(self):
        time.sleep(20)
        delay = 5
        while not self.w.stop.is_set():
            for url in list(self.h.urls):
                try:
                    self._listen(url)
                    delay = 5
                except Exception as err:  # noqa: BLE001
                    LOG.debug("Live link %s: %s", url, err)
                if self.w.stop.is_set():
                    return
            if self.w.stop.wait(delay):
                return
            delay = min(delay * 2, 120)

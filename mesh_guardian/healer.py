# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Automatic recovery of lost Matter nodes.

When a Thread border router changes (restart, update, new leader), the IPv6
prefix of the Thread nodes can change. The Matter Server sometimes keeps using
the old address and the node stays "unavailable" although it still answers in
the mesh. A ping_node request makes the Matter Server resolve the node again
(mDNS) and reach it on its new address.

This module:
- reads from Home Assistant (Core API through the Supervisor) which Matter
  nodes are unavailable and since when;
- pings a node unavailable for `ping_after` seconds (faster right after a
  prefix change), then every `ping_retry` seconds, at most `ping_max_attempts`
  times;
- measures the outcome: back after a ping, back on its own, or given up;
- keeps per-node statistics and publishes everything to MQTT.
"""

import ipaddress
import json
import logging
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import websocket  # websocket-client

from i18n import t

LOG = logging.getLogger("mg.healer")

NODES_TEMPLATE = (
    "{% set ns = namespace(out=[]) %}"
    "{% for d in integration_entities('matter')|map('device_id')|reject('none')|unique %}"
    "{% for i in device_attr(d,'identifiers') if i[0]=='matter' and 'MatterNodeDevice' in i[1] %}"
    "{% set ents = device_entities(d)|reject('match','(button|event)\\.')|list %}"
    "{% set probe = ((ents|select('match','update\\.')|list) + ents)|first %}"
    "{% if probe and states[probe] %}"
    "{% set ns.out = ns.out + [{'node': i[1].split('-')[1], "
    "'name': device_attr(d,'name_by_user') or device_attr(d,'name'), "
    "'area': area_name(d), 'floor': floor_name(area_id(d)) if area_id(d) else none, 'model': device_attr(d,'model'), 'state': states(probe), "
    "'since': as_timestamp(states[probe].last_changed), 'probe': probe, "
    "'custom': device_attr(d,'name_by_user') is not none, "
    "'battery': (device_entities(d)|select('match','sensor\\.')|select('is_state_attr','device_class','battery')|list|length > 0)}] %}"
    "{% endif %}{% endfor %}{% endfor %}{{ ns.out|tojson }}"
)


def short_id(node_hex):
    return "0x" + (node_hex.lstrip("0") or "0")


def n_ping_failed(n):
    return n.get("last_ping_ok") is False


def now_iso_local():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def hhmm(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class Healer:
    def __init__(self, watch, options):
        self.w = watch
        self.enabled = False
        self.enabled_origin = t("default")
        self.ping_after = int(options.get("ping_after", 120))
        self.ping_after_fast = 30
        self.ping_retry = int(options.get("ping_retry", 300))
        self.max_attempts = int(options.get("ping_max_attempts", 6))
        urls = options.get("matter_server_url") or ""
        self.urls = [u for u in [urls, "ws://127.0.0.1:5580/ws", "ws://core-matter-server:5580/ws"] if u]
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        self.lock = threading.RLock()
        self.nodes = {}          # node hex -> dict(name, area, available, since, pings, last_ping, gave_up)
        self.fast_until = 0      # fast reaction after a prefix change
        self._backfilled = False
        self.mass_until = 0      # pause after a global outage (Home Assistant / Matter Server restart)
        self.success = 0         # nodes back after a ping
        self.self_recovered = 0  # nodes back without a ping
        self.failures = 0        # given up after the maximum number of pings
        self.pings_sent = 0
        self.last_result = t("none")
        self.ha_ok = False
        self.matter_ok = None
        self.state_file = "/data/healer_state.json"
        self.rebuild_history = bool(options.get("rebuild_history", True))
        self.ping_all_interval = int(options.get("ping_all_interval", 60)) * 60
        self.sweep = {"date": None, "ok": 0, "total": 0, "unreachable": []}
        self.outages = {}        # node hex -> [[start, end or None, global_outage], ...]
        self.outages_file = "/data/outages.json"
        self._sweep_lock = threading.Lock()
        self.storm = None        # storm detector (storm.py), plugged in by watcher
        self.started = time.time()
        self.session = {"pings_sent": 0, "recovered_by_ping": 0, "back_on_their_own": 0, "gave_up": 0}
        self.recent = []         # [time, kind] of the last 24h (same kinds as self.session)
        self.routing = {"problem": False, "since": None, "announced_unreachable": 0, "details": None}
        self._routing_reported = 0
        self.history_done = False   # 7-day history taken over (or statistics reset): never again
        self._load_state()
        self._load_outages()

    # ------------------------------------------------------------- state
    def _load_state(self):
        try:
            with open(self.state_file) as f:
                st = json.load(f)
            if "enabled" in st:
                self.enabled = st["enabled"]
                self.enabled_origin = t("last state saved, set by the switch")
            self.success = st.get("success", 0)
            self.self_recovered = st.get("self_recovered", 0)
            self.failures = st.get("failures", 0)
            self.pings_sent = st.get("pings_sent", 0)
            self.last_result = st.get("last_result", self.last_result)
            self.recent = [r for r in st.get("recent", []) if r[0] >= time.time() - 86400]
            self.history_done = st.get("history_done", True)
        except Exception:  # noqa: BLE001
            pass

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump({"enabled": self.enabled, "success": self.success,
                           "self_recovered": self.self_recovered, "failures": self.failures,
                           "pings_sent": self.pings_sent, "last_result": self.last_result,
                           "recent": self.recent, "history_done": self.history_done}, f)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot save state: {err}", err=err))

    @staticmethod
    def mass_threshold(total):
        """Nodes dropping together that mean "global outage": 20% of the network, at least 5."""
        return max(5, int(total * 0.2 + 0.999))

    # ------------------------------------------------------------- statistics
    def _load_outages(self):
        try:
            with open(self.outages_file) as f:
                self.outages = json.load(f)
        except Exception:  # noqa: BLE001
            self.outages = {}

    def _save_outages(self):
        cutoff = time.time() - 8 * 86400
        for k in list(self.outages):
            self.outages[k] = [o for o in self.outages[k] if (o[1] or time.time()) >= cutoff]
            if not self.outages[k]:
                del self.outages[k]
        try:
            with open(self.outages_file, "w") as f:
                json.dump(self.outages, f)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot save statistics: {err}", err=err))

    def backfill(self, data):
        """On first start: rebuild 7 days of outages from the Home Assistant history."""
        if self.outages or self.history_done:
            return
        self.history_done = True
        self._save_state()
        if not self.rebuild_history:
            LOG.info(t("Statistics start from zero"))
            return
        probes = {item["probe"]: item["node"].upper() for item in data if item.get("probe")}
        if not probes or not self.token:
            return
        start = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()
        url = ("http://supervisor/core/api/history/period/" + urllib.parse.quote(start)
               + "?minimal_response&no_attributes&filter_entity_id=" + ",".join(probes))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                hist = json.loads(resp.read().decode())
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot read the history: {err}", err=err))
            return
        periods = []
        for series in hist:
            if not series:
                continue
            ent = series[0].get("entity_id")
            node = probes.get(ent)
            down = None
            for st in series:
                ts = datetime.fromisoformat(st["last_changed"]).timestamp()
                if st["state"] == "unavailable" and down is None:
                    down = ts
                elif st["state"] != "unavailable" and down is not None:
                    periods.append([node, down, ts])
                    down = None
            if down is not None:
                periods.append([node, down, None])
        # global outages: many nodes dropping within the same 3-minute window
        starts = sorted(p[1] for p in periods)
        threshold = self.mass_threshold(len(probes))
        for node, a, b in periods:
            mass = sum(1 for x in starts if abs(x - a) <= 180) >= threshold
            self.outages.setdefault(node, []).append([a, b, mass])
        self._save_outages()
        n = sum(1 for p in periods)
        self.w.emit("statistics", t("7-day history: {n} outages", n=n),
                    count=n)

    def reset_stats(self):
        """Every counter and the outage history back to zero (the switch state is kept)."""
        with self.lock:
            self.success = self.self_recovered = self.failures = self.pings_sent = 0
            self.session = dict.fromkeys(self.session, 0)
            self.recent = []
            self.outages = {}
            self.last_result = t("none")
            self.sweep = {"date": None, "ok": 0, "total": 0, "unreachable": []}
            self.started = time.time()
            self.history_done = True
        self._save_state()
        self._save_outages()

    def prune(self, ids):
        """Forget the outages of nodes that no longer exist (ids: set of int node ids)."""
        with self.lock:
            gone = [k for k in self.outages if int(k, 16) not in ids]
            for k in gone:
                del self.outages[k]
        if gone:
            self._save_outages()
        return len(gone)

    def tally(self, kind, n=1):
        """Count an outcome since the start and over a sliding 24h."""
        now = time.time()
        self.session[kind] = self.session.get(kind, 0) + n
        if n > 0:
            self.recent.extend([[now, kind]] * n)
        else:
            for _ in range(-n):   # cancel the latest ones (global return)
                for i in range(len(self.recent) - 1, -1, -1):
                    if self.recent[i][1] == kind:
                        del self.recent[i]
                        break
        self.recent = [r for r in self.recent if r[0] >= now - 86400]

    def last_24h(self):
        now = time.time()
        out = {k: 0 for k in self.session}
        for ts, kind in self.recent:
            if ts >= now - 86400:
                out[kind] = out.get(kind, 0) + 1
        return out

    def node_outages(self, node):
        """(outages 24h, outages 7 days, downtime over 7 days in s) of one node, global outages excluded."""
        now = time.time()
        own = [o for o in self.outages.get(node, []) if not o[2]]
        d24 = sum(1 for o in own if o[0] >= now - 86400)
        d7 = sum(1 for o in own if o[0] >= now - 7 * 86400)
        down7 = sum(min(o[1] or now, now) - max(o[0], now - 7 * 86400) for o in own if (o[1] or now) >= now - 7 * 86400)
        return d24, d7, down7

    def stats(self):
        rows = []
        for node in list(self.outages):
            d24, d7, down7 = self.node_outages(node)
            if d7 == 0:
                continue
            n = self.nodes.get(node, {})
            rows.append({"name": n.get("name", short_id(node)), "area": n.get("area", "?"),
                         "battery": n.get("battery", False), "outages_24h": d24, "outages_7d": d7,
                         "downtime_7d_min": int(down7 // 60),
                         "availability_7d_pct": round(100 - 100 * down7 / (7 * 86400), 2)})
        rows.sort(key=lambda r: (-r["outages_7d"], -r["downtime_7d_min"]))
        return rows

    # ------------------------------------------------------------- sweep
    def ping_all_now(self, origin):
        """Ping every node now, battery nodes and unavailable nodes included (manual button)."""
        if not self._sweep_lock.acquire(blocking=False):
            LOG.info(t("Ping of all nodes already running"))
            return
        try:
            with self.lock:
                targets = sorted(self.nodes, key=lambda k: (self.nodes[k].get("battery", False), self.nodes[k].get("name", "")))
            self.w.emit("ping_all", t("Ping of all nodes: {n} nodes",
                                      origin=origin, n=len(targets)), total=len(targets), origin=origin)
            ok, bad = 0, []
            started = time.time()
            for node in targets:
                if self.w.stop.is_set():
                    return
                n = self.nodes.get(node, {})
                try:
                    res = self.matter_command("ping_node", {"node_id": int(node, 16)}, timeout=60)
                    self._answered(node, res)
                except Exception as err:  # noqa: BLE001
                    res = None
                    if isinstance(err, ConnectionError):
                        LOG.warning(t("Ping of all nodes interrupted: {err}", err=err))
                        return
                self.pings_sent += 1
                self.tally("pings_sent")
                if any((res or {}).values()):
                    ok += 1
                    if not n.get("available", True):
                        n["last_ping"] = time.time()   # a return right after counts as recovered by ping
                else:
                    bad.append(n.get("name", short_id(node)) + (t(", battery") if n.get("battery") else ""))
            self.last_result = t("{time} ping of all nodes: {ok}/{total}", time=hhmm(time.time()), ok=ok, total=len(targets))
            self.w.emit("ping_all_done", t("Ping of all nodes: {ok}/{total} answer", m=int((time.time() - started) // 60),
                                           ok=ok, total=len(targets))
                        + (t("; no answer: {names}", names=", ".join(bad)) if bad else ""),
                        ok=ok, total=len(targets), no_answer=bad, origin=origin)
            self._save_state()
            self.w.dirty = True
        finally:
            self._sweep_lock.release()

    def _answered(self, node, res):
        """A ping answered: it counts as a contact with the node."""
        live = getattr(self.w, "live", None)
        if live and any((res or {}).values()):
            live.note_contact(f"{int(node, 16):016X}", src="ping")

    def sweep_mains(self):
        """Ping every mains-powered node that Home Assistant believes is available."""
        if not self._sweep_lock.acquire(blocking=False):
            return
        try:
            self._sweep_mains()
        finally:
            self._sweep_lock.release()

    def _sweep_mains(self):
        with self.lock:
            targets = [k for k, n in self.nodes.items() if n["available"] and not n.get("battery")]
        if not targets or not self.enabled or time.time() < self.mass_until:
            return
        if self.storm and self.storm.active:
            LOG.info(t("Sweep skipped (storm)"))
            return
        ok, bad = 0, []
        for node in targets:
            if self.w.stop.is_set():
                return
            try:
                res = self.matter_command("ping_node", {"node_id": int(node, 16)}, timeout=60)
                self._answered(node, res)
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Sweep interrupted: {err}", err=err))
                return
            self.pings_sent += 1
            self.tally("pings_sent")
            if any((res or {}).values()):
                ok += 1
            else:
                bad.append(self.nodes.get(node, {}).get("name", short_id(node)))
            time.sleep(2)
        self.sweep = {"date": hhmm(time.time()), "ok": ok, "total": len(targets), "unreachable": bad}
        self.last_result = t("{time} sweep: {ok}/{total}", time=hhmm(time.time()), ok=ok, total=len(targets))
        self.w.emit("sweep", t("Sweep: {ok}/{total} answer", ok=ok, total=len(targets)), ok=ok, total=len(targets), bad=bad)
        self._save_state()
        self.w.dirty = True

    def run_sweeper(self):
        if self.ping_all_interval <= 0:
            return
        self.w.stop.wait(300)
        while not self.w.stop.is_set():
            try:
                self.sweep_mains()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Sweep failed: {err}", err=err))
            if self.w.stop.wait(self.ping_all_interval):
                return

    def set_enabled(self, value, origin):
        value = bool(value)
        if value == self.enabled:
            LOG.info(t("Automatic recovery already {state}",
                       state=t("on") if value else t("off"), origin=origin))
            self.w.dirty = True
            return
        self.enabled = value
        self._save_state()
        self.w.emit("auto_recovery", (t("Automatic recovery on") if self.enabled
                                      else t("Automatic recovery off")),
                    enabled=self.enabled, origin=origin)
        self.w.dirty = True

    def prefix_changed(self):
        """Called when the OMR prefix or the prefix of the nodes changes."""
        self.fast_until = time.time() + 600
        LOG.info(t("Prefix changed: fast pings for 10min"))

    def label(self, node_hex):
        """"Name (area)" of a node according to Home Assistant, or None."""
        n = self.nodes.get(str(node_hex).upper().zfill(16))
        if not n or not n.get("name"):
            return None
        return f"{n['name']} ({n['area']})" if n.get("area") else n["name"]

    def fabric_id(self):
        """Compressed fabric id of Home Assistant, read from the Matter Server."""
        for url in self.urls:
            try:
                ws = websocket.create_connection(url, timeout=10)
                info = json.loads(ws.recv())
                ws.close()
            except Exception:  # noqa: BLE001
                continue
            cfid = info.get("compressed_fabric_id")
            if isinstance(cfid, int):
                return f"{cfid:016X}"
            if isinstance(cfid, str) and cfid:
                return cfid.upper().replace("0X", "").zfill(16)
        return None

    def render_template(self, template):
        """Render a Home Assistant template and return the text (or None)."""
        if not self.token:
            return None
        req = urllib.request.Request(
            "http://supervisor/core/api/template",
            data=json.dumps({"template": template}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode()
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------- HA
    def fetch_ha_nodes(self):
        if not self.token:
            return None
        req = urllib.request.Request(
            "http://supervisor/core/api/template",
            data=json.dumps({"template": NODES_TEMPLATE}).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            self.ha_ok = True
            return data
        except Exception as err:  # noqa: BLE001
            if self.ha_ok:
                LOG.warning(t("Cannot read the nodes from Home Assistant: {err}", err=err))
            self.ha_ok = False
            return None

    # ------------------------------------------------------------- Matter Server
    def matter_command(self, command, args=None, timeout=60, timing=None):
        """Send one command to the Matter Server. timing (dict): receives "ms", the time
        between sending the command and its answer (connection time excluded)."""
        last_err = None
        for url in self.urls:
            try:
                ws = websocket.create_connection(url, timeout=10)
            except Exception as err:  # noqa: BLE001
                last_err = err
                continue
            try:
                ws.settimeout(timeout)
                ws.recv()  # server info, sent on connect
                mid = uuid.uuid4().hex[:8]
                ws.send(json.dumps({"message_id": mid, "command": command, "args": args or {}}))
                sent = time.monotonic()
                deadline = time.time() + timeout
                while time.time() < deadline:
                    msg = json.loads(ws.recv())
                    if msg.get("message_id") != mid:
                        continue
                    if "error_code" in msg:
                        raise RuntimeError(f"{msg.get('error_code')} {msg.get('details')}")
                    self.matter_ok = True
                    if timing is not None:
                        timing["ms"] = round((time.monotonic() - sent) * 1000)
                    if url != self.urls[0]:
                        self.urls.insert(0, self.urls.pop(self.urls.index(url)))
                    return msg.get("result")
                raise TimeoutError("no answer")
            finally:
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
        self.matter_ok = False
        raise ConnectionError(t("Matter Server unreachable ({err})", err=last_err))

    def ping(self, node_hex):
        n = self.nodes[node_hex]
        n["pings"] += 1
        n["last_ping"] = time.time()
        self.pings_sent += 1
        self.tally("pings_sent")
        try:
            result = self.matter_command("ping_node", {"node_id": int(node_hex, 16)}, timeout=90)
            self._answered(node_hex, result)
        except Exception as err:  # noqa: BLE001
            self.w.emit("ping_error", t("Cannot ping {node} {name}: {err}", node=short_id(node_hex), name=n["name"], err=err),
                        node=short_id(node_hex), name=n["name"])
            return
        ok = [ip for ip, v in (result or {}).items() if v]
        ko = [ip for ip, v in (result or {}).items() if not v]
        n["last_ping_ok"] = bool(ok)
        txt = t("answers") if ok else t("does not answer")
        self.last_result = f"{hhmm(time.time())} {n['name']}: {txt} (ping {n['pings']}/{self.max_attempts})"
        self.w.emit("ping", t("Ping {i}/{max} {name}: {result}", i=n["pings"], max=self.max_attempts,
                              name=n["name"], node=short_id(node_hex), area=n["area"], result=txt),
                    node=short_id(node_hex), name=n["name"], area=n["area"], attempt=n["pings"],
                    reachable=ok, unreachable=ko)
        self._save_state()

    # ------------------------------------------------------------- routing (point of view of HA)
    def host_networks(self):
        """IPv4 networks of the host (the add-on shares the host network), cached 10min."""
        if getattr(self, "_hostnets_t", 0) > time.time() - 600:
            return self._hostnets
        nets = []
        try:
            out = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True, timeout=5).stdout
        except Exception:  # noqa: BLE001
            out = ""
        for line in out.splitlines():
            parts = line.split()
            if "inet" not in parts or len(parts) < 2:
                continue
            ifname = parts[1]
            if ifname.startswith(("lo", "docker", "hassio", "veth")):
                continue
            try:
                nets.append(ipaddress.ip_interface(parts[parts.index("inet") + 1]).network)
            except (ValueError, IndexError):
                continue
        self._hostnets, self._hostnets_t = nets, time.time()
        return nets

    def same_subnet(self, addrs):
        """True / False if one IPv4 address is / none is in a network of the host, None if unknown."""
        nets = self.host_networks()
        ip4 = [a for a in addrs or [] if "." in a]
        if not nets or not ip4:
            return None
        return any(ipaddress.ip_address(a) in net for a in ip4 for net in nets)

    def check_routing(self):
        """Nodes announced in mDNS but not answering any ping while most of them are
        unavailable: Home Assistant probably has no route to the Thread network."""
        with self.lock:
            nodes = {k: dict(n) for k, n in self.nodes.items()}
        with self.w.lock:
            announced = {k for k, m in self.w.matter.items() if m.get("online")}
            brs = [(self.w.br_label(b), b.get("addrs", [])) for b in self.w.br.values()
                   if self.w.br_relevant(b) and b.get("online")]
        total = len(nodes)
        down = [k for k, n in nodes.items() if not n["available"]]
        bad = [k for k in down if k in announced and n_ping_failed(nodes[k])]
        problem = total >= 5 and len(down) > total / 2 and len(bad) >= max(3, len(down) // 2)
        if problem and not self.routing["problem"]:
            other = [name for name, addrs in brs if self.same_subnet(addrs) is False]
            nets = ", ".join(str(n) for n in self.host_networks()) or "?"
            txt = t("Thread nodes unreachable from Home Assistant: no route to the Thread network ({bad} nodes)", bad=len(bad), down=len(down))
            if other:
                txt += t("; border routers on another network: {names}",
                         nets=nets, names=", ".join(sorted(other)))
            self.routing = {"problem": True, "since": now_iso_local(), "announced_unreachable": len(bad),
                            "details": txt, "border_routers_other_subnet": sorted(other), "host_networks": nets}
            self.w.emit("routing_problem", txt, unreachable=len(bad), unavailable=len(down),
                        other_subnet=sorted(other), host_networks=nets)
        elif not problem and self.routing["problem"] and len(down) <= total / 4:
            self.routing = {"problem": False, "since": now_iso_local(), "announced_unreachable": 0, "details": None}
            self.w.emit("routing_ok", t("Thread nodes reachable again"))

    # ------------------------------------------------------------- loop
    def cycle(self):
        data = self.fetch_ha_nodes()
        if data is None:
            return
        if not self._backfilled:
            self._backfilled = True
            try:
                self.backfill(data)
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot rebuild statistics: {err}", err=err))
        now = time.time()
        due = []
        events = []  # (kind, text, data, direction) ; direction = "down" / "up"
        with self.lock:
            seen = set()
            for item in data:
                node = item["node"].upper()
                seen.add(node)
                avail = item["state"] != "unavailable"
                since = item.get("since") or now
                n = self.nodes.get(node)
                if n is None:
                    n = {"available": avail, "since": since, "pings": 0, "last_ping": None, "gave_up": False}
                    self.nodes[node] = n
                    first = True
                else:
                    first = False
                n["name"], n["area"] = item.get("name") or short_id(node), item.get("area") or "?"
                n["battery"] = bool(item.get("battery"))
                n["custom"] = bool(item.get("custom"))
                n["model"] = item.get("model") or "?"
                n["floor"] = item.get("floor") or "?"
                if not first and n["available"] != avail:
                    if avail:
                        down = now - n["since"]
                        if n["last_ping"] and now - n["last_ping"] < 600:
                            self.success += 1
                            self.tally("recovered_by_ping")
                            events.append(("node_recovered_by_ping",
                                           t("{name} back after ping {i} ({m}min)",
                                             name=n["name"], area=n["area"], s=int(now - n["last_ping"]),
                                             i=n["pings"], m=int(down // 60)),
                                           dict(node=short_id(node), name=n["name"], area=n["area"],
                                                pings=n["pings"], offline_s=int(down)), "up"))
                        else:
                            self.self_recovered += 1
                            self.tally("back_on_their_own")
                            events.append(("node_back_on_its_own",
                                           t("{name} back on its own ({m}min)", name=n["name"],
                                             area=n["area"], m=int(down // 60)),
                                           dict(node=short_id(node), name=n["name"], area=n["area"],
                                                offline_s=int(down)), "up"))
                        n.update({"pings": 0, "last_ping": None, "gave_up": False, "last_ping_ok": None})
                        self._save_state()
                    else:
                        events.append(("node_unavailable", t("{name} unavailable",
                                                             name=n["name"], area=n["area"]),
                                       dict(node=short_id(node), name=n["name"], area=n["area"]), "down"))
                    n["available"] = avail
                    n["since"] = since
                    lst = self.outages.setdefault(node, [])
                    if not avail:
                        lst.append([since, None, False])
                    elif lst and lst[-1][1] is None:
                        lst[-1][1] = since
                if avail or not self.enabled or n["gave_up"] or now < self.mass_until:
                    continue
                storm = bool(self.storm and self.storm.active)
                wait = self.ping_after_fast if now < self.fast_until and not storm else self.ping_after
                if now - n["since"] < wait:
                    continue
                # during a Thread storm, pings are spaced out: the mesh is busy re-forming
                if n["last_ping"] and now - n["last_ping"] < self.ping_retry * (3 if storm else 1):
                    continue
                if n["pings"] >= self.max_attempts:
                    n["gave_up"] = True
                    self.failures += 1
                    self.tally("gave_up")
                    self.w.emit("ping_gave_up",
                                t("{name}: no answer after {max} pings",
                                  name=n["name"], area=n["area"], max=self.max_attempts),
                                node=short_id(node), name=n["name"], area=n["area"])
                    self._save_state()
                    continue
                due.append(node)
            for gone in set(self.nodes) - seen:
                del self.nodes[gone]
            downs = [e for e in events if e[3] == "down"]
            ups = [e for e in events if e[3] == "up"]
            mass = self.mass_threshold(len(self.nodes))
            if len(downs) >= mass:
                # global outage (Home Assistant or Matter Server restart): no ping for 5min
                self.mass_until = now + 300
                due = []
        if len(downs) >= mass:
            for kind, txt, d, _ in downs:  # not counted in the per-node statistics
                for node, lst in self.outages.items():
                    if lst and lst[-1][1] is None and short_id(node) == d["node"]:
                        lst[-1][2] = True
        if events:
            self._save_outages()
        if len(downs) >= mass:
            self.w.emit("global_outage", t("{n} nodes unavailable together: pings paused 5min", n=len(downs)),
                        count=len(downs), nodes=[d["name"] for _, _, d, _ in downs])
        else:
            for kind, txt, data, _ in downs:
                self.w.emit(kind, txt, **data)
        if len(ups) >= mass:
            # global return after a restart: counted neither as a ping success nor as a self recovery
            own = sum(1 for e in ups if e[0] == "node_back_on_its_own")
            pinged = sum(1 for e in ups if e[0] == "node_recovered_by_ping")
            self.self_recovered -= own
            self.success -= pinged
            self.tally("back_on_their_own", -own)
            self.tally("recovered_by_ping", -pinged)
            self.w.emit("global_return", t("{n} nodes back together", n=len(ups)), count=len(ups))
        else:
            for kind, txt, data, _ in ups:
                self.w.emit(kind, txt, **data)
        # at most 5 pings per cycle (2 during a storm), one after the other
        for node in due[:2 if self.storm and self.storm.active else 5]:
            self.ping(node)
        self.check_routing()
        self.w.dirty = True

    def run(self):
        time.sleep(30)  # let Home Assistant and the Matter Server settle after a start
        while not self.w.stop.wait(15):
            try:
                self.cycle()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Recovery cycle failed: {err}", err=err))

    # ------------------------------------------------------------- MQTT
    def summary(self):
        with self.lock:
            down = sorted((n for n in self.nodes.values() if not n["available"]), key=lambda n: n["since"])
            stats = self.stats()
            return {
                "unavailable": len(down),
                "available": len(self.nodes) - len(down),
                "unavailable_list": [{"node": short_id(k), "name": n["name"], "area": n["area"],
                                      "since": hhmm(n["since"]), "pings": n["pings"], "gave_up": n["gave_up"]}
                                     for k, n in self.nodes.items() if not n["available"]][:40],
                "recovered_by_ping": self.success,
                "since_start": dict(self.session),
                "last_24h": self.last_24h(),
                "started": datetime.fromtimestamp(self.started).astimezone().isoformat(timespec="seconds"),
                "routing": self.routing,
                "back_on_their_own": self.self_recovered,
                "gave_up": self.failures,
                "pings_sent": self.pings_sent,
                "last_ping": self.last_result,
                "auto": "ON" if self.enabled else "OFF",
                "ha_ok": self.ha_ok,
                "matter_server_ok": self.matter_ok,
                "sweep": self.sweep,
                "fragile": [r for r in stats if r["outages_7d"] >= 2][:20],
                "fragile_count": len([r for r in stats if r["outages_7d"] >= 2]),
            }

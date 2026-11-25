# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# © 2026 Pintjes. All rights reserved. See LICENSE.
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

import collections
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
from store import load_json, save_json

LOG = logging.getLogger("mg.healer")
SHORT_LIST_S = 600   # s: a list of nodes far shorter than before is taken as the real one after this time
PING_BUDGET_S = 100  # s: pings of one recovery cycle (a new ping is not started after this time)
CMD_KEEP_S = 24 * 3600   # commands sent to the Matter Server: counted over this window (in memory only)
# commands answered from the Matter Server cache: no radio exchange with a node
CMD_NO_RADIO = frozenset({"get_nodes", "get_node"})
# after the pings gave up, a node is not left alone: pinged again (counter at zero) at a sign of
# life, and once every SLOW_RETRY_S while it stays unavailable (twice that during a storm)
SLOW_RETRY_S = 1800
# a node back within this time after an action on it (automatic ping, ping from the page,
# recovery attempt) is counted "back after <that action>", else "back on its own". It only says
# that the return followed the action, not that the action caused it
AFTER_ACTION_S = 180
ACTION_KINDS = ("auto", "manual", "attempt")

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
        self.mass = None         # last global outage: {"t", "cause": "matter"/"ha"/None, "nodes": [hex]}
        self.ha_down_t = None    # last time Home Assistant did not answer (restart)
        self.success = 0         # nodes back after a ping
        self.self_recovered = 0  # nodes back without a ping
        self.failures = 0        # given up after the maximum number of pings
        self.pings_sent = 0
        self.last_result = t("none")
        self.ha_ok = False
        self.ha_read = False     # the nodes were read from Home Assistant at least once since the start
        self.matter_ok = None
        self.cmd_lock = threading.Lock()
        self.cmd_log = collections.deque()   # (time, command) of every command sent, CMD_KEEP_S
        self.cmd_since = time.time()         # counting starts with the add-on (memory only)
        self.state_file = "/data/healer_state.json"
        self.rebuild_history = bool(options.get("rebuild_history", True))
        self.ping_all_interval = int(options.get("ping_all_interval", 60)) * 60
        self.sweep = {"date": None, "ok": 0, "total": 0, "unreachable": []}
        self.outages = {}        # node hex -> [[start, end or None, global_outage], ...]
        self.outages_file = "/data/outages.json"
        self._sweep_lock = threading.Lock()
        self.storm = None        # storm detector (storm.py), plugged in by watcher
        self.anchor = None       # radio and OMR prefix of the border router of HA (anchor.py), plugged in by watcher
        self.started = time.time()
        self.session = {"pings_sent": 0, "recovered_by_ping": 0, "back_on_their_own": 0, "gave_up": 0,
                        "back_after_auto": 0, "back_after_manual": 0, "back_after_attempt": 0}
        self.recent = []         # [time, kind] of the last 24h (same kinds as self.session)
        self.routing = {"problem": False, "since": None, "announced_unreachable": 0, "details": None}
        self._routing_reported = 0
        self.history_done = False   # 7-day history taken over (or statistics reset): never again
        self._load_state()
        self._load_outages()

    # ------------------------------------------------------------- state
    def _load_state(self):
        try:
            st = load_json(self.state_file, {})
            if not isinstance(st, dict):
                st = {}
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
            # nodes the recovery pings gave up on: kept across a restart (the advice depends on it)
            m = st.get("mass")
            self.mass = m if m and time.time() - m.get("t", 0) < 86400 else None
            self.gave_up_saved = {k: v for k, v in (st.get("gave_up_nodes") or {}).items() if time.time() - v < 7 * 86400}
            # recovery pings already sent to the nodes still unavailable: the count goes on after a restart
            self.pings_saved = {k: v for k, v in (st.get("ping_counts") or {}).items()
                                if v and v[1] and time.time() - v[1] < 86400}
        except Exception as err:  # noqa: BLE001 - a value of an unexpected type: the rest is kept
            LOG.warning(t("Cannot save state: {err}", err=err))

    def _save_state(self):
        try:
            # built under the lock (the nodes change from several threads), and only one writer
            # at a time: two threads writing the same file could mix their contents
            with self.lock:
                data = {"enabled": self.enabled, "success": self.success,
                        "self_recovered": self.self_recovered, "failures": self.failures,
                        "pings_sent": self.pings_sent, "last_result": self.last_result,
                        "recent": list(self.recent), "history_done": self.history_done, "mass": self.mass,
                        "gave_up_nodes": {k: n.get("gave_up_t") or time.time() for k, n in self.nodes.items()
                                          if n.get("gave_up") and not n.get("available")},
                        "ping_counts": {k: [n["pings"], n.get("last_ping")] for k, n in self.nodes.items()
                                        if n.get("pings") and not n.get("gave_up") and not n.get("available")}}
                save_json(self.state_file, data)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot save state: {err}", err=err))

    @staticmethod
    def mass_threshold(total):
        """Nodes dropping together that mean "global outage": 20% of the network, at least 5."""
        return max(5, int(total * 0.2 + 0.999))

    # ------------------------------------------------------------- statistics
    def _load_outages(self):
        data = load_json(self.outages_file, {})
        self.outages = data if isinstance(data, dict) else {}

    def _save_outages(self):
        cutoff = time.time() - 8 * 86400
        try:
            with self.lock:   # the outages are read under the lock by the table and the history
                for k in list(self.outages):
                    self.outages[k] = [o for o in self.outages[k] if (o[1] or time.time()) >= cutoff]
                    if not self.outages[k]:
                        del self.outages[k]
                save_json(self.outages_file, self.outages)
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
        """Count an outcome since the start and over a sliding 24h (under the lock: the sweep, the
        recovery and the actions of the page count from their own threads)."""
        now = time.time()
        with self.lock:
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

    def note_action(self, node_hex, kind):
        """An action was sent to an unavailable node now ("auto", "manual" or "attempt"): a return
        that follows it within AFTER_ACTION_S is counted after that action."""
        with self.lock:
            n = self.nodes.get(str(node_hex).upper().zfill(16))
            if n is not None:
                n["action_t"], n["action"] = time.time(), kind

    def note_sign(self, node_hex, why):
        """A sign of life of a node (it answered a ping of the page or of a recovery attempt): a node
        the pings gave up on is pinged again."""
        with self.lock:
            n = self.nodes.get(str(node_hex).upper().zfill(16))
            if n is not None:
                n["sign_t"], n["sign"] = time.time(), why

    def _signs(self):
        """What the other parts know of the life of the nodes, read before the cycle takes its lock
        (no lock held inside another): node hex -> [(time, why)]."""
        out = {}
        live = getattr(self.w, "live", None)
        try:
            with live.lock:
                for k, ts in live.contacts.items():
                    out.setdefault(k, []).append((ts, t("Matter contact")))
        except Exception:  # noqa: BLE001
            pass
        try:
            with self.w.lock:
                for k, m in self.w.matter.items():
                    if m.get("online") and m.get("since"):
                        out.setdefault(k, []).append((m["since"], t("mDNS announcement back")))
        except Exception:  # noqa: BLE001
            pass
        table = getattr(self.w, "table", None)
        try:
            for k, (ts, info) in dict(table.last_heard()).items():
                out.setdefault(k, []).append((ts, t("heard by {by}", by=(info or {}).get("by") or "?")))
        except Exception:  # noqa: BLE001
            pass
        return out

    @staticmethod
    def sign_of_life(n, signs):
        """Why a node the pings gave up on shows life again since it gave up, or None."""
        since = n.get("gave_up_t") or 0
        if (n.get("sign_t") or 0) > since:
            return n.get("sign") or t("answers the ping")
        late = [why for ts, why in signs if ts and ts > since]
        return late[0] if late else None

    def _ping_counted(self):
        with self.lock:
            self.pings_sent += 1
            self.tally("pings_sent")

    def last_24h(self):
        now = time.time()
        with self.lock:
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
                if n.get("available") is False:
                    self.note_action(node, "manual")
                try:
                    res = self.matter_command("ping_node", {"node_id": int(node, 16)}, timeout=60)
                    self._answered(node, res)
                except Exception as err:  # noqa: BLE001
                    res = None
                    if isinstance(err, ConnectionError):
                        LOG.warning(t("Ping of all nodes interrupted: {err}", err=err))
                        return
                self._ping_counted()
                if any((res or {}).values()):
                    ok += 1
                    if not n.get("available", True):
                        n["last_ping"] = time.time()   # a return right after counts as recovered by ping
                else:
                    bad.append(n.get("name", short_id(node)) + (t(" (battery)") if n.get("battery") else ""))
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
        if self.anchor and self.anchor.blocked():
            LOG.info(t("Sweep skipped: {why}", why=self.anchor.blocked()))
            return
        # a node Home Assistant still lists but the Matter Server no longer knows (removed or
        # reset) is left out: the server would only answer "does not exist"
        live = getattr(self.w, "live", None)
        known = live.node_ids() if live and live.connected else None
        if known:
            targets = [k for k in targets if int(k, 16) in known]
        # less radio traffic: a node that gave a sign of life within the interval of the sweep (a report,
        # a read, a ping, passive contact) is alive: no ping. The sweep looks for the silent ones
        skipped = 0
        if isinstance(getattr(live, "contacts", None), dict):
            now = time.time()
            with live.lock:
                contacts = dict(live.contacts)
            quiet = [k for k in targets if now - (contacts.get(f"{int(k, 16):016X}") or 0) >= self.ping_all_interval]
            skipped, targets = len(targets) - len(quiet), quiet
        if not targets:
            self.sweep = {"date": hhmm(time.time()), "ok": 0, "total": 0, "unreachable": [], "skipped": skipped}
            if skipped:   # said in the log too: the sweep ran, every node was heard (no ping, no radio traffic)
                self.last_result = t("{time} sweep: nothing to ping", time=hhmm(time.time()))
                self.w.emit("sweep", t("Sweep: nothing to ping ({n} heard within the hour)", n=skipped),
                            ok=0, total=0, bad=[], skipped=skipped)
            return
        ok, bad = 0, []
        for node in targets:
            if self.w.stop.is_set():
                return
            try:
                res = self.matter_command("ping_node", {"node_id": int(node, 16)}, timeout=60)
                self._answered(node, res)
            except ConnectionError as err:   # the Matter Server is out of reach: no point going on
                LOG.warning(t("Sweep interrupted: {err}", err=err))
                return
            except Exception as err:  # noqa: BLE001 - this node only: it counts as not answering
                LOG.debug("sweep, %s: %s", node, err)
                res = None
            self._ping_counted()
            if any((res or {}).values()):
                ok += 1
            else:
                bad.append(self.nodes.get(node, {}).get("name", short_id(node)))
            time.sleep(2)
        self.sweep = {"date": hhmm(time.time()), "ok": ok, "total": len(targets), "unreachable": bad, "skipped": skipped}
        self.last_result = t("{time} sweep: {ok}/{total}", time=hhmm(time.time()), ok=ok, total=len(targets))
        self.w.emit("sweep", t("Sweep: {ok}/{total} answer", ok=ok, total=len(targets))
                    + (t(" ({n} heard within the hour, not pinged)", n=skipped) if skipped else ""),
                    ok=ok, total=len(targets), bad=bad, skipped=skipped)
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

    def device_registry(self):
        """Names the user gave in Home Assistant, for the border routers: the devices of the registry
        (config/device_registry/list, name_by_user) and the entries of the OpenThread Border Router
        integration (config_entries/get, domain otbr: their title is the name given there).
        Returns (devices, otbr entries), or None when the registry cannot be read."""
        if not self.token:
            return None
        ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=20)
        try:
            json.loads(ws.recv())   # auth_required
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            if json.loads(ws.recv()).get("type") != "auth_ok":
                return None
            out = []
            msgs = ({"type": "config/device_registry/list"}, {"type": "config_entries/get", "domain": "otbr"},
                    {"type": "thread/list_datasets"})   # the preferred border router (read only)
            for i, msg in enumerate(msgs, 1):
                ws.send(json.dumps({"id": i, **msg}))
                res = json.loads(ws.recv())
                while res.get("id") != i:   # an event in between (none subscribed, but to be safe)
                    res = json.loads(ws.recv())
                result = res.get("result") if res.get("success") else None
                out.append(result.get("datasets") if i == 3 and isinstance(result, dict) else
                           result if isinstance(result, list) else None)
            self.thread_datasets = out[2] if isinstance(out[2], list) else None
            return None if out[0] is None else (out[0], out[1] or [])
        finally:
            ws.close()

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
                self._count_command(command)
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

    def _count_command(self, command, now=None):
        """One command sent to the Matter Server (answered or not). Counting only: no traffic."""
        now = time.time() if now is None else now
        with self.cmd_lock:
            self.cmd_log.append((now, str(command)))
            while self.cmd_log and self.cmd_log[0][0] <= now - CMD_KEEP_S:
                self.cmd_log.popleft()

    def command_counts(self, now=None):
        """Commands sent by this add-on to the Matter Server, by type: last hour (rolling), last
        24 h, and each of the last 24 clock hours. "radio" leaves out the commands answered from
        the cache of the Matter Server (get_nodes…). Since the start of the add-on at most."""
        now = time.time() if now is None else now
        with self.cmd_lock:
            log = [(ts, c) for ts, c in self.cmd_log if ts > now - CMD_KEEP_S]
            since = self.cmd_since

        def count(items):
            out = {}
            for _, c in items:
                out[c] = out.get(c, 0) + 1
            return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

        def radio(by):
            return sum(n for c, n in by.items() if c not in CMD_NO_RADIO)

        hour = count([x for x in log if x[0] > now - 3600])
        day = count(log)
        buckets = {}
        for ts, c in log:
            buckets.setdefault(int(ts // 3600 * 3600), []).append((ts, c))
        hours = [{"t": h, "total": len(v), "radio": radio(count(v)), "by": count(v)} for h, v in sorted(buckets.items())]
        return {"since": since, "hour": {"total": sum(hour.values()), "radio": radio(hour), "by": hour},
                "day": {"total": sum(day.values()), "radio": radio(day), "by": day,
                        "seconds": round(min(CMD_KEEP_S, now - since))},
                "hours": hours}

    def ping(self, node_hex):
        with self.lock:
            n = self.nodes[node_hex]
            slow = bool(n.get("gave_up"))   # the slow retry of a node the pings gave up on: not counted in its 6
            if not slow:
                n["pings"] += 1
            n["last_ping"] = time.time()
            n["action_t"], n["action"] = n["last_ping"], "auto"
        self._ping_counted()
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
        if slow:
            self.last_result = f"{hhmm(time.time())} {n['name']}: {txt} (ping {t('every 30 min')})"
            self.w.emit("ping", t("Ping every 30 min {name}: {result}", name=n["name"], node=short_id(node_hex),
                                  area=n["area"], result=txt),
                        node=short_id(node_hex), name=n["name"], area=n["area"], attempt=0, slow=True,
                        reachable=ok, unreachable=ko)
            if ok:
                self.note_sign(node_hex, t("answers the ping"))   # pings again, counter at zero
        else:
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
        short = data is not None and len(self.nodes) >= 10 and len(data) < len(self.nodes) // 2
        if not short:
            self._short_since = None
        elif not getattr(self, "_short_since", None):
            self._short_since = time.time()
        if data is None or (short and time.time() - self._short_since < SHORT_LIST_S):
            # Home Assistant is starting (its Matter integration not loaded yet): the nodes are
            # not gone, wait for the full list. A short list that lasts is the real one (nodes
            # removed by the user): taken after SHORT_LIST_S, or the recovery would stop for good
            self.ha_down_t = time.time()
            return
        if not self._backfilled:
            self._backfilled = True
            try:
                self.backfill(data)
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot rebuild statistics: {err}", err=err))
        signs = self._signs()   # read before taking the lock
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
                    saved = getattr(self, "gave_up_saved", {}).get(node)
                    if saved and not avail:   # still unavailable after a restart: the pings already gave up
                        n.update({"gave_up": True, "gave_up_t": saved, "pings": 0})
                    sent = getattr(self, "pings_saved", {}).get(node)
                    if sent and not avail and not n["gave_up"]:   # same outage: go on counting
                        n.update({"pings": min(int(sent[0]), self.max_attempts), "last_ping": sent[1]})
                    self.nodes[node] = n
                    first = True
                    # an outage left open (the node came back while the add-on was stopped, or
                    # Home Assistant left it out of a list) ends now that the node is back
                    lst = self.outages.get(node)
                    if avail and lst and lst[-1][1] is None:
                        lst[-1][1] = max(since, lst[-1][0])
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
                        kind = n.get("action") if n.get("action_t") and now - n["action_t"] < AFTER_ACTION_S else None
                        if kind in ACTION_KINDS:
                            # back soon after an action: said "after", never "thanks to" (it may have
                            # come back anyway: the counter of returns on their own tells how often)
                            self.success += 1
                            self.tally("recovered_by_ping")
                            self.tally("back_after_" + kind)
                            s = int(now - n["action_t"])
                            txt = (t("{name} back after ping {i} ({m}min)", name=n["name"], area=n["area"], s=s,
                                     i=n["pings"], m=int(down // 60)) if kind == "auto" and n["pings"] and not n.get("gave_up")
                                   else t("{name} back {s} s after a ping every 30 min ({m}min)", name=n["name"], s=s,
                                          m=int(down // 60)) if kind == "auto"
                                   else t("{name} back {s} s after a ping from the page ({m}min)", name=n["name"], s=s,
                                          m=int(down // 60)) if kind == "manual"
                                   else t("{name} back {s} s after the recovery attempt ({m}min)", name=n["name"], s=s,
                                          m=int(down // 60)))
                            events.append(("node_recovered_by_ping", txt,
                                           dict(node=short_id(node), name=n["name"], area=n["area"], after=kind,
                                                after_s=s, pings=n["pings"], offline_s=int(down)), "up"))
                        else:
                            self.self_recovered += 1
                            self.tally("back_on_their_own")
                            events.append(("node_back_on_its_own",
                                           t("{name} back on its own ({m}min)", name=n["name"],
                                             area=n["area"], m=int(down // 60)),
                                           dict(node=short_id(node), name=n["name"], area=n["area"],
                                                offline_s=int(down)), "up"))
                        n.update({"pings": 0, "last_ping": None, "gave_up": False, "last_ping_ok": None,
                                  "action_t": None, "action": None})
                        self._save_state()
                    else:
                        n["action_t"] = n["action"] = None   # an action before this outage is not one on it
                        events.append(("node_unavailable", t("{name} unavailable",
                                                             name=n["name"], area=n["area"]),
                                       dict(node=short_id(node), name=n["name"], area=n["area"],
                                            node_hex=node), "down"))
                    n["available"] = avail
                    n["since"] = since
                    lst = self.outages.setdefault(node, [])
                    if not avail:
                        lst.append([since, None, False])
                    elif lst and lst[-1][1] is None:
                        lst[-1][1] = since
                if avail or not self.enabled or now < self.mass_until:
                    continue
                storm = bool(self.storm and self.storm.active)
                if n["gave_up"]:
                    # given up: not for good. A sign of life since then -> its pings again (counter at
                    # zero); else one slow ping every SLOW_RETRY_S. The limits below still apply
                    why = self.sign_of_life(n, signs.get(node) or [])
                    if why:
                        n.update({"gave_up": False, "pings": 0, "last_ping": None})
                        events.append(("ping_rearmed", t("{name}: sign of life ({why}), pings again", name=n["name"],
                                                         why=why, area=n["area"]),
                                       dict(node=short_id(node), name=n["name"], area=n["area"], why=why), "info"))
                    else:
                        last = max(n.get("gave_up_t") or 0, n.get("last_ping") or 0)
                        if now - last >= SLOW_RETRY_S * (2 if storm else 1):
                            due.append(node)
                        continue
                wait = self.ping_after_fast if now < self.fast_until and not storm else self.ping_after
                if now - n["since"] < wait:
                    continue
                # during a Thread storm, pings are spaced out: the mesh is busy re-forming
                if n["last_ping"] and now - n["last_ping"] < self.ping_retry * (3 if storm else 1):
                    continue
                if n["pings"] >= self.max_attempts:
                    n["gave_up"], n["gave_up_t"] = True, now
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
            self.ha_read = True   # from now on the counts mean something (published to MQTT)
            downs = [e for e in events if e[3] == "down"]
            ups = [e for e in events if e[3] == "up"]
            mass = self.mass_threshold(len(self.nodes))
            if len(downs) >= mass:
                # global outage (Home Assistant or Matter Server restart): no ping for 5min
                self.mass_until = now + 300
                due = []
                live = getattr(self.w, "live", None)
                lost = getattr(live, "lost_t", None)
                cause = "matter" if lost and now - lost < 300 else \
                    "ha" if self.ha_down_t and now - self.ha_down_t < 300 else None
                self.mass = {"t": min(n_since for n_since in (self.nodes[d[2]["node_hex"]]["since"] for d in downs)),
                             "cause": cause, "nodes": [d[2]["node_hex"] for d in downs]}
                self._save_state()
        if self.anchor and self.anchor.blocked():
            # the radio or the OMR prefix of the border router of HA is out: pinging is pointless,
            # the nodes that drop now get one targeted pass once it is back (catch-up)
            self.anchor.note_dropped([d[2]["node_hex"] for d in downs if d[2].get("node_hex")])
            due = []
        elif self.anchor:
            back = self.anchor.take_catchup(now)
            if back:
                threading.Thread(target=self.catchup, args=(back,), daemon=True, name="catchup").start()
        if len(downs) >= mass:
            for kind, txt, d, _ in downs:  # not counted in the per-node statistics
                d.pop("node_hex", None)
                for node, lst in self.outages.items():
                    if lst and lst[-1][1] is None and short_id(node) == d["node"]:
                        lst[-1][2] = True
        if events:
            self._save_outages()
        if len(downs) >= mass:
            self.w.emit("global_outage", t("{n} nodes unavailable together: pings paused 5min", n=len(downs)),
                        count=len(downs), nodes=[d["name"] for _, _, d, _ in downs])
        else:
            m = self.mass
            for kind, txt, data, _ in downs:
                hexid = data.pop("node_hex", None)
                # stragglers of a restart (down in the next cycles): part of the same restart
                if m and now - m["t"] < 180 and hexid and hexid not in m["nodes"]:
                    m["nodes"].append(hexid)
                self.w.emit(kind, txt, **data)
        if len(ups) >= mass:
            # global return after a restart: counted neither as a ping success nor as a self recovery
            own = sum(1 for e in ups if e[0] == "node_back_on_its_own")
            pinged = [e for e in ups if e[0] == "node_recovered_by_ping"]
            self.self_recovered -= own
            self.success -= len(pinged)
            self.tally("back_on_their_own", -own)
            self.tally("recovered_by_ping", -len(pinged))
            for kind in ACTION_KINDS:
                k = sum(1 for e in pinged if e[2].get("after") == kind)
                if k:
                    self.tally("back_after_" + kind, -k)
            self.w.emit("global_return", t("{n} nodes back together", n=len(ups)), count=len(ups))
        else:
            for kind, txt, data, _ in ups:
                self.w.emit(kind, txt, **data)
        for kind, txt, data, direction in events:
            if direction == "info":
                self.w.emit(kind, txt, **data)
        # at most 5 pings per cycle (2 during a storm), one after the other, and not more than
        # PING_BUDGET_S in all: a ping of a lost node can wait 90 s for its answer, and five in a
        # row kept the next cycle (new outages, nodes back) waiting for minutes. The nodes not
        # pinged stay due: they are pinged in the next cycles.
        start = time.monotonic()
        for node in due[:2 if self.storm and self.storm.active else 5]:
            if time.monotonic() - start >= PING_BUDGET_S:
                break
            self.ping(node)
        self.check_routing()
        self.w.dirty = True

    def catchup(self, nodes):
        """After a cut of the radio or of the OMR prefix: the nodes that dropped meanwhile and are
        still unavailable get their pings back (counter at zero) and one ping now, and only them."""
        with self.lock:
            todo = [k for k in nodes if k in self.nodes and not self.nodes[k]["available"]]
            for k in todo:
                self.nodes[k].update({"pings": 0, "last_ping": None, "gave_up": False})
        if not todo:
            self.w.emit("recovery_catchup", t("Catch-up after the cut: every node that dropped is back"), total=0, back=len(nodes))
            return
        for k in todo:
            if self.w.stop.is_set():
                return
            try:
                self.ping(k)
            except Exception as err:  # noqa: BLE001
                LOG.debug("catch-up, %s: %s", k, err)
        names = [self.nodes.get(k, {}).get("name", short_id(k)) for k in todo]
        self.w.emit("recovery_catchup", t("Catch-up after the cut: {n} nodes pinged ({names})", n=len(todo), names=", ".join(names)),
                    total=len(todo), back=len(nodes) - len(todo), nodes=names)
        self._save_state()
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

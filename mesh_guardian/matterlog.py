# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""What the Matter Server itself says about each node, read in its log.

Home Assistant only shows a node as unavailable after a while. Before that, the Matter
Server already wrote what went wrong: a subscription that got no report in time, a session
closed because the node stopped answering, an address that cannot be reached. Counted per
node over 24 hours, they show the fragile nodes before they drop.

The add-on reads the log of the Matter Server through one stream kept open (Supervisor role
"manager"). A line is read, counted and dropped: no text of the log is kept, only numbers
per node and per hour, and the last address the Matter Server used for the node.

The lines only exist when the Matter Server logs at level "info" (its default) or lower.
"""
import collections
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

from i18n import t
from store import gone_keys, load_json, save_json

LOG = logging.getLogger("mg")

MATTER_SLUG = "core_matter_server"
STATE_FILE = "/data/matter_log.json"
KEEP_H = 25            # hours kept
READ_TIMEOUT = 900     # s without a line: the stream is opened again (a quiet log, nothing lost)
SEEN_KEEP = 200        # last lines kept, against counting twice the lines sent again when the stream reopens
SAVE_S = 300

ANSI = re.compile(r"\x1b\[[0-9;]*m")
NODE = r"@(\d+):([0-9a-fA-F]+)"
P_SUB = re.compile(r"Subscription \S+ to peer " + NODE + r" timed out")
P_SESSION = re.compile(NODE + r"\S* All probes failed, closing session")
P_OFFLINE = re.compile(NODE + r" is offline\b")
P_ONLINE = re.compile(NODE + r" is online\b")
P_RESOLVE = re.compile(NODE + r" Resolving \((address is unreachable|no address known)\)")
P_PING_KO = re.compile(r"Node " + NODE + r" is connected but no pings succeeded")
P_ADDR = re.compile(r"New session with " + NODE + r".*?address: udp://\[([0-9a-fA-F:]+)\]")
# counters of one node in one hour
FIELDS = ("sub", "session", "offline", "offline_s", "unreachable", "ping")


def node_key(m):
    """Node hex as the rest of the add-on writes it, from "@1:7d"."""
    return f"{int(m.group(2), 16):016X}"


class MatterLog:
    def __init__(self, watch=None):
        self.w = watch
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        self.lock = threading.Lock()
        self.hours = {}        # hour (epoch // 3600) -> {node hex: [sub, session, offline, offline_s, unreachable, ping]}
        self.down = {}         # node hex -> since when the Matter Server sees it offline
        self.addr = {}         # node hex -> last address of a new session
        self.opened = {}       # node hex -> times of the sessions opened in the last hour
        self.since = None      # counts are known from this time on
        self.gaps = []         # [start, end] when the log was not read (the counts miss those times)
        self.status = {"ok": False, "since": None, "lines": 0, "used": 0, "error": None, "level": None}
        self._saved = 0
        self.seen = collections.deque(maxlen=SEEN_KEEP)   # last lines read (as suplog.py)
        self._opened = False   # the stream of the current try was opened
        self._load()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            st = load_json(STATE_FILE)
            if not isinstance(st, dict):
                return
            now_h = int(time.time() // 3600)
            self.hours = {int(h): v for h, v in (st.get("hours") or {}).items() if now_h - int(h) < KEEP_H}
            self.addr = st.get("addr") or {}
            self.opened = {k: [x for x in v if time.time() - x < 3600] for k, v in (st.get("opened") or {}).items()}
            self.since = st.get("since")
            self.gaps = [g for g in (st.get("gaps") or []) if time.time() - g[1] < KEEP_H * 3600]
            if st.get("saved"):       # not read while the add-on was stopped
                self.gaps.append([st["saved"], time.time()])
        except Exception as err:  # noqa: BLE001
            LOG.debug("matter log state: %s", err)

    def save(self):
        try:
            with self.lock:   # written as text under the lock: the log follower keeps feeding these
                text = json.dumps({"hours": self.hours, "addr": self.addr, "opened": self.opened, "since": self.since,
                                   "gaps": self.gaps[-20:], "saved": time.time()})
            save_json(STATE_FILE, json.loads(text))
        except (OSError, TypeError, ValueError, RuntimeError) as err:
            LOG.warning(t("Cannot write {file}: {err}", file=STATE_FILE, err=err))
        self._saved = time.time()

    def prune(self, ids):
        """Forget what the log said of nodes that no longer exist (ids: set of int node ids)."""
        n = 0
        with self.lock:
            for d in (self.down, self.addr, self.opened, *self.hours.values()):
                for k in gone_keys(list(d), ids):
                    del d[k]
                    n += 1
        if n:
            self.save()
        return n

    # ------------------------------------------------------------ reading
    def _add(self, nid, field, n=1, now=None):
        now = now or time.time()
        h = int(now // 3600)
        row = self.hours.setdefault(h, {}).setdefault(nid, [0] * len(FIELDS))
        row[FIELDS.index(field)] += n
        for old in [x for x in self.hours if h - x >= KEEP_H]:
            del self.hours[old]

    def feed(self, raw, now=None):
        """One line of the Matter Server log: counted, then dropped."""
        self.status["lines"] += 1
        if "@" not in raw:
            return
        line = ANSI.sub("", raw)
        now = now or time.time()
        with self.lock:
            if self.since is None:
                self.since = now
            m = P_SUB.search(line)
            if m:
                self._add(node_key(m), "sub", now=now)
            elif (m := P_SESSION.search(line)):
                self._add(node_key(m), "session", now=now)
            elif (m := P_OFFLINE.search(line)):
                nid = node_key(m)
                if nid not in self.down:
                    self.down[nid] = now
                    self._add(nid, "offline", now=now)
            elif (m := P_ONLINE.search(line)):
                t0 = self.down.pop(node_key(m), None)
                if t0:
                    self._add(node_key(m), "offline_s", max(0, round(now - t0)), now=now)
            elif (m := P_RESOLVE.search(line)):
                self._add(node_key(m), "unreachable", now=now)
            elif (m := P_PING_KO.search(line)):
                self._add(node_key(m), "ping", now=now)
            elif (m := P_ADDR.search(line)):
                self.addr[node_key(m)] = m.group(3).lower()
                self.opened[node_key(m)] = [x for x in self.opened.get(node_key(m), []) if now - x < 3600][-19:] + [now]
            else:
                return
        self.status["used"] += 1

    # ------------------------------------------------------------ use
    def node(self, nid, now=None):
        """Counts of one node over the last 24 hours, or None when the log is not read."""
        now = now or time.time()
        with self.lock:
            if self.since is None:
                return None
            h_now = int(now // 3600)
            tot = [0] * len(FIELDS)
            for h, nodes in self.hours.items():
                if h_now - h < 24 and nid in nodes:
                    tot = [a + b for a, b in zip(tot, nodes[nid])]
            out = dict(zip(FIELDS, tot))
            t0 = self.down.get(nid)
            if t0:      # still offline for the Matter Server
                out["offline_s"] += max(0, round(now - t0))
                out["offline_since"] = t0
            out["address"] = self.addr.get(nid)
            # sessions opened in the last hour: several of them for a node that is unavailable means
            # that it answers now and then
            out["opened_1h"] = sum(1 for x in self.opened.get(nid, []) if now - x < 3600)
            # the counts only cover the time the log was read
            out["since"] = max(self.since, now - 86400)
            out["missed_s"] = round(sum(max(0, min(e, now) - max(s, now - 86400)) for s, e in self.gaps))
            return out

    def summary(self):
        with self.lock:
            return {**self.status, "known_since": self.since, "hours": len(self.hours),
                    "nodes": len({n for v in self.hours.values() for n in v}), "offline_now": len(self.down)}

    # ------------------------------------------------------------ loop
    def _open(self, path, entries=None, timeout=30):
        headers = {"Authorization": "Bearer " + (self.token or ""), "Accept": "text/plain"}
        if entries:
            headers["Range"] = f"entries=:-{entries}:"
        return urllib.request.urlopen(urllib.request.Request("http://supervisor" + path, headers=headers),
                                      timeout=timeout)

    def _level(self):
        """Log level of the Matter Server: the lines counted here need "info" or lower."""
        try:
            with self._open("/addons/" + MATTER_SLUG + "/info") as r:
                level = ((json.loads(r.read()).get("data") or {}).get("options") or {}).get("log_level")
            self.status["level"] = level
            if level and level not in ("info", "debug", "verbose"):
                LOG.warning(t("Matter Server log level is \"{level}\": the per-node counts need \"info\"", level=level))
        except Exception as err:  # noqa: BLE001
            LOG.debug("Matter Server info: %s", err)

    def _follow(self):
        with self._open("/addons/" + MATTER_SLUG + "/logs/follow", entries=1, timeout=READ_TIMEOUT) as r:
            self._opened = True
            first = not self.status["ok"]
            self.status.update({"ok": True, "error": None, **({"since": time.time()} if first else {})})
            if first:
                LOG.info(t("Matter Server log: followed per node"))
            self.feed_lines(r)

    def feed_lines(self, lines):
        """Lines of the stream: the ones read before (sent again when the stream reopens) are skipped."""
        known = set(self.seen)
        for raw in lines:
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if known:
                if line in known:
                    continue
                known = set()          # past the lines sent again: every line is new
            self.seen.append(line)
            self.feed(line)
            if time.time() - self._saved > SAVE_S:
                self.save()
            if self.w and self.w.stop.is_set():
                return

    def run(self):
        if not self.token:
            self.status["error"] = "no Supervisor token"
            return
        time.sleep(8)
        self._level()
        delay, lost = 10, None
        while not (self.w and self.w.stop.is_set()):
            self._opened = False
            try:
                if lost:
                    with self.lock:
                        self.gaps.append([lost, time.time()])
                        self.down.clear()      # the Matter Server may have restarted: nothing known
                    lost = None
                self._follow()
                delay = 10
            except TimeoutError as err:
                if self._opened:
                    # the stream was open and no line came for READ_TIMEOUT: the log was quiet (at
                    # night), nothing was missed. Opened again at once: no gap, the offline nodes
                    # kept, no new log line, the line sent again not counted twice (feed_lines)
                    continue
                self.status.update({"ok": False, "error": str(err)[:120] or "timeout"})
                LOG.debug("Matter Server log: %s", err)
            except urllib.error.HTTPError as err:
                self.status.update({"ok": False, "error": f"HTTP {err.code}"})
                if err.code in (401, 403):
                    LOG.warning(t("Matter Server log not readable (HTTP {code}): no per-node counts", code=err.code))
                    return
            except Exception as err:  # noqa: BLE001
                self.status.update({"ok": False, "error": str(err)[:120]})
                LOG.debug("Matter Server log: %s", err)
            lost = lost or time.time()
            self.status["ok"] = False
            if not self.w or self.w.stop.wait(delay):
                break
            delay = min(delay * 2, 300)
        self.save()

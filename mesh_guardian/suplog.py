# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Restarts of the Matter Server and of Home Assistant, read in the Supervisor log.

A restart is a fact written by the Supervisor (when, why, which version), not something to
deduce from a dropped link. The add-on only reads: the Supervisor log (one stream kept open,
no polling) and the name and version of the Matter Server. Only the lines about a stop, an
exit, an update or a start of the Matter Server or of Home Assistant are used; nothing else
is kept, and no other add-on is read, started or stopped.

Needs the Supervisor role "manager". Without it (403) or when the log cannot be read, the
restarts are still detected by the live link to the Matter Server (matterlive.py).
"""
import calendar
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

LOG = logging.getLogger("mg")

MATTER_SLUG = "core_matter_server"
BACKLOG = 5000        # lines read at start: the restarts that happened while the add-on was down
KEEP_S = 48 * 3600    # restarts kept
STALE_S = 900         # a stop without a start after this long is not the same restart
READ_TIMEOUT = 900    # s without a line: the stream is opened again

ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:[.,](\d{1,6}))?\s?(Z|[+-]\d\d:?\d\d)?")
P_STOP = re.compile(r"Stopping (?:app|addon)_" + MATTER_SLUG + r" application")
P_EXIT = re.compile(r"(?:App|Add-on|Addon) (.+?) exited with non-zero exit code (-?\d+)")
P_WATCHDOG = re.compile(r"Watchdog found (?:app|add-on|addon) (.+?) (?:exited with code (-?\d+)|is \w+|failed)", re.I)
P_UPDATE = re.compile(r"Updating image (\S+):(\S+) to (\S+):(\S+)")
P_START = re.compile(r"Starting Docker (?:app|add-on|addon) (\S+) with version (\S+)")
P_HA_DOWN = re.compile(r"(?:Restarting homeassistant\b|Stopping homeassistant application)")
P_HA_UP = re.compile(r"Home Assistant Core state changed to APIState\(core_state='RUNNING'")
P_OWN = re.compile(r"/supervisor/logs\S* access from (\S+)")


def stamp(line):
    """(seconds as if the wall time were UTC, offset in s or None when the line gives none)."""
    m = STAMP.match(line)
    if not m:
        return None, None
    naive = calendar.timegm(tuple(int(x) for x in m.groups()[:6]) + (0, 0, 0))
    naive += float("0." + m.group(7)) if m.group(7) else 0
    tz = m.group(8)
    if not tz:
        return naive, None
    if tz == "Z":
        return naive, 0
    sign = -1 if tz[0] == "-" else 1
    digits = tz[1:].replace(":", "")
    return naive, sign * (int(digits[:2]) * 3600 + int(digits[2:4]))


def is_matter_image(image):
    low = image.lower()
    return "matter-server" in low or "matter_server" in low


class SupervisorLog:
    def __init__(self, watch=None):
        self.w = watch
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        self.lock = threading.Lock()
        self.restarts = []    # oldest first: {"who", "t", "up", "cause", "code", "version", "before"}
        self.pending = {}     # who -> what is known of a restart in progress
        self.app_name = "Matter Server"
        self.own_slug = None
        self.tz = None        # offset of the log timestamps when the lines give none
        self.first_t = None   # time of the oldest line read
        self.seen = collections.deque(maxlen=400)   # last lines, against duplicates when the stream reopens
        self.status = {"ok": False, "since": None, "lines": 0, "used": 0, "error": None, "http": None}

    # ------------------------------------------------------------ reading
    def _open(self, path, entries=None, timeout=30):
        headers = {"Authorization": "Bearer " + (self.token or ""), "Accept": "text/plain"}
        if entries:
            headers["Range"] = f"entries=:-{entries}:"
        return urllib.request.urlopen(urllib.request.Request("http://supervisor" + path, headers=headers),
                                      timeout=timeout)

    def _info(self):
        """Name of the Matter Server and slug of this add-on (to recognise its own lines)."""
        for path, key in (("/addons/" + MATTER_SLUG + "/info", "name"), ("/addons/self/info", "slug")):
            try:
                with self._open(path) as r:
                    value = json.loads(r.read()).get("data", {}).get(key)
                if value and key == "name":
                    self.app_name = value
                elif value:
                    self.own_slug = value
            except Exception as err:  # noqa: BLE001
                LOG.debug("Supervisor %s: %s", path, err)

    def _time(self, line, live):
        """Time of a line. Read live, a line is from now; in the backlog its own timestamp counts."""
        naive, off = stamp(line)
        if naive is None:
            return time.time()
        if off is not None:
            return naive - off
        if self.tz is not None:
            return naive - self.tz
        if live:
            return time.time()
        return time.mktime(time.gmtime(naive))   # local time of the add-on

    def _calibrate(self, lines):
        """Timestamps without an offset: the line of our own request was written just now."""
        for line in reversed(lines[-5:]):
            naive, off = stamp(line)
            m = P_OWN.search(line)
            if naive is not None and off is None and m and (not self.own_slug or m.group(1) == self.own_slug):
                self.tz = round((naive - time.time()) / 900) * 900
                return

    def feed(self, raw, live=True):
        """One line of the Supervisor log."""
        line = ANSI.sub("", raw).strip()
        if not line:
            return
        self.status["lines"] += 1
        if "homeassistant" not in line and "atter" not in line and "Home Assistant" not in line:
            return
        ts = self._time(line, live)
        with self.lock:
            done = self._match(line, ts)
        if done:
            self.status["used"] += 1
            if live and self.w and time.time() - done["up"] < 120:
                try:
                    self.w.emit("server_restart", text_of(done, time.strftime("%H:%M", time.localtime(done["t"]))),
                                who=done["who"], cause=done["cause"], code=done.get("code"),
                                version=done.get("version"), before=done.get("before"))
                except Exception as err:  # noqa: BLE001
                    LOG.debug("server_restart event: %s", err)

    def _match(self, line, ts):
        """Follows one restart from its first sign (stop, exit, update) to the start. Returns
        the restart when it is complete."""
        p = self.pending
        for who in list(p):
            if "t" in p[who] and ts - p[who]["t"] > STALE_S:
                del p[who]
        if P_STOP.search(line):
            m = p.setdefault("matter", {})
            m.setdefault("t", ts)
            m.setdefault("requested", True)   # a stop after an exit is the restart of a crash
            return None
        m = P_EXIT.search(line)
        if m:
            if m.group(1) == self.app_name:
                e = p.setdefault("matter", {})
                if "t" not in e:              # exited without being asked to: a crash
                    e.update({"t": ts, "requested": False})
                e["code"] = int(m.group(2))
            return None
        m = P_WATCHDOG.search(line)
        if m:
            if m.group(1) == self.app_name:
                e = p.setdefault("matter", {})
                e.setdefault("t", ts)
                e["requested"] = False
                if m.group(2):
                    e["code"] = int(m.group(2))
            return None
        m = P_UPDATE.search(line)
        if m:
            image = m.group(1)
            who = "matter" if is_matter_image(image) else "ha" if image.endswith("homeassistant") else None
            if who and m.group(2) != m.group(4):
                p.setdefault(who, {})["update"] = (m.group(2), m.group(4))
            return None
        m = P_START.search(line)
        if m:
            if not is_matter_image(m.group(1)):
                return None
            e = p.pop("matter", {})
            return self._done("matter", e, ts, m.group(2))
        if P_HA_DOWN.search(line):
            e = p.setdefault("ha", {})
            e.setdefault("t", ts)
            e.setdefault("requested", True)
            return None
        if P_HA_UP.search(line):
            e = p.pop("ha", None)
            if e and "t" in e:
                return self._done("ha", e, ts, (e.get("update") or (None, None))[1])
        return None

    def _done(self, who, e, up, version):
        upd = e.get("update")
        if "t" not in e:
            cause = "start"            # started without a stop seen (it was stopped)
        elif upd and upd[1] == version:
            cause = "update"
        elif e.get("requested") is False:
            cause = "crash"
        else:
            cause = "requested"
        r = {"who": who, "t": e.get("t", up), "up": up, "cause": cause, "code": e.get("code"),
             "version": version, "before": upd[0] if cause == "update" else None}
        self.restarts = [x for x in self.restarts if up - x["up"] < KEEP_S
                         and not (x["who"] == who and abs(x["up"] - up) < 2)] + [r]
        return r

    # ------------------------------------------------------------ use
    def last(self, now=None):
        """Latest complete restart (Matter Server or Home Assistant) of the last 24 h."""
        now = now or time.time()
        with self.lock:
            for r in reversed(self.restarts):
                if now - r["up"] < 86400:
                    return dict(r)
        return None

    def rules_out(self, when):
        """True when the log was being read at that time and shows no restart then, done or
        in progress: nodes that dropped together did not drop because of a restart."""
        with self.lock:
            if not self.status["ok"] or self.first_t is None or self.first_t > when:
                return False
            if any("t" in e and abs(e["t"] - when) < 300 for e in self.pending.values()):
                return False
            return not any(r["t"] - 120 <= when <= r["up"] + 300 for r in self.restarts)

    def summary(self):
        with self.lock:
            return {**self.status, "restarts": [dict(r) for r in self.restarts],
                    "in_progress": {k: dict(v) for k, v in self.pending.items()}}

    # ------------------------------------------------------------ loop
    def _backlog(self):
        with self._open("/supervisor/logs", entries=BACKLOG, timeout=60) as r:
            self.status["http"] = r.status
            lines = r.read().decode("utf-8", "replace").splitlines()
        self._calibrate([ANSI.sub("", x) for x in lines])
        for line in lines:
            if stamp(ANSI.sub("", line))[0] is not None:
                self.first_t = self._time(ANSI.sub("", line), False)
                break
        for line in lines:
            self.seen.append(line)
            self.feed(line, live=False)
        found = self.summary()["restarts"]
        LOG.info(t("Supervisor log: {n} lines read, {r} restarts found", n=len(lines), r=len(found)))
        for x in found:
            LOG.info("  %s", text_of(x, time.strftime("%d/%m %H:%M:%S", time.localtime(x["t"]))))

    def _follow(self):
        with self._open("/supervisor/logs/follow", entries=100, timeout=READ_TIMEOUT) as r:
            self.status.update({"ok": True, "since": time.time(), "error": None, "http": r.status})
            known = set(self.seen)
            first = True
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if first and line in known:
                    continue                  # already read before the stream opened
                if line not in known:
                    first = False
                self.seen.append(line)
                self.feed(line, live=True)
                if self.w and self.w.stop.is_set():
                    return

    def run(self):
        if not self.token:
            self.status["error"] = "no Supervisor token"
            return
        time.sleep(5)
        self._info()
        delay, read = 10, False
        while not (self.w and self.w.stop.is_set()):
            try:
                if not read:
                    self._backlog()
                    read = True
                self._follow()
                delay = 10
            except urllib.error.HTTPError as err:
                self.status.update({"ok": False, "error": f"HTTP {err.code}", "http": err.code})
                if err.code in (401, 403):
                    LOG.warning(t("Supervisor log not readable (HTTP {code}): restarts are detected by the live link only",
                                  code=err.code))
                    return
            except Exception as err:  # noqa: BLE001
                self.status.update({"ok": False, "error": str(err)[:120]})
                LOG.debug("Supervisor log: %s", err)
            if self.w and self.w.stop.wait(delay):
                return
            if not self.w:
                return
            delay = min(delay * 2, 300)


def text_of(r, at):
    """What happened, in one short sentence."""
    if r["who"] == "ha":
        if r["cause"] == "update" and r.get("version"):
            return t("Home Assistant was updated to {v} at {t}", v=r["version"], t=at)
        return t("Home Assistant restarted at {t}", t=at)
    if r["cause"] == "update" and r.get("version"):
        return t("The Matter Server was updated to {v} at {t}", v=r["version"], t=at)
    if r["cause"] == "crash":
        if r.get("code") is not None:
            return t("The Matter Server crashed at {t} (code {code})", t=at, code=r["code"])
        return t("The Matter Server crashed at {t}", t=at)
    if r["cause"] == "start":
        return t("The Matter Server started at {t}", t=at)
    return t("The Matter Server was restarted at {t}", t=at)

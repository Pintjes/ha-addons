# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""7-day history of every node: availability, parent (or best link), signal and response
time every 15 minutes, for the node panel of the table."""

import json
import logging
import threading
import time

from i18n import t

LOG = logging.getLogger("mg.history")
FILE = "/data/node_history.json"
STEP_S = 15 * 60
KEEP_S = 7 * 86400


class History:
    def __init__(self, watch):
        self.w = watch
        self.lock = threading.Lock()
        self.data = {}   # node hex -> [[t, available, parent, rssi, response ms], ...]
        try:
            with open(FILE) as f:
                self.data = json.load(f)
        except Exception:  # noqa: BLE001
            self.data = {}

    def _save(self):
        try:
            with self.lock:
                text = json.dumps(self.data, separators=(",", ":"))
            with open(FILE, "w") as f:
                f.write(text)
        except OSError as err:
            LOG.warning(t("Cannot write {file}: {err}", file=FILE, err=err))

    @staticmethod
    def _point(r, now):
        router = r.get("role") in ("router", "leader")
        parent = r.get("parent") or (("↔ " + r["best_link"]) if router and r.get("best_link") else None)
        rssi = r.get("rssi") if r.get("rssi") is not None else (r.get("best_rssi") if router else None)
        return [now, bool(r.get("available")), parent, rssi, r.get("rtt_ms")]

    def sample_one(self, nid):
        """One point now for one node, from the table just rebuilt (after a parent search:
        the change shows in the node panel at once, not at the next 15-minute point)."""
        table = getattr(self.w, "table", None)
        rows = ((table.cache or {}).get("rows") or []) if table else []
        rid = f"0x{nid.lstrip('0') or '0'}"
        r = next((x for x in rows if x.get("id") == rid), None)
        if r:
            with self.lock:
                self.data.setdefault(nid, []).append(self._point(r, round(time.time())))

    def sample(self):
        table = getattr(self.w, "table", None)
        rows = ((table.cache or {}).get("rows") or []) if table else []
        if not rows:
            return
        now = round(time.time())
        with self.lock:
            for r in rows:
                try:
                    nid = f"{int(r['id'], 16):016X}"
                except (KeyError, ValueError):
                    continue
                self.data.setdefault(nid, []).append(self._point(r, now))
            cutoff = now - KEEP_S
            for k in list(self.data):
                self.data[k] = [x for x in self.data[k] if x[0] >= cutoff]
                if not self.data[k]:
                    del self.data[k]

    def node(self, nid):
        """Series and outages of one node over 7 days."""
        with self.lock:
            series = list(self.data.get(nid, []))
        h = getattr(self.w, "healer", None)
        outages = []
        if h:
            with h.lock:
                outages = [[o[0], o[1]] for o in h.outages.get(nid, []) if not o[2] and (o[1] or time.time()) >= time.time() - KEEP_S]
        changes, last = [], None
        for x in series:
            if x[2] and x[2] != last:
                if last is not None:
                    changes.append([x[0], last, x[2]])
                last = x[2]
        return {"series": series, "outages": outages, "parent_changes": changes}

    def run(self):
        time.sleep(180)
        while not self.w.stop.is_set():
            try:
                self.sample()
                self._save()
            except Exception as err:  # noqa: BLE001
                LOG.debug("history: %s", err)
            if self.w.stop.wait(STEP_S):
                return

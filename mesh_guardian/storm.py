# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Detection of Thread "storms".

A storm is a period where the mesh keeps falling apart and re-forming: the
network splits into partitions again and again, several OMR prefixes coexist,
and many nodes drop. Pinging during a storm only adds traffic, so the recovery
slows down (healer.py) and the hourly sweep is skipped until it is over.

A storm starts when, over a sliding window of 15 minutes, one threshold is
exceeded; it ends after 15 minutes without any.
"""

import time
from datetime import datetime

from i18n import t

WINDOW = 15 * 60
THRESHOLDS = {"splits": 3, "omr_prefixes": 3, "nodes_down": 15}   # "more than"
CALM = 15 * 60


def iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


class Storm:
    def __init__(self, watch):
        self.w = watch
        self.active = False
        self.splits = []        # times of partition splits
        self.downs = []         # [time, node name]
        self.start = None
        self.end = None
        self.calm_since = None
        self.nodes = set()      # nodes that dropped during the storm
        self.brs_detached = set()
        self.prefixes = set()
        self.peak = {"splits": 0, "omr_prefixes": 0, "nodes_down": 0}
        self.count = 0
        self.last = None        # summary of the last storm

    def reset(self):
        """Forget past storms (a storm in progress keeps going)."""
        self.count = 0
        self.last = None

    # ---------------------------------------------------------- inputs
    def observe(self, kind, data):
        """Called for every event of the add-on."""
        now = time.time()
        if kind == "partition_change" and len(data.get("after") or []) > max(1, len(data.get("before") or [])):
            self.splits.append(now)
        elif kind == "node_unavailable":
            self.downs.append([now, data.get("name") or data.get("node")])
        elif kind == "global_outage" and self.active:
            # a mass drop is not counted (a restart of Home Assistant looks the same), only listed
            self.nodes.update(data.get("nodes") or [])

    # ---------------------------------------------------------- check
    def check(self, summary):
        now = time.time()
        self.splits = [x for x in self.splits if x >= now - WINDOW]
        self.downs = [d for d in self.downs if d[0] >= now - WINDOW]
        values = {"splits": len(self.splits), "omr_prefixes": len(summary.get("omr_list") or []),
                  "nodes_down": len({d[1] for d in self.downs})}
        hot = [k for k, v in values.items() if v > THRESHOLDS[k]]
        if self.active:
            for k, v in values.items():
                self.peak[k] = max(self.peak[k], v)
            self.nodes.update(d[1] for d in self.downs)
            self.prefixes.update(summary.get("omr_list") or [])
            with self.w.lock:
                for b in self.w.br.values():
                    if self.w.br_relevant(b) and b.get("role") == "detached":
                        self.brs_detached.add(self.w.br_label(b))
        if hot and not self.active:
            # the storm started with the first event counted, not when the threshold was crossed
            first = [x for x in self.splits] + [d[0] for d in self.downs]
            self.active, self.start, self.end, self.calm_since = True, min(first) if first else now, None, None
            self.count += 1
            self.peak = dict(values)
            self.nodes = {d[1] for d in self.downs}
            self.prefixes = set(summary.get("omr_list") or [])
            self.brs_detached = set()
            self.w.emit("storm_start", t("Thread storm: {why}", why=", ".join(self._why(values, hot))),
                        **values, reasons=hot)
        elif self.active and not hot:
            self.calm_since = self.calm_since or now
            if now - self.calm_since >= CALM:
                self.active, self.end = False, self.calm_since
                self.last = self.attributes()
                self.w.emit("storm_end", t("End of the Thread storm ({m}min, {n} nodes dropped)",
                                           m=int((self.end - self.start) // 60), n=len(self.nodes), s=self.peak["splits"],
                                           p=len(self.prefixes), brs=", ".join(sorted(self.brs_detached)) or t("none")),
                            duration_min=int((self.end - self.start) // 60), nodes=sorted(self.nodes),
                            border_routers_detached=sorted(self.brs_detached), prefixes=sorted(self.prefixes))
        elif self.active:
            self.calm_since = None
        self.values = values

    @staticmethod
    def _why(values, hot):
        txt = {"splits": t("{n} partition splits in 15min"), "omr_prefixes": t("{n} OMR prefixes at the same time"),
               "nodes_down": t("{n} nodes unavailable in 15min")}
        return [txt[k].format(n=values[k]) for k in hot]

    # ---------------------------------------------------------- MQTT
    def attributes(self):
        end = self.end or time.time()
        return {"start": iso(self.start), "end": iso(self.end) if not self.active else None,
                "duration_min": int((end - self.start) // 60) if self.start else 0,
                "nodes": sorted(self.nodes)[:60], "nodes_count": len(self.nodes),
                "border_routers_detached": sorted(self.brs_detached), "prefixes": sorted(self.prefixes),
                "peak": dict(self.peak)}

    def summary(self):
        cur = getattr(self, "values", {})
        out = {"state": "ON" if self.active else "OFF", "storms_since_start": self.count,
               "now": cur, "thresholds": THRESHOLDS}
        if self.active:
            out.update(self.attributes())
        else:
            out["last_storm"] = self.last
        return out

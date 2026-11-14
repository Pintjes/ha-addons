# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Radio quality of the Thread mesh, read from the Matter Server.

Every Thread node exposes (Thread Network Diagnostics cluster, endpoint 0):
- 0/53/1  routing role (2 sleepy end device, 3 end device, 4 REED, 5 router, 6 leader)
- 0/53/4  extended PAN id of its Thread network
- 0/53/7  neighbor table: extended address (0), age (1), RLOC16 (2), LQI (5),
          average RSSI (6), last RSSI (7), frame error rate (8), is child (13)
- 0/53/14..21 counters: detached, child, router, leader, attach attempts,
          partition changes, better partition, parent changes (since the last
          reboot of the node)
and (General Diagnostics) 0/51/0 network interfaces (hardware address = Thread
extended address), 0/51/2 uptime.

The module reads all of this periodically (get_nodes: values cached by the
Matter Server, no radio traffic), works out who is neighbor / parent of whom,
finds weak links and computes the instability of every node (detaches, parent
and partition changes) as the difference between two surveys.
"""

import base64
import json
import logging
import threading
import time
from datetime import datetime

from i18n import t, tn
from nodetable import ext_of, find_parents

LOG = logging.getLogger("mg.radio")

ROLE = {0: "unspecified", 1: "unassigned", 2: "sleepy_end_device", 3: "end_device", 4: "reed",
        5: "router", 6: "leader"}
COUNTERS = {"14": "detached", "15": "child", "16": "router", "17": "leader", "18": "attach_attempts",
            "19": "partition_changes", "20": "better_partition", "21": "parent_changes"}
WEAK_RSSI = -85   # same threshold as the red of the node table
EPISODE_MIN_NODES = 5   # detaches of at least this many nodes in one survey interval:
EPISODE_SHARE = 0.2     # (or this share of the nodes) are one network episode
HISTORY_FILE = "/data/radio_history.json"
TOPOLOGY_FILE = "/share/mesh_guardian/topology.json"


def _g(d, key, default=None):
    """Field of a Matter struct: numeric key ("6") or name."""
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    return default


def ext_from_b64(value):
    try:
        raw = base64.b64decode(value)
        return int.from_bytes(raw, "big") if len(raw) == 8 else None
    except Exception:  # noqa: BLE001
        return None


class Radio:
    def __init__(self, watch, healer, options):
        self.w = watch
        self.h = healer
        self.interval = int(options.get("radio_interval", 30)) * 60
        self.last = None          # last survey
        self.advisor = None       # radio advice (advice.py), plugged in by watcher
        self.live = None          # live copy of the Matter Server cache (matterlive.py)
        self.leader_name, self.leader_t, self.leader_partitions = None, 0, None
        self._survey_lock = threading.Lock()
        self.history = []         # counter snapshots: [{"t": ts, "nodes": {hex: {counters, uptime}}}]
        self.ok = None
        self._load()

    def _load(self):
        try:
            with open(HISTORY_FILE) as f:
                self.history = json.load(f)
        except Exception:  # noqa: BLE001
            self.history = []

    def _save(self):
        cutoff = time.time() - 8 * 86400
        self.history = [h for h in self.history if h["t"] >= cutoff]
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.history, f)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot save the radio history: {err}", err=err))

    def reset(self):
        """Forget the counter history: the 24h columns start again from the next survey."""
        self.history = []
        self._save()

    # ------------------------------------------------------------------ noms
    def _names(self):
        """Extended address -> name (Matter nodes, and border routers via their "xa" TXT record)."""
        names = {}
        with self.w.lock:
            for b in self.w.br.values():
                if b.get("xa") is not None:
                    names[b["xa"]] = self.w.br_display(b)
        return names

    @staticmethod
    def _match(ext, table):
        """The Matter Server may round 64-bit integers (JSON): allow a small tolerance."""
        if ext is None:
            return None
        if ext in table:
            return table[ext]
        for k, v in table.items():
            if abs(k - ext) <= 4096:
                return v
        return None

    # ------------------------------------------------------------------ survey
    def survey(self):
        with self._survey_lock:
            return self._survey()

    def reference(self, now=None, min_age=3600, max_age=26 * 3600):
        """Snapshot of about 24h ago (or the oldest one at least 1h old)."""
        now = now or time.time()
        ref = None
        for h in self.history:
            if now - h["t"] >= min_age:
                ref = h
                if now - h["t"] <= max_age:
                    break
        return ref

    def own_detaches(self, ref):
        """Detaches per node since `ref`, without the survey intervals where many nodes
        detached together (one network episode: border router restart, storm...)."""
        snaps = [h for h in self.history if h["t"] >= ref["t"]]
        own = {}
        for prev, cur in zip(snaps, snaps[1:]):
            deltas = {}
            for nid, c in cur["nodes"].items():
                p = prev["nodes"].get(nid)
                if not p:
                    continue
                a, b = (c.get("c") or {}).get("detached"), (p.get("c") or {}).get("detached")
                if a is None or b is None:
                    continue
                d = a if (c.get("u") or 0) < (p.get("u") or 0) else max(0, a - b)
                if d:
                    deltas[nid] = d
            if len(deltas) >= max(EPISODE_MIN_NODES, EPISODE_SHARE * len(cur["nodes"])):
                continue
            for nid, d in deltas.items():
                own[nid] = own.get(nid, 0) + d
        return own

    def _survey(self):
        if self.live and self.live.connected:
            nodes = self.live.snapshot()   # same values, already received: no request at all
        else:
            nodes = self.h.matter_command("get_nodes", {}, timeout=120)
        if not isinstance(nodes, list):
            raise RuntimeError("unexpected get_nodes answer")
        now = time.time()
        meta = {}
        with self.h.lock:
            for k, n in self.h.nodes.items():
                meta[k] = (n.get("name", k), n.get("area", "?"), n.get("battery", False), n.get("model", "?"),
                           n.get("floor", "?"))
        ext_names = self._names()
        info = {}
        raw = {}
        for node in nodes:
            nid = f"{int(node.get('node_id', 0)):016X}"
            attrs = node.get("attributes") or {}
            if attrs.get("0/53/1") is None:
                continue  # not Thread (Wi-Fi, or not interviewed yet)
            name, area, battery, model, floor = meta.get(nid, (f"0x{nid.lstrip('0')}", "?", False, "?", "?"))
            ext = None
            for itf in attrs.get("0/51/0") or []:
                if _g(itf, "7") == 4 or _g(itf, "0") == attrs.get("0/53/2"):
                    ext = ext_from_b64(_g(itf, "4"))
            info[nid] = {
                "name": name, "area": area, "floor": floor, "battery": battery, "model": model,
                "available": node.get("available"),
                "role": ROLE.get(attrs.get("0/53/1"), str(attrs.get("0/53/1"))),
                "ext": ext, "uptime": attrs.get("0/51/2"), "ext_pan": attrs.get("0/53/4"),
                "reboots": attrs.get("0/51/1"), "boot": attrs.get("0/51/4"),
                "counters": {v: attrs.get(f"0/53/{k}") for k, v in COUNTERS.items()},
                "neighbors": attrs.get("0/53/7") or [],
            }
            raw[nid] = {"name": name, "attrs": attrs}
            if ext is not None:
                ext_names[ext] = name
        # liens
        links = {}
        parents = {}
        heard = 0
        for nid, n in info.items():
            for nb in n["neighbors"]:
                peer = self._match(_g(nb, "0"), ext_names) or f"unknown {(_g(nb, '2') or 0):04x}"
                rssi = _g(nb, "6")
                lqi = _g(nb, "5")
                if rssi is None:
                    continue
                heard += 1
                # LQI 0 = neighbor only overheard, no link established: ignored
                if not (lqi or _g(nb, "13")):
                    continue
                key = tuple(sorted((n["name"], peer)))
                cur = links.get(key)
                if cur is None or rssi < cur["rssi"]:
                    links[key] = {"a": key[0], "b": key[1], "rssi": rssi, "lqi": lqi,
                                  "errors_pct": round((_g(nb, "8") or 0) / 100, 1) if _g(nb, "8") else 0}
        found, _rlocs, best = find_parents(raw, ext_names)
        for nid, (parent, rssi, lqi, key) in found.items():
            parents[info[nid]["name"]] = {"parent": parent, "rssi": rssi, "lqi": lqi, "key": str(key)}
        # weak links: only the links in use (child -> parent, router -> its best link)
        used = [{"a": info[nid]["name"], "b": p[0], "rssi": p[1], "lqi": p[2]} for nid, p in found.items()]
        used += [{"a": info[nid]["name"], "b": l[0], "rssi": l[1], "lqi": l[2]} for nid, l in best.items()
                 if nid not in found]
        weak = sorted((l for l in used if l["rssi"] is not None and (l["rssi"] <= WEAK_RSSI or l["lqi"] == 1)),
                      key=lambda l: l["rssi"])
        # instability: difference with the survey of ~24h ago (or the oldest available)
        snapshot = {nid: {"c": n["counters"], "u": n["uptime"], "r": n["reboots"]} for nid, n in info.items()}
        self.history.append({"t": now, "nodes": snapshot})
        self._save()
        ref = self.reference(now)
        unstable = []
        span_h = round((now - ref["t"]) / 3600, 1) if ref else 0
        own = self.own_detaches(ref) if ref else {}
        if ref:
            for nid, n in info.items():
                old = ref["nodes"].get(nid)
                if not old:
                    continue
                # reboot counter (the cached uptime can be stale); a software update is not instability
                reboots = (max(0, n["reboots"] - old["r"]) if n.get("reboots") is not None
                           and old.get("r") is not None else 0)
                rebooted = reboots > 0
                if reboots and n.get("boot") == 5:
                    reboots -= 1
                d = {}
                for k in ("detached", "parent_changes", "partition_changes", "attach_attempts"):
                    a, b = n["counters"].get(k), (old["c"] or {}).get(k)
                    if a is None or b is None:
                        continue
                    d[k] = a if rebooted else max(0, a - b)
                score = d.get("detached", 0) * 3 + d.get("partition_changes", 0) * 2 + d.get("parent_changes", 0)
                if score or reboots:
                    unstable.append({"name": n["name"], "area": n["area"], "role": n["role"],
                                     "detaches": d.get("detached", 0), "own_detaches": own.get(nid, 0),
                                     "parent_changes": d.get("parent_changes", 0),
                                     "partition_changes": d.get("partition_changes", 0),
                                     "rebooted": rebooted, "reboots": reboots, "score": score})
        unstable.sort(key=lambda x: -x["score"])
        roles = {}
        for n in info.values():
            roles[n["role"]] = roles.get(n["role"], 0) + 1
        self.last = {
            "t": now, "thread_nodes": len(info), "roles": roles, "links": len(links),
            "weak_links": weak, "parents": parents, "unstable": unstable, "period_h": span_h,
            "leaders": sorted(n["name"] for n in info.values() if n["role"] == "leader"),
            "names": sorted({n["name"] for n in info.values() if n.get("name")}),
        }
        self.ok = True
        if self.advisor:
            try:
                self.advisor.update(info, parents, unstable)
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot compute radio advice: {err}", err=err))
        try:
            with open(TOPOLOGY_FILE, "w") as f:
                json.dump({"date": datetime.now().isoformat(timespec="seconds"),
                           "nodes": {k: {kk: vv for kk, vv in v.items() if kk != "neighbors"} | {"ext": hex(v["ext"]) if v["ext"] else None}
                                     for k, v in info.items()},
                           "links": list(links.values()), "parents": parents}, f, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass
        worst = weak[0] if weak else None
        # Thread networks used by the Home Assistant nodes (border router filter)
        nets = {int(n["ext_pan"]) for n in info.values() if isinstance(n.get("ext_pan"), int)}
        if nets:
            self.w.set_ha_networks(nets)
        self.w.emit("radio_survey",
                    t("Radio survey: {n} nodes, {weak}",
                      n=len(info), weak=tn("{n} weak link", "{n} weak links", len(weak)))
                    + (t(" (worst: {a} ↔ {b} {rssi}dBm)", a=worst["a"], b=worst["b"], rssi=worst["rssi"]) if worst else "")
                    + (t(", most unstable: {name} ({d} detach)" if unstable[0]["detaches"] == 1 else ", most unstable: {name} ({d} detaches)",
                         name=unstable[0]["name"], d=unstable[0]["detaches"]) if unstable else ""),
                    weak=len(weak), links=len(links), unstable=len(unstable))
        self.w.dirty = True

    def mesh_leader(self):
        """Names of the Matter nodes that are Thread leader (current values when possible)."""
        if self.leader_name and time.time() - self.leader_t < 2400:
            return [self.leader_name]
        if self.live and self.live.connected:
            with self.h.lock:
                return sorted((self.h.nodes.get(k) or {}).get("name") or f"0x{k.lstrip('0')}"
                              for k in self.live.leaders())
        return sorted((self.last or {}).get("leaders", []))

    def check_leader(self):
        """When no border router is leader, ask the mesh who is (after a partition change,
        and every 30 minutes)."""
        s = self.w.summary()
        if not s["partitions"] or s["leaders_count"]:
            self.leader_name = None   # no network, or a border router is leader (known from mDNS)
            return
        parts = tuple(s["partition_ids"])
        if self.leader_name and parts == self.leader_partitions and time.time() - self.leader_t < 1800:
            return
        with self.w.lock:
            names = {b["xa"]: self.w.br_label(b) for b in self.w.br.values() if b.get("xa") is not None}
        with self.h.lock:
            meta = {k: n.get("name") for k, n in self.h.nodes.items()}
        for n in self.live.snapshot():
            ext = ext_of(n["attributes"])
            if ext is not None:
                nid = f"{n['node_id']:016X}"
                names[ext] = meta.get(nid) or f"0x{nid.lstrip('0')}"
        name = self.live.resolve_leader(names)
        if name:
            self.leader_name, self.leader_t, self.leader_partitions = name, time.time(), parts
            self.w.dirty = True

    def run_leader(self):
        time.sleep(120)
        while not self.w.stop.is_set():
            if self.live and self.live.connected:
                try:
                    self.check_leader()
                except Exception as err:  # noqa: BLE001
                    LOG.debug("leader: %s", err)
            if self.w.stop.wait(60):
                return

    def run(self):
        time.sleep(90)
        while True:
            try:
                self.survey()
            except Exception as err:  # noqa: BLE001
                self.ok = False
                LOG.warning(t("Radio survey failed: {err}", err=err))
            try:
                self.w.br_thread_refresh()
                self.w.prune_gone()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cleanup failed: {err}", err=err))
            if self.w.stop.wait(self.interval):
                return

    def summary(self):
        r = self.last or {}
        return {
            "weak_links": len(r.get("weak_links", [])),
            "weak_links_list": [f"{l['a']} ↔ {l['b']}: {l['rssi']}dBm, LQI {l['lqi']}"
                                for l in r.get("weak_links", [])[:25]],
            "parents": {k: f"{v['parent']} ({'?' if v['rssi'] is None else v['rssi']}dBm)" for k, v in list(r.get("parents", {}).items())[:60]},
            "unstable": len(r.get("unstable", [])),
            "unstable_list": [t("{name} ({area}, {role}): {d} detaches, {p} parent changes, {q} partition changes",
                                name=u["name"], area=u["area"], role=t(u["role"]), d=u["detaches"],
                                p=u["parent_changes"], q=u["partition_changes"])
                              + (t(" [rebooted]") if u["rebooted"] else "")
                              for u in r.get("unstable", [])[:15]],
            "period_h": r.get("period_h", 0),
            "roles": {t(k): v for k, v in r.get("roles", {}).items()},
            "thread_nodes": r.get("thread_nodes", 0),
            "survey_time": datetime.fromtimestamp(r["t"]).strftime("%H:%M") if r.get("t") else None,
            "ok": self.ok,
        }

# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Network quality score, response times of the nodes and passive contact detection.

Probe: reads the UpTime of each node (General Diagnostics 0/51/2) through the Matter
Server and times the answer. It gives the response time of the node, a fresh uptime
and a contact. Mains-powered nodes every 15 min, battery nodes every hour.

Sniffer (option passive_contact): every IPv6 packet sent by a node and seen on the
host counts as a contact, including unchanged reports that the Matter Server does not
forward and the answers to pings sent by Home Assistant. Only the source address is
read (Matter traffic is encrypted).

Score: one sample per minute, score over a sliding hour (24h in the attributes).
  availability 50 %, radio 25 %, outages 10 %, backbone 10 %, partition 5 %
  (capped at 70 % when the network stays partitioned 5 min or more).
"""

import logging
import socket
import threading
import time
from collections import deque

from advice import weak_link
from i18n import t
from store import gone_keys, load_json, save_json

LOG = logging.getLogger("mg.quality")
STATE_FILE = "/data/quality.json"

PROBE_MAINS_S = 15 * 60
PROBE_MAINS_QUIET_S = 60 * 60   # a mains node that gave a sign of life of its own since the last read (report,
                                # passive contact, ping…) within PROBE_MAINS_S: read only this often
PROBE_BATTERY_S = 60 * 60
PROBE_RETRY_S = 2 * 60
NEIGHBOR_REFRESH_S = 60 * 60   # mains nodes: role and neighbor table read again at most hourly   # first new try after a failed read
PROBE_GAP_S = 5            # between two reads
STARTUP_MAX_S = 20 * 60    # the startup reread of the Thread tables gives up after this
REREAD_GAP_S = 5 * 60      # page reread: at most once every 5 minutes
REREAD_WORKERS = 3         # page reread: nodes read at the same time
RTT_KEEP = 20              # answers kept for the average

SAMPLE_S = 60
WINDOW_1H = 60
WINDOW_24H = 1440
WEIGHTS = {"availability": 50, "radio": 25, "outages": 10, "backbone": 10, "partition": 5}
PARTITION_CAP = 70
PARTITION_CAP_SAMPLES = 5
ETH_P_IPV6 = 0x86DD
PACKET_OUTGOING = 4


def color(score):
    if score is None:
        return None
    return "good" if score >= 90 else "mid" if score >= 80 else "bad"


class Quality:
    def __init__(self, watch, healer, live, options):
        self.w, self.h, self.live = watch, healer, live
        self.lock = threading.RLock()
        self.rtt = {}            # node hex -> {"last": ms|None, "ok": [ms...], "t": ts, "fails": n}
        self.samples = deque(maxlen=WINDOW_24H)
        self.passive = bool(options.get("passive_contact", False))
        self.sniffing = False
        self.sniffed = 0
        self._counted = None     # outages already counted (None: first sample, nothing counted)
        self.tables_ready = False  # Thread tables of the mains nodes read again since the start
        self.reread = {"running": False, "t": 0, "done": 0, "total": 0}   # page reread
        self._load()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            st = load_json(STATE_FILE, {}) or {}
            self.rtt = st.get("rtt", {})
            cutoff = time.time() - WINDOW_24H * SAMPLE_S
            self.samples.extend(s for s in st.get("samples", []) if s["t"] >= cutoff)
        except Exception:  # noqa: BLE001
            pass

    def _save(self):
        try:
            with self.lock:   # a copy: the probes add to these lists while the file is written
                data = {"rtt": {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                                for k, v in self.rtt.items()}, "samples": list(self.samples)}
            save_json(STATE_FILE, data)
        except (OSError, TypeError, ValueError, RuntimeError) as err:
            LOG.warning(t("Cannot write {file}: {err}", file=STATE_FILE, err=err))

    def prune(self, ids):
        """Forget the responses of nodes that no longer exist (ids: set of int node ids)."""
        with self.lock:
            gone = gone_keys(list(self.rtt), ids)
            for k in gone:
                del self.rtt[k]
        if gone:
            self._save()
        return len(gone)

    def reset(self):
        with self.lock:
            self.rtt = {}
            self.samples.clear()
        self._save()

    # ------------------------------------------------------------ probe
    def response(self, nid):
        """(last response in ms, average in ms, last read failed) of a node."""
        with self.lock:
            r = self.rtt.get(nid)
            if not r:
                return None, None, False
            ok = r.get("ok") or []
            return r.get("last"), (round(sum(ok) / len(ok)) if ok else None), bool(r.get("t")) and r.get("last") is None

    def read_times(self, nid):
        """(time of the last response read, time of the last uptime read), None when never."""
        with self.lock:
            r = self.rtt.get(nid) or {}
            return r.get("t") or None, r.get("up_t")

    def uptime(self, nid):
        """Uptime in s from the last read plus the time since (survives restarts), or None."""
        with self.lock:
            r = self.rtt.get(nid) or {}
            if r.get("up") is None:
                return None
            return r["up"] + (time.time() - r["up_t"])

    def _due(self):
        now = time.time()
        storm = bool(getattr(self.w, "storm", None) and self.w.storm.active)
        if storm or now < self.h.mass_until or not self.live.connected:
            return None
        known = self.live.node_ids()
        with self.h.lock:
            nodes = [(k, n) for k, n in self.h.nodes.items() if n["available"] and int(k, 16) in known]
        contacts = {}
        if isinstance(getattr(self.live, "contacts", None), dict):
            with self.live.lock:
                contacts = dict(self.live.contacts)
        best = None
        with self.lock:
            for k, n in nodes:
                every = PROBE_BATTERY_S if n.get("battery") else PROBE_MAINS_S
                r = self.rtt.get(k) or {}
                last = r.get("t") or 0
                # less radio traffic: a mains node that showed a sign of life of its own since our last read
                # (not the read itself), within the usual gap, is read hourly only (its tables stay hourly)
                seen = contacts.get(f"{int(k, 16):016X}") or 0
                if not n.get("battery") and seen > last + 5 and now - seen < PROBE_MAINS_S:
                    every = PROBE_MAINS_QUIET_S
                if r.get("streak"):
                    # last read failed (node switched off, out of reach…): retry soon once it is
                    # available again, then back off (2, 4, 8… min) so a node that keeps failing costs little
                    every = min(every, PROBE_RETRY_S * 2 ** (r["streak"] - 1))
                if now - last >= every and (best is None or last < best[1]):
                    best = (k, last, bool(n.get("battery")))
        return best

    def probe(self, nid, battery):
        timing = {}
        try:
            res = self.h.matter_command("read_attribute", {"node_id": int(nid, 16), "attribute_path": "0/51/2"},
                                        timeout=120 if battery else 30, timing=timing)
            value = res.get("0/51/2") if isinstance(res, dict) else res
            ok = "ms" in timing
        except Exception as err:  # noqa: BLE001
            LOG.debug("probe %s: %s", nid, err)
            value, ok = None, False
        with self.lock:
            r = self.rtt.setdefault(nid, {"last": None, "ok": [], "t": 0, "fails": 0})
            r["t"] = time.time()
            if ok:
                if isinstance(value, (int, float)):
                    r["up"], r["up_t"] = value, r["t"]
                r["last"], r["streak"] = timing["ms"], 0
                r["ok"] = (r.get("ok") or [])[-(RTT_KEEP - 1):] + [timing["ms"]]
            else:
                r["last"] = None
                r["fails"] = r.get("fails", 0) + 1
                r["streak"] = r.get("streak", 0) + 1
        if ok:
            self._refresh_thread(nid, battery)
        if ok:
            self.live.note_contact(nid, src="read")
            if isinstance(value, (int, float)):
                self.live.set_attribute(nid, "0/51/2", value)

    def reread_all(self):
        """Page opened or Refresh pressed: read every available node again, battery ones
        included (response time, uptime, contact; role and tables of the Thread nodes), a few
        at a time. At most once every REREAD_GAP_S, never during a storm or a mass drop.
        Returns True when a reread starts."""
        now = time.time()
        storm = bool(getattr(self.w, "storm", None) and self.w.storm.active)
        if storm or now < self.h.mass_until or not self.live.connected:
            return False
        with self.live.lock:
            thread = {k for k, n in self.live.nodes.items() if n["attributes"].get("0/53/1") is not None}
            known = set(self.live.nodes)
        with self.h.lock:
            todo = [(k, bool(n.get("battery")), f"{int(k, 16):016X}" in thread) for k, n in self.h.nodes.items()
                    if n["available"] and f"{int(k, 16):016X}" in known]
        todo.sort(key=lambda x: x[1])   # mains nodes first: they answer at once
        with self.lock:
            if self.reread["running"] or now - self.reread["t"] < REREAD_GAP_S or not todo:
                return False
            self.reread = {"running": True, "t": now, "done": 0, "total": len(todo)}
        threading.Thread(target=self._reread, args=(todo,), daemon=True, name="reread").start()
        return True

    def _reread(self, todo):
        queue = list(todo)

        def worker():
            while not self.w.stop.is_set():
                if getattr(self.w, "storm", None) and self.w.storm.active:
                    return
                with self.lock:
                    if not queue:
                        return
                    nid, battery, thread = queue.pop(0)
                try:
                    if thread and not battery:
                        with self.lock:
                            self.rtt.setdefault(nid, {"last": None, "ok": [], "t": 0, "fails": 0})["thr_t"] = 0
                    if battery:   # its tables are read just below, not twice
                        with self.lock:
                            self.rtt.setdefault(nid, {"last": None, "ok": [], "t": 0, "fails": 0})["thr_t"] = time.time()
                    self.probe(nid, battery)   # mains Thread nodes: tables read too
                    if battery and thread:
                        with self.lock:
                            awake = (self.rtt.get(nid) or {}).get("last") is not None
                        if awake:   # it just answered: role and parent link
                            self._read_paths(nid, ("0/53/1", "0/53/7", "0/51/0"), 120)   # table and RLOC16 together
                except Exception as err:  # noqa: BLE001
                    LOG.debug("reread %s: %s", nid, err)
                finally:
                    with self.lock:
                        self.reread["done"] += 1
                    table = getattr(self.w, "table", None)
                    if table is not None:
                        table.cache_t = 0

        try:
            workers = [threading.Thread(target=worker, daemon=True, name="reread-w") for _ in range(REREAD_WORKERS)]
            for th in workers:
                th.start()
            for th in workers:
                th.join()
        finally:
            with self.lock:
                self.reread["running"] = False

    def reading(self):
        """Reread in progress for the page: None, or {"done", "total"} (startup: done/total unknown)."""
        with self.lock:
            if self.reread["running"]:
                return {"done": self.reread["done"], "total": self.reread["total"]}
        return None if self.tables_ready else {"done": None, "total": None}

    def _read_paths(self, nid, paths, timeout=30):
        """Every path in ONE read (one exchange with the node instead of one per path: less radio
        traffic). The Matter Server answers {path: value}."""
        paths = list(paths)
        try:
            res = self.h.matter_command("read_attribute", {"node_id": int(nid, 16),
                                                           "attribute_path": paths if len(paths) > 1 else paths[0]},
                                        timeout=timeout)
        except Exception as err:  # noqa: BLE001
            LOG.debug("thread read %s %s: %s", nid, paths, err)
            return
        if not isinstance(res, dict):
            res = {paths[0]: res} if len(paths) == 1 else {}
        for path in paths:
            value = res.get(path)
            if value is not None:
                self.live.set_attribute(nid, path, value)

    def _refresh_thread(self, nid, battery=False):
        """Read again, at most hourly, the values a node does not report by itself (some never
        report their tables again, e.g. after becoming an end device): without it the Matter
        Server cache keeps an old value and nothing tells how old it is. The read updates
        that cache.
        Mains Thread node: role, neighbor and route tables, addresses, counters.
        Battery Thread node: role, neighbor table and addresses only, right after its hourly response
        read, while it is awake (no wake-up added).
        Wi-Fi node: its signal."""
        now = time.time()
        with self.live.lock:
            attrs = (self.live.nodes.get(nid) or {}).get("attributes") or {}
            thread = attrs.get("0/53/1") is not None
            wifi = not thread and any(k.startswith("0/54/") for k in attrs)
        if thread and battery:
            paths = ("0/53/1", "0/53/7", "0/51/0")   # table and RLOC16 together: the parent comes from both
        elif thread:
            # role, neighbors, routes (the link a router sends through comes from both tables: read
            # together, they agree), addresses (RLOC16), counters (detaches, partition and parent changes)
            paths = ("0/53/1", "0/53/7", "0/53/8", "0/51/0", "0/53/14", "0/53/19", "0/53/21")
        elif wifi and not battery:
            paths = ("0/54/4",)
        else:
            return
        with self.lock:
            r = self.rtt.setdefault(nid, {"last": None, "ok": [], "t": 0, "fails": 0})
            if now - (r.get("thr_t") or 0) < NEIGHBOR_REFRESH_S - 120:
                return
            r["thr_t"] = now
        self._read_paths(nid, paths, 120 if battery else 30)

    def startup_tables(self):
        """At start, read again the Thread tables of every mains node: the values read before
        the restart are gone and the Matter Server cache can be hours old (wrong parents, weak
        links missed). The first radio survey waits for it. Never for battery nodes."""
        end = time.time() + STARTUP_MAX_S
        try:
            while not self.live.connected and time.time() < end:
                if self.w.stop.wait(5):
                    return
            with self.live.lock:
                thread = {k for k, n in self.live.nodes.items() if n["attributes"].get("0/53/1") is not None}
            with self.h.lock:
                todo = [k for k, n in self.h.nodes.items() if n["available"] and not n.get("battery")
                        and f"{int(k, 16):016X}" in thread]
            done = 0
            for nid in todo:
                while getattr(self.w, "storm", None) and self.w.storm.active and time.time() < end:
                    if self.w.stop.wait(10):
                        return
                if time.time() >= end or not self.live.connected:
                    break
                with self.lock:
                    self.rtt.setdefault(nid, {"last": None, "ok": [], "t": 0, "fails": 0})["thr_t"] = 0
                self._refresh_thread(nid)
                done += 1
                if self.w.stop.wait(PROBE_GAP_S):
                    return
            LOG.info(t("Thread tables read again: {n}/{total} nodes", n=done, total=len(todo)))
        except Exception as err:  # noqa: BLE001
            LOG.debug("startup tables: %s", err)
        finally:
            self.tables_ready = True

    def run_probe(self):
        time.sleep(90)
        self.startup_tables()
        saved = time.time()
        while not self.w.stop.is_set():
            due = None
            try:
                due = self._due()
                if due:
                    self.probe(due[0], due[2])
                if time.time() - saved > 600:
                    saved = time.time()
                    self._save()
            except Exception as err:  # noqa: BLE001
                LOG.debug("probe: %s", err)
            if self.w.stop.wait(PROBE_GAP_S if due else 20):
                return

    # ------------------------------------------------------------ sniffer
    def run_sniffer(self):
        if not self.passive:
            return
        try:
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(ETH_P_IPV6))
            sock.settimeout(2)
        except (OSError, AttributeError) as err:
            LOG.warning(t("Passive contact unavailable: {err}", err=err))
            return
        self.sniffing = True
        LOG.info(t("Passive contact on: every packet of a node counts as a contact"))
        addrs, refreshed, seen = {}, 0, {}
        while not self.w.stop.is_set():
            now = time.time()
            if now - refreshed > 60:
                refreshed = now
                addrs = {a: k for k, lst in self.live.addresses().items() for a in lst}
            try:
                pkt, info = sock.recvfrom(128)
            except socket.timeout:
                continue
            except OSError as err:
                LOG.warning(t("Passive contact stopped: {err}", err=err))
                break
            if len(pkt) < 40 or (len(info) > 2 and info[2] == PACKET_OUTGOING):
                continue
            nid = addrs.get(bytes(pkt[8:24]))
            if nid is None:
                continue
            self.sniffed += 1
            if now - seen.get(nid, 0) >= 10:   # one contact every 10 s per node is enough
                seen[nid] = now
                self.live.note_contact(nid, now, src="passive")
        self.sniffing = False
        sock.close()

    # ------------------------------------------------------------ score
    def _links(self):
        """(used links, weak ones): parent link of a child, first hop of a router."""
        table = getattr(self.w, "table", None)
        rows = ((table.cache or {}).get("rows") or []) if table else []
        used = weak = 0
        for r in rows:
            if not r.get("available") or r.get("network", "thread") != "thread":
                continue
            router = r.get("role") in ("router", "leader")
            rssi, lqi = (r.get("rssi"), r.get("lqi")) if r.get("parent") else \
                ((r.get("best_rssi"), r.get("best_lqi")) if router else (None, None))
            if rssi is None and lqi is None:
                continue
            used += 1
            if weak_link(rssi, lqi):
                weak += 1
        return used, weak

    def sample(self):
        now = time.time()
        if now < self.h.mass_until or not self.h.ha_ok:
            return   # Home Assistant / Matter Server restart: not the network
        with self.h.lock:
            total = len(self.h.nodes)
            down = sum(1 for n in self.h.nodes.values() if not n["available"])
            new = {f"{k}:{o[0]}" for k, lst in self.h.outages.items() for o in lst
                   if not o[2] and o[0] >= now - 3600}
        starts = len(new - self._counted) if self._counted is not None else 0
        self._counted = new
        if not total:
            return
        s = self.w.summary()
        used, weak = self._links()
        with self.lock:
            self.samples.append({
                "t": round(now), "nodes": total, "down": down, "cuts": starts,
                "used": used, "weak": weak,
                "br": s["br_online"], "br_total": s["br_total"],
                "leader": s["leader"] not in (t("none"), t("unknown")),
                "parts": s["partitions"],
            })

    def score(self, window):
        with self.lock:
            sm = list(self.samples)[-window:]
        if not sm:
            return None
        avail = sum(1 - x["down"] / x["nodes"] for x in sm) / len(sm)
        cuts = sum(x["cuts"] for x in sm) / (sum(x["nodes"] for x in sm) / len(sm)) * (WINDOW_1H / len(sm))
        used = sum(x["used"] for x in sm)
        weak_share = sum(x["weak"] for x in sm) / used if used else 0
        bb = sum((x["br"] / x["br_total"] if x["br_total"] else 0) * (1 if x["leader"] else 0.5) for x in sm) / len(sm)
        parted = sum(1 for x in sm if x["parts"] > 1)
        sub = {
            # 1 node out of 20 unavailable the whole time: 75
            "availability": max(0.0, 1 - 5 * (1 - avail)),
            "radio": max(0.0, 1 - 2 * weak_share),
            # outages per node and per hour: 1 outage per 10 nodes and per hour gives 0
            "outages": max(0.0, 1 - 10 * cuts),
            "backbone": bb,
            "partition": 1 - parted / len(sm),
        }
        total = sum(WEIGHTS[k] * v for k, v in sub.items())
        capped = parted >= PARTITION_CAP_SAMPLES and total > PARTITION_CAP
        if capped:
            total = PARTITION_CAP
        return {"score": round(total, 1), "parts": {k: round(100 * v, 1) for k, v in sub.items()},
                "capped": capped, "minutes": len(sm), "since": sm[0]["t"]}

    def run_score(self):
        # not before the start is over: border routers and leader are still being found
        time.sleep(300)
        while not self.w.stop.is_set():
            try:
                self.sample()
                self.w.dirty = True
            except Exception as err:  # noqa: BLE001
                LOG.debug("quality sample: %s", err)
            if self.w.stop.wait(SAMPLE_S):
                self._save()
                return

    def summary(self):
        h1, h24 = self.score(WINDOW_1H), self.score(WINDOW_24H)
        with self.lock:
            rtts = [r["last"] for r in self.rtt.values() if r.get("last") is not None]
        return {
            "score": h1["score"] if h1 else None,
            "color": color(h1["score"]) if h1 else None,
            "parts": h1["parts"] if h1 else None,
            "capped": h1["capped"] if h1 else False,
            "minutes": h1["minutes"] if h1 else 0,
            "score_24h": h24["score"] if h24 else None,
            "parts_24h": h24["parts"] if h24 else None,
            "passive_contact": self.sniffing,
            "probed_nodes": len(rtts),
            "median_response_ms": sorted(rtts)[len(rtts) // 2] if rtts else None,
        }

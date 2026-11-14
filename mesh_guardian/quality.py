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

import json
import logging
import socket
import threading
import time
from collections import deque

from i18n import t

LOG = logging.getLogger("mg.quality")
STATE_FILE = "/data/quality.json"

PROBE_MAINS_S = 15 * 60
PROBE_BATTERY_S = 60 * 60
PROBE_GAP_S = 5            # between two reads
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
        self._load()

    # ------------------------------------------------------------ state
    def _load(self):
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            self.rtt = st.get("rtt", {})
            cutoff = time.time() - WINDOW_24H * SAMPLE_S
            self.samples.extend(s for s in st.get("samples", []) if s["t"] >= cutoff)
        except Exception:  # noqa: BLE001
            pass

    def _save(self):
        try:
            with self.lock:
                data = {"rtt": self.rtt, "samples": list(self.samples)}
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except OSError as err:
            LOG.warning(t("Cannot write {file}: {err}", file=STATE_FILE, err=err))

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
        best = None
        with self.lock:
            for k, n in nodes:
                every = PROBE_BATTERY_S if n.get("battery") else PROBE_MAINS_S
                last = (self.rtt.get(k) or {}).get("t") or 0
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
                r["last"] = timing["ms"]
                r["ok"] = (r.get("ok") or [])[-(RTT_KEEP - 1):] + [timing["ms"]]
            else:
                r["last"] = None
                r["fails"] = r.get("fails", 0) + 1
        if ok:
            self.live.note_contact(nid, src="read")
            if isinstance(value, (int, float)):
                self.live.set_attribute(nid, "0/51/2", value)

    def run_probe(self):
        time.sleep(90)
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
        """(used links, weak ones): parent link of a child, best link of a router."""
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
            if (rssi is not None and rssi <= -85) or lqi == 1:
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

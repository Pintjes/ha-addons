# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# © 2026 Pintjes. All rights reserved. See LICENSE.
"""The radio and the OMR prefix of the OpenThread border router of Home Assistant.

Read on MQTT, never acted on directly:
- `thread_anchor/state` (Thread Anchor add-on): the OMR prefix the border router is kept on
  (`wanted`, `enforced`, `error`) and the one the whole network favors (`favored`). Before
  Thread Anchor, USB/IP Link published the same fields under "omr" of `usbip_link/state`:
  still read when Thread Anchor says nothing.
- `usbip_link/state` (USB/IP Link add-on): the radio plugged into another computer.

What is done with it:
- pause: while the radio is cut off, or the prefix is no longer in place with an error,
  pinging lost nodes is pointless (the cause is known): the recovery waits;
- catch-up: once radio and prefix are back, one targeted pass on the nodes that dropped
  during the cut, and only them;
- report: OMR prefix changes and lost nodes per day, before and since the anchoring;
- takeover: the other border routers (Google TV) favored their own prefix again;
- proposal: Thread Anchor installed without a prefix: the current OMR prefix of the network
  is proposed (nothing to renumber) and written into its options on a click.
"""

import ipaddress
import json
import logging
import os
import threading
import time
import urllib.request
import uuid
from datetime import datetime

from i18n import t, tn
from store import load_json, save_json

LOG = logging.getLogger("mesh_guardian")

ANCHOR_TOPIC = "thread_anchor/state"
ANCHOR_AVAIL_TOPIC = "thread_anchor/state/available"
DIAG_REQUEST_TOPIC = "thread_anchor/diag/request"    # Thread diagnostic of one node, run by Thread Anchor (ot-ctl)
DIAG_RESULT_TOPIC = "thread_anchor/diag/result/"    # + request id
CHILDREN_TOPIC = "thread_anchor/children"   # retained: the children Thread Anchor learned in its searches
CHILDREN_KEEP_S = 24 * 3600   # an entry older than this is not used (the child may have changed parent)
DIAG_WAIT_S = 130       # one answer: 15 s for a known RLOC16, but a search by ext / ML-EID runs the
                         # meshdiag scan of Thread Anchor (90 s budget) plus its other steps: 90 + 15 + margin
DIAG_BUSY_WAIT_S = 120   # "busy" (another diagnostic runs): asked again for this long
DIAG_BUSY_RETRY_S = 10   # every this often
ANCHOR_FILE = "/data/anchor.json"
ANCHOR_SUFFIX = "_thread_anchor"   # slug of the add-on in the Supervisor: <repository hash>_thread_anchor
CATCHUP_SETTLE_S = 60   # after the return of radio and prefix: time left to the nodes to follow
RETAINED_GRACE_S = 60   # a retained state (sent again by the broker when MG connects) can be old: an
#                         error in it waits this long for a live state before it pauses the recovery or is said
REPORT_DAYS = 7         # days of the event log read before the anchoring
REPORT_EVERY_S = 600    # the report is computed again this often (it reads the event log)
OMR_EPISODE_S = 1800    # OMR changes this close together are one episode (a burst of the border routers)


def day_of(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def parse_iso(s):
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except (TypeError, ValueError):
        return None


def _num(v):
    """A number given as a number or as text (hex with 0x, else hex for 16 digits, else decimal)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v or "").strip().lower()
    try:
        if s.startswith("0x"):
            return int(s, 16)
        return int(s, 16) if len(s) == 16 or any(c in "abcdef" for c in s) else int(s)
    except ValueError:
        return None


def omr_episodes(times):
    """Times of OMR changes -> start of each episode (changes within OMR_EPISODE_S of the previous one)."""
    out, last = [], None
    for x in sorted(times):
        if last is None or x - last > OMR_EPISODE_S:
            out.append(x)
        last = x
    return out


def read_events(paths, since, kinds):
    """(time, type, data) of the events of these kinds since `since`, from the event log files."""
    out = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not any(k in line for k in kinds):
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    ts = parse_iso(e.get("t"))
                    if ts is not None and ts >= since and e.get("type") in kinds:
                        out.append((ts, e["type"], e))
        except OSError:
            continue
    return sorted(out, key=lambda x: x[0])


class Anchor:
    def __init__(self, watch, clock=time.time, event_files=None):
        self.w = watch
        self.clock = clock
        self.lock = threading.RLock()
        self.state = None            # thread_anchor/state, last message
        self.available = None        # thread_anchor/state/available: True / False / None (never heard)
        self.blocked_since = None    # radio or prefix out: recovery paused since
        self.block_reason = None
        self.retained_t = None       # state or availability known only from a retained message, since (None: live)
        self.dropped = set()         # nodes that dropped while blocked: the catch-up pass
        self.catchup_at = None       # time of the catch-up pass (blocked ended + settle)
        self.takeover_since = None   # the other border routers favor their own prefix since
        self.anchored_since = None   # first time the prefix was in place
        self.event_files = event_files or []
        self._report, self._report_t = None, 0
        self.slug = None
        self._diag_waits = {}        # request id -> [Event, result]
        self.children = {}           # extended address -> {"rloc16", "parent", "rssi", "lqi", "t"} (thread_anchor/children)
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self):
        d = load_json(ANCHOR_FILE)
        self.anchored_prefix = None   # the prefix anchored_since is about
        if isinstance(d, dict):
            try:
                self.anchored_since = float(d["anchored_since"]) if d.get("anchored_since") else None
                self.anchored_prefix = d.get("prefix") if isinstance(d.get("prefix"), str) else None
            except (TypeError, ValueError):
                self.anchored_since = None

    def _save(self):
        try:
            save_json(ANCHOR_FILE, {"anchored_since": self.anchored_since, "prefix": self.anchored_prefix})
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot write {file}: {err}", file=ANCHOR_FILE, err=err))

    # ------------------------------------------------------------ MQTT
    def _heard(self, retained):
        """A retained message (sent again by the broker when MG connects, e.g. after a restart of
        Home Assistant) may be old: noted, so an error in it waits for a live state (RETAINED_GRACE_S).
        A live message ends that wait."""
        if retained:
            if self.retained_t is None:
                self.retained_t = self.clock()
        else:
            self.retained_t = None

    def on_state(self, payload, retained=False):
        try:
            data = json.loads(payload) if payload else None
        except ValueError:
            return
        with self.lock:
            self.state = data if isinstance(data, dict) else None
            self._heard(retained)
        self.update()

    def on_available(self, payload, retained=False):
        txt = (payload.decode() if isinstance(payload, bytes) else str(payload or "")).strip().lower()
        with self.lock:
            self.available = True if txt == "online" else False if txt == "offline" else None
            self._heard(retained)
        self.update()

    def on_children(self, payload):
        """thread_anchor/children (Thread Anchor 0.1.11, version 1): the nodes Thread Anchor learned in its
        searches (meshdiag, child tables), no radio traffic of its own:
        {"version": 1, "nodes": {"<ext, 16 hex>": {"rloc16": "0x6c05", "parent": "0x6c00" | null, "role":
        "child" | "router", "read_at": ISO, "signal": {...}}}}. Only the children are kept. "signal" is
        measured toward the border router of Home Assistant, not toward the node's parent: never used
        as the signal of its link. Read leniently (also "children", a list of entries with "ext")."""
        try:
            data = json.loads(payload) if payload else None
        except ValueError:
            return
        items = (data.get("nodes") if isinstance(data.get("nodes"), (dict, list)) else data.get("children")) \
            if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = [dict(v, ext=k) for k, v in items.items() if isinstance(v, dict)]
        out = {}
        for e in items if isinstance(items, list) else []:
            if not isinstance(e, dict):
                continue
            ext, rloc = _num(e.get("ext")), _num(e.get("rloc16"))
            if ext is None or rloc is None or not rloc & 0x3FF or e.get("role") == "router":
                continue   # no address, or a router (not a child)
            parent = _num(e.get("parent"))
            when = e.get("read_at", e.get("t"))
            when = when if isinstance(when, (int, float)) else parse_iso(when)
            out[ext] = {"rloc16": rloc, "parent": parent if parent is not None else rloc & 0xFC00,
                        "rssi": e.get("rssi") if isinstance(e.get("rssi"), (int, float)) else None,
                        "lqi": e.get("lqi") if isinstance(e.get("lqi"), int) else None, "t": when}
        with self.lock:
            self.children = out

    def child(self, ext, now=None):
        """What Thread Anchor learned of this child (by extended address), when it is recent enough."""
        if ext is None:
            return None
        now = self.clock() if now is None else now
        with self.lock:
            e = self.children.get(ext)
            if e is None:   # the Matter Server may round 64-bit integers
                e = next((v for k, v in self.children.items() if abs(k - ext) <= 4096), None)
        if e is None or (e["t"] is not None and now - e["t"] > CHILDREN_KEEP_S):
            return None
        return e

    # ------------------------------------------------------------ Thread diagnostic of one node
    def diag_ready(self):
        """Thread Anchor publishes and is not stopped: it can run a diagnostic."""
        return isinstance(self.state, dict) and self.available is not False

    def diag(self, rloc16, ext=None, ping=True, timeout=DIAG_WAIT_S, mleid=None,
             busy_wait=DIAG_BUSY_WAIT_S, busy_retry=DIAG_BUSY_RETRY_S):
        """Asks Thread Anchor for the Thread diagnostic of a node, reached through the mesh by its
        RLOC16 and/or its mesh-local EID (whatever its OMR prefix; the ML-EID stays when the RLOC16
        changes), ext to check it is the right node: ping and current addresses. Returns its answer
        ({"ping": {"ok", "rtt_ms"}, "addresses", "omr_addresses", "other_prefix_addresses", "error"…}),
        or None when nothing came back in time. Waits for the whole search of Thread Anchor (up to
        `timeout`); a "busy" answer (it runs another diagnostic) is asked again every `busy_retry`
        seconds for `busy_wait` seconds, then returned as it is."""
        end = time.monotonic() + busy_wait
        while True:
            res = self._diag_once(rloc16, ext, ping, timeout, mleid)
            if not (isinstance(res, dict) and str(res.get("error") or "") == "busy") \
                    or time.monotonic() + busy_retry > end:
                return res
            stop = getattr(self.w, "stop", None)
            if stop.wait(busy_retry) if stop is not None else time.sleep(busy_retry):
                return res

    def _diag_once(self, rloc16, ext, ping, timeout, mleid):
        mq = getattr(self.w, "mqtt", None)
        if mq is None or not self.diag_ready():
            return None
        rid = uuid.uuid4().hex[:12]
        ev = threading.Event()
        with self.lock:
            self._diag_waits[rid] = [ev, None]
        try:
            req = {"id": rid, "ping": bool(ping)}
            if rloc16 is not None:
                req["rloc16"] = f"0x{int(rloc16):04X}"
            if ext is not None:
                req["ext"] = f"{int(ext):016x}"
            if mleid:
                req["mleid"] = str(mleid)
            mq.publish(DIAG_REQUEST_TOPIC, json.dumps(req))
            ev.wait(timeout)
            with self.lock:
                return self._diag_waits[rid][1]
        finally:
            with self.lock:
                self._diag_waits.pop(rid, None)

    def on_diag(self, topic, payload):
        rid = topic[len(DIAG_RESULT_TOPIC):]
        try:
            data = json.loads(payload) if payload else None
        except ValueError:
            return
        with self.lock:
            w = self._diag_waits.get(rid)
            if w is not None and isinstance(data, dict):
                w[1] = data
                w[0].set()

    # ------------------------------------------------------------ reading
    def omr(self):
        """State of the fixed OMR prefix: Thread Anchor, else the older "omr" of USB/IP Link; None
        when nothing is fixed (no add-on, or its option empty)."""
        with self.lock:
            st = self.state
        if isinstance(st, dict):
            if not st.get("wanted"):
                return None
            st = dict(st)
            if self.available is False:
                # the add-on itself is stopped (often a restart): its last state is not news, and a
                # stop is not a prefix error. Nobody imposes the prefix any more; whether the network
                # still has it is seen in the announcements of the border routers. Still there: no
                # error, no pause ("still published, no longer imposed" after the grace time). Gone,
                # or not visible: a real loss, said at once
                st["enforced"], st["stopped"] = False, True
                pub = self.published_omr()
                st["current"] = st["wanted"] if st["wanted"] in pub else (next(iter(pub)) if len(pub) == 1 else None)
                st["error"] = None if st["current"] == st["wanted"] else t("Thread Anchor is stopped")
            return st
        old = (getattr(self.w, "usb_links", None) or {}).get("omr")
        return old if isinstance(old, dict) and old.get("wanted") else None

    def published_omr(self):
        """OMR prefixes the border routers of the network announce now (mDNS), empty if unknown."""
        try:
            with self.w.lock:
                return set(self.w._omr_now())
        except Exception:  # noqa: BLE001
            return set()

    def installed(self):
        """Thread Anchor publishes (it is installed and started at least once)."""
        return self.state is not None

    def radio_cut(self):
        """Names of the devices USB/IP Link no longer has attached (a radio cut off)."""
        links = getattr(self.w, "usb_links", None) or {}
        return [d.get("name") or "?" for d in links.get("devices") or [] if not d.get("attached")]

    def network_omr(self):
        """The OMR prefix the network uses now: Thread Anchor's `favored`, else the only one the
        border routers announce."""
        st = self.state if isinstance(self.state, dict) else {}
        if st.get("favored"):
            return st["favored"]
        try:
            with self.w.lock:
                omr = self.w._omr_now()
        except Exception:  # noqa: BLE001
            omr = set()
        return next(iter(omr)) if len(omr) == 1 else None

    # ------------------------------------------------------------ state machine
    def update(self, now=None):
        """Called on every message and by the recovery cycle: pause, catch-up, takeover, anchoring
        (one caller at a time: MQTT, the page refresh and the recovery cycle each call it)."""
        with self.lock:
            self._update(self.clock() if now is None else now)

    def _update(self, now):
        omr = self.omr()
        cut = self.radio_cut()
        # a prefix error known only from a retained message, less than RETAINED_GRACE_S ago: maybe old,
        # a live state usually follows within seconds. Nothing paused nor said meanwhile
        held = bool(omr and not omr.get("enforced") and omr.get("error") and self.retained_t is not None
                    and now - self.retained_t < RETAINED_GRACE_S)
        reason = None
        if cut:
            reason = t("radio {names} cut off (USB/IP)", names=", ".join(cut))
        elif omr and not omr.get("enforced") and omr.get("error") and not held:
            reason = t("OMR prefix no longer in place ({err})", err=omr["error"])
        events = []
        with self.lock:
            if omr and omr.get("enforced"):
                # Thread Anchor 0.1.1+ says since when the prefix is in place without a break: it
                # knows better (its own start, a prefix already in place); else the first time seen
                told = parse_iso(omr.get("anchored_since"))
                first = omr.get("applied_at")
                since = told if told is not None else \
                    min(x for x in (now, first if isinstance(first, (int, float)) else None) if x is not None)
                # the report "before / since the anchoring" starts when this prefix was first anchored:
                # a later date of Thread Anchor for the same prefix (it starts again after a radio cut
                # or a restart) does not move it; an earlier one is better knowledge. Another prefix
                # fixed starts a new anchoring
                prefix = omr.get("wanted")
                other = bool(self.anchored_prefix and prefix and prefix != self.anchored_prefix)
                if other or self.anchored_since is None or since < self.anchored_since:
                    self.anchored_since, self.anchored_prefix = since, prefix
                    self._save()
                    self._report_t = 0
                elif prefix and not self.anchored_prefix:
                    self.anchored_prefix = prefix   # file of an older version: the prefix noted now
                    self._save()
            if reason and self.blocked_since is None:
                self.blocked_since, self.block_reason = now, reason
                self.catchup_at = None
                events.append(("recovery_paused", t("Recovery of lost nodes paused: {why}", why=reason), {"reason": reason}))
            elif reason:
                self.block_reason = reason
            elif self.blocked_since is not None:
                lasted = int(now - self.blocked_since)
                self.blocked_since, self.block_reason = None, None
                self.catchup_at = now + CATCHUP_SETTLE_S
                events.append(("recovery_resumed",
                               tn("Recovery of lost nodes resumed after {m} min: {n} node that dropped meanwhile pinged in {s} s",
                                  "Recovery of lost nodes resumed after {m} min: {n} nodes that dropped meanwhile pinged in {s} s",
                                  len(self.dropped), m=lasted // 60, s=CATCHUP_SETTLE_S),
                               {"seconds": lasted, "dropped": len(self.dropped)}))
            fav = (self.state or {}).get("favored") if isinstance(self.state, dict) else None
            wanted = (omr or {}).get("wanted")
            took = bool(wanted and fav and fav != wanted)
            if took and self.takeover_since is None:
                self.takeover_since = now
                events.append(("omr_takeover", t("The other border routers took over the OMR prefix: {fav} instead of {wanted}",
                                                 fav=fav, wanted=wanted), {"favored": fav, "wanted": wanted}))
            elif not took and self.takeover_since is not None:
                lasted = int(now - self.takeover_since)
                self.takeover_since = None
                if wanted:
                    events.append(("omr_takeover_end", t("OMR prefix {wanted} favored again on the network ({m} min)",
                                                         wanted=wanted, m=lasted // 60), {"wanted": wanted, "seconds": lasted}))
        for kind, txt, data in events:
            self.w.emit(kind, txt, **data)
        if events:
            self.w.dirty = True
        if hasattr(self.w, "omr_fixed") and not held:
            self.w.omr_fixed(omr, now=now)   # 🧭 events: prefix no longer / again in place

    def blocked(self):
        """Why the recovery of lost nodes waits (radio or prefix out), or None."""
        return self.block_reason if self.blocked_since is not None else None

    def note_dropped(self, nodes):
        with self.lock:
            self.dropped.update(nodes)

    def take_catchup(self, now=None):
        """Nodes of the catch-up pass, once it is due (each returned once)."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.catchup_at is None or now < self.catchup_at or self.blocked_since is not None:
                return []
            nodes, self.dropped, self.catchup_at = sorted(self.dropped), set(), None
        return nodes

    # ------------------------------------------------------------ takeover
    def renumbered(self):
        """Nodes now on the prefix the other border routers favored instead of the fixed one."""
        st = self.state if isinstance(self.state, dict) else {}
        fav = st.get("favored")
        if not self.takeover_since or not fav:
            return 0
        with self.w.lock:
            return sum(1 for n in self.w.matter.values() if n.get("online") and n.get("prefix") == fav)

    # ------------------------------------------------------------ report
    def report(self, now=None):
        """OMR prefix changes and lost nodes per day, before and since the anchoring."""
        now = self.clock() if now is None else now
        if self.anchored_since is None:
            return None
        if self._report is not None and now - self._report_t < REPORT_EVERY_S:
            return self._report
        a = self.anchored_since
        evs = read_events(self.event_files, a - REPORT_DAYS * 86400, ("omr_change", "node_unavailable"))
        start = min((e[0] for e in evs), default=a)

        def part(t0, t1):
            omr = omr_episodes([e[0] for e in evs if e[1] == "omr_change" and t0 <= e[0] < t1])
            lost = [e for e in evs if e[1] == "node_unavailable" and t0 <= e[0] < t1]
            days = max((t1 - t0) / 86400, 1 / 24)
            # seconds: under one day the page shows the counts as they are, not a rate per day
            return {"days": round((t1 - t0) / 86400, 1), "seconds": round(t1 - t0), "omr": len(omr), "lost": len(lost),
                    "omr_per_day": round(len(omr) / days, 1), "lost_per_day": round(len(lost) / days, 1)}

        self._report = {"anchored_since": datetime.fromtimestamp(a).astimezone().isoformat(timespec="minutes"),
                        "before": part(start, a) if start < a else None, "after": part(a, now)}
        self._report_t = now
        return self._report

    # ------------------------------------------------------------ proposal
    def proposal(self):
        """Prefix to fix with Thread Anchor: installed, nothing fixed yet, one OMR prefix on the network."""
        st = self.state if isinstance(self.state, dict) else None
        if st is None or st.get("wanted"):
            return None
        return self.network_omr()

    def _sup(self, method, path, body=None):
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise RuntimeError("no Supervisor token")
        req = urllib.request.Request("http://supervisor" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read() or b"{}")
        if data.get("result") not in (None, "ok"):
            raise RuntimeError(data.get("message") or data.get("result"))
        return data.get("data") or {}

    def find_slug(self, sup=None):
        sup = sup or self._sup
        for a in sup("GET", "/addons").get("addons") or []:
            if str(a.get("slug", "")).endswith(ANCHOR_SUFFIX) or a.get("slug") == ANCHOR_SUFFIX[1:]:
                return a["slug"]
        return None

    def apply(self, prefix, sup=None):
        """Writes `prefix` as omr_prefix of Thread Anchor (all its options sent back) and restarts it.
        Only the prefix proposed now: one the network already uses, nothing to renumber."""
        sup = sup or self._sup
        want = self.proposal()
        if not want or str(prefix) != want:
            return {"ok": False, "result": "changed"}
        net = ipaddress.IPv6Network(want, strict=True)
        if net.prefixlen != 64:
            return {"ok": False, "result": "changed"}
        slug = self.slug or self.find_slug(sup)
        if not slug:
            return {"ok": False, "result": "missing"}
        self.slug = slug
        opts = dict(sup("GET", f"/addons/{slug}/info").get("options") or {})
        opts["omr_prefix"] = str(net)
        sup("POST", f"/addons/{slug}/options", {"options": opts})
        sup("POST", f"/addons/{slug}/restart")
        self.w.emit("omr_anchor_set", t("Thread Anchor: OMR prefix {p} fixed, app restarted", p=str(net)), prefix=str(net))
        return {"ok": True, "result": "set", "prefix": str(net)}

    # ------------------------------------------------------------ page
    def public(self):
        omr = self.omr()
        st = self.state if isinstance(self.state, dict) else None
        if st is None and omr is None and self.anchored_since is None:
            return None
        return {"installed": self.installed(), "available": self.available,
                "wanted": (omr or {}).get("wanted"), "enforced": bool((omr or {}).get("enforced")),
                "favored": (st or {}).get("favored"),
                "error": (omr or {}).get("error") or (t("Thread Anchor is stopped") if (omr or {}).get("stopped") else None),
                "proposal": self.proposal(), "paused": self.blocked(),
                "takeover": bool(self.takeover_since), "renumbered": self.renumbered(),
                "report": self.report()}

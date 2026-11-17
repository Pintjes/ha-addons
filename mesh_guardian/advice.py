# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Radio advice: weak parents, follow-up after an action, autonomous models.

In Thread, a node picks its parent when it joins the network. Some firmwares
look for a better parent on their own when the signal drops ("Periodic Parent
Search"); many stay attached to a weak parent as long as the link holds. Nobody
can choose a parent remotely; an end device can only be asked to attach again
(reattach.py), which makes it pick one among the routers it hears.

advise() gives the advice of the node table, computed at every build from what is
known right now. Rules: one proof per advice (shown in its detail); the cheapest
action first (the button before moving a node, moving before buying a router);
an advice always names an action (an observation alone stays in the node panel);
the cause before the symptom; the room and the floor are hints, the radio decides.

The Advisor, called after every radio survey:
- follows the parent of every node from one survey to the next and reports each
  change, saying whether it is better or worse and why it happened (node
  rebooted = battery removed / power cycled, old parent gone, or spontaneous);
- deduces, model by model, which battery devices change parent on their own;
- keeps what advise() needs across restarts (parent searches, weak links).
"""

import logging
import time

from i18n import t, tn
from store import load_json, save_json

LOG = logging.getLogger("mg.advice")
STATE_FILE = "/data/advice_state.json"
WEAK_RSSI = -90        # dBm: weak link when the link quality is not known
GOOD_GAIN = 6          # dB: gain from which a change counts as "better"
UNSTABLE_DETACHES = 3  # detaches over about 24h from which a parent counts as unstable
OMR_CHANGES_WARN = 2   # OMR prefix changes (episodes) over 24h from which the network gets a note
OMR_FIXED_GRACE_S = 60   # fixed OMR prefix (USB/IP Link) off without an error: a note after this time
# USB/IP link of the radio (time to open a TCP connection to the server, ~1 ms on a wired LAN):
# the radio protocol (Spinel) waits for each answer, a slow or jumpy link drops the border router
USB_LAT_AVG_WARN_MS = 50     # average over 5 min from which the link is slow
USB_LAT_PEAK_WARN_MS = 200   # worst over 5 min from which a peak counts, when also USB_LAT_PEAK_RATIO × the average
USB_LAT_PEAK_RATIO = 5


def usb_latency_note(links):
    """Orange note when the USB/IP link of the radio is slow (average) or jumpy (peaks), else None."""
    avg, peak = links.get("latency_avg_ms"), links.get("latency_max_ms")
    if not isinstance(avg, (int, float)):
        return None
    server = links.get("server") or "?"
    if avg >= USB_LAT_AVG_WARN_MS:
        return t("USB/IP link to {server} slow: {avg} ms on average (worst {max} ms), the radio of the border router "
                 "can drop: check the network between Home Assistant and that computer (Wi-Fi, cable, load)",
                 server=server, avg=round(avg), max=round(peak) if isinstance(peak, (int, float)) else "?")
    if isinstance(peak, (int, float)) and peak >= USB_LAT_PEAK_WARN_MS and peak >= USB_LAT_PEAK_RATIO * avg:
        return t("USB/IP link to {server} with peaks: {max} ms at worst for {avg} ms on average, the radio of the border "
                 "router can drop: check the network between Home Assistant and that computer (Wi-Fi, cable, load)",
                 server=server, avg=round(avg), max=round(peak))
    return None
UNSTABLE_REBOOTS = 2   # crashes over 24h from which a node counts as unstable (power cuts never count)
UNKNOWN_REBOOTS = 3    # restarts of unknown cause over 24h from which the power of the node is to check
CRASH_BOOT = ("brown_out", "software_watchdog", "hardware_watchdog", "software_reset")
POWER_CUT_S = 300      # s: mains nodes restarting or dropping this close together: a power cut
WIFI_WEAK = -85        # dBm
WEAK_CLEAR_S = 6 * 3600   # s: a link has to stay good this long to forget it was weak (it flaps at the limit)
PAST_GOOD_RSSI = -80   # dBm: a past parent is a proof of a better one above this (when no link quality was kept)
SETTLE_S = 86400       # s: no "Unstable parent" during this time after a move to a better parent,
                       # nor after a parent search that kept the same parent (it was tried)
FORCED_S = 7200        # s: a parent change this long after a requested parent search is not spontaneous


def weak_link(rssi, lqi):
    """One rule everywhere (colors, advice, parent search, score): a link is weak when its
    Thread link quality is 1 or 0 (0 on an established link: no margin above the noise);
    the RSSI only decides when the link quality is not known (None)."""
    if lqi is not None:
        return lqi <= 1
    return rssi is not None and rssi <= WEAK_RSSI


def lowest(*values):
    """Weakest direction of a link: the lowest known value (None and 0 = not known)."""
    known = [v for v in values if v]
    return min(known) if known else None


def min_known(*values):
    """Lowest known value, 0 included (a link quality of 0 measured on an established link)."""
    known = [v for v in values if v is not None]
    return min(known) if known else None


def dbm(v):
    return "?" if v is None else v


def ago(seconds):
    s = max(0, int(seconds))
    if s < 5400:
        return t("{n} min ago", n=max(1, round(s / 60)))
    if s < 48 * 3600:
        return t("{n} h ago", n=round(s / 3600))
    return t("{n} d ago", n=round(s / 86400))


def boot_kind(row, rows):
    """Why a node last restarted, when it did within 24h: "crash" (reported by the node),
    "power" (power on reported, or several mains nodes restarted together: a power cut),
    "unknown" (alone, no reason reported), or None. A power cut is never instability."""
    up = row.get("uptime_s")
    if not row.get("reboots_24h") or up is None or up > 86400:
        return None
    reason = row.get("boot_reason")
    if reason in CRASH_BOOT:
        return "crash"
    if reason == "power_on" or reason == "software_update":
        return "power"
    if not row.get("battery"):
        together = sum(1 for o in rows if o is not row and not o.get("battery") and o.get("uptime_s") is not None
                       and abs(o["uptime_s"] - up) <= POWER_CUT_S)
        if together >= 2:
            return "power"
    return "unknown"


def _is_router(r):
    return r.get("role") in ("router", "leader")


def _routers_near(row, rows, brs, key):
    """Other available routers of the same room (key "area") or floor (key "floor"),
    the current parent excluded. A border router counts when its name ends with the room."""
    where = (row.get(key) or "").strip()
    if not where or where == "?":
        return 0
    n = sum(1 for o in rows if o is not row and _is_router(o) and o.get("available") and o.get(key) == where
            and o.get("name") != row.get("parent"))
    if key == "area":
        n += sum(1 for b in brs if b.get("online") and b["name"] != row.get("parent")
                 and b["name"].lower().endswith(" " + where.lower()))
    return n


def _past_parent(row, points, usable, now):
    """Proof of a better parent in the 7-day history of the node: the last parent, other
    than the current one and still there, it had a good link with. (name, rssi, lqi, time)."""
    for x in reversed(points or []):
        name, rssi, lqi = x[2], x[3], (x[5] if len(x) > 5 else None)
        if not name or name == row.get("parent") or name.startswith("↔") or name not in usable:
            continue
        if (lqi is not None and lqi >= 2) or (lqi is None and rssi is not None and rssi > PAST_GOOD_RSSI):
            return name, rssi, lqi, x[0]
    return None


def _signal(rssi, lqi):
    return ", ".join(x for x in (f"LQI {lqi}" if lqi else None, f"{rssi} dBm" if rssi is not None else None) if x)


def advise(rows, brs, ctx):
    """Advice of every row of the node table, in place (advice, advice_level, advice_detail).
    Returns the notes about the network itself: [(level, text)].
    ctx: now, tried {name: (time, result)}, forced {name: time}, weak_since {name: {...}} (kept
    by the caller), unstable {name: detaches}, history(id) -> 7-day points, gave_up {id}, ghosts [id]."""
    now = ctx["now"]
    by_name = {r["name"]: r for r in rows}
    usable = {r["name"] for r in rows if _is_router(r) and r.get("available")} | {b["name"] for b in brs if b.get("online")}
    children = {}
    for r in rows:
        if r.get("parent") and r.get("network") == "thread":
            children.setdefault(r["parent"], []).append(r["name"])
    kinds = {r["name"]: boot_kind(r, rows) for r in rows if r.get("network") == "thread"}

    def unstable_parent(name):
        """(kind, count) when this parent keeps dropping its children, else None."""
        p = by_name.get(name)
        if p and kinds.get(name) == "crash" and (p.get("reboots_24h") or 0) >= UNSTABLE_REBOOTS:
            return "reboots", p["reboots_24h"]
        if (ctx["unstable"].get(name) or 0) >= UNSTABLE_DETACHES:
            return "detaches", ctx["unstable"][name]
        return None

    for r in rows:
        out = []   # (short, detail, level), most useful first
        bat = r.pop("_bat", None)
        cand = r.pop("_cand", None)
        area = r.get("area") or "?"
        if not r.get("available"):
            par = by_name.get(r.get("parent") or "")
            cut = 0
            if not r.get("battery") and r.get("area") and r.get("since"):
                cut = sum(1 for o in rows if o is not r and not o.get("available") and not o.get("battery")
                          and o.get("area") == r["area"] and o.get("since") and abs(o["since"] - r["since"]) <= POWER_CUT_S)
            st = r.get("stale_prefix")
            if st:
                # the border routers changed the address prefix and this node did not follow: the
                # cause is known, "check its power" would be wrong
                out.append((t("Stayed on the old address prefix after {br} changed it at {at}", br=st["br"], at=st["at"]),
                            t("{prefix}: its new address is not known, no command reaches it until it announces itself again",
                              prefix=st["prefix"]), "high"))
            elif par is not None and not par.get("available"):
                out.append((t("Comes back with {parent}", parent=par["name"]),
                            t("its parent {parent} is unavailable too", parent=par["name"]), "high"))
            elif cut >= 2:
                out.append((t("Power cut in {area}?", area=r["area"]),
                            t("{n} other mains-powered nodes of the room dropped at the same time", n=cut), "high"))
            elif bat:
                out.append((bat, bat, "high"))
            elif r["id"] in ctx["gave_up"]:
                out.append((t("Remove the battery for 10s") if r.get("battery") else t("Unplug it for 10s"),
                            t("it did not come back after the recovery pings"), "high"))
            elif r.get("ping_ok") is True or (r.get("server") or {}).get("opened_1h", 0) >= 2:
                # it answered a recovery ping, or the Matter Server opened several sessions within the hour:
                # it has power, "check its power" would be wrong
                out.append((t("Answers now and then: remove the battery for 10s") if r.get("battery")
                            else t("Answers now and then: unplug it for 10s"), "", "high"))
            else:
                out.append((t("Check its batteries") if r.get("battery") else t("Check its power"), "", "high"))
        elif r.get("network") != "thread":
            if (r.get("network") == "wifi" and r.get("rssi") is not None and r["rssi"] <= WIFI_WEAK
                    and not r.get("link_old")):
                ap = r.get("access_point") or r.get("parent")
                out.append((t("Weak Wi-Fi signal with {ap}", ap=ap) if ap else t("Weak Wi-Fi signal"),
                            t("{rssi} dBm: move the node or an access point closer", rssi=r["rssi"]), "high"))
        else:
            if bat:
                out.append((bat, bat, "high"))
            name, rssi, lqi = r["name"], r.get("rssi"), r.get("lqi")
            searching = now - (ctx["forced"].get(name) or 0) < 120 or (r.get("search") or {}).get("state") == "pending"
            ws = ctx["weak_since"]
            # an old link (not given by the node for 2 h, or nobody knows when) proves nothing now:
            # no advice from it, in either direction
            fresh = not r.get("link_old")
            if r.get("parent") and not searching and fresh:
                weak = weak_link(rssi, lqi)
                known = rssi is not None or lqi is not None
                if weak:
                    ws.setdefault(name, {"since": now})["ok"] = None
                elif name in ws and known:
                    ws[name]["ok"] = ws[name].get("ok") or now
                    if now - ws[name]["ok"] > WEAK_CLEAR_S:
                        del ws[name]
                tried = ctx["tried"].get(name)
                done = bool(tried and tried[1] not in (None, "noanswer", "unknown"))
                shaky = unstable_parent(r["parent"])
                if weak:
                    # a search only counts once the link was weak: an older one proves nothing today
                    failed = done and tried[0] >= ws[name]["since"] - 60
                    room, floor = _routers_near(r, rows, brs, "area"), _routers_near(r, rows, brs, "floor")
                    if not failed:
                        past = None if cand else _past_parent(r, ctx["history"](r["id"]), usable, now)
                        if cand:
                            short = t("Find a new link: {name}, {signal} now", name=cand[0], signal=_signal(cand[1], cand[2]))
                            detail = t("it hears {name} better than its parent", name=cand[0])
                        elif past:
                            short = t("Find a new link: {name}, {signal} {ago}", name=past[0],
                                      signal=_signal(past[1], past[2]), ago=ago(now - past[3]))
                            detail = t("it had a good link with {name} {ago}", name=past[0], ago=ago(now - past[3]))
                        elif room:
                            short = tn("Find a new link ({n} router in the room)", "Find a new link ({n} routers in the room)", room)
                            detail = t("routers of {area} it could attach to", area=area)
                        elif floor:
                            short = tn("Find a new link ({n} router on the floor)", "Find a new link ({n} routers on the floor)", floor)
                            detail = t("routers of the same floor it could attach to")
                        else:
                            short, detail = t("Find a new link"), t("it attaches again and picks the best parent it hears")
                    else:
                        when = time.strftime("%d/%m %H:%M", time.localtime(tried[0]))
                        if room:
                            short = tn("Move the node: the router of the room does not hear it well",
                                       "Move the node: none of the {n} routers of the room hears it well", room)
                        else:
                            short = t("Add a router in {area}", area=area)
                        detail = t("no better parent found by the search of {when}", when=when)
                    out.append((short, detail, "high"))
                elif shaky and not (done and now - tried[0] < SETTLE_S):
                    kind, cnt = shaky
                    key = ("{parent} restarts ({n}× in 24h): finding a new link could improve the situation" if kind == "reboots"
                           else "{parent} detaches ({n}× in 24h): finding a new link could improve the situation")
                    out.append((t(key, parent=r["parent"], n=cnt), t("this node loses its parent each time"), "low"))
            # the node itself, when others depend on it or when it restarts
            kids = len(children.get(name, []))
            dep = tn(" · {n} node depends on it", " · {n} nodes depend on it", kids) if kids else ""
            n_boot = r.get("reboots_24h") or 0
            hop_weak = (fresh and _is_router(r) and not r.get("parent") and r.get("best_link")
                        and weak_link(r.get("best_rssi"), r.get("best_lqi")))
            if hop_weak:
                peer = by_name.get(r["best_link"])
                there = (peer or {}).get("area") or next((a for a in {o.get("area") for o in rows if o.get("area")}
                                                        if r["best_link"].lower().endswith(" " + a.lower())), None)
                short = (t("Add a router between {a} and {b}", a=area, b=there) if there and there != area and area != "?"
                         else t("Add a router near {area}", area=area))
                out.append((short, t("weak link with {peer}: a router has no parent to change, it needs a closer router", peer=r["best_link"]) + dep, "high"))
            if kinds.get(name) == "crash" and n_boot >= UNSTABLE_REBOOTS:
                out.append((t("Restarts ({n}× in 24h): update its firmware", n=n_boot),
                            t("last restart: {reason}", reason=r.get("boot_reason")) + dep, "high"))
            elif kinds.get(name) == "unknown" and n_boot >= UNKNOWN_REBOOTS and not r.get("battery"):
                out.append((t("Restarts ({n}× in 24h): check its power", n=n_boot), t("no reason reported by the node") + dep, "high"))
        if out:
            # battery first when both: it is one more thing to do; then the most useful advice
            shorts = [o[0] for o in out[:2]] if bat and len(out) > 1 and out[0][0] == bat else [out[0][0]]
            r["advice"] = "; ".join(shorts)
            r["advice_level"] = "high" if any(o[2] == "high" for o in out[:len(shorts)]) else "low"
            r["advice_detail"] = "; ".join(f"{o[0]} ({o[1]})" if o[1] and o[1] != o[0] else o[0] for o in out)
        else:
            r["advice"] = r["advice_level"] = r["advice_detail"] = None
    for gone in [k for k in ctx["weak_since"] if k not in by_name]:
        del ctx["weak_since"][gone]

    notes, brief = [], []
    for b in brs:
        through = sum(1 for r in rows if (r.get("route") or {}).get("br") == b["name"])
        dep = tn(" · {n} node goes through it", " · {n} nodes go through it", through) if through else ""
        n_det = b.get("detached_24h") or 0
        if not b.get("online"):
            notes.append(("bad", t("{name} is offline: check its power and its network", name=b["name"])))
        elif n_det >= UNSTABLE_DETACHES:
            notes.append(("warn", t("{name} detaches ({n}× in 24h): check its power and its network", name=b["name"], n=n_det) + dep))
        elif n_det:
            brief.append((b["name"], n_det, b.get("last_detached")))
    if brief:
        # a few detaches of border routers: good to know, one note for all (often the same storm)
        names = ", ".join(f"{n} ({k}×)" if k > 1 else n for n, k, _ in brief)
        last = max((x[2] for x in brief if x[2]), default=None)
        when = last[11:16] if last else None
        notes.append(("info", t("{names} detached in the last 24h, the last time at {t}", names=names, t=when)
                      if when else t("{names} detached in the last 24h", names=names)))
    links = ctx.get("usb_links") or {}
    for d in links.get("devices") or []:
        if d.get("attached"):
            continue
        since = time.strftime("%H:%M", time.localtime(d["since"])) if isinstance(d.get("since"), (int, float)) else "?"
        why = (t("{server} does not answer", server=links.get("server")) if links.get("server_ok") is False
               else d.get("error") or "")
        notes.append(("bad", t("{name}: USB/IP link cut since {at}, the radio it carries is out", name=d.get("name") or "?",
                               at=since) + (f" ({why})" if why else "")))
    if links.get("server_ok") is not False and all(d.get("attached") for d in links.get("devices") or []):
        lat = usb_latency_note(links)   # a cut link already has its red note
        if lat:
            notes.append(("warn", lat))
    # fixed OMR prefix: Thread Anchor (ctx "omr_fixed"), else the older "omr" of USB/IP Link
    omr = ctx["omr_fixed"] if "omr_fixed" in ctx else links.get("omr")
    off = ctx.get("omr_fixed_off")
    if isinstance(omr, dict) and not omr.get("enforced") and (
            omr.get("error") or (off is not None and ctx["now"] - off >= OMR_FIXED_GRACE_S)):
        cur = omr.get("current") or omr.get("mode") or t("unknown")
        notes.append(("bad" if omr.get("error") else "warn",
                      t("Fixed OMR prefix {p} no longer in place on the border router (now: {cur}): the other border "
                        "routers (Google TV…) can publish their prefixes again and the network change its prefix",
                        p=omr.get("wanted"), cur=cur) + (f" ({omr['error']})" if omr.get("error") else "")))
    anc = ctx.get("anchor") or {}
    if anc.get("takeover"):
        notes.append(("warn", tn("The other border routers (Google TV…) took over the OMR prefix: {fav} instead of {wanted}; "
                                 "{n} node took it, it comes back to {wanted} with the border router of Home Assistant",
                                 "The other border routers (Google TV…) took over the OMR prefix: {fav} instead of {wanted}; "
                                 "{n} nodes took it, they come back to {wanted} with the border router of Home Assistant",
                                 anc.get("renumbered") or 0, fav=anc.get("favored"), wanted=anc.get("wanted"))))
    if anc.get("paused"):
        notes.append(("info", t("Recovery of lost nodes paused while {why}: the nodes that drop meanwhile are pinged "
                                "once it is back", why=anc["paused"])))
    n_omr = ctx.get("omr_changes") or 0
    if n_omr >= OMR_CHANGES_WARN:
        notes.append(("warn", t("The border routers changed the address prefix {n}× in 24h: each time every node must "
                                "take a new address, the ones that do not follow drop", n=n_omr)))
    if ctx["ghosts"]:
        notes.append(("info", t("Announced but unknown to the Matter Server: {ids} (removed without a factory reset?)",
                                ids=", ".join(ctx["ghosts"]))))
    return notes


class Advisor:
    def __init__(self, watch):
        self.w = watch
        self.prev = {}          # child -> {"parent", "rssi", "since"}
        self.uptimes = {}       # name -> last uptime seen
        self.models = {}        # model -> {"spontaneous": n, "observed_h": hours, "nodes": [..]}
        self.changes = []       # recent parent changes (text)
        self.advice = []        # current advice (dicts)
        self.forced = {}        # child -> time of a parent search requested with the button (reattach.py)
        self.tried = {}         # child -> (time, result) of the last parent search (reattach.py)
        self.weak_since = {}    # child -> {"since", "ok"}: since when its link is weak (advise())
        self.unstable = {}      # node -> own detaches over about 24h (last survey)
        self.last_t = None
        self._load()

    # ------------------------------------------------------------- state
    def _load(self):
        try:
            st = load_json(STATE_FILE)
            if not isinstance(st, dict):
                return
            self.prev = st.get("prev", {})
            self.uptimes = st.get("reboot_counts", {})
            self.models = st.get("models", {})
            self.changes = st.get("changes", [])
            self.last_t = st.get("last_t")
            self.tried = {k: tuple(v) for k, v in (st.get("tried") or {}).items()}
            self.weak_since = st.get("weak_since") or {}
        except Exception:  # noqa: BLE001
            pass

    def save(self):
        self._save()

    def _save(self):
        try:
            save_json(STATE_FILE, {"prev": self.prev, "reboot_counts": self.uptimes, "models": self.models,
                                   "changes": self.changes[-30:], "last_t": self.last_t,
                                   "tried": {k: v for k, v in list(self.tried.items()) if time.time() - v[0] < 7 * 86400},
                                   "weak_since": self.weak_since}, ensure_ascii=False)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot save the radio advice state: {err}", err=err))

    def reset(self):
        self.prev, self.uptimes, self.models, self.changes, self.advice, self.last_t = {}, {}, {}, [], [], None
        self._save()

    def prune(self, names):
        """Forget nodes that no longer exist (names: current node names)."""
        gone = [k for k in set(self.prev) | set(self.uptimes) if k not in names]
        for k in gone:
            self.prev.pop(k, None)
            self.uptimes.pop(k, None)
        if gone:
            self._save()
        return len(gone)

    # ------------------------------------------------------------- survey
    def update(self, info, parents, unstable):
        now = time.time()
        by_name = {n["name"]: n for n in info.values()}
        rebooted = set()
        for name, n in by_name.items():
            # reboot counter, not the uptime: the cached uptime can be stale
            cnt, old = n.get("reboots"), self.uptimes.get(name)
            if cnt is not None and old is not None and cnt > old:
                rebooted.add(name)
            if cnt is not None:
                self.uptimes[name] = cnt
        # detaches of each node over about 24h (those shared by many nodes in the same survey
        # interval are a network episode, not the node): advise() reads them
        self.unstable = {u["name"]: u.get("own_detaches", u.get("detaches")) or 0 for u in unstable}
        hours = (now - self.last_t) / 3600 if self.last_t else 0
        self.last_t = now

        # 1. parent changes since the previous survey
        seen_models = set()
        for child, p in parents.items():
            n = by_name.get(child, {})
            model = n.get("model") or "?"
            if n.get("battery") and model != "?" and 0 < hours < 3:
                m = self.models.setdefault(model, {"spontaneous": 0, "observed_h": 0.0, "nodes": []})
                if model not in seen_models:
                    seen_models.add(model)
                    m["observed_h"] = round(m["observed_h"] + hours, 1)
                if child not in m["nodes"]:
                    m["nodes"] = (m["nodes"] + [child])[-10:]
            old = self.prev.get(child)
            key = p.get("key")
            if old and (old.get("key") is None or key is None):
                old.update({"key": key, "parent": p["parent"], "rssi": p["rssi"]})   # state of an older version
                continue
            if old and old["key"] != key:
                known = p["rssi"] is not None and old.get("rssi") is not None
                gain = p["rssi"] - old["rssi"] if known else 0
                verdict = ("?" if not known else t("▲ better") if gain >= GOOD_GAIN
                           else (t("▼ worse") if gain <= -GOOD_GAIN else t("≈ similar")))
                if now - self.forced.get(child, 0) < FORCED_S:
                    why = t("after a parent search requested with the button")
                elif child in rebooted:
                    why = t("after the node rebooted (battery removed or power cycled)")
                elif old["parent"] not in by_name or old["parent"] in rebooted:
                    why = t("its old parent disappeared or rebooted")
                else:
                    why = t("spontaneous change")
                    if n.get("battery") and model != "?":
                        m = self.models.setdefault(model, {"spontaneous": 0, "observed_h": 0.0, "nodes": []})
                        m["spontaneous"] += 1
                txt = t("{child}: new parent {parent} ({rssi}dBm), before {old} ({old_rssi}dBm) {verdict}",
                        child=child, area=n.get("area", "?"), parent=p["parent"], rssi=dbm(p["rssi"]),
                        old=old["parent"], old_rssi=dbm(old["rssi"]), verdict=verdict, why=why)
                self.changes = (self.changes + [f"{time.strftime('%d/%m %H:%M')} {txt}"])[-30:]
                self.w.emit("parent_change", txt, child=child, parent=p["parent"], rssi=p["rssi"],
                            before=old["parent"], rssi_before=old["rssi"], gain=gain, cause=why)
                self.prev[child] = {"parent": p["parent"], "rssi": p["rssi"], "since": now, "key": key,
                                    "better": known and gain >= GOOD_GAIN}
            elif old:
                old["rssi"], old["parent"] = p["rssi"], p["parent"]   # same parent, name may have been resolved
            else:
                self.prev[child] = {"parent": p["parent"], "rssi": p["rssi"], "since": now, "key": key}

        # 2. advice: computed by the node table (advise()), announced here when it is new
        table = getattr(self.w, "table", None)
        rows = []
        try:
            if table:
                table.cache_t = 0
                rows = table.get(force=True).get("rows") or []
        except Exception as err:  # noqa: BLE001
            LOG.debug("advice from the table: %s", err)
        advice = [{"node": r["name"], "area": r.get("area") or "?", "model": r.get("model") or "?",
                   "battery": bool(r.get("battery")), "parent": r.get("parent") or r.get("best_link") or "?",
                   "rssi": r.get("rssi") if r.get("parent") else r.get("best_rssi"),
                   "actions": [r.get("advice_detail") or r["advice"]], "short": [r["advice"]],
                   "severity": r.get("advice_level") or "high"}
                  for r in rows if r.get("advice") and r.get("available")]
        advice.sort(key=lambda a: (a["rssi"] if a["rssi"] is not None else 0))
        old = {a["node"]: a["short"] for a in self.advice}
        new_names = {a["node"] for a in advice if old.get(a["node"]) != a["short"]}
        self.advice = advice
        if advice and new_names and len(new_names) <= 5:
            for a in advice:
                if a["node"] in new_names:
                    self.w.emit("radio_advice", t("{node}: {action}", node=a["node"], area=a["area"], action=a["short"][0]),
                                node=a["node"])
        if len(advice) != getattr(self, "_logged_n", None):   # only when the count changes
            self._logged_n = len(advice)
            LOG.info(tn("Advice: {n} node", "Advice: {n} nodes", len(advice)))
        self._save()

    # ------------------------------------------------------------- MQTT
    def summary(self):
        models = {}
        for model, m in sorted(self.models.items()):
            if m["spontaneous"]:
                models[model] = t("yes ({n} spontaneous change(s) seen)", n=m["spontaneous"])
            elif m["observed_h"] >= 48:
                models[model] = t("not seen in {h}h of observation", h=int(m["observed_h"]))
            else:
                models[model] = t("under observation ({h}h)", h=int(m["observed_h"]))
        return {
            "advice_count": len(self.advice),
            "advice": [f"{a['node']} ({a['area']}{t(', battery') if a['battery'] else ''}) → {a['parent']} "
                       f"{dbm(a['rssi'])}dBm: " + "; ".join(a["actions"]) for a in self.advice[:20]],
            "models_changing_parent_on_their_own": models,
            "recent_parent_changes": self.changes[-10:][::-1],
        }

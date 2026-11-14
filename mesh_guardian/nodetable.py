# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Rows of the node table (sidebar page).

Every Thread node of Home Assistant with its radio link to its parent, its
neighbors, its instability over 24h, its outages and its reboots. Radio values
are the current ones of the Matter Server cache (live link, matterlive.py), so
the effect of an action (battery removed, plug moved) shows within seconds of
the next report of the node. Nothing here sends traffic to the nodes.
"""

import base64
import json
import logging
import os
import threading
import time

from i18n import lang, t

LOG = logging.getLogger("mg.table")
from advice import lowest, weak_link  # noqa: E402

ROLE = {0: "unspecified", 1: "unassigned", 2: "sleepy_end_device", 3: "end_device", 4: "reed",
        5: "router", 6: "leader"}
BOOT_REASON = {0: "unspecified", 1: "power_on", 2: "brown_out", 3: "software_watchdog",
               4: "hardware_watchdog", 5: "software_update", 6: "software_reset"}
COUNTERS = {"detached": "0/53/14", "partition_changes": "0/53/19", "parent_changes": "0/53/21"}
# signal colors, shared with the page (sent in every answer)
# (link quality 3 and 2 = good and fair, 1 = weak; the RSSI only when it is not known)
THRESHOLDS = {"rssi_good": -80, "rssi_bad": -90, "lqi_good": 3, "lqi_bad": 1}
NEW_PARENT_S = 30 * 60
BACKGROUND_S = 20


def nb_rssi(nb):
    """Signal of a neighbor entry: average RSSI (field 6), or the last RSSI (field 7) when
    the average is implausible — some firmwares report e.g. -21dBm for a link heard at -77."""
    avg, last = nb.get("6"), nb.get("7")
    if avg is None or avg > RSSI_PLAUSIBLE_MAX:
        return last if last is not None and last <= RSSI_PLAUSIBLE_MAX else None
    return avg


RSSI_PLAUSIBLE_MAX = -30   # dBm: a Thread link stronger than this is a reporting error


def ext_of(attrs):
    """Thread extended address of a node (General Diagnostics network interfaces)."""
    for itf in attrs.get("0/51/0") or []:
        if not isinstance(itf, dict):
            continue
        if itf.get("7") == 4 or (itf.get("0") is not None and itf.get("0") == attrs.get("0/53/2")):
            try:
                raw = base64.b64decode(itf.get("4") or "")
            except Exception:  # noqa: BLE001
                continue
            if len(raw) == 8:
                return int.from_bytes(raw, "big")
    return None


BATTERY_LOW = 20   # % : below this, "change the batteries"


def battery_of(attrs):
    """(percent, level) from the Power Source cluster: BatPercentRemaining (x/47/12, in half
    percent) and BatChargeLevel (x/47/14: 0 ok, 1 warning, 2 critical)."""
    pct = lvl = None
    for k, v in attrs.items():
        parts = k.split("/")
        if len(parts) != 3 or parts[1] != "47":
            continue
        if parts[2] == "12" and isinstance(v, (int, float)):
            pct = round(v / 2)
        elif parts[2] == "14" and isinstance(v, int):
            lvl = v
    return pct, lvl


def is_thread(attrs):
    """Thread interface in General Diagnostics, even without the Thread diagnostics cluster
    (some devices, e.g. locks, do not expose it)."""
    return any(isinstance(i, dict) and i.get("7") == 4 for i in attrs.get("0/51/0") or [])


def is_router_role(role):
    return role in (5, 6)


def rloc_of(attrs):
    """RLOC16 of a node, read from its mesh-local RLOC address (…:0:ff:fe00:RLOC16).

    The address list may still hold an old RLOC address (e.g. a child that became a
    router): when there are several, the one that matches the role of the node is kept."""
    found = []
    for itf in attrs.get("0/51/0") or []:
        if not isinstance(itf, dict) or itf.get("7") != 4:
            continue
        for addr in itf.get("6") or []:
            try:
                raw = base64.b64decode(addr)
            except Exception:  # noqa: BLE001
                continue
            if len(raw) == 16 and raw[8:14] == b"\x00\x00\x00\xff\xfe\x00":
                rloc = int.from_bytes(raw[14:16], "big")
                if rloc < 0xFC00 and rloc not in found:   # 0xFCxx: anycast locators, not a node
                    found.append(rloc)
    if not found:
        return None
    role = attrs.get("0/53/1")
    if role in (2, 3, 4, 5, 6):
        router = is_router_role(role)
        for rloc in found:
            if router == (not rloc & 0x3FF):
                return rloc
    return found[0]


def fed_parent(attrs):
    """Router id of the parent of a full end device (REED, FED), from its route table, or None.
    Such a child keeps radio links with the routers around it, like a router, but routes
    nothing itself: every route has its parent as next hop, and the entry of the parent
    carries the link quality with it. A router has an entry for itself and several next hops."""
    if attrs.get("0/53/1") in (2, 3):
        return None   # minimal end devices have no routes
    routes = [rt for rt in attrs.get("0/53/8") or [] if isinstance(rt, dict) and rt.get("2") is not None]
    if len(routes) < 2:
        return None
    hops = [rt.get("3") for rt in routes]
    parent = max(set(hops), key=hops.count)
    if parent in (None, 63):
        return None
    own = [rt for rt in routes if rt["2"] == parent]
    if len(own) != 1 or not (own[0].get("5") and own[0].get("6")):
        return None
    if any(rt.get("3") != parent for rt in routes if rt["2"] != parent):
        return None
    return parent


def router_of(attrs, rloc):
    """True for a router. The reported role and the RLOC16 can each be out of date:
    when they agree (or only one is known) it is that one; when they disagree, the
    neighbor table decides (an end device only has a link with its parent)."""
    role = attrs.get("0/53/1")
    by_role = is_router_role(role) if role in (2, 3, 4, 5, 6) else None
    by_rloc = (not rloc & 0x3FF) if rloc is not None else None
    if by_rloc is not True and fed_parent(attrs) is not None:
        return False   # links with several routers, but everything goes through its parent: a child
    nbs = [nb for nb in attrs.get("0/53/7") or [] if isinstance(nb, dict)]
    if by_rloc is None and nbs:
        # no RLOC16 published: a node with children, or with established links to several
        # routers, is a router whatever its (possibly stale) reported role
        if any(nb.get("13") for nb in nbs):
            return True
        routers = [nb for nb in nbs if nb.get("5") and nb.get("2") is not None and not nb["2"] & 0x3FF]
        if len(routers) >= 2:
            return True
    if by_rloc is False and nbs and role not in (2, 3):   # never for (sleepy) end devices: their table is not refreshed
        # said to be a child, but its (fresh) neighbor table has no link with that parent and
        # established links with several routers: the role and the address are out of date
        prloc = rloc & 0xFC00
        routers = [nb for nb in nbs if nb.get("5") and nb.get("2") is not None and not nb["2"] & 0x3FF]
        if not any(nb.get("2") == prloc for nb in nbs) and len(routers) >= 2:
            return True
    if by_role is None or by_rloc is None or by_role == by_rloc:
        return by_role if by_role is not None else bool(by_rloc)
    links = [nb for nb in attrs.get("0/53/7") or [] if isinstance(nb, dict) and (nb.get("5") or nb.get("13"))]
    return len(links) >= 2


def find_parents(thread, labels):
    """Parent of every child node, with the weakest direction of their link.

    thread: node hex -> {"name", "attrs"}; labels: extended address -> name
    (Matter nodes and border routers). Returns (parents, rlocs):
    parents: node hex -> (parent name, rssi, lqi, stable key of the parent); rlocs: node hex -> RLOC16.
    A link only works as well as its weakest direction: rssi and lqi are the lowest of what
    the child hears from its parent and what the parent hears from the child (one direction
    only when the parent is a border router: it is not a Matter node, its table cannot be read).

    1. RLOC16: a child's RLOC16 is its parent's router RLOC16 plus a child id
       (rloc & 0x03FF != 0), so the parent is the router with rloc & 0xFC00.
       Works when the parent is a border router (not a Matter node).
    2. Otherwise the neighbor entry flagged "is child" in the parent's table.
    3. Otherwise the only neighbor of an end device.
    A router (see router_of) has no parent.
    """
    by_name = {v["name"]: k for k, v in thread.items()}
    rlocs = {nid: rloc_of(v["attrs"]) for nid, v in thread.items()}
    router = {nid: router_of(v["attrs"], rlocs[nid]) for nid, v in thread.items()}
    rloc_ext = {}   # RLOC16 of routers -> extended address, from every table of the mesh
    for v in thread.values():
        for nb in v["attrs"].get("0/53/7") or []:
            if isinstance(nb, dict) and nb.get("2") is not None and nb.get("0") and not (nb["2"] & 0x3FF):
                rloc_ext.setdefault(nb["2"], nb["0"])
        for rt in v["attrs"].get("0/53/8") or []:
            if isinstance(rt, dict) and rt.get("0") and rt.get("1") is not None:
                rloc_ext.setdefault(rt["1"], rt["0"])
    parents = {}
    for nid, v in thread.items():
        nbs = [nb for nb in v["attrs"].get("0/53/7") or [] if isinstance(nb, dict)]
        rloc = rlocs.get(nid)
        fed = fed_parent(v["attrs"]) if not router[nid] else None   # full end device: its route table names its parent
        if not router[nid] and (fed is not None or (rloc is not None and rloc & 0x3FF)):
            prloc = fed << 10 if fed is not None else rloc & 0xFC00
            own = [nb for nb in nbs if nb.get("2") == prloc]
            ext = own[0].get("0") if own else rloc_ext.get(prloc)
            name = match(ext, labels) if ext else None
            name = name or f"router {prloc >> 10} (0x{prloc:04x})"
            # link quality in and out with the parent, from the route table of a full end device
            rt = next((x for x in v["attrs"].get("0/53/8") or [] if isinstance(x, dict) and x.get("2") == prloc >> 10), {})
            parents[nid] = (name, nb_rssi(own[0]) if own else None,
                            lowest(own[0].get("5") if own else None, rt.get("5"), rt.get("6")), ext or prloc)
    for nid, v in thread.items():   # seen from the parent side
        for nb in v["attrs"].get("0/53/7") or []:
            if isinstance(nb, dict) and nb.get("13"):
                child = by_name.get(match(nb.get("0"), labels))
                if not child or router[child]:
                    continue   # router since: stale entry
                cur = parents.get(child)
                if cur is None or cur[0] == v["name"] or cur[0].startswith("router "):
                    # weakest of the two directions (cur: what the child hears from this parent)
                    parents[child] = (v["name"], lowest(nb_rssi(nb), cur[1] if cur else None),
                                      lowest(nb.get("5"), cur[2] if cur else None), ext_of(v["attrs"]) or nid)
    for nid, v in thread.items():   # an end device only keeps its parent in its table
        if nid in parents or v["attrs"].get("0/53/1") not in (2, 3):
            continue
        nbs = [nb for nb in v["attrs"].get("0/53/7") or [] if isinstance(nb, dict) and nb_rssi(nb) is not None]
        if len(nbs) == 1:
            parents[nid] = (match(nbs[0].get("0"), labels) or f"0x{(nbs[0].get('2') or 0):04x}",
                            nb_rssi(nbs[0]), nbs[0].get("5"), nbs[0].get("0"))
    for nid in [k for k in parents if router[k]]:
        del parents[nid]   # a router has no parent (stale "is child" entry in a neighbor table)
    return parents, rlocs


def hop_links(thread, routes, parents, rlocs):
    """Link every router really sends through: the first hop of its route to the border
    router. Returns node hex -> (name, rssi, lqi), weakest direction of the link: what the
    router hears from the hop, what the hop hears from it (when the hop is a Matter node),
    and the link quality in and out of its route table. No route known: no link shown."""
    by_name = {v["name"]: k for k, v in thread.items()}
    out = {}
    for nid, r in routes.items():
        hop = r.get("hop_rid")
        if nid in parents or hop is None or nid not in thread:
            continue
        a = thread[nid]["attrs"]
        name = r.get("via") or r.get("br")
        rssi = lqi = None
        for nb in a.get("0/53/7") or []:
            if isinstance(nb, dict) and nb.get("2") is not None and nb["2"] >> 10 == hop and not nb["2"] & 0x3FF:
                rssi, lqi = nb_rssi(nb), nb.get("5")
                break
        for rt in a.get("0/53/8") or []:
            if isinstance(rt, dict) and rt.get("2") == hop:
                lqi = lowest(lqi, rt.get("5"), rt.get("6"))
                break
        peer, rloc, ext = by_name.get(name), rlocs.get(nid), ext_of(a)
        for nb in (thread[peer]["attrs"].get("0/53/7") or []) if peer and peer != nid else []:
            if not isinstance(nb, dict):
                continue
            if (rloc is not None and nb.get("2") == rloc) or \
                    (ext is not None and nb.get("0") is not None and abs(nb["0"] - ext) <= 4096):
                rssi, lqi = lowest(rssi, nb_rssi(nb)), lowest(lqi, nb.get("5"))
                break
        if rssi is not None or lqi:
            out[nid] = (name, rssi, lqi)
    return out


def routes_to_br(thread, labels, br_exts, rlocs, parents):
    """Path of every node to the nearest border router, from the route tables (0/53/8).

    Each entry of a router's route table gives, for a destination router, the next
    hop (router id) and the path cost. The nearest border router is the one with the
    lowest cost; its traffic towards Home Assistant most likely leaves the mesh there.
    An end device goes through its parent. Returns node hex -> {"br", "via", "cost"}
    ("via" None: direct link)."""
    id_ext = {}   # router id -> extended address, from every route and neighbor table
    for v in thread.values():
        for rt in v["attrs"].get("0/53/8") or []:
            if isinstance(rt, dict) and rt.get("0") and rt.get("2") is not None:
                id_ext.setdefault(rt["2"], rt["0"])
        for nb in v["attrs"].get("0/53/7") or []:
            if isinstance(nb, dict) and nb.get("0") and nb.get("2") is not None and not nb["2"] & 0x3FF:
                id_ext.setdefault(nb["2"] >> 10, nb["0"])
    br_names = {labels[x] for x in br_exts if x in labels}
    name_of = lambda rid: match(id_ext.get(rid), labels) or f"router {rid}"
    out = {}
    lq_cost = {3: 1, 2: 2, 1: 4}

    def link_cost(e):
        """Cost of a direct link, from the link quality in both directions (Thread)."""
        if not e:
            return None
        lq = min(e.get("5") or 0, e.get("6") or 0)
        return lq_cost.get(lq) if e.get("9") or lq else None

    tables = {nid: {rt["2"]: rt for rt in v["attrs"].get("0/53/8") or []
                    if isinstance(rt, dict) and rt.get("2") is not None} for nid, v in thread.items()}
    rid_node = {}   # router id -> node hex (Matter routers)
    for nid, v in thread.items():
        rloc = rlocs.get(nid)
        if rloc is not None and not rloc & 0x3FF:
            rid_node[rloc >> 10] = nid
    for rid, ext in id_ext.items():
        name = match(ext, labels)
        for nid, v in thread.items():
            if v["name"] == name:
                rid_node.setdefault(rid, nid)

    def walk(first, dest):
        """Routers crossed from the next hop `first` to the border router `dest`, following
        the next hop announced by each router. Returns (names, complete)."""
        path, hop = [], first
        while hop is not None and len(path) < 12:
            if hop in (63, dest) or name_of(hop) in path:
                break
            if name_of(hop) in br_names:
                break   # reached a border router (by another router id than expected): the path ends here
            path.append(name_of(hop))
            node = rid_node.get(hop)
            entry = tables.get(node, {}).get(dest) if node else None
            if not entry:
                return path, False   # not a Matter node or no route table: the rest is unknown
            nxt = entry.get("3")
            hop = None if nxt in (None, 63, dest) else nxt
        return path, True

    for nid, v in thread.items():
        if nid in parents:
            continue   # an end device sends through its parent (its own route table is stale)
        table = tables[nid]
        best = None
        for rid, rt in table.items():
            dest = match(rt.get("0") or id_ext.get(rid), labels)
            if dest not in br_names:
                continue
            # PathCost is the cost from the next hop onwards: add the link to the next hop
            options = []
            direct = link_cost(rt)
            if direct is not None:
                options.append((direct, None))
            hop = rt.get("3")
            if hop not in (None, 63, rid) and rt.get("4") is not None:
                first = link_cost(table.get(hop))
                # link quality to the next hop not published: count it as one good hop
                options.append((rt["4"] + (first if first is not None else 1), hop))
            for cost, via in options:
                if cost < 16 and (best is None or cost < best[1]):
                    best = (dest, cost, via, rid)
        if best:
            path, complete = walk(best[2], best[3]) if best[2] is not None else ([], True)
            out[nid] = {"br": best[0], "via": name_of(best[2]) if best[2] is not None else None, "cost": best[1],
                        "hop_rid": best[2] if best[2] is not None else best[3],   # router id of the first hop
                        "path": path, "hops": len(path) + 1, "complete": complete}
    by_name = {v["name"]: k for k, v in thread.items()}
    for nid, p in parents.items():   # end devices: their parent, then the parent's path
        if p[0] in br_names:
            out[nid] = {"br": p[0], "via": None, "cost": 0, "parent": p[0], "path": [], "hops": 1, "complete": True}
        elif by_name.get(p[0]) in out:
            r = out[by_name[p[0]]]
            out[nid] = {"br": r["br"], "via": r["via"], "cost": r["cost"], "parent": p[0],
                        "path": [p[0]] + r["path"], "hops": r["hops"] + 1, "complete": r["complete"]}
    return out


def match(ext, table):
    """The Matter Server may round 64-bit integers (JSON): allow a small tolerance."""
    if ext is None:
        return None
    if ext in table:
        return table[ext]
    for k, v in table.items():
        if abs(k - ext) <= 4096:
            return v
    return None


class NodeTable:
    def __init__(self, watch, healer, radio, live, advisor):
        self.w, self.h, self.radio, self.live, self.advisor = watch, healer, radio, live, advisor
        self.lock = threading.Lock()
        self.parents = {}     # node hex -> {"parent", "rssi", "since", "prev", "prev_rssi"}
        self.cache = None
        self.cache_t = 0

    # ---------------------------------------------------------- data
    def _nodes(self):
        if self.live.connected:
            return self.live.snapshot()
        nodes = self.h.matter_command("get_nodes", {}, timeout=120)
        if not isinstance(nodes, list):
            raise RuntimeError("unexpected get_nodes answer")
        return [{**n, "last": None, "radio": None} for n in nodes]

    def build(self):
        now = time.time()
        nodes = self._nodes()
        with self.h.lock:
            meta = {k: dict(n) for k, n in self.h.nodes.items()}
        with self.w.lock:
            labels = {b["xa"]: self.w.br_display(b) for b in self.w.br.values() if b.get("xa") is not None}
        thread, other = {}, {}
        for node in nodes:
            attrs = node.get("attributes") or {}
            if attrs.get("0/53/1") is None and not is_thread(attrs):
                net = "wifi" if any(k.startswith("0/54/") for k in attrs) else \
                    "ethernet" if any(k.startswith("0/55/") for k in attrs) else None
                if net:   # Matter over Wi-Fi or Ethernet (not interviewed yet: skipped)
                    nid = f"{int(node['node_id']):016X}"
                    m = meta.get(nid, {})
                    other[nid] = {"node": node, "attrs": attrs, "meta": m, "net": net,
                                  "name": m.get("name") or f"0x{nid.lstrip('0') or '0'}"}
                continue
            nid = f"{int(node['node_id']):016X}"
            m = meta.get(nid, {})
            thread[nid] = {"node": node, "attrs": attrs, "meta": m,
                           "name": m.get("name") or f"0x{nid.lstrip('0') or '0'}"}
            ext = ext_of(attrs)
            if ext is not None:
                labels[ext] = thread[nid]["name"]
        parent_of, rlocs = find_parents(thread, labels)
        with self.w.lock:
            br_exts = [b["xa"] for b in self.w.br.values() if b.get("xa") is not None]
        try:
            routes = routes_to_br(thread, labels, br_exts, rlocs, parent_of)
        except Exception as err:  # noqa: BLE001 - never break the table for this extra
            LOG.debug("route to border router: %s", err)
            routes = {}
        # a router has no parent: the link shown is the one it really sends through
        best = hop_links(thread, routes, parent_of, rlocs)
        named = bool(meta)
        leader = None
        if self.radio and self.radio.leader_name and time.time() - self.radio.leader_t < 2400:
            leader = self.radio.leader_name   # Home Assistant names loaded: parent history can start
        ref = (self.radio.reference(now, min_age=3600) or {}).get("nodes", {}) if self.radio else {}
        advice = {a["node"]: ("; ".join(a.get("short") or a["actions"]), "; ".join(a["actions"]), a.get("severity", "high"),
                              a.get("parent"))
                  for a in (self.advisor.advice if self.advisor else [])}
        rows = []
        for nid, v in thread.items():
            a, m = v["attrs"], v["meta"]
            role = a.get("0/53/1")
            rloc = rlocs.get(nid)
            if role in (2, 3, 4, 5, 6) or rloc is not None:
                if router_of(a, rloc):
                    role = role if role in (5, 6) else 5
                else:
                    role = role if role in (2, 3, 4) else 4
            # the leader found by asking the mesh (cached roles are not updated by the Matter Server)
            if leader is not None:
                if v["name"] == leader:
                    role = 6
                elif role == 6:
                    role = 5
            bl = best.get(nid)
            bat = battery_of(a) if m.get("battery") or any(k.split("/")[1:2] == ["47"] for k in a) else (None, None)
            low = (bat[0] is not None and bat[0] < BATTERY_LOW) or bat[1] == 2
            bat_short = t("Change the batteries") if low and m.get("battery") else None
            # parent and its history
            p = parent_of.get(nid)
            hist = self.parents.get(nid)
            if p and named:
                # compared by a stable key (extended address), not by the name shown
                if hist is None:
                    hist = self.parents[nid] = {"key": p[3], "parent": p[0], "rssi": p[1], "since": None,
                                                "prev": None, "prev_rssi": None}
                elif hist["key"] != p[3]:
                    hist.update({"prev": hist["parent"], "prev_rssi": hist["rssi"], "since": now, "key": p[3]})
                hist["parent"], hist["rssi"] = p[0], p[1]
            # advice is computed at the radio survey (every 30 min): drop it as soon as the
            # node has left the parent it was about (weak link fixed, unstable parent left)
            adv = advice.get(v["name"])
            strong = bool(p) and (p[1] is not None or bool(p[2])) and not weak_link(p[1], p[2])   # known and not weak
            if adv and p and adv[3] and p[0] != adv[3] and (adv[2] == "low" or not weak_link(p[1], p[2])):
                adv = None
            elif adv and adv[2] == "high" and strong:
                adv = None   # weak-link advice, but the link shown is no longer weak
            if not adv and not p and bl and weak_link(bl[1], bl[2]) and v["meta"].get("available", True):
                # a router has no parent to change: the link it sends through is weak, it needs a closer router
                adv = (t("Add a router near {area}", area=m.get("area") or "?"),
                       t("weak link with {peer}: add a mains-powered Thread router (e.g. a Matter smart plug) between them",
                         peer=bl[0]), "high", None)
            new_parent = None
            if p and hist and hist.get("since") and now - hist["since"] <= NEW_PARENT_S and hist.get("prev"):
                new_parent = {"before": hist["prev"], "before_rssi": hist["prev_rssi"], "at": hist["since"]}
            # neighbors
            nbs = [nb for nb in a.get("0/53/7") or [] if isinstance(nb, dict) and (nb.get("5") or nb.get("13"))]
            weak = [nb for nb in nbs if weak_link(nb_rssi(nb), nb.get("5"))]
            # instability over 24h (difference with the survey of about 24h ago)
            old = ref.get(nid)
            uptime, reboots = a.get("0/51/2"), a.get("0/51/1")
            rebooted = bool(old and uptime is not None and (old.get("u") or 0) > uptime)
            diff = {}
            for key, path in COUNTERS.items():
                cur, before = a.get(path), ((old or {}).get("c") or {}).get(key)
                if cur is None or before is None:
                    diff[key] = None
                else:
                    diff[key] = cur if rebooted else max(0, cur - before)
            reb_24 = None
            if old and reboots is not None and old.get("r") is not None:
                reb_24 = max(0, reboots - old["r"])
            d24, d7, down7 = self.h.node_outages(nid)
            src = self.live.source(nid)
            up_read = self.quality.uptime(nid) if getattr(self, "quality", None) else None
            if up_read is not None:
                uptime = up_read
            q = getattr(self, "quality", None)
            rtt_last, rtt_avg, rtt_fail = q.response(nid) if q else (None, None, False)
            avail = m.get("available")
            if avail is None:
                avail = v["node"].get("available") is not False
            rows.append({
                "network": "thread",
                "id": f"0x{nid.lstrip('0') or '0'}", "name": v["name"], "area": m.get("area") or "",
                "floor": m.get("floor") or "", "model": m.get("model") or "",
                "battery": bool(m.get("battery")), "available": bool(avail), "added": v["node"].get("date_commissioned"),
                "since": m.get("since") if not avail else None,
                "role": ROLE.get(role, str(role)) if role is not None else None,
                "parent": p[0] if p else None, "rssi": p[1] if p else None, "lqi": p[2] if p else None,
                "new_parent": new_parent,
                "rloc16": f"0x{rloc:04x}" if rloc is not None else None,
                "best_link": bl[0] if bl else None, "best_rssi": bl[1] if bl else None, "best_lqi": bl[2] if bl else None,
                "route": routes.get(nid),
                "neighbors": len(nbs), "weak": len(weak),
                "detaches_24h": diff["detached"], "parent_changes_24h": diff["parent_changes"],
                "partition_changes_24h": diff["partition_changes"],
                "outages_24h": d24, "outages_7d": d7, "downtime_7d_min": int(down7 // 60),
                "reboots": reboots, "reboots_24h": reb_24,
                "boot_reason": BOOT_REASON.get(a.get("0/51/4"), a.get("0/51/4")),
                "uptime_h": round(uptime / 3600, 1) if isinstance(uptime, (int, float)) else None,
                "uptime_s": round(uptime) if isinstance(uptime, (int, float)) else None,
                "battery_pct": bat[0], "battery_level": bat[1],
                "advice": "; ".join(x for x in (bat_short, (adv or (None, None, None))[0]) if x) or None,
                "advice_level": "high" if low else (adv or (None, None, None))[2],
                "advice_detail": "; ".join(x for x in (bat_short, (adv or (None, None, None))[1]) if x) or None,
                "contact_src": src[0], "active_gap_max_s": src[1], "since_active_s": src[2], **self._silence(nid, bool(avail)),
                "rtt_ms": rtt_last, "rtt_avg_ms": rtt_avg, "rtt_fail": rtt_fail,
                "last_report": v["node"].get("last"), "last_radio": v["node"].get("radio"),
            })
        for nid, v in other.items():
            rows.append(self._other_row(nid, v))
        for gone in set(self.parents) - set(thread):
            del self.parents[gone]
        return rows

    MAC_TEMPLATE = ("{% set ns = namespace(s=[], o=[]) %}{% for st in states %}{% set d = device_id(st.entity_id) %}"
                    "{% if d and d not in ns.s %}{% set ns.s = ns.s + [d] %}{% for c in device_attr(d, 'connections') or [] %}"
                    "{% if c[0] == 'mac' %}{% set ns.o = ns.o + [[c[1], device_attr(d, 'name_by_user') or device_attr(d, 'name')]] %}"
                    "{% endif %}{% endfor %}{% endif %}{% endfor %}{{ ns.o | tojson }}")

    def _macs(self):
        """MAC address -> device name, from the Home Assistant device registry (cached 10 min)."""
        now = time.time()
        if now - getattr(self, "_macs_t", 0) > 600:
            self._macs_t = now
            try:
                raw = self.h.render_template(self.MAC_TEMPLATE)
                self._macs_v = {bytes.fromhex(m.replace(":", "").replace("-", "")): n
                                for m, n in json.loads(raw or "[]") if m and n and len(m.replace(":", "").replace("-", "")) == 12}
            except Exception as err:  # noqa: BLE001
                LOG.debug("MAC addresses: %s", err)
                self._macs_v = getattr(self, "_macs_v", {})
        return getattr(self, "_macs_v", {})

    def _silence(self, nid, available):
        """Usual rhythm of the node and, when it has been silent for much longer than usual,
        for how long: an early sign that it lost power, minutes before the Matter Server
        declares it unavailable. Only with passive contact (every packet is seen), and not
        while the silence can come from our side (start, reconnection, mass outage)."""
        usual, since = self.live.rhythm(nid)
        out = {"rhythm_s": usual, "silent_limit_s": None, "silent_s": None}
        if usual is None:
            return out
        limit = out["silent_limit_s"] = round(max(2 * usual, usual + 45))
        q = getattr(self, "quality", None)
        now = time.time()
        listening = now - max(self.live.t0, self.live.since or now)
        if (available and since is not None and since > limit and q and getattr(q, "sniffing", False)
                and self.live.connected and now >= self.h.mass_until and listening > limit):
            out["silent_s"] = round(since)
        return out

    AP_FILE = "/data/ap_names.json"

    def _ap_names(self):
        if not hasattr(self, "_ap_names_v"):
            try:
                with open(self.AP_FILE, encoding="utf-8") as f:
                    self._ap_names_v = {k.lower(): v for k, v in json.load(f).items()}
            except (OSError, ValueError):
                self._ap_names_v = {}
        return self._ap_names_v

    def set_ap_name(self, bssid, name):
        """Name given in the node panel to an access point (BSSID); empty name: forget it."""
        b = bssid.strip().lower()
        if len(b.replace(":", "")) != 12:
            raise ValueError("bad BSSID")
        names = dict(self._ap_names())
        name = name.strip()[:40]
        if name:
            names[b] = name
        else:
            names.pop(b, None)
        with open(self.AP_FILE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False)
        os.replace(self.AP_FILE + ".tmp", self.AP_FILE)
        self._ap_names_v = names
        self.cache_t = 0   # next /api/table rebuilds with the new name

    def _access_point(self, bssid):
        """(BSSID text, access point name or None). A BSSID is the MAC of one radio of the
        access point: same bytes 2-5 as the device MAC, last byte a little higher, first
        byte sometimes with the "locally administered" bits set."""
        try:
            b = base64.b64decode(bssid) if isinstance(bssid, str) else bytes(bssid or b"")
        except Exception:  # noqa: BLE001
            return None, None
        if len(b) != 6:
            return None, None
        text = ":".join(f"{x:02x}" for x in b)
        best = None
        for mac, name in self._macs().items():
            if mac[1:5] == b[1:5] and (mac[0] | 0x0E) == (b[0] | 0x0E) and 0 <= b[5] - mac[5] <= 15:
                if best is None or b[5] - mac[5] < best[0]:
                    best = (b[5] - mac[5], name)
        if best:
            return text, best[1]
        return text, self._ap_names().get(text)

    def _other_row(self, nid, v):
        """Row of a Matter node on Wi-Fi or Ethernet: no mesh, its own link only."""
        a, m = v["attrs"], v["meta"]
        wifi = v["net"] == "wifi"
        ch = a.get("0/54/3")
        bssid, ap = self._access_point(a.get("0/54/0")) if wifi else (None, None)
        link = (ap or t("Wi-Fi")) + (f" · ch {ch}" if ch else "") if wifi else t("Ethernet")
        uptime, reboots = a.get("0/51/2"), a.get("0/51/1")
        q = getattr(self, "quality", None)
        up_read = q.uptime(nid) if q else None
        if up_read is not None:
            uptime = up_read
        rtt_last, rtt_avg, rtt_fail = q.response(nid) if q else (None, None, False)
        d24, d7, down7 = self.h.node_outages(nid)
        src = self.live.source(nid)
        avail = m.get("available")
        if avail is None:
            avail = v["node"].get("available") is not False
        bat = battery_of(a) if m.get("battery") or any(k.split("/")[1:2] == ["47"] for k in a) else (None, None)
        return {
            "network": v["net"], "id": f"0x{nid.lstrip('0') or '0'}", "name": v["name"],
            "area": m.get("area") or "", "floor": m.get("floor") or "", "model": m.get("model") or "",
            "battery": bool(m.get("battery")), "available": bool(avail), "added": v["node"].get("date_commissioned"),
            "since": m.get("since") if not avail else None, "role": None,
            "parent": link, "rssi": a.get("0/54/4") if wifi else None, "lqi": None, "new_parent": None,
            "rloc16": None, "best_link": None, "best_rssi": None, "best_lqi": None, "route": None,
            "neighbors": None, "weak": None,
            "detaches_24h": None, "parent_changes_24h": None,
            "partition_changes_24h": None,
            "outages_24h": d24, "outages_7d": d7, "downtime_7d_min": int(down7 // 60),
            "reboots": reboots, "reboots_24h": None,
            "boot_reason": BOOT_REASON.get(a.get("0/51/4"), a.get("0/51/4")),
            "uptime_h": round(uptime / 3600, 1) if isinstance(uptime, (int, float)) else None,
            "uptime_s": round(uptime) if isinstance(uptime, (int, float)) else None,
            "battery_pct": bat[0], "battery_level": bat[1],
            "advice": None, "advice_level": None, "advice_detail": None,
            "contact_src": src[0], "active_gap_max_s": src[1], "since_active_s": src[2], **self._silence(nid, bool(avail)),
            "rtt_ms": rtt_last, "rtt_avg_ms": rtt_avg, "rtt_fail": rtt_fail,
            "last_report": v["node"].get("last"), "last_radio": None,
            "bssid": bssid, "access_point": ap,
        }

    def header(self):
        s = self.w.summary()
        with self.w.lock:
            brs = []
            for key, b in self.w.br.items():
                if not self.w.br_relevant(b):
                    continue
                st = self.w.br_stats(key)
                brs.append({"name": self.w.br_label(b), "key": key[:16], "role": b.get("role") if b["online"] else "offline",
                            "online": bool(b["online"]), "partition": b.get("partition"), "omr": b.get("omr"),
                            "primary": bool(b.get("bbr_primary")) and bool(b["online"]),
                            "last_contact": self.w.br_contact(b)[0], "contact_src": self.w.br_contact(b)[1],
                            "detached_24h": st["detached_24h"], "last_detached": st["last_detached"],
                            "same_subnet": self.h.same_subnet(b.get("addrs"))})
        brs.sort(key=lambda x: (not x["online"], x["name"].lower()))
        with self.h.lock:
            unavailable = sum(1 for n in self.h.nodes.values() if not n["available"])
            total = len(self.h.nodes)
        storm = self.w.storm.summary() if getattr(self.w, "storm", None) else {}
        q = getattr(self, "quality", None)
        return {"quality": q.summary() if q else None, "border_routers": brs,
                "network": {"partitions": s["partitions"], "omr": s["omr_list"], "leader": s["leader"],
                            "unavailable": unavailable, "nodes": total, "storm": storm.get("state") == "ON",
                            "routing_problem": self.h.routing.get("details") if self.h.routing.get("problem") else None,
                            "auto_recovery": self.h.enabled}}

    def get(self, force=False):
        """Answer of /api/table. Cached a few seconds (several open pages share it)."""
        with self.lock:
            fresh = time.time() - self.cache_t < (2 if force else 10)
            if not fresh or self.cache is None:
                if force and not self.live.connected:
                    self.live.resync()
                rows = self.build()
                self.cache = {"rows": rows}
                self.cache_t = time.time()
            out = dict(self.cache)
        out.update(self.header())
        out.update({"time": time.time(), "lang": lang(), "thresholds": THRESHOLDS,
                    "live": self.live.connected, "live_since": self.live.since})
        return out

    def _ping_silent(self, rows):
        """A node that has just gone silent gets one ping, in the background: if it answers,
        the contact clears the silence; if not, it stays silent until the Matter Server
        decides. One ping per silence (a node keeps the same last contact while silent)."""
        pinged = self.__dict__.setdefault("_silent_pinged", {})
        for r in rows:
            if not r.get("silent_s"):
                continue
            nid = f"{int(r['id'], 16):016X}"
            last = self.live.contacts.get(nid)
            if pinged.get(nid) == last:
                continue
            pinged[nid] = last

            def ping(nid=nid, name=r["name"]):
                try:
                    res = self.h.matter_command("ping_node", {"node_id": int(nid, 16)}, timeout=60)
                    if isinstance(res, dict) and any(res.values()):
                        self.live.note_contact(nid, src="ping")
                        self.cache_t = 0
                    LOG.debug("silent %s pinged: %s", name, res)
                except Exception as err:  # noqa: BLE001
                    LOG.debug("silent %s ping: %s", name, err)
            threading.Thread(target=ping, daemon=True, name="ping-silent").start()

    def run(self):
        """Keep the parent history going even when nobody looks at the page."""
        time.sleep(60)
        while not self.w.stop.is_set():
            if self.live.connected:
                try:
                    with self.lock:
                        self.cache = {"rows": self.build()}
                        self.cache_t = time.time()
                    self._ping_silent(self.cache["rows"])
                except Exception as err:  # noqa: BLE001
                    LOG.debug("table: %s", err)
            if self.w.stop.wait(BACKGROUND_S):
                return


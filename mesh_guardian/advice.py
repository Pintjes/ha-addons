# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Radio advice: weak parents, follow-up after an action, autonomous models.

In Thread, a node picks its parent when it joins the network. Some firmwares
look for a better parent on their own when the signal drops ("Periodic Parent
Search"); many stay attached to a weak parent as long as the link holds. Nobody
can choose a parent remotely; an end device can only be asked to attach again
(reattach.py), which makes it pick one among the routers it hears.

Called after every radio survey, this module:
- lists the nodes whose parent link is weak (link quality 1) or unstable (parent
  rebooted / detached), with the recommended action;
- follows the parent of every node from one survey to the next and reports each
  change, saying whether it is better or worse and why it happened (node
  rebooted = battery removed / power cycled, old parent gone, or spontaneous);
- deduces, model by model, which battery devices change parent on their own.
"""

import json
import logging
import time

from i18n import t, tn

LOG = logging.getLogger("mg.advice")
STATE_FILE = "/data/advice_state.json"
WEAK_RSSI = -90        # dBm: weak link when the link quality is not known
GOOD_GAIN = 6          # dB: gain from which a change counts as "better"
UNSTABLE_DETACHES = 3  # detaches over about 24h from which a parent counts as unstable
UNSTABLE_REBOOTS = 2   # reboots over about 24h (software updates excluded) from which a parent counts as unstable
SETTLE_S = 86400       # s: no "Unstable parent" during this time after a move to a better parent
FORCED_S = 7200        # s: a parent change this long after a requested parent search is not spontaneous


def weak_link(rssi, lqi):
    """One rule everywhere (colors, advice, parent search, score): a link is weak when its
    Thread link quality is 1; the RSSI only decides when the link quality is not known."""
    if lqi:
        return lqi <= 1
    return rssi is not None and rssi <= WEAK_RSSI


def lowest(*values):
    """Weakest direction of a link: the lowest known value (None and 0 = not known)."""
    known = [v for v in values if v]
    return min(known) if known else None


def dbm(v):
    return "?" if v is None else v


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
        self.last_t = None
        self._load()

    # ------------------------------------------------------------- state
    def _load(self):
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            self.prev = st.get("prev", {})
            self.uptimes = st.get("reboot_counts", {})
            self.models = st.get("models", {})
            self.changes = st.get("changes", [])
            self.last_t = st.get("last_t")
        except Exception:  # noqa: BLE001
            pass

    def _save(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"prev": self.prev, "reboot_counts": self.uptimes, "models": self.models,
                           "changes": self.changes[-30:], "last_t": self.last_t}, f, ensure_ascii=False)
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
        # unstable parent: rebooted, or detached at least UNSTABLE_DETACHES times, over about 24h
        # (detaches shared by many nodes in the same survey interval are a network episode, not the parent)
        unstable_parents = {}
        for u in unstable:
            if (u.get("reboots") or 0) >= UNSTABLE_REBOOTS:
                unstable_parents[u["name"]] = ("reboots", u["reboots"])
            elif (u.get("own_detaches", u.get("detaches")) or 0) >= UNSTABLE_DETACHES:
                unstable_parents[u["name"]] = ("detaches", u.get("own_detaches", u.get("detaches")))
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

        # 2. advice
        advice = []
        for child, p in parents.items():
            n = by_name.get(child)
            if not n:
                continue
            weak = weak_link(p["rssi"], p.get("lqi"))
            since = self.prev.get(child, {}).get("since")
            # just moved to a better parent: the past of that parent is not this node's problem
            settling = bool(since and self.prev[child].get("better") and now - since < SETTLE_S)
            shaky = p["parent"] in unstable_parents and not settling
            if not (weak or shaky):
                continue
            days = (now - since) / 86400 if since else 0
            model = n.get("model") or "?"
            autonomous = self.models.get(model, {}).get("spontaneous", 0) > 0
            actions, short = [], []
            tried = self.tried.get(child)
            no_better = bool(tried and now - tried[0] < 7 * 86400 and tried[1] in ("same", "similar", "worse"))
            if weak:
                if no_better or child in rebooted or (autonomous and days > 1):
                    actions.append(t("add a mains-powered Thread router (e.g. a Matter smart plug) near \"{area}\": "
                                     "the node already had a chance to find a better parent and did not",
                                     area=n.get("area", "?")))
                    short.append(t("Add a router near {area}", area=n.get("area", "?")))
                else:
                    actions.append(t("press Find a new parent on its line: it attaches again and picks the best parent it hears "
                                     "(if it refuses: remove the battery or unplug it for 10s)"))
                    short.append(t("Finding a new parent could improve the situation"))
            if shaky:
                kind, cnt = unstable_parents[p["parent"]]
                if kind == "reboots":
                    short.append(t("{parent} restarts ({n}× in 24h): finding a new parent could improve the situation", parent=p["parent"], n=cnt))
                    why = t("{parent} restarted {n} times in 24h", parent=p["parent"], n=cnt)
                else:
                    short.append(t("{parent} detaches ({n}× in 24h): finding a new parent could improve the situation", parent=p["parent"], n=cnt))
                    why = t("{parent} detached {n} times in 24h", parent=p["parent"], n=cnt)
                actions.append(why + t(": this node loses its parent each time. ") +
                               t("Press Find a new parent on its line so it picks a steadier parent"))
            advice.append({
                "node": child, "area": n.get("area", "?"), "model": model,
                "battery": bool(n.get("battery")), "parent": p["parent"], "rssi": p["rssi"],
                "days": round(days, 1), "actions": actions, "short": short,
                # a weak link is a problem now; an unstable parent only a risk
                "severity": "high" if weak else "low",
            })
        advice.sort(key=lambda a: (a["rssi"] if a["rssi"] is not None else 0))
        new_names = {a["node"] for a in advice} - {a["node"] for a in self.advice}
        self.advice = advice
        if advice and new_names and len(new_names) <= 5:
            for a in advice:
                if a["node"] in new_names:
                    self.w.emit("radio_advice", t("{node}: {action} (parent {parent}, {rssi}dBm)",
                                                  node=a["node"], area=a["area"], parent=a["parent"],
                                                  rssi=dbm(a["rssi"]), action=(a.get("short") or a["actions"])[0]), node=a["node"])
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

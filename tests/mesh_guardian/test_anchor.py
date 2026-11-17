"""Essai de anchor.py (add-on Thread Anchor) : lecture de thread_anchor/state (repli sur "omr" de
usbip_link/state), pause de la recuperation tant que la radio ou le prefixe est hors service,
rattrapage cible, reprise par les autres border routers, bilan avant / apres, proposition du prefixe."""
import json
import os
import sys
import tempfile
import threading
import types
from datetime import datetime

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import advice  # noqa: E402
import anchor as A  # noqa: E402
import healer as H  # noqa: E402

TMP = tempfile.mkdtemp()
A.ANCHOR_FILE = os.path.join(TMP, "anchor.json")
P, G = "fdd7:20e4:8187:1::/64", "fd11:2222:3333:1::/64"   # prefixe impose, prefixe d'un Google TV


class W:
    def __init__(self):
        self.lock, self.events, self.dirty = threading.RLock(), [], False
        self.usb_links, self.br = None, {}
        self.matter = {"01": {"online": True, "prefix": G}, "02": {"online": True, "prefix": P},
                       "03": {"online": True, "prefix": G}}
        self.fixed = []

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def omr_fixed(self, omr, now=None):
        self.fixed.append(omr)

    def _omr_now(self):
        return {b["omr"] for b in self.br.values()}

    def kinds(self):
        return [k for k, _ in self.events]


T0 = 1763370000.0   # 17/11/2025 : une vraie date (Windows refuse les dates de 1970)
clock = [T0 + 1000]
w = W()
a = A.Anchor(w, clock=lambda: clock[0])
assert a.omr() is None and a.public() is None and a.proposal() is None

# repli : l'ancienne cle "omr" de USB/IP Link tant que Thread Anchor ne dit rien
w.usb_links = {"server": "s", "devices": [{"name": "ZBT-2", "attached": True}],
               "omr": {"wanted": P, "enforced": True, "error": None, "applied_at": T0 + 900}}
a.update()
assert a.omr()["wanted"] == P and a.anchored_since == T0 + 900          # date d'ancrage = premiere application
assert json.load(open(A.ANCHOR_FILE))["anchored_since"] == T0 + 900
assert w.fixed[-1]["wanted"] == P                                      # evenements 🧭 de watcher.omr_fixed

# Thread Anchor installe sans prefixe : proposition = le prefixe retenu (rien a renumeroter)
st = {"version": "0.1.0", "wanted": None, "preference": "high", "mode": "auto", "enforced": False,
      "favored": G, "favored_preference": "low", "error": None}
a.on_state(json.dumps(st))
assert a.installed() and a.omr() is None and a.proposal() == G
calls = []


def sup(method, path, body=None):
    calls.append((method, path, body))
    if path == "/addons":
        return {"addons": [{"slug": "core_matter_server"}, {"slug": "4f047962_thread_anchor"}]}
    if path.endswith("/info"):
        return {"options": {"omr_prefix": "", "omr_preference": "high", "language": "fr", "check_interval": 30}}
    return {}


assert a.apply(P, sup=sup) == {"ok": False, "result": "changed"} and not calls   # autre que la proposition : refuse
out = a.apply(G, sup=sup)
assert out["ok"] and out["prefix"] == G, out
assert calls[2] == ("POST", "/addons/4f047962_thread_anchor/options",
                    {"options": {"omr_prefix": G, "omr_preference": "high", "language": "fr", "check_interval": 30}})
assert calls[3] == ("POST", "/addons/4f047962_thread_anchor/restart", None) and "omr_anchor_set" in w.kinds()
# sans favored : le seul prefixe annonce par les border routers ; plusieurs : pas de proposition
a.on_state(json.dumps(dict(st, favored=None)))
w.br = {"x": {"omr": G}}
assert a.proposal() == G
w.br = {"x": {"omr": G}, "y": {"omr": P}}
assert a.proposal() is None

# Thread Anchor en place : prefere a l'ancienne cle
ok = dict(st, wanted=P, mode="custom", current=P, enforced=True, favored=P, favored_preference="high", applied_at=T0 + 950)
a.on_state(json.dumps(ok))
assert a.omr()["enforced"] and a.blocked() is None and a.anchored_since == T0 + 900
a.on_available("offline")   # add-on arrete : son dernier etat n'est plus une nouvelle
assert not a.omr()["enforced"] and a.omr()["error"]
a.on_available("online")

# pause : radio coupee -> pas de ping, nodes tombees retenues ; retour -> rattrapage apres 60 s
w.events.clear()
w.usb_links["devices"][0]["attached"] = False
a.update()
assert a.blocked() and "ZBT-2" in a.blocked() and w.kinds() == ["recovery_paused"]
a.note_dropped(["00000000000000AA", "00000000000000BB"])
clock[0] = T0 + 1600
w.usb_links["devices"][0]["attached"] = True
a.update()
assert a.blocked() is None and w.kinds() == ["recovery_paused", "recovery_resumed"]
assert a.take_catchup() == []                       # pas avant 60 s
clock[0] = T0 + 1661
assert a.take_catchup() == ["00000000000000AA", "00000000000000BB"]
assert a.take_catchup() == []                       # une seule fois
# prefixe pas en place AVEC erreur : pause aussi ; sans erreur : pas de pause
a.on_state(json.dumps(dict(ok, enforced=False, mode="auto", error="404 No such container")))
assert a.blocked() and "404" in a.blocked()
a.on_state(json.dumps(dict(ok, enforced=False, mode="auto", error=None)))
assert a.blocked() is None

# reprise par les autres border routers : evenement, nodes renumerotees, note ; fin
w.events.clear()
a.on_state(json.dumps(dict(ok, enforced=False, mode="auto", favored=G, favored_preference="low", error="stopped")))
assert "omr_takeover" in w.kinds() and a.renumbered() == 2
pub = a.public()
assert pub["takeover"] and pub["renumbered"] == 2 and pub["favored"] == G
ctx = {"now": clock[0], "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 0, "usb_links": None, "omr_fixed_off": None,
       "anchor": pub, "omr_fixed": a.omr()}
notes = advice.advise([], [], ctx)
kinds = [n[0] for n in notes]
assert kinds.count("bad") == 1 and "warn" in kinds and "info" in kinds, notes   # prefixe (erreur), reprise, pause
assert any(G in n[1] and P in n[1] and "2" in n[1] for n in notes if n[0] == "warn")
a.on_state(json.dumps(ok))
assert "omr_takeover_end" in w.kinds() and a.renumbered() == 0

# bilan avant / apres depuis le journal des evenements
ev = os.path.join(TMP, "events.jsonl")
day = 86400.0
anch = T0 + 10 * day
with open(ev, "w", encoding="utf-8") as f:
    def put(ts, kind):
        f.write(json.dumps({"t": datetime.fromtimestamp(ts).astimezone().isoformat(), "type": kind}) + "\n")
    for d in range(3):                                   # 3 jours avant : 2 episodes par jour, 4 nodes perdues
        base = anch - (3 - d) * day
        put(base + 100, "omr_change")
        put(base + 200, "omr_change")                    # meme episode
        put(base + 40000, "omr_change")
        for k in range(4):
            put(base + 500 + k, "node_unavailable")
    put(anch + 3600, "node_unavailable")                 # apres : 1 node en 2 jours, aucun changement
    put(anch + 3700, "ping")
w2 = W()
b = A.Anchor(w2, clock=lambda: anch + 2 * day, event_files=[ev + ".1", ev])
b.anchored_since = anch
r = b.report()
assert r["before"]["omr"] == 6 and r["before"]["lost"] == 12 and r["before"]["omr_per_day"] == 2.0, r
assert r["after"]["omr"] == 0 and r["after"]["lost"] == 1 and r["after"]["lost_per_day"] == 0.5, r

# guerisseur : en pause, aucun ping et nodes tombees retenues ; rattrapage = ces nodes seules
h = H.Healer.__new__(H.Healer)
h.lock, h.w = threading.RLock(), types.SimpleNamespace(stop=threading.Event(), emit=lambda *x, **k: None, dirty=False)
h.nodes = {"00000000000000AA": {"available": False, "pings": 5, "last_ping": 1, "gave_up": True, "name": "Miele"},
           "00000000000000BB": {"available": True, "pings": 0, "last_ping": None, "gave_up": False, "name": "Lampe"},
           "00000000000000CC": {"available": False, "pings": 5, "last_ping": 1, "gave_up": True, "name": "Autre"}}
pinged = []
h.ping = pinged.append
h._save_state = lambda: None
h.catchup(["00000000000000AA", "00000000000000BB"])
assert pinged == ["00000000000000AA"] and not h.nodes["00000000000000AA"]["gave_up"]
assert h.nodes["00000000000000AA"]["pings"] == 0 and h.nodes["00000000000000CC"]["gave_up"]

# latence du lien USB/IP (USB/IP Link 0.3.0) : note orange si lente en moyenne ou avec des pics ; rien sinon
links = {"server": "192.168.1.10", "server_ok": True, "devices": [{"name": "ZBT-2", "attached": True}],
         "latency_ms": 0.8, "latency_avg_ms": 0.9, "latency_max_ms": 2.1}
assert advice.usb_latency_note(links) is None
assert "slow" in advice.usb_latency_note(dict(links, latency_avg_ms=80, latency_max_ms=150)) or \
    "lent" in advice.usb_latency_note(dict(links, latency_avg_ms=80, latency_max_ms=150))
assert advice.usb_latency_note(dict(links, latency_avg_ms=20, latency_max_ms=250)) is not None   # pic 12x la moyenne
assert advice.usb_latency_note(dict(links, latency_avg_ms=45, latency_max_ms=210)) is None       # pic < 5x
assert advice.usb_latency_note(dict(links, latency_avg_ms=None)) is None                          # pas encore mesuree
ctx = {"now": clock[0], "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 0, "usb_links": dict(links, latency_avg_ms=80, latency_max_ms=150)}
assert [n[0] for n in advice.advise([], [], ctx)] == ["warn"]
ctx["usb_links"]["devices"][0]["attached"] = False   # lien coupe : la note rouge suffit, pas de note de latence
assert [n[0] for n in advice.advise([], [], ctx)] == ["bad"]
import nodetable  # noqa: E402
assert nodetable.is_ha_br({"vendor": "HomeAssistant", "model": "OpenThreadBorderRouter"})
assert not nodetable.is_ha_br({"vendor": "Google Inc.", "model": "Google Nest Hub"})
print("OK")

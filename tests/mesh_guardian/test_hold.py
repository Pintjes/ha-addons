"""Essai de la 2.34.0 : annonce a sa place gardee jusqu'a la vraie (B), recuperation automatique par
le diagnostic Thread avec ses garde-fous (C), ancien prefixe juge par rapport au prefixe retenu (A),
nom donne aux border routers dans Home Assistant (E). Methodes extraites de watcher.py par ast."""
import ast
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import anchor as A  # noqa: E402
import reattach as R  # noqa: E402
from i18n import t  # noqa: E402

A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
want = ("_omr_now", "stale_prefix", "favored_omr", "proxy_hold", "check_proxy_holds", "br_label", "refresh_user_names")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
consts = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("PROXY_HOLD_S",)]
ns = {"LOG": logging.getLogger("x"), "time": time, "t": t}
exec(compile(ast.fix_missing_locations(ast.Module(body=consts + [ast.ClassDef(
    name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])), "watcher_extrait", "exec"), ns)

P, G = "fdd7:20e4:8187:1::/64", "fdc0:6359:d5be:1::/64"
MIELE = "000000000000005A"


class W(ns["W"]):
    def __init__(self):
        self.lock, self.events, self.dirty = threading.RLock(), [], False
        self.br = {"ha": {"online": True, "omr": P, "vendor": "Home Assistant", "model": "OpenThread Border Router",
                          "instance": "Home Assistant OpenThread Border Router #1950"},
                   "tv": {"online": True, "omr": G, "vendor": "Google Inc.", "model": "Google TV", "label": "Google TV Cuisine",
                          "instance": "Google-TV-1"}}
        self.matter = {MIELE: {"online": False, "prefix": G}}
        self.omr_left, self.proxy_holds, self.proxies = {}, {}, {}
        self.anchor = types.SimpleNamespace(state={"favored": P})
        self.withdrawn = []

    def br_relevant(self, b):
        return True

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def proxy_withdraw(self, node):
        self.withdrawn.append(node)


# (A) le Google TV annonce encore son propre prefixe fdc0 : sans Thread Anchor il compte comme actuel,
# avec Thread Anchor seul le prefixe retenu (favored) compte
w = W()
assert w.stale_prefix(MIELE, thread=True) == {"prefix": G, "br": None, "t": None, "at": None}
w.anchor = None
assert w.stale_prefix(MIELE, thread=True) is None
w.anchor = types.SimpleNamespace(state={"favored": P})
w.matter[MIELE]["prefix"] = P
assert w.stale_prefix(MIELE, thread=True) is None

# (B) annonce gardee : tant que la node ne s'annonce pas elle-meme sur le prefixe retenu ; 24 h au plus
w = W()
w.proxy_hold(MIELE, ["fdd7:20e4:8187:1:ef69:9a13:7033:2b07"], "Prise Lave-linge Miele")
now = w.proxy_holds[MIELE]["since"]
w.check_proxy_holds(now + 60)
assert MIELE in w.proxy_holds and not w.withdrawn                     # pas encore annoncee
w.matter[MIELE].update(online=True, prefix=G)
w.check_proxy_holds(now + 120)
assert MIELE in w.proxy_holds and not w.withdrawn                     # son vieil enregistrement fdc0 revient : on garde
w.matter[MIELE].update(online=True, prefix=P)
w.check_proxy_holds(now + 180)
assert MIELE not in w.proxy_holds and w.withdrawn == [MIELE] and w.events[-1][0] == "proxy_released"
w = W()
w.proxy_hold(MIELE, ["fdd7::1"], "Prise Lave-linge Miele")
w.check_proxy_holds(w.proxy_holds[MIELE]["since"] + 24 * 3600 + 1)
assert w.withdrawn == [MIELE] and w.events[-1][0] == "proxy_expired"

# (E) noms donnes dans Home Assistant
w = W()
devs = [{"name": "OpenThread Border Router", "model": "OpenThread Border Router", "name_by_user": "Home Assistant",
         "identifiers": [["otbr", "abc"]]},
        {"name": "Google TV Cuisine", "name_by_user": "TV de la cuisine", "identifiers": [["cast", "x"]]},
        {"name": "Nest Hub", "name_by_user": None}]
assert w.refresh_user_names(devs) and w.dirty
assert w.br_label(w.br["ha"]) == "Home Assistant" and w.br_label(w.br["tv"]) == "TV de la cuisine"
w.refresh_user_names([])                                             # nom retire dans HA : nom d'origine
assert w.br_label(w.br["ha"]) == "Home Assistant OpenThread Border Router #1950"
assert w.br_label(w.br["tv"]) == "Google TV Cuisine"
w.healer = types.SimpleNamespace(device_registry=lambda: None)
assert w.refresh_user_names() is False                               # registre illisible : rien ne change

# (C) recuperation automatique : garde-fous, chemin doux, jamais ConnectNetwork
ans = {"ping": {"ok": True, "rtt_ms": 70}, "addresses": [], "omr_addresses": ["fdd7:20e4:8187:1:ef69:9a13:7033:2b07"],
       "other_prefix_addresses": [], "error": None}


def setup(answer=ans, back=True):
    w = W()
    w.stop = threading.Event()
    w.announced, w.held = [], []
    w.proxy_announce = lambda node, ips: w.announced.append((node, list(ips))) or True
    w.proxy_hold = lambda node, ips, name: w.held.append(node) or w.proxy_holds.__setitem__(node, {})
    a = A.Anchor(w)
    a.on_state(json.dumps({"wanted": P, "enforced": True, "favored": P, "error": None}))
    a.on_available("online")
    w.anchor = a
    r = R.Reattach.__new__(R.Reattach)
    r.w, r.recovering, r.results, r.table, r.busy = w, set(), {}, None, threading.Lock()
    r.auto_diag = True
    r.h = types.SimpleNamespace(lock=threading.Lock(), storm=None,
                                nodes={MIELE: {"name": "Prise Lave-linge Miele", "available": False, "since": 1}})
    r._cached = lambda nid: {}
    r._hearing = lambda nid, ext, recent: {"by": "Prise Chauffe Eau Buanderie", "rloc16": 0xB45C, "ago_s": 30}
    calls = []
    r._thread_diag = lambda nid, name, ext: calls.append(nid) or (
        {"text": "diag", "omr": answer["omr_addresses"], "result": "omr" if answer["omr_addresses"] else "unknown", "outcome": ""})
    r._is_back = lambda nid: back
    r._command = lambda *x, **k: (_ for _ in ()).throw(AssertionError("no Matter command in the automatic way"))
    R.PROXY_SETTLE_S = 0
    return r, w, calls


R.ext_of = lambda attrs: 0xCA7A34808B66E461
r, w, calls = setup()
assert r.auto_pass(now=1000.0) == MIELE and calls == [MIELE]
assert w.announced and w.held == [MIELE] and r.results[MIELE]["result"] == "back_announce"
assert r.auto_pass(now=1100.0) is None                               # gardee (hold) et 30 min par node
r, w, calls = setup()
r.auto_diag = False
assert r.auto_pass(now=1000.0) is None and not calls                 # option coupee
r, w, calls = setup()
w.anchor.on_available("offline")
assert r.auto_pass(now=1000.0) is None and not calls                 # Thread Anchor arrete
r, w, calls = setup()
r.h.storm = types.SimpleNamespace(active=True)
assert r.auto_pass(now=1000.0) is None and not calls                 # tempete Thread
r, w, calls = setup()
w.usb_links = {"devices": [{"name": "ZBT-2", "attached": False}]}
w.anchor.update()
assert w.anchor.blocked() and r.auto_pass(now=1000.0) is None and not calls   # radio coupee : pause
r, w, calls = setup()
r._hearing = lambda nid, ext, recent: None
assert r.auto_pass(now=1000.0) is None and not calls                 # personne ne l'entend
r, w, calls = setup()
w.matter[MIELE].update(online=True, prefix=P)
assert r.auto_pass(now=1000.0) is None and not calls                 # annoncee sur le bon prefixe : rien a faire
# 5 nodes par heure au plus
r, w, calls = setup()
for i in range(7):
    r.h.nodes[f"{i:016X}"] = {"name": f"n{i}", "available": False, "since": 2 + i}
    w.matter[f"{i:016X}"] = {"online": False, "prefix": None}
handled = [r.auto_pass(now=1000.0 + k) for k in range(8)]
assert len([x for x in handled if x]) == 5, handled
print("OK")

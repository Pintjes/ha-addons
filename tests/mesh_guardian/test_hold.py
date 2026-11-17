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

# (E) noms donnes dans Home Assistant : une regle generique (valeurs fictives)
AG1, AG2 = "aaaa1111bbbb2222cccc3333dddd4444", "eeee5555ffff6666aaaa7777bbbb8888"


def wn(two=False):
    w = W()
    w.br["ha"]["agent_id"] = AG1
    w.br["ha"]["instance"] = "OTBR exemple #1"
    if two:
        w.br["ha2"] = {"online": True, "omr": P, "vendor": "OpenThread", "model": "OTBR", "instance": "OTBR exemple #2",
                       "agent_id": AG2}
    w.anchor = types.SimpleNamespace(state={"favored": P, "otbr_addon": "repo_otbr"})
    return w


addon = {"name": "Mon OTBR", "model": "Home Assistant App", "name_by_user": None, "identifiers": [["hassio", "repo_otbr"]]}
tv = {"name": "Google TV Cuisine", "name_by_user": "TV de la cuisine", "identifiers": [["cast", "x"]]}
e1 = {"domain": "otbr", "entry_id": "E1", "title": "Mon OTBR", "source": "hassio", "unique_id": AG1}
e2 = {"domain": "otbr", "entry_id": "E2", "title": "Open Thread Border Router", "source": "zeroconf", "unique_id": AG2}
lab = lambda w, k: w.br_label(w.br[k])   # noqa: E731

# 0 entree otbr : l'OTBR garde son nom mDNS, meme si l'appareil de l'add-on est renomme ; le BR tiers prend le sien
w = wn()
assert w.refresh_user_names([dict(addon, name_by_user="Salon"), tv], []) and w.dirty
assert lab(w, "ha") == "OTBR exemple #1" and lab(w, "tv") == "TV de la cuisine"
# 1 entree : titre par defaut (= nom de l'add-on) -> nom mDNS ; titre change -> ce titre ; add-on renomme -> passe devant
w = wn()
w.refresh_user_names([addon], [e1])
assert lab(w, "ha") == "OTBR exemple #1"
w.refresh_user_names([addon], [dict(e1, title="Cave")])
assert lab(w, "ha") == "Cave"
w.refresh_user_names([dict(addon, name_by_user="Salon")], [dict(e1, title="Cave")])
assert lab(w, "ha") == "Salon"
# un appareil de l'entree renomme (integration otbr) passe devant le titre
w.refresh_user_names([addon, {"name": "x", "name_by_user": "Grenier", "config_entries": ["E1"]}], [dict(e1, title="Cave")])
assert lab(w, "ha") == "Grenier"
# 1 entree, 2 OTBR : seulement celui dont le border agent id correspond ; sans id a comparer : aucun
w = wn(two=True)
w.refresh_user_names([addon], [dict(e1, title="Cave")])
assert lab(w, "ha") == "Cave" and lab(w, "ha2") == "OTBR exemple #2"
w.refresh_user_names([addon], [dict(e1, title="Cave", unique_id=None)])
assert lab(w, "ha") == "OTBR exemple #1" and lab(w, "ha2") == "OTBR exemple #2"
# 1 entree sans id et 1 seul OTBR : pas de doute
w = wn()
w.refresh_user_names([addon], [dict(e1, title="Cave", unique_id=None)])
assert lab(w, "ha") == "Cave"
# 2 entrees, 2 OTBR : chacun la sienne ; titre par defaut ignore
w = wn(two=True)
w.refresh_user_names([addon], [dict(e1, title="Cave"), dict(e2, title="Bureau")])
assert lab(w, "ha") == "Cave" and lab(w, "ha2") == "Bureau"
w.refresh_user_names([addon], [dict(e1, title="Cave"), e2])
assert lab(w, "ha2") == "OTBR exemple #2"
# sans otbr_addon connu : l'appareil de l'add-on n'est pas utilise
w = wn()
w.anchor = types.SimpleNamespace(state={"favored": P})
w.refresh_user_names([dict(addon, name_by_user="Salon")], [dict(e1, title="Cave")])
assert lab(w, "ha") == "Cave"
# nom retire dans HA : nom d'origine ; registre illisible : rien ne change
w.refresh_user_names([], [])
assert lab(w, "ha") == "OTBR exemple #1" and lab(w, "tv") == "Google TV Cuisine"
w.healer = types.SimpleNamespace(device_registry=lambda: None)
assert w.refresh_user_names() is False

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
R.BACK_WAIT_S = 0.1   # attente de retour apres l'annonce : courte dans l'essai
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
assert r.auto_pass(now=1000.0) is None and not calls                 # personne ne l'entend, pas d'ML-EID connu
# 2.35.0 : personne ne l'entend mais son ML-EID est connu -> diagnostic quand meme, toutes les 2 h seulement
real_mleid = R.mleid_of
R.mleid_of = lambda attrs: "fd27:7233:83bf:0:1234:5678:9abc:def0" if attrs else None
r, w, calls = setup(back=False)
r._cached = lambda nid: {"0/53/5": "x"}
r._hearing = lambda nid, ext, recent: None
assert r.auto_pass(now=10000.0) == MIELE and calls == [MIELE]
w.proxy_holds.clear()
assert r.auto_pass(now=10000.0 + 1801) is None                         # 30 min : trop tot sans voisin
assert r.auto_pass(now=10000.0 + 7201) == MIELE and calls == [MIELE, MIELE]
R.mleid_of = real_mleid
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

# 2.34.1 : le bouton, une fois le diagnostic Thread fait, n'envoie JAMAIS le fail-safe ni ConnectNetwork
R.BACK_WAIT_S = 0.1
for answer, expect in ((ans, "announced"), (dict(ans, omr_addresses=[]), "unknown")):
    r, w, calls = setup(answer=answer, back=False)
    r._alive = lambda nid, node_id, ext: {"ok": [], "ko": ["fdc0:6359:d5be:1::1"], "heard": [("Prise Chauffe Eau", 30, -60)],
                                          "radio_known": True}
    r._recover_send = lambda *x, **k: (_ for _ in ()).throw(AssertionError("fail-safe sent after a Thread diagnostic"))
    r.busy.acquire()
    r._recover(MIELE, "Prise Lave-linge Miele", "Buanderie", b"net", 0xCA7A34808B66E461)
    assert r.results[MIELE]["result"] == expect, r.results[MIELE]
    assert not r.busy.locked() and MIELE not in r.recovering
assert w.held == [] and r.results[MIELE]["text"]

# 2.35.0 : le bouton fait aussi le diagnostic quand aucun voisin ne l'entend (test de vie sans « heard »)
r, w, calls = setup(answer=ans, back=False)
r._alive = lambda nid, node_id, ext: {"ok": [], "ko": [], "heard": [], "radio_known": True}
r._recover_send = lambda *x, **k: (_ for _ in ()).throw(AssertionError("fail-safe sent after a Thread diagnostic"))
r.busy.acquire()
r._recover(MIELE, "Prise Lave-linge Miele", "Buanderie", b"net", 0xCA7A34808B66E461)
assert calls == [MIELE] and r.results[MIELE]["result"] == "announced", r.results[MIELE]

# 2.35.0 : « frozen » seulement si un voisin l'a entendue il y a moins de 15 min
r, w, calls = setup()
del r._thread_diag
r.live = types.SimpleNamespace(lock=threading.Lock(), nodes={})
w.anchor.diag = lambda *a, **k: {"ping": {"ok": False, "rtt_ms": None}, "error": "no answer to the network diagnostic"}
# 2.35.1 : et seulement sur une entree fiable : enfant d'un parent qui repond, ou routeur entendu il y a < 2 min
# (17/11 : 0x3000 dans la table de 0x59 a 339 s, la Miele absente de la topologie)
for ago, child, extra, expect in ((60, False, {}, "frozen"), (339, False, {}, "unknown"), (600, True, {}, "frozen"),
                                  (1800, True, {}, "unknown"), (60, False, {"old": True}, "unknown")):
    r._hearing = lambda nid, ext, recent, ago=ago, child=child, extra=extra: dict(
        {"by": "Prise Chauffe Eau", "rloc16": 0xB45C, "ago_s": ago, "child": child}, **extra)
    assert r._thread_diag(MIELE, "Prise Lave-linge Miele", 0xCA7A34808B66E461)["result"] == expect, (ago, child, extra)
# alive (Thread Anchor 0.1.4) : vrai = jamais figee ; faux = jamais d'annonce
r._hearing = lambda nid, ext, recent: {"by": "x", "rloc16": 0xB45C, "ago_s": 30, "child": True}
w.anchor.diag = lambda *a, **k: {"ping": {"ok": False}, "alive": True, "error": "no answer to the network diagnostic"}
assert r._thread_diag(MIELE, "Prise Lave-linge Miele", 0xCA7A34808B66E461)["result"] == "unknown"
w.anchor.diag = lambda *a, **k: {"ping": {"ok": False}, "alive": False, "error": None, "omr_addresses": ["fdd7::9"]}
d = r._thread_diag(MIELE, "Prise Lave-linge Miele", 0xCA7A34808B66E461)
assert d["result"] == "unknown" and not d["omr"]

# 2.35.0 : le « dernier entendu » survit a un redemarrage (fichier dans /data)
import nodetable  # noqa: E402
nodetable.NodeTable.HEARD_FILE = os.path.join(tempfile.mkdtemp(), "last_heard.json")
t1 = nodetable.NodeTable.__new__(nodetable.NodeTable)
t1.last_heard()[MIELE] = (time.time() - 600, {"by": "0x59", "rssi": -93, "by_id": "59", "ago_s": 0})
t1.save_last_heard(force=True)
t2 = nodetable.NodeTable.__new__(nodetable.NodeTable)
assert MIELE in t2.last_heard() and t2.last_heard()[MIELE][1]["by"] == "0x59"
t1.last_heard()["OLD"] = (time.time() - 25 * 3600, {"by": "x"})
t1.save_last_heard(force=True)
assert "OLD" not in nodetable.NodeTable.__new__(nodetable.NodeTable).last_heard()   # plus de 24 h : oublie

# Regle de l'utilisateur : aucun conseil de debranchement (couper le courant, retirer la pile) sans
# « frozen » prouve par le diagnostic Thread. Toutes les combinaisons d'une node indisponible
import advice  # noqa: E402
import itertools  # noqa: E402
cut_words = ("unplug", "remove the battery", "cut its power", "débrancher", "retirer la pile", "couper son alimentation")
heard = {"by": "Prise Chauffe Eau", "ago_s": 60, "rssi": -60}
for bat, hb, stale, gave, ping, srch in itertools.product(
        (False, True), (None, heard), (None, {"prefix": G, "br": None, "t": None, "at": None}), (False, True),
        (None, True), (None, {"state": "done", "result": "unknown", "text": "x"}, {"state": "pending"},
                       {"state": "done", "result": "old_prefix_only", "text": "x"}, {"state": "done", "result": "frozen", "text": "x"})):
    row = {"id": "0x5A", "name": "Miele", "area": "Buanderie", "network": "thread", "available": False, "battery": bat,
           "since": 1000.0, "heard_by": hb, "stale_prefix": stale, "ping_ok": ping, "search": srch}
    advice.advise([row], [], {"now": 2000.0, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {},
                              "history": lambda rid: [], "gave_up": {"0x5A"} if gave else set(), "ghosts": [], "omr_changes": 0})
    txt = f"{row['advice']} {row['advice_detail']}".lower()
    proven = hb is not None and (srch or {}).get("result") == "frozen"
    assert proven or not any(wd in txt for wd in cut_words), (row, txt)
print("OK")

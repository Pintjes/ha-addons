"""2.40.0 : (1) le rattachement d'un enfant appris par Thread Anchor (thread_anchor/children, version 1)
quand rien d'autre ne le donne, sans trafic en plus, et jamais avec le « signal » de Thread Anchor (mesure
vers son border router) ; (2) le border router préféré de Home Assistant (thread/list_datasets).
Valeurs fictives uniquement."""
import ast
import json
import os
import sys
import time
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import anchor as A  # noqa: E402
import nodetable  # noqa: E402

A.ANCHOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_unused_anchor.json")
CHILD, BR = 0x1122334455667788, 0x99AABBCCDDEEFF00
now = time.time()
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))   # noqa: E731

# (1) lecture du sujet : enfants seulement, signal ignore, parent par defaut = RLOC16 & 0xFC00
a = A.Anchor(types.SimpleNamespace(), clock=lambda: now)
a.on_children(json.dumps({"version": 1, "updated": iso(now), "count": 3, "nodes": {
    f"{CHILD:016x}": {"rloc16": "0x6c05", "parent": "0x6c00", "role": "child", "source": "childtable", "read_at": iso(now - 600),
                      "signal": {"rssi_avg": -40, "toward": "otbr"}},
    "0011223344556677": {"rloc16": "0x7400", "parent": None, "role": "router", "read_at": iso(now)},
    "8899aabbccddeeff": {"rloc16": "0x5001", "parent": None, "role": "child", "read_at": iso(now - 8 * 86400)}}}))
e = a.child(CHILD)
assert e and e["rloc16"] == 0x6C05 and e["parent"] == 0x6C00 and e["rssi"] is None and e["lqi"] is None, e
assert a.child(0x0011223344556677) is None                     # un routeur n'est pas un enfant
assert a.child(0x5001) is None and a.child(0x8899AABBCCDDEEFF) is None   # trop ancien (plus de 24 h)
assert a.child(None) is None
a.on_children("pas du json")                                      # rien ne casse, la liste reste
assert a.child(CHILD)

# (2) find_parents : voie 4, nommee par les tables du maillage (le border router annonce son ext)
thread = {
    "000000000000000A": {"name": "Prise enfant", "attrs": {"0/53/1": 4, "0/53/7": [], "0/53/8": []}},
    "000000000000000B": {"name": "Routeur voisin", "attrs": {"0/53/1": 5, "0/51/0": [],
                         "0/53/7": [{"0": BR, "2": 0x6C00, "5": 3, "6": -60, "13": False}]}},
}
labels = {BR: "Routeur tiers A"}
used = {}
parents, rlocs = nodetable.find_parents(thread, labels, used, {"000000000000000A": e})
assert parents["000000000000000A"][0] == "Routeur tiers A", parents
assert parents["000000000000000A"][1] is None and parents["000000000000000A"][2] is None   # pas de signal invente
assert used["000000000000000A"] == {("thread_anchor", e["t"])} and rlocs["000000000000000A"] == 0x6C05
# le signal vient de la propre table de l'enfant quand il y a son parent
thread["000000000000000A"]["attrs"]["0/53/7"] = [{"0": BR, "2": 0x6C00, "5": 2, "6": -71, "13": False}]
parents, _ = nodetable.find_parents(thread, labels, {}, {"000000000000000A": e})
assert parents["000000000000000A"][1:3] == (-71, 2), parents
# une autre voie a deja trouve le parent : la voie 4 ne le remplace pas
thread["000000000000000B"]["attrs"]["0/53/7"].append({"0": 0x42, "2": 0x6C07, "5": 3, "6": -50, "13": True})
labels[0x42] = "Prise enfant"
parents, _ = nodetable.find_parents(thread, labels, {}, {"000000000000000A": e})
assert parents["000000000000000A"][0] == "Routeur voisin", parents
# parent inconnu des tables : nom generique « router N »
parents, _ = nodetable.find_parents({"000000000000000A": thread["000000000000000A"]}, {}, {}, {"000000000000000A": e})
assert parents["000000000000000A"][0] == "router 27 (0x6c00)", parents

# (3) border router prefere : extrait de watcher.py (zeroconf absent)
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Watch")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("set_preferred", "is_preferred")]
assert len(body) == 2
ns = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body,
                                                                       decorator_list=[])], type_ignores=[])), "w", "exec"), ns)
w = ns["W"]()
w.set_preferred([{"preferred": False, "preferred_border_agent_id": "aa"},
                 {"preferred": True, "preferred_border_agent_id": "ABCDEF0123456789", "preferred_extended_address": "99aabbccddeeff00",
                  "network_name": "Reseau-Demo"}])
assert w.is_preferred({"agent_id": "abcdef0123456789"}) and w.is_preferred({"xa": BR})
assert not w.is_preferred({"agent_id": "other", "xa": 0x1234})
w.set_preferred([])
assert w.preferred is None and not w.is_preferred({"xa": BR})
w.set_preferred(None)
assert not w.is_preferred({"xa": BR})

# (4) la page : icone et « i » du border router prefere, en anglais et en francais
page = open(os.path.join(MG, "web", "index.html"), encoding="utf-8").read()
assert "IC.phonekey" in page and 'tipI(L("br_pref_tip"))' in page and page.count("br_pref_tip:") == 2 and page.count("br_pref_l:") == 2
# 2.40.1 : le texte court choisi par l'utilisateur, exactement
assert 'br_pref_tip:"Identifiants Android / iOS (HA)"' in page and 'br_pref_tip:"Android / iOS credentials (HA)"' in page
print("OK")

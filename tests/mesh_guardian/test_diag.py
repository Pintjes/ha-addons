"""Essai du diagnostic Thread par Thread Anchor (MQTT thread_anchor/diag) dans la tentative de
recuperation : RLOC16 lu chez les voisins, adresses courantes -> annonce a sa place, ancien prefixe
seulement, pile figee ; conseil de la fiche ; date d'ancrage donnee par Thread Anchor."""
import json
import os
import sys
import tempfile
import threading
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import advice  # noqa: E402
import anchor as A  # noqa: E402
import nodetable  # noqa: E402
import reattach as R  # noqa: E402

A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
MIELE, MIELE_HEX = 0xCA7A34808B66E461, "000000000000005A"
P = "fdd7:20e4:8187:1::/64"


class Mq:
    """Faux MQTT : Thread Anchor repond tout de suite a la requete."""
    def __init__(self, answer):
        self.answer, self.sent, self.anchor = answer, [], None

    def publish(self, topic, payload, **kw):
        self.sent.append((topic, json.loads(payload)))
        req = json.loads(payload)
        if self.answer is not None:
            res = dict(self.answer, id=req["id"], rloc16=req["rloc16"])
            threading.Timer(0.05, self.anchor.on_diag, args=(A.DIAG_RESULT_TOPIC + req["id"], json.dumps(res))).start()


class W:
    def __init__(self):
        self.lock, self.events, self.dirty, self.usb_links, self.br = threading.RLock(), [], False, None, {}
        self.matter = {MIELE_HEX: {"online": False, "prefix": "fdc0:6359:d5be:1::/64"}}
        self.stop = threading.Event()
        self.proxied = []

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def _omr_now(self):
        return {P}

    def proxy_announce(self, node, ips):
        self.proxied.append((node, list(ips)))
        return True

    def proxy_withdraw(self, node):
        self.proxied.append(("withdraw", node))


def anchor_with(answer):
    w = W()
    a = A.Anchor(w)
    w.mqtt = Mq(answer)
    w.mqtt.anchor = a
    w.anchor = a
    a.on_state(json.dumps({"wanted": P, "enforced": True, "favored": P, "error": None,
                           "anchored_since": "2026-11-17T11:30:00+01:00"}))
    a.on_available("online")
    return w, a


# date d'ancrage : celle de Thread Anchor quand elle est donnee et le prefixe en place
w, a = anchor_with(None)
assert a.anchored_since == A.parse_iso("2026-11-17T11:30:00+01:00"), a.anchored_since

# requete / reponse MQTT
ans = {"ping": {"ok": True, "rtt_ms": 41}, "addresses": ["fdd7:20e4:8187:1:1:2:3:4"],
       "omr_addresses": ["fdd7:20e4:8187:1:1:2:3:4"], "other_prefix_addresses": [], "error": None}
w, a = anchor_with(ans)
res = a.diag(0xB45C, MIELE, timeout=2)
assert w.mqtt.sent[0][0] == A.DIAG_REQUEST_TOPIC
assert w.mqtt.sent[0][1]["rloc16"] == "0xB45C" and w.mqtt.sent[0][1]["ext"] == "ca7a34808b66e461" and w.mqtt.sent[0][1]["ping"]
assert res["omr_addresses"] == ["fdd7:20e4:8187:1:1:2:3:4"] and not a._diag_waits
w2, a2 = anchor_with(None)
assert a2.diag(0xB45C, MIELE, timeout=0.2) is None                     # pas de reponse : None
a2.on_available("offline")
assert not a2.diag_ready() and a2.diag(0xB45C, MIELE, timeout=0.2) is None

# RLOC16 chez les voisins ; extAddress passee par un flottant : retrouvee quand meme
live = types.SimpleNamespace(stamp=lambda nid, path: 1000.0, lock=threading.Lock())
thread = {"36": {"name": "Prise Chauffe Eau Buanderie", "meta": {"available": True}, "node": {},
                 "attrs": {"0/53/7": [{"0": float(MIELE), "1": 196, "2": 46172, "6": -54, "10": True, "11": True, "13": True}]}}}
hm = nodetable.heard_map(thread, live, 1060.0)
e = nodetable.heard_of(hm, MIELE)
assert e and e["rloc16"] == 0xB45C and e["child"] and e["ftd"] and e["fuzzy"], e
assert nodetable.heard_of(hm, MIELE + 10 ** 6) is None


# tentative de recuperation : les trois issues du diagnostic
def reattach_for(answer):
    w, a = anchor_with(answer)
    r = R.Reattach.__new__(R.Reattach)
    r.w = w
    r.h = types.SimpleNamespace(lock=threading.Lock(), nodes={MIELE_HEX: {"name": "Prise Lave-linge Miele"},
                                                             "36": {"name": "Prise Chauffe Eau Buanderie"}})
    r.live = types.SimpleNamespace(lock=threading.Lock(), stamp=lambda nid, path: 1e12,
                                   nodes={"36": {"available": True, "attributes": thread["36"]["attrs"]},
                                          MIELE_HEX: {"available": False, "attributes": {}}})
    return r, w


r, w = reattach_for(ans)
d = r._thread_diag(MIELE_HEX, "Prise Lave-linge Miele", MIELE)
assert d["result"] == "omr" and d["omr"] == ["fdd7:20e4:8187:1:1:2:3:4"] and "0xB45C" in d["text"], d
r, w = reattach_for(dict(ans, omr_addresses=[], other_prefix_addresses=["fdc0:6359:d5be:1:e83c:35e9:edb8:ab71"]))
d = r._thread_diag(MIELE_HEX, "Prise Lave-linge Miele", MIELE)
assert d["result"] == "old_prefix_only" and "fdc0" in d["outcome"], d
# ping sans reponse mais diagnostic qui repond : pas figee (ancien prefixe seulement)
r, w = reattach_for(dict(ans, ping={"ok": False, "rtt_ms": None}, omr_addresses=[], other_prefix_addresses=["fdc0::1"]))
d = r._thread_diag(MIELE_HEX, "Prise Lave-linge Miele", MIELE)
assert d["result"] == "old_prefix_only", d
# ni diagnostic ni ping : figee
r, w = reattach_for({"ping": {"ok": False, "rtt_ms": None}, "addresses": [], "omr_addresses": [],
                     "other_prefix_addresses": [], "error": "no answer to the network diagnostic"})
d = r._thread_diag(MIELE_HEX, "Prise Lave-linge Miele", MIELE)
assert d["result"] == "frozen" and "Chauffe Eau" in d["outcome"], d
# autres erreurs : rien de prouve (occupe, trop tot, une autre node a ce RLOC16)
for err in ("busy", "too soon", "another node answers at this RLOC16: ext 01 instead of ca7a34808b66e461"):
    r, w = reattach_for(dict(ans, error=err))
    d = r._thread_diag(MIELE_HEX, "Prise Lave-linge Miele", MIELE)
    assert d["result"] == "unknown" and err.split(":")[0] in d["text"] and not d["omr"], d

# conseil de la fiche : debrancher seulement apres « pile figee » prouvee
unplug = advice.t("Unplug it for 10s")


def advice_of(row):
    c = {"now": 2000.0, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
         "gave_up": {"0x5A"}, "ghosts": [], "omr_changes": 0}
    advice.advise([row], [], c)
    return row["advice"] or ""


base = {"id": "0x5A", "name": "Prise Lave-linge Miele", "area": "Buanderie", "network": "thread", "available": False,
        "battery": False, "since": 1000.0, "heard_by": e}
assert unplug not in advice_of(dict(base))
assert advice_of(dict(base, search={"result": "frozen", "text": "x"})) == \
    advice.t("Network stack stuck: last resort, cut its power for 10s (your call)")
assert advice_of(dict(base, search={"result": "old_prefix_only", "text": "x"})) == \
    advice.t("Only has the old address prefix: a remedy on the border router is possible")
# 2.33.0 en production : HTTP 503 « 'list' object has no attribute 'items' » sur /api/table. Le resultat
# de heard_map() (un dict) portait le nom « heard », reutilise dans la boucle de build() pour la liste
# des parents candidats d'un enfant : la node suivante appelait heard_of() sur une liste.
import ast  # noqa: E402

src = open(os.path.join(MG, "nodetable.py"), encoding="utf-8").read()
build = next(f for c in ast.parse(src).body if isinstance(c, ast.ClassDef) and c.name == "NodeTable"
             for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "build")
holder = [n.targets[0].id for n in ast.walk(build) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
          and getattr(n.value.func, "id", None) == "heard_map"]
assert len(holder) == 1, holder
again = [n.lineno for n in ast.walk(build) if isinstance(n, ast.Assign) for tg in n.targets
         if isinstance(tg, ast.Name) and tg.id == holder[0]]
assert len(again) == 1, f"{holder[0]} assigned again in build() at lines {again}"
try:   # et le symptome lui-meme : heard_of() sur la liste locale
    nodetable.heard_of([(3, -60, "x")], MIELE)
    raise AssertionError("heard_of on a list should fail")
except AttributeError as err:
    assert "items" in str(err)
print("OK")

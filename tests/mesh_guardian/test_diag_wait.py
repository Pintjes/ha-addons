"""Attente de la reponse de Thread Anchor (2.35.2) : une recherche par ext / ML-EID peut durer tout le
balayage meshdiag (90 s) ; la reponse « busy » (un autre diagnostic en cours) est redemandee, puis rendue
telle quelle ; dans la passe automatique, « busy » ne compte pas comme une tentative.
Valeurs fictives uniquement."""
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

import anchor as A  # noqa: E402
import reattach as R  # noqa: E402

A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
EXT = 0x1122334455667788
P = "fd00:1:2:3::/64"

# l'attente couvre le budget du balayage de Thread Anchor (90 s) et ses autres etapes
assert A.DIAG_WAIT_S >= 90 + 15, A.DIAG_WAIT_S


class Mq:
    """Faux MQTT : Thread Anchor repond « busy » aux `busy` premieres requetes, puis `answer`
    apres `delay` secondes (une recherche qui dure)."""
    def __init__(self, answer, busy=0, delay=0.05):
        self.answer, self.busy, self.delay, self.sent, self.anchor = answer, busy, delay, [], None

    def publish(self, topic, payload, **kw):
        req = json.loads(payload)
        self.sent.append(req)
        if len(self.sent) <= self.busy:
            res, wait = {"id": req["id"], "error": "busy"}, 0.01
        elif self.answer is None:
            return
        else:
            res, wait = dict(self.answer, id=req["id"]), self.delay
        threading.Timer(wait, self.anchor.on_diag, args=(A.DIAG_RESULT_TOPIC + req["id"], json.dumps(res))).start()


def anchor_with(mq):
    w = types.SimpleNamespace(stop=threading.Event(), lock=threading.RLock(), events=[])
    a = A.Anchor(w)
    w.mqtt, w.anchor, mq.anchor = mq, a, a
    a.on_state(json.dumps({"wanted": P, "enforced": True, "favored": P, "error": None}))
    a.on_available("online")
    return w, a


ok = {"ping": {"ok": True, "rtt_ms": 30}, "omr_addresses": ["fd00:1:2:3::9"], "addresses": ["fd00:1:2:3::9"],
      "other_prefix_addresses": [], "error": None, "alive": True}

# une reponse qui arrive tard (recherche longue) est attendue, pas declaree absente
w, a = anchor_with(Mq(ok, delay=0.5))
res = a.diag(None, EXT, timeout=2, mleid="fd00:aa::1")
assert res and res["omr_addresses"] == ["fd00:1:2:3::9"], res

# « busy » : redemande, puis la vraie reponse
w, a = anchor_with(Mq(ok, busy=2))
res = a.diag(None, EXT, timeout=1, mleid="fd00:aa::1", busy_wait=2, busy_retry=0.05)
assert res and res.get("error") is None and len(w.mqtt.sent) == 3, (res, w.mqtt.sent)
assert len({r["id"] for r in w.mqtt.sent}) == 3          # une nouvelle requete a chaque fois
assert not a._diag_waits

# toujours « busy » au bout du temps permis : rendue telle quelle
w, a = anchor_with(Mq(ok, busy=1000))
res = a.diag(None, EXT, timeout=1, mleid="fd00:aa::1", busy_wait=0.3, busy_retry=0.05)
assert res and res["error"] == "busy" and 2 <= len(w.mqtt.sent) <= 10, (res, len(w.mqtt.sent))

# arret de l'add-on pendant l'attente d'un tour : on rend la derniere reponse sans attendre
w, a = anchor_with(Mq(ok, busy=1000))
w.stop.set()
res = a.diag(None, EXT, timeout=1, mleid="fd00:aa::1", busy_wait=5, busy_retry=1)
assert res["error"] == "busy" and len(w.mqtt.sent) == 1

# une autre erreur n'est pas redemandee
w, a = anchor_with(Mq({"error": "too soon"}))
res = a.diag(0x1C01, EXT, timeout=1, busy_wait=2, busy_retry=0.05)
assert res["error"] == "too soon" and len(w.mqtt.sent) == 1

# pas de reponse du tout : None, comme avant
w, a = anchor_with(Mq(None))
assert a.diag(0x1C01, EXT, timeout=0.2) is None

# _thread_diag : « busy » marque, une autre erreur non
rd = R.Reattach.__new__(R.Reattach)
rd.live = True
rd._hearing = lambda nid, ext, s: {"rloc16": 0x1C01, "by": "Routeur A", "ago_s": 30, "child": True}
rd._cached = lambda nid: {}
rd.w = types.SimpleNamespace(anchor=types.SimpleNamespace(diag_ready=lambda: True,
                                                         diag=lambda *a, **k: {"error": "busy"}))
d = rd._thread_diag("00000000000000AB", "Prise test", EXT)
assert d["busy"] and d["result"] == "unknown", d
rd.w.anchor.diag = lambda *a, **k: {"error": "rloc16 not found"}
assert not rd._thread_diag("00000000000000AB", "Prise test", EXT).get("busy")

# passe automatique : « busy » ne consomme ni le creneau de la node ni le quota horaire
calls = []
rd.auto_diag = True
rd.recovering = set()
rd.busy = threading.Lock()
rd.h = types.SimpleNamespace(lock=threading.RLock(), storm=None,
                             nodes={"00000000000000AB": {"available": False, "name": "Prise test", "since": 1}})
rd.w = types.SimpleNamespace(
    anchor=types.SimpleNamespace(diag_ready=lambda: True, blocked=lambda: False),
    matter={"00000000000000AB": {"online": False}}, stale_prefix=lambda nid, thread=True: None,
    emit=lambda *a, **k: calls.append(a))
rd._hearing = lambda nid, ext, s: {"rloc16": 0x1C01}
rd._cached = lambda nid: {"0/53/7": []}
R.ext_of = lambda cached: EXT
rd._thread_diag = lambda nid, name, ext: {"text": "x", "omr": [], "result": "unknown", "outcome": "", "busy": True}
assert rd.auto_pass(now=1000.0) == "00000000000000AB"
assert "00000000000000AB" not in rd.auto_last and rd.auto_done == [] and not calls, (rd.auto_last, rd.auto_done)
rd._thread_diag = lambda nid, name, ext: {"text": "x", "omr": [], "result": "unknown", "outcome": ""}
assert rd.auto_pass(now=1001.0) == "00000000000000AB"
assert rd.auto_last["00000000000000AB"] == 1001.0 and rd.auto_done == [1001.0] and calls
print("OK")

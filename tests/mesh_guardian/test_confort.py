"""Essais du lot confort : compteurs sous verrou, tempete sans interblocage, nodes supprimees oubliees partout."""
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
except ImportError:   # pas besoin du vrai module pour ces essais
    sys.modules["websocket"] = types.ModuleType("websocket")

import healer  # noqa: E402
import matterlive  # noqa: E402
import matterlog  # noqa: E402
import quality  # noqa: E402
import storm  # noqa: E402
from store import gone_keys  # noqa: E402

A, B, C = "00000000000000AB", "00000000000000BC", "00000000000000CD"
IDS = {0xAB, 0xBC}   # CD a ete supprimee du Matter Server

# --- gone_keys : seules les cles de nodes disparues, une cle qui n'est pas un numero reste
assert gone_keys([A, B, C, "pas-un-id"], IDS) == [C]

# --- compteurs : plusieurs fils comptent en meme temps, rien ne se perd
h = healer.Healer.__new__(healer.Healer)
h.lock = threading.RLock()
h.pings_sent = 0
h.session = {"pings_sent": 0, "recovered_by_ping": 0, "back_on_their_own": 0, "gave_up": 0}
h.recent = []


def many():
    for _ in range(500):
        h._ping_counted()


th = [threading.Thread(target=many) for _ in range(8)]
for x in th:
    x.start()
for x in th:
    x.join()
assert h.pings_sent == 4000 and h.session["pings_sent"] == 4000 and h.last_24h()["pings_sent"] == 4000, (h.pings_sent, h.session)
h.tally("gave_up", 3)
h.tally("gave_up", -2)
assert h.last_24h()["gave_up"] == 1 and h.session["gave_up"] == 1


# --- tempete : l'evenement emis repasse par observe, d'un autre fil, pendant que check tourne
class W:
    def __init__(self):
        self.lock = threading.Lock()
        self.br = {"x": {"role": "detached", "name": "BR"}}
        self.events = []
        self.s = None

    def br_relevant(self, b):
        return True

    def br_label(self, b):
        return b["name"]

    def emit(self, kind, msg, **data):
        self.events.append((kind, data))
        # un autre fil qui prend le verrou du watcher puis signale un evenement : interbloque si
        # check gardait son verrou en emettant
        def other():
            with self.lock:
                self.s.observe("node_unavailable", {"name": "Autre"})
                self.s.summary()
        t = threading.Thread(target=other)
        t.start()
        t.join(5)
        assert not t.is_alive(), "interblocage"


w = W()
s = storm.Storm(w)
w.s = s
for _ in range(4):
    s.observe("br_detach", {})
s.check({"omr_list": []})
assert s.active and w.events[0][0] == "storm_start" and w.events[0][1]["splits"] == 4 and w.events[0][1]["reasons"] == ["splits"]
s.check({"omr_list": []})
assert "BR" in s.summary()["border_routers_detached"]
# calme depuis plus de 15 min : fin de tempete, emise hors du verrou elle aussi
s.splits, s.downs, s.calm_since = [], [], time.time() - storm.CALM - 1
s.check({"omr_list": []})
assert not s.active and w.events[-1][0] == "storm_end" and s.summary()["last_storm"]["nodes_count"] >= 1

# --- reponses (quality) : la node supprimee est oubliee
q = quality.Quality.__new__(quality.Quality)
q.lock = threading.RLock()
q.rtt = {A: {"ok": [1]}, B: {"ok": [2]}, C: {"ok": [3]}}
saved = []
q._save = lambda: saved.append("q")
assert q.prune(IDS) == 1 and set(q.rtt) == {A, B} and saved == ["q"]
assert q.prune(IDS) == 0 and saved == ["q"], "rien a oublier : pas d'ecriture"

# --- contacts et sources (matterlive)
ml = matterlive.MatterLive.__new__(matterlive.MatterLive)
ml.lock = threading.RLock()
ml.contacts = {A: 1, C: 2}
ml.sources = {B: {"src": "report"}, C: {"src": "ping"}}
ml._save_contacts = lambda: saved.append("contacts")
ml._save_sources = lambda: saved.append("sources")
assert ml.prune(IDS) == 2 and set(ml.contacts) == {A} and set(ml.sources) == {B}
assert saved[-2:] == ["contacts", "sources"]

# --- journal du Matter Server (matterlog) : adresses, sessions ouvertes, hors ligne, heures
matterlog.STATE_FILE = os.path.join(tempfile.mkdtemp(), "matter_log.json")
lg = matterlog.MatterLog(None)
h0 = int(time.time() // 3600)
lg.addr = {A: "fd00::1", C: "fd00::2"}
lg.opened = {C: [time.time()]}
lg.down = {C: time.time()}
lg.hours = {h0: {A: [1, 0, 0, 0, 0, 0], C: [2, 0, 0, 0, 0, 0]}, h0 - 1: {C: [1, 0, 0, 0, 0, 0]}}
assert lg.prune(IDS) == 5
assert lg.addr == {A: "fd00::1"} and lg.opened == {} and lg.down == {} and lg.hours == {h0: {A: [1, 0, 0, 0, 0, 0]}, h0 - 1: {}}
assert os.path.exists(matterlog.STATE_FILE), "etat ecrit apres l'oubli"

print("OK")

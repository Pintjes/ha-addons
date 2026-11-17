"""Moins de trafic radio (2.37.0) : (a) les tables Thread relues en UNE seule lecture ; (b) une node sur
secteur qui a donne signe de vie d'elle-meme depuis notre derniere lecture n'est relue que toutes les heures ;
(c) le balayage ne pingue pas les nodes entendues dans l'heure. Valeurs fictives uniquement."""
import sys
import threading
import time
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import healer as H  # noqa: E402
import quality as Q  # noqa: E402

A, B, C = "000000000000000A", "000000000000000B", "000000000000000C"


class Live:
    def __init__(self, contacts):
        self.lock, self.connected, self.contacts, self.set = threading.RLock(), True, contacts, []
        self.nodes = {k: {"attributes": {"0/53/1": 3}} for k in (A, B, C)}

    def node_ids(self):
        return {int(k, 16) for k in (A, B, C)}

    def set_attribute(self, nid, path, value):
        self.set.append((nid, path, value))

    def note_contact(self, nid, src="report"):
        self.contacts[nid] = time.time()


# (a) une seule lecture pour les 7 chemins d'une node sur secteur, les valeurs rangees chacune a sa place
calls = []
q = Q.Quality.__new__(Q.Quality)
q.lock, q.rtt, q.live = threading.RLock(), {}, Live({})
q.h = types.SimpleNamespace(matter_command=lambda cmd, args, timeout=0: calls.append((cmd, args)) or
                            {p: i for i, p in enumerate(args["attribute_path"])})
q._refresh_thread(A)
assert len(calls) == 1 and isinstance(calls[0][1]["attribute_path"], list) and len(calls[0][1]["attribute_path"]) == 7, calls
assert {p for _, p, _ in q.live.set} == set(calls[0][1]["attribute_path"])
calls.clear()
q._refresh_thread(A)                     # moins d'une heure apres : rien
assert not calls
q._read_paths(B, ("0/53/1",))           # un seul chemin : demande simple, reponse {chemin: valeur}
assert calls[-1][1]["attribute_path"] == "0/53/1"

# (b) relecture espacee quand la node a donne signe de vie d'elle-meme
now = time.time()
q = Q.Quality.__new__(Q.Quality)
q.lock = threading.RLock()
q.w = types.SimpleNamespace(storm=None)
nodes = {k: {"available": True, "battery": False} for k in (A, B, C)}
q.h = types.SimpleNamespace(lock=threading.RLock(), nodes=nodes, mass_until=0)
last = now - 20 * 60                     # lues il y a 20 min
q.rtt = {k: {"t": last} for k in (A, B, C)}
q.live = Live({A: last + 1,              # contact = notre propre lecture : relue toutes les 15 min
               B: now - 5 * 60,          # rapport d'elle-meme il y a 5 min : relue toutes les heures
               C: now - 40 * 60})        # contact ancien : relue toutes les 15 min
due = q._due()
assert due and due[0] in (A, C), due
q.rtt[A]["t"] = q.rtt[C]["t"] = now      # A et C relues maintenant : B n'est pas due (20 min < 60 min)
assert q._due() is None
q.rtt[B]["t"] = now - 61 * 60            # au bout d'une heure, B est relue quand meme (tables horaires)
assert q._due()[0] == B

# (c) le balayage saute les nodes entendues dans l'heure
pinged = []
h = H.Healer.__new__(H.Healer)
h.lock, h.enabled, h.mass_until, h.storm, h.anchor = threading.RLock(), True, 0, None, None
h.ping_all_interval = 3600
h.nodes = {k: {"available": True, "battery": False, "name": k[-1]} for k in (A, B, C)}
live = Live({A: now - 10 * 60, B: now - 2 * 3600})   # C : jamais de contact
events = []
h.w = types.SimpleNamespace(stop=threading.Event(), live=live, dirty=False,
                            emit=lambda kind, text, **d: events.append((kind, text, d)))
h.matter_command = lambda cmd, args, timeout=0: pinged.append(args["node_id"]) or {"fd00::1": True}
h._ping_counted = lambda: None
h._save_state = lambda: None
H.time.sleep = lambda s: None
h._sweep_mains()
assert sorted(pinged) == [int(B, 16), int(C, 16)], pinged
assert h.sweep["skipped"] == 1 and h.sweep["total"] == 2 and events[-1][2]["skipped"] == 1, (h.sweep, events)
# toutes entendues : aucun ping, rien d'emis
pinged.clear()
live.contacts.update({B: now, C: now})
h._sweep_mains()
assert not pinged and h.sweep["total"] == 0 and h.sweep["skipped"] == 3
print("OK")

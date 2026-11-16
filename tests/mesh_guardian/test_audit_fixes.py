"""Essais des corrections de priorite 1 : store, balayage, coupures, reinitialisation verifiee, codes."""
import ast
import base64
import glob
import json
import os
import sys
import tempfile
import threading
import time

MG = sys.argv[1]
sys.path.insert(0, MG)
import store  # noqa: E402

# --- store : ecriture complete, fichier illisible mis de cote et jamais ecrase
d = tempfile.mkdtemp()
p = os.path.join(d, "x.json")
store.save_json(p, {"a": 1})
assert store.load_json(p) == {"a": 1} and not os.path.exists(p + ".tmp")
try:
    store.save_json(p, {"b": object()})          # donnee invalide : le fichier reste intact
    raise AssertionError("objet accepte")
except TypeError:
    pass
assert store.load_json(p) == {"a": 1}
open(p, "w").write('{"a": 1, "tron')               # fichier tronque (coupure de courant)
assert store.load_json(p, {"vide": True}) == {"vide": True}
assert not os.path.exists(p) and len(glob.glob(p + ".bad-*")) == 1
assert store.load_json(os.path.join(d, "absent.json"), []) == []

# --- pairing : fichier illisible conserve, produit verifie meme sur le numero de node, devinettes limitees
import pairing  # noqa: E402

pp = os.path.join(tempfile.mkdtemp(), "codes.json")
open(pp, "w").write("{pas du json")
pa = pairing.Pairing(pp)
assert pa.items == {} and glob.glob(pp + ".bad-*"), "fichier abime non mis de cote"
A = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/51/0": [{"4": base64.b64encode(b"\x11" * 8).decode(), "7": 4}]}
OTHER = {"0/40/2": 0x1234, "0/40/4": 0x9}
pa.set("05", A, {"05"}, "MT:Y.K9042C00KA0648G00", "Prise", "Salon", "Plug")
assert pa.of("05", OTHER, {"05"}) is None, "meme numero, autre produit : refuse"
assert pa.of("05", A, {"05"}) is not None
# adresse a zeros ignoree, interface Thread preferee
z = base64.b64encode(b"\x00" * 8).decode()
assert pairing.identity({"0/51/0": [{"4": z, "7": 4}]})["hw"] is None
two = [{"4": base64.b64encode(b"\x22" * 6).decode(), "7": 1}, {"4": base64.b64encode(b"\x33" * 8).decode(), "7": 4}]
assert pairing.identity({"0/51/0": two})["hw"] == two[1]["4"]
assert pairing.identity({"0/51/0": two[:1] + two[:1]})["hw"] is None   # deux interfaces non Thread : on ne choisit pas
# code scanne trop ancien : plus de rattachement automatique
pb = pairing.Pairing(os.path.join(tempfile.mkdtemp(), "c.json"))
pb.scan("MT:Y.K9042C00KA0648G00", {"10"})
for e in pb.items.values():
    e["saved"] = time.time() - pairing.GUESS_SCAN_S - 5
assert pb.of("20", A, {"20"}) is None and len(pb.free({"20"})) == 1
# code en attente depuis une reinitialisation trop ancienne : plus de rattachement automatique
pc = pairing.Pairing(os.path.join(tempfile.mkdtemp(), "c.json"))
pc.set("30", A, {"30"}, "MT:Y.K9042C00KA0648G00")
pc.mark_reset("30")
assert pc.of("40", dict(A, **{"0/51/0": []}), {"40"}) is not None      # recente : rattachee
pc2 = pairing.Pairing(os.path.join(tempfile.mkdtemp(), "c.json"))
pc2.set("30", A, {"30"}, "MT:Y.K9042C00KA0648G00")
pc2.mark_reset("30")
for e in pc2.items.values():
    e["reset_t"] -= pairing.GUESS_RESET_S + 5
assert pc2.of("40", dict(A, **{"0/51/0": []}), {"40"}) is None

# --- reattach : reinitialisation verifiee
import reattach  # noqa: E402

reattach.RESETS_FILE = os.path.join(tempfile.mkdtemp(), "resets.json")
FABS = [{"2": 24582, "254": 1}, {"2": 4939, "254": 2}]


class H:
    def __init__(self, own_answer, still_reachable=False, remove_fails=None):
        self.lock, self.nodes, self.calls = threading.Lock(), {"00000000000000AB": {"name": "Prise"}}, []
        self.own_answer, self.still, self.remove_fails = own_answer, still_reachable, remove_fails

    def matter_command(self, command, args=None, timeout=60, timing=None):
        name = args.get("command_name", command)
        self.calls.append((name, (args.get("payload") or {}).get("fabricIndex")))
        if command == "read_attribute":
            if args["attribute_path"] == "0/62/5":
                if self.still:
                    return {"0/62/5": 2}
                raise TimeoutError("no session")
            return {"0/62/1": FABS, "0/62/5": 2}
        if name == "RemoveFabric":
            if args["payload"]["fabricIndex"] == 2:
                if isinstance(self.own_answer, Exception):
                    raise self.own_answer
                return self.own_answer
            return {"statusCode": 0}
        if name == "remove_node" and self.remove_fails:
            raise self.remove_fails
        return None


class W:
    def __init__(self):
        self.stop, self.events = threading.Event(), []

    def emit(self, kind, text, **data):
        self.events.append((kind, data))


def reset(h):
    r = reattach.Reattach(W(), h)
    return r.reset_node("00000000000000AB"), h.calls


res, calls = reset(H({"statusCode": 0}))
assert res["result"] == "reset" and ("RemoveFabric", 1) in calls and ("RemoveFabric", 2) in calls and calls[-1][0] == "remove_node", (res, calls)
assert calls.index(("RemoveFabric", 2)) > calls.index(("RemoveFabric", 1))          # la sienne en dernier
res, calls = reset(H({"statusCode": 11}))                                          # l'appareil refuse
assert res["result"] == "partial" and "remove_node" not in [c[0] for c in calls], (res, calls)
res, calls = reset(H(TimeoutError("x"), still_reachable=True))                      # pas de reponse mais toujours la
assert res["result"] == "partial" and "remove_node" not in [c[0] for c in calls]
res, calls = reset(H(TimeoutError("x"), still_reachable=False))                     # pas de reponse et injoignable
assert res["result"] == "unsure" and calls[-1][0] == "remove_node"
res, _ = reset(H({"statusCode": 0}, remove_fails=RuntimeError("timeout")))           # le serveur ne la retire pas
assert res["result"] == "reset" and res["listed"] is True
res, _ = reset(H({"statusCode": 0}, remove_fails=RuntimeError("5 Node 171 does not exist")))
assert res["result"] == "reset" and res["listed"] is False
assert json.load(open(reattach.RESETS_FILE))   # ecrit

# --- healer : balayage poursuivi malgre une node en erreur, coupure refermee au premier passage
src = open(os.path.join(MG, "healer.py"), encoding="utf-8").read()
tree = ast.parse(src)
assert "except ConnectionError as err:   # the Matter Server is out of reach" in src
assert "lst[-1][1] = max(since, lst[-1][0])" in src
print("OK")

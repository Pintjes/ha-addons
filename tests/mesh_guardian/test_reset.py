"""Essai de Reattach.reset_node et de l'action reset de webui, avec un faux Matter Server."""
import os
import sys
import tempfile
import threading

sys.path.insert(0, sys.argv[1])
import pairing  # noqa: E402
import reattach  # noqa: E402
import webui  # noqa: E402

NID = "00000000000000AB"
reattach.RESETS_FILE = os.path.join(tempfile.mkdtemp(), "resets.json")
FABS = [{"1": "k", "2": 24582, "3": 1, "4": 5, "5": "", "254": 1}, {"2": 4939, "5": "HA", "254": 2},
        {"vendorID": 9999, "label": "Autre", "fabricIndex": 3}]


class Healer:
    def __init__(self, script):
        self.lock, self.calls, self.script = threading.Lock(), [], script
        self.nodes = {NID: {"name": "Prise test", "area": "Salon", "available": True}}

    def matter_command(self, command, args=None, timeout=60, timing=None):
        name = args.get("command_name", command)
        self.calls.append(f"{name}{args.get('payload', '')}" if name == "RemoveFabric" else name)
        if command == "read_attribute":
            out = self.script("read", args)
            return {"0/62/1": FABS, "0/62/5": 2} if out is None else out
        out = self.script(name, args)
        if isinstance(out, Exception):
            raise out
        return {"statusCode": 0} if out is None else out


class Watch:
    def __init__(self):
        self.stop, self.events = threading.Event(), []

    def emit(self, kind, text, **data):
        self.events.append((kind, text, data))


def essai(script):
    w, h = Watch(), Healer(script)
    r = reattach.Reattach(w, h)
    return r, h, w, r.reset_node(NID)


# cas normal : les autres fabrics d'abord, puis celle de Home Assistant (index 2) par RemoveFabric (verifie), puis remove_node
r, h, w, res = essai(lambda n, a: None)
assert res == {"result": "reset", "fabrics": ["Google Home", "Autre", "Home Assistant"], "listed": False}, res
assert h.calls == ["read_attribute", "RemoveFabric{'fabricIndex': 1}", "RemoveFabric{'fabricIndex': 3}",
                   "RemoveFabric{'fabricIndex': 2}", "remove_node"], h.calls
assert w.events[0][0] == "node_reset" and r.busy.acquire(blocking=False)
assert r.was_reset(0xAB) and not r.was_reset(0xAC) and not r.was_reset(None)
assert reattach.Reattach(w, h).was_reset(0xAB)          # retenu apres un redemarrage de l'add-on
# la node ne repond pas a la lecture : rien n'est envoye
r, h, w, res = essai(lambda n, a: TimeoutError("x") if n == "read" else None)
assert res == {"result": "noanswer", "fabrics": []} and h.calls == ["read_attribute"] and not w.events
# liste des fabrics sans celle de Home Assistant : rien n'est envoye
r, h, w, res = essai(lambda n, a: {"0/62/1": FABS[:1], "0/62/5": 2} if n == "read" else None)
assert res["result"] == "noanswer" and h.calls == ["read_attribute"]
# refus au 2e retrait : arret, la node reste dans Home Assistant
r, h, w, res = essai(lambda n, a: {"statusCode": 11} if n == "RemoveFabric" and a["payload"]["fabricIndex"] == 3 else None)
assert res == {"result": "partial", "fabrics": ["Google Home"]} and "remove_node" not in h.calls, (res, h.calls)
# le Matter Server echoue a retirer la node : l'appareil est pourtant reinitialise, signale « encore liste »
r, h, w, res = essai(lambda n, a: RuntimeError("x") if n == "remove_node" else None)
assert res["result"] == "reset" and res["listed"] is True and w.events

# cote page : pas de code conserve -> rien n'est envoye ; avec code -> les fabrics et le code sont annonces
pairing.FILE = os.path.join(tempfile.mkdtemp(), "codes.json")
webui.Pairing = lambda: pairing.Pairing(pairing.FILE)


class Table:
    cache_t = 1

    def _nodes(self):
        return [{"node_id": 0xAB, "attributes": {"0/40/2": 0xFFF1, "0/40/4": 0x8000}}]

    def get(self, force=False):
        return {"rows": [{"id": "0xAB", "name": "Prise test"}]}


w, h = Watch(), Healer(lambda n, a: None)
w.healer, w.reattach = h, reattach.Reattach(w, h)
ui = webui.WebUI(w, Table())
import io  # noqa: E402
import json  # noqa: E402


def action(act):
    H = ui._handler()
    body = json.dumps({"id": "0xAB", "action": act}).encode()
    req = H.__new__(H)
    req.headers, req.rfile, req.wfile = {"Content-Length": str(len(body))}, io.BytesIO(body), io.BytesIO()
    req.send_response = req.send_header = lambda *a: None
    req.end_headers = lambda: None
    req._action()
    return json.loads(req.wfile.getvalue())


assert action("reset") == {"ok": True, "result": "nocode"} and h.calls == [], h.calls
assert action("reset_info") == {"ok": True, "fabrics": ["Google Home", "Home Assistant", "Autre"], "manual": None}
ui.pairing_post({"id": "0xAB", "code": "MT:Y.K9042C00KA0648G00"})
assert action("reset_info")["manual"] == "34970112332"
assert action("reset")["result"] == "reset" and h.calls[-1] == "remove_node"


def table(ip="172.30.32.2"):   # GET /api/table, comme la page (par l'ingress de Home Assistant)
    H = ui._handler()
    req = H.__new__(H)
    req.path, req.client_address, req.wfile = "/api/table", (ip, 0), io.BytesIO()
    req.send_response = req.send_header = lambda *a: None
    req.end_headers = lambda: None
    req.do_GET()
    return json.loads(req.wfile.getvalue())


assert "error" in table("127.0.0.1") and "error" in table("172.30.33.5")   # hors ingress : refuse
d = table()
assert d["pair_free"] == 0 and d["pair_new"] == [] and "rows" in d, d      # la node est encore la : aucun code en attente
Table._nodes = lambda self: []                                             # elle sort du tableau : son code attend
assert table()["pair_free"] == 1
print("OK")

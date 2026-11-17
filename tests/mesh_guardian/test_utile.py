"""Essais du lot « utile » : cycle de recuperation borne, releve radio tolerant, tentative non lancee,
reglages MQTT relus, requetes de la page controlees, codes interdits refuses."""
import io
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

import base64  # noqa: E402

import healer  # noqa: E402
import pairing  # noqa: E402
import radio  # noqa: E402
import reattach  # noqa: E402
import webui  # noqa: E402

TMP = tempfile.mkdtemp()
radio.TOPOLOGY_FILE = os.path.join(TMP, "topo.json")


class W:
    def __init__(self):
        self.lock, self.stop, self.events = threading.Lock(), threading.Event(), []
        self.matter, self.br, self.dirty, self.live = {}, {}, False, None

    def emit(self, kind, text, **data):
        self.events.append(kind)

    def br_relevant(self, b):
        return True

    def br_label(self, b):
        return "BR"


# --- cycle de recuperation : les pings d'un cycle s'arretent apres le temps permis
h = healer.Healer(W(), {})
h.state_file, h.outages_file = os.path.join(TMP, "h.json"), os.path.join(TMP, "o.json")
h.enabled = True
old = time.time() - 3600
h.fetch_ha_nodes = lambda: [{"node": f"{i:016X}", "name": f"N{i}", "state": "unavailable", "since": old} for i in range(1, 6)]
pinged = []
h.ping = lambda node: (pinged.append(node), time.sleep(0.1))
healer.PING_BUDGET_S = 0.15   # marges larges : l'horloge de Windows avance par pas de 15 ms
h.cycle()
assert len(pinged) == 2, pinged   # 0 s, 0,1 s ; le troisieme commencerait apres 0,15 s
healer.PING_BUDGET_S = 100
pinged.clear()
h.cycle()
assert len(pinged) == 5, "les nodes pas pinguees restent dues"

# --- tentative de recuperation : un fil qui ne peut pas demarrer ne laisse rien de bloque
NID = "00000000000000AB"


class H2:
    lock = threading.Lock()
    nodes = {NID: {"name": "Prise", "area": "Salon", "available": False}}


class Live:
    connected = True
    lock = threading.Lock()
    nodes = {NID: {"available": False, "attributes": {"0/49/1": [{"0": "bmV0", "1": True}], "0/49/65529": [0, 2, 3, 4, 6, 8]}}}


r = reattach.Reattach(W(), H2())
r.live = Live()


class NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        raise RuntimeError("can't start new thread")


real = reattach.threading.Thread
reattach.threading.Thread = NoThread
try:
    out = r.recover_node(NID)
finally:
    reattach.threading.Thread = real
assert out == {"result": "failed"}, out
assert NID not in r.recovering and NID not in r.results and r.busy.acquire(blocking=False), "rien ne reste bloque"
r.busy.release()

# --- codes d'appairage interdits par la norme : refuses
for bad in (11111111, 12345678, 87654321):
    for code in (pairing.manual_code(3840, bad),):
        try:
            pairing.parse(code)
            raise AssertionError(f"accepte : {bad}")
        except ValueError as err:
            assert str(err) == "passcode", err
assert pairing.parse(pairing.manual_code(3840, 20202021))["manual"]
try:
    b8 = "8" + pairing.manual_code(3840, 20202021)[1:10]   # premier chiffre > 7
    pairing.parse(b8 + pairing.verhoeff(b8))
except ValueError:
    pass
else:
    raise AssertionError("premier chiffre 8 accepte")

# --- requetes de la page : JSON seulement, meme site, taille et champs controles
assert webui.node_hex("0xab") == NID and webui.node_hex("AB") == NID
for bad in ("", "zz", "1" * 17, None, "1 OR 1"):
    try:
        webui.node_hex(bad)
        raise AssertionError(f"id accepte : {bad!r}")
    except ValueError:
        pass
try:
    webui.text_of({"code": "x" * 600}, "code")
    raise AssertionError("texte trop long accepte")
except ValueError:
    pass
try:
    webui.text_of({"code": {"a": 1}}, "code")
    raise AssertionError("objet accepte")
except ValueError:
    pass


class UI:
    pass


Handler = webui.WebUI._handler(UI())


def requete(headers, body=b"{}"):
    q = Handler.__new__(Handler)
    q.headers, q.rfile, q.sent = headers, io.BytesIO(body), []
    q._send = lambda code, b, *a: q.sent.append(code)
    return q


q = requete({"Content-Type": "application/json", "Origin": "https://maison.example:8123", "X-Forwarded-Host": "maison.example:8123"})
assert q._same_site() and q.sent == []
q = requete({"Content-Type": "text/plain"})
assert not q._same_site() and q.sent == [415], "formulaire d'un autre site"
q = requete({"Content-Type": "application/json", "Origin": "https://pirate.example", "X-Forwarded-Host": "maison.example:8123"})
assert not q._same_site() and q.sent == [403], "autre origine"
q = requete({"Content-Type": "application/json"})   # sans Origin (application) : accepte
assert q._same_site()
q = requete({"Content-Length": "2"}, b"[]")
try:
    q._body()
    raise AssertionError("liste acceptee")
except ValueError:
    pass
q = requete({"Content-Length": str(webui.MAX_BODY + 1)}, b"{}")
try:
    q._body()
    raise AssertionError("trop grand accepte")
except ValueError:
    pass
assert requete({"Content-Length": "9"}, b'{"a": 1}')._body() == {"a": 1}

# --- MQTT : reglages relus a la reconnexion (une fois par minute), le mot de passe change pris
sys.modules.setdefault("paho", types.ModuleType("paho"))
calls = []


class Client:
    def username_pw_set(self, u, p):
        calls.append(("pw", u, p))

    def connect_async(self, host, port, keepalive=60):
        calls.append(("connect", host, port))


src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
i = src.index("    def _mqtt_refresh(self, client):")
j = src.index("\n    def ", i + 10)
ns = {"time": time, "LOG": types.SimpleNamespace(info=lambda *a: None), "t": lambda s, **k: s,
      "MQTT_HOST": "core-mosquitto", "MQTT_PORT": 1883}
answer = {"host": "core-mosquitto", "port": 1883, "username": "addons", "password": "nouveau"}
ns["_load_mqtt"] = lambda: dict(answer)
exec("class G:\n" + src[i:j], ns)   # noqa: S102 - la methode telle qu'elle est dans watcher.py
g = ns["G"]()
g._mq_now, g._mq_t = ("core-mosquitto", 1883, "addons", "ancien"), 0
g._mqtt_refresh(Client())
assert calls == [("pw", "addons", "nouveau")], calls
g._mqtt_refresh(Client())
assert len(calls) == 1, "pas plus d'une fois par minute"
g._mq_t = 0
answer["host"] = "autre-broker"
g._mqtt_refresh(Client())
assert calls[-1] == ("connect", "autre-broker", 1883), calls

# --- releve radio : une node ou une entree de table bizarre est laissee de cote, pas tout le releve
class HR:
    lock = threading.Lock()
    nodes = {}


rd = radio.Radio(W(), HR(), {})
rd._save = lambda: None
ext = lambda b: base64.b64encode(bytes([b]) * 8).decode()   # noqa: E731
X1, X2 = int.from_bytes(b"\x11" * 8, "big"), int.from_bytes(b"\x22" * 8, "big")
routeur = {"node_id": 1, "available": True, "attributes": {"0/53/1": 5, "0/51/0": [{"4": ext(0x11), "7": 4}],
           "0/53/7": [{"0": X2, "1": 0, "2": 0x0401, "4": 0, "5": 3, "6": -60, "13": False}, "abc",
                      {"0": X2, "5": "x", "6": "y"}]}}
enfant = {"node_id": 2, "available": True, "attributes": {"0/53/1": 2, "0/51/0": [{"4": ext(0x22), "7": 4}],
          "0/53/7": [{"0": X1, "1": 0, "2": 0x0400, "4": 0, "5": 3, "6": -55, "13": True}]}}
odd = [{"node_id": 3, "attributes": {"0/53/1": 2, "0/53/7": "pas une liste"}},
       {"node_id": "zz", "attributes": {"0/53/1": 2}}, "pas un objet"]
rd.live = types.SimpleNamespace(connected=True, snapshot=lambda: [routeur, enfant, *odd], leaders=lambda: [])
rd._survey()
assert rd.last and rd.last["roles"] == {"router": 1, "sleepy_end_device": 1}, "releve fait sur les deux nodes correctes"
assert radio.clean_table([{"0": 1, "5": 3}, {"5": "x"}, "abc", {"13": True, "6": None}]) == [{"0": 1, "5": 3}, {"13": True, "6": None}]

print("OK")

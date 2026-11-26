"""Essais de USB/IP Link sans materiel : sorties de l'outil usbip simulees, serveur qui redemarre.
Lancer : python tests/usbip_link/test_link.py usbip_link"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "usbip_link"))
import usbip_link as ul  # noqa: E402

PORT = """Imported USB devices
====================
Port 00: <Port in Use> at Full Speed(12Mbps)
       Espressif : unknown product (303a:831a)
       1-1 -> usbip://192.168.1.10:3240/2-3
           -> remote bus/dev 002/003
Port 01: <Port Available> at High Speed(480Mbps)
"""
LIST = """Exportable USB devices
======================
 - 192.168.1.10
        2-3: Espressif : unknown product (303a:831a)
           : USB\\VID_303A&PID_831A\\10:20:BA:05:B6:F4
           : Miscellaneous Device / ? / Interface Association (ef/02/01)
        1-4: Logitech, Inc. : Unifying Receiver (046d:c52b)
"""
assert ul.parse_port(PORT) == [{"port": "00", "in_use": True, "hwid": "303a:831a", "server": "192.168.1.10", "busid": "2-3"}]
assert ul.parse_port("") == [] and ul.parse_port("Imported USB devices\n====\n") == []
assert ul.parse_list(LIST) == [{"busid": "2-3", "desc": "Espressif : unknown product", "hwid": "303a:831a"},
                               {"busid": "1-4", "desc": "Logitech, Inc. : Unifying Receiver", "hwid": "046d:c52b"}]


class Fake:
    """usbip simule : un serveur qui partage le ZBT-2 et peut s'arreter."""
    def __init__(self):
        self.up, self.attached, self.calls, self.now = True, False, [], 1000.0

    def run(self, args, timeout=20):
        self.calls.append(" ".join(args[1:]))
        if args[1] == "port":
            return PORT if self.attached else "Imported USB devices\n====================\n"
        if args[1] == "list":
            if not self.up:
                raise RuntimeError("usbip: error: could not connect to 192.168.1.10:3240")
            return LIST
        if args[1] == "attach":
            if not self.up:
                raise RuntimeError("could not connect")
            self.attached = True
            return ""
        if args[1] == "detach":
            self.attached = False
            return ""
        raise AssertionError(args)

    def probe(self, host, port):
        return self.up

    def clock(self):
        return self.now


f = Fake()
link = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303A:831A"}],
                "restart_addons": ["core_openthread_border_router"]}, runner=f.run, probe=f.probe, clock=f.clock)
# premier passage : trouve par VID:PID, attache ; OpenThread redemarre seulement s'il tourne deja (course au boot)
assert link.check() and f.attached and "attach -r 192.168.1.10 -b 2-3" in f.calls
st = link.public()["devices"][0]
assert st["attached"] and st["busid"] == "2-3" and st["attaches"] == 1
assert link.restart == ["core_openthread_border_router"] and link.restart_if_running is True
link.restart = []
# rien ne change : rien a faire
f.calls.clear()
assert not link.check() and f.calls == ["port"]
# Windows redemarre : deux verifications sans serveur, le lien reste ; a la troisieme il est libere
f.up = False
link.check()
link.check()
assert f.attached and link.public()["devices"][0]["attached"]
link.check()
assert not f.attached and not link.public()["devices"][0]["attached"] and "detach -p 0" in f.calls
# serveur toujours absent : on attend sans erreur
f.calls.clear()
link.check()
assert "attach -r 192.168.1.10 -b 2-3" not in f.calls
# retour du serveur : rattache, et l'add-on OpenThread est a redemarrer
f.now += 240
f.up = True
assert link.check() and f.attached
kinds = [k for k, _ in link.events]
assert "attached" in kinds and any("4 min" in txt for _, txt in link.events), link.events
assert link.restart == ["core_openthread_border_router"] and link.public()["devices"][0]["attaches"] == 2
assert link.restart_if_running is False   # apres une perte : redemarre dans tous les cas
# lien coupe sans que le serveur se taise (cable USB debranche cote Windows)
link.restart, link.events = [], []
f.attached = False
LIST_EMPTY = "Exportable USB devices\n======================\n - 192.168.1.10\n"
f.run, orig = (lambda args, timeout=20: LIST_EMPTY if args[1] == "list" else Fake.run(f, args, timeout)), f.run
link.run = f.run
link.check()
st = link.public()["devices"][0]
assert not st["attached"] and "introuvable" not in (st["error"] or "") and "303a:831a" in st["error"]
assert [k for k, _ in link.events] == ["lost", "not_found"], link.events
# deja attache au demarrage de l'add-on (redemarrage de l'add-on) : repris tel quel, sans rattacher
f2 = Fake()
f2.attached = True
link2 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "bus_id": "2-3"}],
                 "restart_addons": ["core_openthread_border_router"]}, runner=f2.run, probe=f2.probe, clock=f2.clock)
link2.check()
assert link2.public()["devices"][0]["attached"] and not any(c.startswith("attach") for c in f2.calls)
assert link2.restart == []   # repris tel quel : aucun redemarrage
link2.check()
assert link2.restart == []
assert ul.fmt_duration(42) == "42 s" and ul.fmt_duration(240) == "4 min" and ul.fmt_duration(7300) == "2 h 01"
assert ul.slug_of("ZBT-2 (Thread)") == "zbt_2_thread"

# latence : temps de reponse du serveur en ms ; moyenne et pire valeur sur les derniers passages
f3 = Fake()
f3.attached = True
answers = [2.0, 4.0, 30.0, None, 3.0]
link3 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]}, runner=f3.run,
                probe=lambda host, port: answers.pop(0), clock=f3.clock)
assert link3.check()                  # premier passage : appareil repris, change
st = link3.public()
assert st["latency_ms"] == 2.0 and st["latency_avg_ms"] == 2.0 and st["devices"][0]["latency_ms"] == 2.0
assert not link3.check()              # seule la latence change : pas une raison de publier
assert link3.public()["latency_avg_ms"] == 3.0
link3.check()
assert link3.public()["latency_max_ms"] == 30.0 and link3.public()["latency_avg_ms"] == 12.0
assert link3.public()["latency_p95_ms"] == 30.0   # 3 valeurs : le rang 3 (plus petite valeur couvrant 95 %)
assert link3.check()                  # serveur muet : changement, latence inconnue et fenetre videe
st = link3.public()
assert st["latency_ms"] is None and st["server_ok"] is False
assert st["latency_avg_ms"] is None and st["latency_max_ms"] is None and st["devices"][0]["latency_ms"] is None
assert st["latency_p95_ms"] is None
# percentile au plus proche rang : sur 30 mesures le p95 est la 29e, sur 20 la 19e, sur 1 la seule
assert ul.percentile([], 95) is None and ul.percentile([7.0], 95) == 7.0
assert ul.percentile([float(i) for i in range(30, 0, -1)], 95) == 29.0 and ul.percentile([float(i) for i in range(1, 21)], 95) == 19.0
assert ul.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0 and ul.percentile([1.0, 2.0, 3.0, 4.0], 100) == 4.0
assert link3.latencies == []
link3.check()
st = link3.public()
assert st["latency_ms"] == 3.0 and st["server_ok"] is True and st["latency_avg_ms"] == 3.0 and st["latency_max_ms"] == 3.0
assert len(link3.latencies) == 1
# l'etat sans latence ne bouge pas avec elle (pour decider de publier)
assert "latency_ms" not in link3.public(latency=False) and "latency_ms" not in link3.public(latency=False)["devices"][0]
# vraie sonde : un port ferme ne repond pas
assert ul.server_up("127.0.0.1", 9, timeout=0.5) is None

# serveur donne par son nom : `usbip port` affiche l'adresse ; reconnu une fois le nom resolu
f4 = Fake()
f4.attached = True                     # PORT montre usbip://192.168.1.10


def run4(args, timeout=20):
    if args[1] == "attach":            # deja attache : usbipd refuse un second attachement
        f4.calls.append(" ".join(args[1:]))
        raise RuntimeError("usbip: error: Attach Request for 2-3 failed - Device busy (exported)")
    return Fake.run(f4, args, timeout)


resolves = [set(), {"192.168.1.10"}]   # DNS pas pret au premier passage
link4 = ul.Link({"server": "usbip-host.local", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
                runner=run4, probe=f4.probe, clock=f4.clock, resolver=lambda host: resolves.pop(0))
link4.check()                          # nom pas encore resolu : le port n'est pas reconnu, l'attachement est refuse
st = link4.public()["devices"][0]
assert not st["attached"] and "Device busy" in st["error"] and not link4.resolved
f4.calls.clear()
link4.check()                          # resolu : le port est reconnu, aucune tentative d'attachement en boucle
st = link4.public()["devices"][0]
assert st["attached"] and st["error"] is None and link4.resolved and resolves == []
assert not any(c.startswith("attach") for c in f4.calls)
link4.check()                          # plus de resolution une fois faite (resolves vide : pop leverait)
assert ul.find_port(ul.parse_port(PORT), {"hardware_id": "303a:831a"}, "192.168.1.99") is None
assert ul.find_port(ul.parse_port(PORT), {"hardware_id": "303a:831a"}, {"x.lan", "192.168.1.10"})["port"] == "00"
assert ul.resolve("127.0.0.1") == {"127.0.0.1"}

# publication : changement, evenement, battement ; la latence seule au plus toutes les 60 s
lat_a, lat_b = {"latency_ms": 1.0}, {"latency_ms": 2.0}
assert ul.publish_due(True, [], 1000, 990, lat_a, lat_a)
assert ul.publish_due(False, [("x", "y")], 1000, 990, lat_a, lat_a)
assert ul.publish_due(False, [], 1000, 1000 - ul.HEARTBEAT_S - 1, lat_a, lat_a)
assert not ul.publish_due(False, [], 1000, 970, lat_b, lat_a)      # latence bougee il y a 30 s : attendre
assert ul.publish_due(False, [], 1000, 940, lat_b, lat_a)          # 60 s : publier
assert not ul.publish_due(False, [], 1000, 900, lat_a, lat_a)      # rien n'a bouge

# redemarrages : apres une perte, toujours ; au premier attachement, seulement les add-ons en marche ou en erreur
calls = []
states = {"otbr": "started", "zha": "stopped", "matter": "error", "bad": "boom"}


def sup(path, method="GET", timeout=30):
    calls.append((method, path))
    slug = path.split("/")[2]
    if slug == "bad":
        raise RuntimeError("404")
    return {"state": states[slug]} if path.endswith("/info") else {}


assert ul.do_restarts(["otbr", "zha", "matter", "bad"], True, sup=sup) == ["otbr", "matter"]
assert ("POST", "/addons/zha/restart") not in calls and ("POST", "/addons/otbr/restart") in calls
calls.clear()
assert ul.do_restarts(["otbr", "zha"], False, sup=sup) == ["otbr", "zha"]
assert all(m == "POST" for m, _ in calls)

# discovery : une entite par appareil, la latence (None = inconnu pour HA, pas une chaine), l'ancienne entite OMR retiree
disc = ul.discovery([{"name": "ZBT-2"}, {"name": "Dongle d'Ana"}])
topics = [tp for tp, _ in disc]
assert topics == ["homeassistant/binary_sensor/usbip_link/zbt_2/config",
                  "homeassistant/binary_sensor/usbip_link/dongle_d_ana/config",
                  "homeassistant/sensor/usbip_link/latency/config",
                  "homeassistant/sensor/usbip_link/latency_max/config",
                  "homeassistant/sensor/usbip_link/latency_p95/config",
                  "homeassistant/binary_sensor/usbip_link/omr_prefix/config"]
zbt = ul.json.loads(disc[0][1])
assert zbt["unique_id"] == "usbip_link_zbt_2" and zbt["device_class"] == "connectivity"
assert zbt["state_topic"] == "usbip_link/state" and zbt["availability_topic"] == "usbip_link/state/available"
assert "selectattr('name', 'eq', 'ZBT-2')" in zbt["value_template"] and zbt["device"]["sw_version"] == ul.VERSION
assert "'Dongle dAna'" in ul.json.loads(disc[1][1])["value_template"]
lat = ul.json.loads(disc[2][1])
assert lat["unique_id"] == "usbip_link_latency" and lat["unit_of_measurement"] == "ms" and lat["state_class"] == "measurement"
assert "'unknown'" not in lat["value_template"] and "else 'None'" in lat["value_template"]
for entry, key in ((disc[3], "max"), (disc[4], "p95")):   # pic et percentile 95 : capteurs a historique long
    sens = ul.json.loads(entry[1])
    assert sens["unique_id"] == f"usbip_link_latency_{key}" and sens["state_class"] == "measurement"
    assert sens["unit_of_measurement"] == "ms" and sens["device_class"] == "duration" and sens["entity_category"] == "diagnostic"
    assert f"value_json.latency_{key}_ms" in sens["value_template"] and "else 'None'" in sens["value_template"]
assert disc[5][1] == ""
try:   # le rendu des templates comme HA (Jinja), si jinja2 est la
    import jinja2
except ImportError:
    jinja2 = None
if jinja2:
    env = jinja2.Environment()
    env.filters["tojson"] = ul.json.dumps

    def render(tpl, state):
        return env.from_string(tpl).render(value_json=state)

    assert render(lat["value_template"], {"latency_avg_ms": None}) == "None"
    assert render(lat["value_template"], {"latency_avg_ms": 0.9}) == "0.9"
    assert render(ul.json.loads(disc[4][1])["value_template"], {"latency_p95_ms": None}) == "None"
    assert render(ul.json.loads(disc[3][1])["value_template"], {"latency_max_ms": 2.4}) == "2.4"
    devs = {"devices": [{"name": "ZBT-2", "attached": True}]}
    assert render(zbt["value_template"], devs) == "ON"
    assert render(zbt["value_template"], {"devices": [{"name": "ZBT-2", "attached": False}]}) == "OFF"

# demarrage de l'add-on, device deja attache : aucun etat "non attache" publie avant le premier passage
# (sinon Mesh Guardian ecrit « lien coupe » puis « retabli » a chaque redemarrage de USB/IP Link)
class Client:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))


f5 = Fake()
f5.attached = True
link5 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
                runner=f5.run, probe=f5.probe, clock=f5.clock)
mq = ul.Mqtt.__new__(ul.Mqtt)          # sans broker : le client est simule
mq.link, mq.client = link5, Client()
mq.on_connect(mq.client, None, None, 0)   # connexion MQTT avant le premier passage
assert [tp for tp, _ in mq.client.sent if tp == "usbip_link/state"] == []
assert ("usbip_link/state/available", "online") in mq.client.sent and len(mq.client.sent) == 6   # online + 5 discovery (appareil, latence, max, p95, ancienne entite OMR)
mq.publish()
assert [tp for tp, _ in mq.client.sent if tp == "usbip_link/state"] == []
link5.check()
mq.publish()
states = [ul.json.loads(p) for tp, p in mq.client.sent if tp == "usbip_link/state"]
assert len(states) == 1 and states[0]["devices"][0]["attached"] is True and states[0]["version"] == ul.VERSION
mq.client.sent.clear()
mq.on_connect(mq.client, None, None, 0)   # reconnexion apres le premier passage : etat publie, attache
states = [ul.json.loads(p) for tp, p in mq.client.sent if tp == "usbip_link/state"]
assert len(states) == 1 and states[0]["devices"][0]["attached"] is True

import logging  # noqa: E402


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


# 0.4.2 : retour du serveur apres un silence, meme d'un seul passage (VM reprise, usbipd relance : le noyau ne voit pas la
# liaison mourir) : detache puis rattache, puis redemarre les add-ons
f6 = Fake()
f6.attached = True
link6 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}],
                 "restart_addons": ["core_openthread_border_router"]}, runner=f6.run, probe=f6.probe, clock=f6.clock)
link6.check()                                        # port deja tenu au demarrage : repris tel quel, et dit
assert [k for k, _ in link6.events] == ["adopted"] and "repris tel quel" not in link6.events[0][1]
assert "already attached (port 00, 192.168.1.10 2-3)" in link6.events[0][1] and link6.restart == []
link6.events = []
f6.calls.clear()
link6.check()
assert f6.calls == ["port"] and link6.events == []   # serveur present : rien n'est touche
f6.up = False
link6.check()                                        # un seul passage muet : pas de detachement (DEAD_CHECKS = 3)
assert f6.attached and link6.silent and link6.public()["devices"][0]["attached"]
f6.up = True
f6.calls.clear()
link6.events = []
f6.now += 10
link6.check()
assert f6.calls[:3] == ["port", "detach -p 0", "list -r 192.168.1.10"] and "attach -r 192.168.1.10 -b 2-3" in f6.calls
assert [k for k, _ in link6.events] == ["server_up", "resumed", "attached"], link6.events
assert "again after 10 s" in link6.events[2][1] and link6.public()["devices"][0]["attaches"] == 1
assert link6.restart == ["core_openthread_border_router"] and link6.restart_if_running is False and not link6.silent
f6.calls.clear()
link6.check()
assert f6.calls == ["port"]                          # le drapeau est retombe : pas de rattachement en boucle
# detachement refuse : dit une fois, retente au passage suivant, drapeau garde
f7 = Fake()
f7.attached = True
link7 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
                runner=lambda a, timeout=20: (_ for _ in ()).throw(RuntimeError("busy")) if a[1] == "detach" else f7.run(a, timeout),
                probe=f7.probe, clock=f7.clock)
link7.check()
f7.up = False
link7.check()
f7.up = True
link7.events = []
link7.check()
assert [k for k, _ in link7.events] == ["server_up", "detach_failed"] and "port 00: busy" in link7.events[1][1] and link7.silent
assert link7.public()["devices"][0]["attached"]
link7.events = []
link7.check()
assert link7.events == [] and link7.silent           # meme refus : pas de repetition dans le journal
# BUSID qui change sur le serveur (autre port USB) : dit, retrouve par VID:PID
f8 = Fake()
link8 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
                runner=f8.run, probe=f8.probe, clock=f8.clock)
link8.check()
f8.attached = False
LIST_MOVED = LIST.replace("2-3: Espressif", "1-1: Espressif")
f8.run, orig8 = (lambda a, timeout=20: LIST_MOVED if a[1] == "list" else Fake.run(f8, a, timeout)), f8.run
link8.run = f8.run
link8.events = []
link8.check()
assert [k for k, _ in link8.events] == ["lost", "busid_changed", "attached"], link8.events
assert "2-3 -> 1-1" in link8.events[1][1] and link8.public()["devices"][0]["busid"] == "1-1"

# redemarrages avec nouveaux essais : un 503 du Supervisor (boot) est retente, dit dans le journal, puis abandonne
class Http(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP Error {code}")
        self.code = code


logs = []
cap2 = _Cap()
ul.LOG.addHandler(cap2)
ul.LOG.setLevel(logging.INFO)
try:
    refuse = {"otbr": 3, "zha": 99, "gone": 1}
    posts = []

    def sup2(path, method="GET", timeout=30):
        slug = path.split("/")[2]
        if path.endswith("/info"):
            return {"state": "started"}
        posts.append(slug)
        if slug == "gone":
            raise Http(404)
        if refuse.get(slug, 0) > 0:
            refuse[slug] -= 1
            raise Http(503)
        return {}

    q = ul.RestartQueue(sup=sup2)
    assert not q.due(0)
    q.add(["otbr", "zha", "gone"], False, 1000.0)
    assert q.due(1000.0) and q.run(1000.0) == [] and set(q.items) == {"otbr", "zha"}   # 404 : abandonne tout de suite
    assert not q.due(1000.0 + ul.RETRY_S - 1) and q.due(1000.0 + ul.RETRY_S)
    assert q.run(1015.0) == [] and q.run(1030.0) == []
    assert q.run(1045.0) == ["otbr"] and set(q.items) == {"zha"}                       # 4e essai : repart
    assert q.run(1060.0) == [] and "zha" in q.items
    assert q.run(1000.0 + ul.RETRY_MAX_S) == [] and q.items == {} and not q.due(2000.0)   # delai ecoule : abandon dit
finally:
    ul.LOG.removeHandler(cap2)
msgs = cap2.messages
assert sum("Cannot restart the add-on otbr: HTTP Error 503 (trying again for up to 5 min)" in m for m in msgs) == 1, msgs
assert any("Cannot restart the add-on gone: HTTP Error 404" in m and "trying again" not in m for m in msgs)
assert any("Add-on otbr restarted after 4 tries" in m for m in msgs) and any("Add-on zha not restarted after 5 min" in m for m in msgs)
# un nouvel ordre pendant l'attente : fusionne ; « seulement ceux qui tournent » ne l'emporte pas sur « toujours »
q2 = ul.RestartQueue(sup=lambda p, method="GET", timeout=30: {"state": "started"})
q2.add(["a"], True, 0.0)
q2.add(["a", "b"], False, 5.0)
assert q2.items["a"]["if_running"] is False and q2.items["b"]["if_running"] is False

# liaison MQTT reprise en tache de fond : le courtier introuvable au boot est cherche a nouveau, sans bruit
tries = []
mq3 = ul.Mqtt.__new__(ul.Mqtt)
mq3.link, mq3.client, mq3.last_try, mq3.warned = link5, None, 100.0, True
mq3.connect = lambda: (tries.append(1), setattr(mq3, "client", object() if len(tries) == 2 else None))
mq3.retry(100.0 + ul.MQTT_RETRY_S - 1)
assert tries == []
mq3.retry(100.0 + ul.MQTT_RETRY_S)
mq3.retry(100.0 + ul.MQTT_RETRY_S + 1)               # trop tot depuis l'essai
mq3.retry(100.0 + 2 * ul.MQTT_RETRY_S + 1)
assert len(tries) == 2 and mq3.client is not None
mq3.retry(10000.0)                                   # connecte : plus d'essai
assert len(tries) == 2
cap3 = _Cap()
ul.LOG.addHandler(cap3)
try:
    mq4 = ul.Mqtt(link5)                             # sans Supervisor (pas de jeton) : un seul avertissement
    mq4.last_try = 0.0
    mq4.retry(1e9)
finally:
    ul.LOG.removeHandler(cap3)
assert mq4.client is None and sum("No MQTT broker yet" in m for m in cap3.messages) == 1, cap3.messages

# reprise d'une VM mise en pause (Hyper-V « enregistrer ») : l'horloge murale saute, la monotone non
class Clocks:
    def __init__(self):
        self.w, self.m = 1_000_000.0, 500.0

    def wall(self):
        return self.w

    def mono(self):
        return self.m

    def tick(self, s):               # temps qui passe normalement
        self.w += s
        self.m += s


ck = Clocks()
cw = ul.ClockWatch(wall=ck.wall, mono=ck.mono)
ck.tick(2)
assert cw.poll(2) == 0.0
ck.tick(2.5)                         # un peu de retard : pas une pause
assert cw.poll(2) == 0.0
ck.w += 52                           # pause de 52 s : monotone arretee, murale remise a l'heure (cas du 19/11)
assert cw.poll(2) == 52.0
ck.tick(2)
assert cw.poll(2) == 0.0             # une seule fois
ck.w += 19                           # sous le seuil (20 s) : ignore
assert cw.poll(2) == 0.0
ck.w -= 40                           # horloge remise en arriere
assert cw.poll() == -40.0
ck.tick(60)                          # monotone qui compte la pause : une attente de 2 s qui dure 60 s
assert cw.poll(2) == 58.0
ck.tick(60)                          # sans attente connue (travail de la passe) : rien, la derive est nulle
assert cw.poll() == 0.0

# reprise detectee, serveur deja la : detache tout de suite et rattache dans le meme passage, add-ons redemarres
f9 = Fake()
f9.attached = True
link9 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}],
                 "restart_addons": ["core_openthread_border_router"]}, runner=f9.run, probe=f9.probe, clock=f9.clock)
link9.check()
link9.events = []
f9.calls.clear()
f9.now += 52
link9.resumed(52.0)
assert [k for k, _ in link9.events] == ["clock_jump"] and "+52 s" in link9.events[0][1] and link9.resume_pending
assert f9.calls == []                # rien n'est fait avant le passage
link9.check()
assert f9.calls[:2] == ["port", "detach -p 0"] and "attach -r 192.168.1.10 -b 2-3" in f9.calls
assert [k for k, _ in link9.events] == ["clock_jump", "resumed", "attached"], link9.events
assert "the machine was paused" in link9.events[1][1] and "again after 52 s" in link9.events[2][1]
assert link9.restart == ["core_openthread_border_router"] and not link9.resume_pending and not link9.silent
# reprise, serveur pas encore la (reseau pas remonte) : detache quand meme, rattache des qu'il repond
f10 = Fake()
f10.attached = True
link10 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}],
                  "restart_addons": ["core_openthread_border_router"]}, runner=f10.run, probe=f10.probe, clock=f10.clock)
link10.check()
f10.up = False
link10.resumed(52.0)
link10.events = []
f10.calls.clear()
link10.check()
assert not f10.attached and "detach -p 0" in f10.calls and not any(c.startswith("attach") for c in f10.calls)
assert [k for k, _ in link10.events] == ["server_down", "resumed"] and not link10.public()["devices"][0]["attached"]
assert not link10.resume_pending                      # rien de plus a detacher
f10.up = True
f10.now += 8
link10.events = []
link10.check()
assert f10.attached and link10.restart == ["core_openthread_border_router"] and not link10.silent
assert [k for k, _ in link10.events] == ["server_up", "attached"] and "again after" in link10.events[1][1]
# reprise mais detachement refuse : retente au passage suivant
f11 = Fake()
f11.attached = True
fail = [True]


def run11(a, timeout=20):
    if a[1] == "detach" and fail[0]:
        raise RuntimeError("busy")
    return f11.run(a, timeout)


link11 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
                 runner=run11, probe=f11.probe, clock=f11.clock)
link11.check()
link11.resumed(30.0)
link11.check()
assert link11.resume_pending and f11.attached
fail[0] = False
link11.check()
assert not link11.resume_pending and f11.attached and link11.public()["devices"][0]["attaches"] == 1
assert any("attach -r" in c for c in f11.calls)

# 0.4.4 : attachement accepte mais enumeration bloquee (incident du 26/11) : port invisible pour `usbip port`
STATUS = ("hub port sta spd dev      sockfd local_busid\n"
          "hs  0000 006 002 00010001 000003 1-1\n"
          "hs  0001 005 000 00000000 000000 0-0\n"
          "ss  0008 004 000 00000000 000000 0-0\n")
assert ul.parse_vhci(STATUS) == [{"port": 0, "status": 6, "local_busid": "1-1"}, {"port": 1, "status": 5, "local_busid": "0-0"},
                                 {"port": 8, "status": 4, "local_busid": "0-0"}]
assert ul.parse_vhci("") == [] and ul.read_vhci(os.path.join("nulle", "part")) is None


class Kernel:
    """vhci simule : `outcomes` donne le sort de chaque attachement (ok, stuck : enumeration bloquee, notty)."""
    def __init__(self, outcomes=()):
        self.ports = {0: ul.VDEV_NULL, 1: ul.VDEV_NULL}
        self.kind, self.calls, self.outcomes, self.now, self.slept = {}, [], list(outcomes), 1000.0, 0

    def run(self, args, timeout=20):
        self.calls.append(" ".join(args[1:]))
        if args[1] == "port":      # comme le vrai outil : ni les ports libres ni les non enumeres
            if any(s == ul.VDEV_USED for s in self.ports.values()):
                return PORT
            return "Imported USB devices\n====================\n"
        if args[1] == "list":
            return LIST
        if args[1] == "attach":
            if ul.VDEV_NOTASSIGNED in self.ports.values():
                raise RuntimeError("usbip: error: Attach Request for 2-3 failed - Device busy (exported)")
            port = min(p for p, s in self.ports.items() if s == ul.VDEV_NULL)
            self.kind[port] = self.outcomes.pop(0) if self.outcomes else "ok"
            self.ports[port] = ul.VDEV_NOTASSIGNED if self.kind[port] == "stuck" else ul.VDEV_USED
            return ""
        if args[1] == "detach":
            self.ports[int(args[3])] = ul.VDEV_NULL
            return ""
        raise AssertionError(args)

    def vhci(self):
        return [{"port": p, "status": s, "local_busid": f"1-{p + 1}" if s == ul.VDEV_USED else "0-0"}
                for p, s in sorted(self.ports.items())]

    def ready(self, busid):
        return self.kind.get(int(busid.split("-")[1]) - 1) == "ok"

    def sleep(self, s):
        self.slept += s
        self.now += s

    def link(self, **kw):
        return ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}],
                        "restart_addons": ["core_openthread_border_router"]}, runner=kw.get("runner", self.run),
                       probe=lambda h, p: True, clock=lambda: self.now, vhci=self.vhci, ready=self.ready, sleep=self.sleep)


# enumeration bloquee : pas « attache », seul ce port est detache, aucun redemarrage ; nouvel essai au passage suivant
k = Kernel(["stuck", "ok"])
lk = k.link()
lk.check()
assert not lk.public()["devices"][0]["attached"] and lk.public()["devices"][0]["attaches"] == 0 and lk.restart == []
assert [e for e, _ in lk.events] == ["enum_failed"] and "did not appear within 15 s" in lk.events[0][1], lk.events
assert "detach -p 0" in k.calls and "detach -p 1" not in k.calls and k.ports == {0: 4, 1: 4} and k.slept == ul.ENUM_TIMEOUT_S
lk.events = []
lk.check()
assert lk.public()["devices"][0]["attached"] and [e for e, _ in lk.events] == ["attached"]
assert lk.restart == ["core_openthread_border_router"] and lk.public()["devices"][0]["error"] is None
# enumere mais sans tty : meme traitement, dit une seule fois s'il se repete
k = Kernel(["notty", "notty"])
lk = k.link()
lk.check()
lk.check()
assert [e for e, _ in lk.events] == ["enum_failed"] and lk.restart == [] and k.ports == {0: 4, 1: 4}
# port bloque deja la au demarrage de l'add-on : libere avant tout attachement (sinon « busy (exported) »)
k = Kernel()
k.ports[0] = ul.VDEV_NOTASSIGNED
lk = k.link()
lk.check()
assert k.calls[:2] == ["detach -p 0", "port"] and [e for e, _ in lk.events] == ["stuck_freed", "attached"], (k.calls, lk.events)
assert lk.public()["devices"][0]["attached"]
# port en cours d'enumeration (devient pret pendant la confirmation) : pas touche
k = Kernel()
k.ports[1], k.kind[1] = ul.VDEV_NOTASSIGNED, "ok"
k.sleep = lambda s: k.ports.__setitem__(1, ul.VDEV_USED)
lk = k.link()
lk.free_stuck()
assert k.calls == [] and lk.events == []
# detachement du port bloque refuse : dit une fois, retente a chaque passage
k = Kernel()
k.ports[0] = ul.VDEV_ERROR


def run_refuse(a, timeout=20):
    if a[1] == "detach":
        k.calls.append("refus")
        raise RuntimeError("refused")
    return k.run(a, timeout)


lk = k.link(runner=run_refuse)
lk.free_stuck()
lk.free_stuck()
assert [e for e, _ in lk.events] == ["stuck_failed"] and k.calls == ["refus", "refus"]


# presence du peripherique dans sysfs : identifie, interfaces, et tty pour un CDC ACM
def put(root, rel, text=""):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as fh:
        fh.write(text)


with tempfile.TemporaryDirectory() as root:
    # Windows refuse « : » dans un nom de dossier : l'interface « 1-1:1.0 » est simulee par listdir/chemins
    assert not ul.usb_ready("1-1", root)
    put(root, "1-1/idVendor", "303a\n")
    assert not ul.usb_ready("1-1", root)          # pas encore d'interface

real = (ul.os.listdir, ul.os.path.isfile, ul._read)
tree = {"/u": ["1-1", "1-1:1.0", "1-1:1.1"], "/u/1-1:1.0": ["bInterfaceClass"], "/u/1-1:1.1": ["bInterfaceClass"]}
files = {"/u/1-1:1.0/bInterfaceClass": "02", "/u/1-1:1.0/bInterfaceSubClass": "02", "/u/1-1:1.1/bInterfaceClass": "0a"}
ul.os.listdir = lambda p: tree[p.replace("\\", "/")]
ul.os.path.isfile = lambda p: p.replace("\\", "/") == "/u/1-1/idVendor"
ul._read = lambda p: files.get(p.replace("\\", "/"), "")
try:
    assert not ul.usb_ready("1-1", "/u")          # CDC ACM sans tty : pas pret
    tree["/u/1-1:1.0"] = ["bInterfaceClass", "tty"]
    tree["/u/1-1:1.0/tty"] = []
    assert not ul.usb_ready("1-1", "/u")
    tree["/u/1-1:1.0/tty"] = ["ttyACM0"]
    assert ul.usb_ready("1-1", "/u")
    files.clear()                                 # pas un port serie CDC : l'enumeration suffit
    tree["/u/1-1:1.0"] = ["bInterfaceClass"]
    assert ul.usb_ready("1-1", "/u")
finally:
    ul.os.listdir, ul.os.path.isfile, ul._read = real

# redemarrage refuse avec 400 (le Supervisor ne voit pas encore le port serie) : retente
q3 = ul.RestartQueue(sup=lambda p, method="GET", timeout=30: (_ for _ in ()).throw(Http(400)))
q3.add(["otbr"], False, 0.0)
assert q3.run(0.0) == [] and "otbr" in q3.items
assert ul.retryable(Http(400)) and ul.retryable(Http(503)) and not ul.retryable(Http(404)) and not ul.retryable(Http(403))

# remontage de /sys : un refus (profil AppArmor, droit manquant) est dit dans le journal, sans arreter l'add-on
calls = []
assert ul.remount_sys(lambda args, timeout=20: calls.append((args, timeout))) is True
assert calls == [(["mount", "-o", "remount,rw", "/sys"], 10)]
def refused(args, timeout=20):
    raise RuntimeError("mount: /sys: permission denied")
import logging  # noqa: E402
class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []
    def emit(self, record):
        self.messages.append(record.getMessage())
cap = _Cap()
ul.LOG.addHandler(cap)
try:
    assert ul.remount_sys(refused) is False
finally:
    ul.LOG.removeHandler(cap)
assert any("Cannot remount /sys" in m and "permission denied" in m for m in cap.messages), cap.messages

# configuration de l'add-on : plus de full_access (la note de securite forcee a 1), profil AppArmor dedie
import re  # noqa: E402
ADDON = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "usbip_link")
conf = open(os.path.join(ADDON, "config.yaml"), encoding="utf-8").read()
assert not re.search(r"^\s*full_access\s*:\s*true", conf, re.M) and not re.search(r"^\s*docker_api\s*:\s*true", conf, re.M)
assert re.search(r"^apparmor:\s*true\s*$", conf, re.M) and re.search(r'^version:\s*"%s"' % re.escape(ul.VERSION), conf, re.M)
assert re.search(r"^\s*-\s*SYS_ADMIN\s*$", conf, re.M) and re.search(r"^kernel_modules:\s*true\s*$", conf, re.M)
profile = open(os.path.join(ADDON, "apparmor.txt"), encoding="utf-8").read()
names = re.findall(r"^profile ([^ ]+)", profile, re.M)   # le Supervisor exige exactement un profil
assert len(names) == 1, names
assert re.search(r"capability sys_admin,", profile) and re.search(r"capability sys_module,", profile)
assert "remount, rw" in profile and "vhci_hcd.0" in profile
changelog = open(os.path.join(ADDON, "CHANGELOG.md"), encoding="utf-8").read()
assert changelog.startswith("# Changelog\n\n## [%s]" % ul.VERSION)
print("OK")

"""Essais de USB/IP Link sans materiel : sorties de l'outil usbip simulees, serveur qui redemarre.
Lancer : python tests/usbip_link/test_link.py usbip_link"""
import os
import sys

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
assert link3.check()                  # serveur muet : changement, latence inconnue et fenetre videe
st = link3.public()
assert st["latency_ms"] is None and st["server_ok"] is False
assert st["latency_avg_ms"] is None and st["latency_max_ms"] is None and st["devices"][0]["latency_ms"] is None
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
link4 = ul.Link({"server": "desktop-serveur.local", "devices": [{"name": "ZBT-2", "hardware_id": "303a:831a"}]},
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
                  "homeassistant/binary_sensor/usbip_link/omr_prefix/config"]
zbt = ul.json.loads(disc[0][1])
assert zbt["unique_id"] == "usbip_link_zbt_2" and zbt["device_class"] == "connectivity"
assert zbt["state_topic"] == "usbip_link/state" and zbt["availability_topic"] == "usbip_link/state/available"
assert "selectattr('name', 'eq', 'ZBT-2')" in zbt["value_template"] and zbt["device"]["sw_version"] == ul.VERSION
assert "'Dongle dAna'" in ul.json.loads(disc[1][1])["value_template"]
lat = ul.json.loads(disc[2][1])
assert lat["unique_id"] == "usbip_link_latency" and lat["unit_of_measurement"] == "ms" and lat["state_class"] == "measurement"
assert "'unknown'" not in lat["value_template"] and "else 'None'" in lat["value_template"]
assert disc[3][1] == ""
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
assert ("usbip_link/state/available", "online") in mq.client.sent and len(mq.client.sent) == 4   # online + 3 discovery
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

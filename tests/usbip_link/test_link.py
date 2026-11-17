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
# premier passage : trouve par VID:PID, attache, pas de redemarrage (premier attachement)
assert link.check() and f.attached and "attach -r 192.168.1.10 -b 2-3" in f.calls
st = link.public()["devices"][0]
assert st["attached"] and st["busid"] == "2-3" and st["attaches"] == 1 and link.restart == []
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
link2 = ul.Link({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "bus_id": "2-3"}]}, runner=f2.run, probe=f2.probe,
                clock=f2.clock)
link2.check()
assert link2.public()["devices"][0]["attached"] and not any(c.startswith("attach") for c in f2.calls)
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
link3.check()                         # serveur muet : latence inconnue, moyenne gardee
assert link3.public()["latency_ms"] is None and link3.public()["server_ok"] is False
assert link3.public()["latency_avg_ms"] == 12.0
link3.check()
assert link3.public()["latency_ms"] == 3.0 and link3.public()["server_ok"] is True
assert len(link3.latencies) == 4
# l'etat sans latence ne bouge pas avec elle (pour decider de publier)
assert "latency_ms" not in link3.public(latency=False) and "latency_ms" not in link3.public(latency=False)["devices"][0]
# vraie sonde : un port ferme ne repond pas
assert ul.server_up("127.0.0.1", 9, timeout=0.5) is None
print("OK")

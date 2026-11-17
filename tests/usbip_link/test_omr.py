"""Essais du prefixe OMR impose, sans border router : ot-ctl simule (redemarrage, arret, version trop ancienne).
Lancer : python tests/usbip_link/test_omr.py usbip_link"""
import os
import sys

sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "usbip_link"))
import usbip_link as ul  # noqa: E402

# sortie de ot-ctl telle que la CLI OpenThread l'ecrit
assert ul.parse_omrconfig("auto\r\nDone\r\n") == ("auto", None, None)
assert ul.parse_omrconfig("disabled\nDone\n") == ("disabled", None, None)
assert ul.parse_omrconfig("custom (fdd7:20e4:8187:1:0:0:0:0/64, prf:high)\nDone\n") == \
    ("custom", "fdd7:20e4:8187:1::/64", "high")
assert ul.parse_omrconfig("custom (fd00:0:0:0::/64, prf:med)\r\nDone") == ("custom", "fd00::/64", "med")
for bad in ("Error 35: InvalidCommand\n", "", "something\n"):
    try:
        ul.parse_omrconfig(bad)
        raise AssertionError(bad)
    except RuntimeError:
        pass

# flux d'un exec Docker sans tty : en-tetes de 8 octets ; sinon texte brut
frame = lambda stream, data: bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data  # noqa: E731
assert ul.demux(frame(1, b"auto\r\n") + frame(1, b"Done\r\n")) == "auto\r\nDone\r\n"
assert ul.demux(frame(2, b"Error 35: InvalidCommand\n")) == "Error 35: InvalidCommand\n"
assert ul.demux(b"auto\nDone\n") == "auto\nDone\n"


class FakeOtbr:
    """Le conteneur du border router : l'etat omrconfig vit en memoire et se perd a chaque redemarrage."""
    def __init__(self):
        self.running, self.config, self.calls, self.old, self.now = True, "auto", [], False, 1000.0

    name = "app_core_openthread_border_router"

    def exec(self, container, cmd):
        if container != self.name:
            raise ul.DockerError(f"404 No such container: {container}")
        assert cmd[:3] == ["ot-ctl", "br", "omrconfig"], cmd
        self.calls.append(" ".join(cmd[1:]))
        if not self.running:
            raise ul.DockerError("409 container is not running")
        if self.old:
            return 1, "Error 35: InvalidCommand\r\n"
        if len(cmd) == 3:
            return 0, f"{self.config}\r\nDone\r\n"
        prefix, prf = cmd[4], cmd[5]
        full = prefix.replace("::/64", ":0:0:0:0/64")
        self.config = f"custom ({full}, prf:{prf})"
        return 0, "Done\r\n"

    def restart(self):
        self.config = "auto"

    def clock(self):
        return self.now


# option absente : rien n'est fait
off = ul.OmrKeeper({}, executor=lambda *a: (_ for _ in ()).throw(AssertionError("no call expected")))
assert not off.enabled and not off.due() and off.check() is False and off.config_error is None

# options invalides : signalees, fonction coupee
for opts in ({"omr_prefix": "fdd7:20e4:8187:1::/48"}, {"omr_prefix": "pas un prefixe"},
             {"omr_prefix": "fdd7:20e4:8187:1::/64", "omr_preference": "max"}):
    k = ul.OmrKeeper(opts)
    assert not k.enabled and k.config_error, opts

f = FakeOtbr()
k = ul.OmrKeeper({"omr_prefix": "FDD7:20E4:8187:1::/64"}, executor=f.exec, clock=f.clock)
assert k.enabled and k.prefix == "fdd7:20e4:8187:1::/64" and k.preference == "high" and k.due()
# premier passage : lu en auto, impose, relu
assert k.check()
assert f.calls == ["br omrconfig", "br omrconfig custom fdd7:20e4:8187:1::/64 high", "br omrconfig"], f.calls
st = k.public()
assert st["enforced"] and st["applied"] == 1 and st["current"] == "fdd7:20e4:8187:1::/64" and st["error"] is None
assert [kind for kind, _ in k.events] == ["omr_set"] and "auto" in k.events[0][1]
# pas encore l'heure ; puis lecture seule, rien a refaire
k.events, f.calls = [], []
assert not k.due()
f.now += ul.OMR_CHECK_S
assert k.due() and not k.check() and f.calls == ["br omrconfig"] and k.events == []
# le border router redemarre : le reglage est perdu, il est remis
f.restart()
f.now += ul.OMR_CHECK_S
k.check()
assert k.public()["enforced"] and k.public()["applied"] == 2 and [x for x, _ in k.events] == ["omr_set"]
# le border router est arrete : une seule alerte, pas une par passage
k.events = []
f.running = False
for _ in range(3):
    f.now += ul.OMR_CHECK_S
    k.check()
assert [x for x, _ in k.events] == ["omr_error"] and not k.public()["enforced"] and "409" in k.public()["error"]
# il revient deja sur le bon prefixe (pas redemarre) : rien a reimposer, retour signale
k.events = []
f.running = True
f.now += ul.OMR_CHECK_S
k.check()
assert k.public()["enforced"] and k.public()["error"] is None and k.public()["applied"] == 2
assert [x for x, _ in k.events] == ["omr_ok"]
# autre prefixe custom pose a la main : remis sur celui des options
f.config = "custom (fd00:0:0:0:0:0:0:0/64, prf:med)"
f.now += ul.OMR_CHECK_S
k.check()
assert k.public()["current"] == "fdd7:20e4:8187:1::/64" and k.public()["current_preference"] == "high"

# OpenThread trop ancien : message clair, une seule fois
f2 = FakeOtbr()
f2.old = True
k2 = ul.OmrKeeper({"omr_prefix": "fdd7:20e4:8187:1::/64", "omr_preference": "med"}, executor=f2.exec, clock=f2.clock)
k2.check()
f2.now += ul.OMR_CHECK_S
k2.check()
assert [x for x, _ in k2.events] == ["omr_error"] and "omrconfig" in k2.public()["error"]

# pas d'acces a Docker (mode protection actif) : message qui le dit
k3 = ul.OmrKeeper({"omr_prefix": "fdd7:20e4:8187:1::/64"},
                  executor=lambda *a: (_ for _ in ()).throw(ul.DockerError("[Errno 2] No such file or directory")))
k3.check()
assert "Docker" in k3.public()["error"]

# autre add-on de border router
f4 = FakeOtbr()
seen = []


def exec4(container, cmd):
    seen.append(container)
    return f4.exec(f4.name, cmd)


k4 = ul.OmrKeeper({"omr_prefix": "fdd7:20e4:8187:1::/64", "otbr_addon": "abc_otbr"}, executor=exec4)
k4.check()
assert k4.public()["enforced"] and set(seen) == {"app_abc_otbr"}

# Supervisor d'avant les apps : conteneur addon_<slug>, trouve au premier refus puis garde
f5 = FakeOtbr()
f5.name = "addon_core_openthread_border_router"
tried = []


def exec5(container, cmd):
    tried.append(container)
    return f5.exec(container, cmd)


k5 = ul.OmrKeeper({"omr_prefix": "fdd7:20e4:8187:1::/64"}, executor=exec5, clock=f5.clock)
k5.check()
assert k5.public()["enforced"] and tried[0] == "app_core_openthread_border_router" and tried[1] == f5.name
tried.clear()
f5.now += ul.OMR_CHECK_S
k5.check()
assert tried == [f5.name], tried
# aucun des deux noms : erreur claire
f6 = FakeOtbr()
f6.name = "autre"
k6 = ul.OmrKeeper({"omr_prefix": "fdd7:20e4:8187:1::/64"}, executor=f6.exec)
k6.check()
assert "404" in k6.public()["error"] and not k6.public()["enforced"]
print("OK")

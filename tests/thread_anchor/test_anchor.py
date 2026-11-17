"""Essais de Thread Anchor sans border router : conteneur et ot-ctl simules (redemarrage, arret,
version trop ancienne, autre nommage des conteneurs, prefixe deja en place, date d'ancrage gardee,
reseau qui ne suit pas, prefixe non local refuse, broker MQTT absent puis trouve, arret).
Lancer : python tests/thread_anchor/test_anchor.py thread_anchor"""
import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "thread_anchor"))
import thread_anchor as ta  # noqa: E402

P = "fdd7:20e4:8187:1::/64"

# reponses de la CLI OpenThread
assert ta.parse_omrconfig("auto\r\nDone\r\n") == ("auto", None, None)
assert ta.parse_omrconfig("disabled\nDone\n") == ("disabled", None, None)
assert ta.parse_omrconfig("custom (fdd7:20e4:8187:1:0:0:0:0/64, prf:high)\nDone\n") == ("custom", P, "high")
assert ta.parse_omrprefix("Local: fd10:6d6a:dd8f:1::/64\r\nFavored: fdd7:20e4:8187:1:0:0:0:0/64 prf:high\r\nDone\r\n") == \
    {"local": "fd10:6d6a:dd8f:1::/64", "favored": P, "favored_preference": "high"}
assert ta.parse_omrprefix("Local: fd10::/64\nFavored: \nDone\n") == {"local": "fd10::/64", "favored": None,
                                                                    "favored_preference": None}
for bad in ("Error 35: InvalidCommand\n", "", "nimporte\n"):
    try:
        ta.parse_omrconfig(bad)
        raise AssertionError(bad)
    except RuntimeError:
        pass
frame = lambda s, d: bytes([s, 0, 0, 0]) + len(d).to_bytes(4, "big") + d  # noqa: E731
assert ta.demux(frame(1, b"auto\r\n") + frame(1, b"Done\r\n")) == "auto\r\nDone\r\n"
assert ta.demux(b"auto\nDone\n") == "auto\nDone\n"


class FakeDocker:
    """Le conteneur du border router : omrconfig vit en memoire et se perd au redemarrage ; le reseau
    retient le prefixe de plus haute preference (le notre une fois impose, sinon celui d'une Google TV)."""
    name = "app_core_openthread_border_router"

    def __init__(self):
        self.running, self.config, self.calls, self.old, self.now = True, "auto", [], False, 1000.0
        self.start, self.google = "2026-11-17T10:57:34Z", ("fdc0:6359:d5be:1::/64", "low")
        self.rival = None      # prefixe qu'un autre border router fait retenir malgre le notre
        self.refuse = False    # le border router refuse `omrconfig custom`

    def _check(self, container):
        if container != self.name:
            raise ta.DockerError(f"404 No such container: {container}")
        if not self.running:
            raise ta.DockerError("409 container is not running")

    def started_at(self, container):
        self._check(container)
        return self.start

    def exec(self, container, cmd):
        self._check(container)
        assert cmd[:2] == ["ot-ctl", "br"], cmd
        self.calls.append(" ".join(cmd[1:]))
        if self.old:
            return 1, "Error 35: InvalidCommand\r\n"
        if cmd[2] == "omrprefix":
            fav = self.google
            if self.config.startswith("custom"):
                fav = (P, self.config.split("prf:")[1].rstrip(")"))
            fav = self.rival or fav
            return 0, f"Local: fd10:6d6a:dd8f:5d7f::/64\r\nFavored: {fav[0]} prf:{fav[1]}\r\nDone\r\n"
        if len(cmd) == 3:
            return 0, f"{self.config}\r\nDone\r\n"
        if self.refuse:
            return 1, "Error 7: InvalidArgs\r\n"
        self.config = f"custom ({cmd[4].replace('::/64', ':0:0:0:0/64')}, prf:{cmd[5]})"
        return 0, "Done\r\n"

    def restart(self, when):
        self.config, self.start = "auto", when

    def clock(self):
        return self.now


# sans omr_prefix : observe seulement, rien n'est impose
d0 = FakeDocker()
a0 = ta.Anchor({}, docker=d0, clock=d0.clock)
assert not a0.enabled and a0.config_error is None and a0.check()
assert d0.calls == ["br omrconfig", "br omrprefix"] and not a0.public()["enforced"]
assert a0.public()["favored"] == "fdc0:6359:d5be:1::/64" and a0.public()["wanted"] is None

# options invalides
for opts in ({"omr_prefix": "fdd7:20e4:8187:1::/48"}, {"omr_prefix": "abc"}, {"omr_prefix": P, "omr_preference": "max"}):
    a = ta.Anchor(opts, docker=FakeDocker())
    assert not a.enabled and a.config_error, opts

# prefixe non local (hors fc00::/7) : refuse, rien n'est impose
for glob in ("2001:db8:1:2::/64", "2a02:a03f:1:2::/64", "fe80::/64"):
    dg = FakeDocker()
    ag = ta.Anchor({"omr_prefix": glob}, docker=dg, clock=dg.clock)
    assert not ag.enabled and "fc00::/7" in ag.config_error and glob in ag.config_error, ag.config_error
    ag.check()
    assert dg.calls == ["br omrconfig", "br omrprefix"] and dg.config == "auto"
    assert ag.public()["wanted"] is None and not ag.public()["enforced"] and ag.public()["anchored_since"] is None
assert ta.Anchor({"omr_prefix": "fc00:1:2:3::/64"}, docker=FakeDocker()).enabled

d = FakeDocker()
a = ta.Anchor({"omr_prefix": "FDD7:20E4:8187:1::/64"}, docker=d, clock=d.clock)
assert a.enabled and a.prefix == P and a.preference == "high" and a.interval == 30 and a.due()
# premier passage : lu en auto, impose, relu, puis prefixe retenu par le reseau
assert a.check()
assert d.calls == ["br omrconfig", f"br omrconfig custom {P} high", "br omrconfig", "br omrprefix"], d.calls
st = a.public()
assert st["enforced"] and st["applied"] == 1 and st["favored"] == P and st["favored_preference"] == "high"
assert st["local"] == "fd10:6d6a:dd8f:5d7f::/64" and st["error"] is None
assert [k for k, _ in a.events] == ["anchor_set", "favored"], a.events
# pas encore l'heure ; puis lecture seule, rien de neuf
a.events, d.calls = [], []
assert not a.due()
d.now += 30
assert a.due() and not a.check() and d.calls == ["br omrconfig", "br omrprefix"] and a.events == []
# redemarrage du conteneur : detecte au tic suivant, reimpose tout de suite
assert not a.restarted() and a.started_at == "2026-11-17T10:57:34Z"
d.restart("2026-11-18T03:00:00Z")
assert a.restarted() and a.started_at == "2026-11-18T03:00:00Z"
a.check("restart")
assert a.public()["enforced"] and a.public()["applied"] == 2
assert [k for k, _ in a.events] == ["otbr_restart", "anchor_set"], a.events
# border router arrete : une alerte, puis on revient plus vite (10 s)
a.events = []
d.running = False
for _ in range(3):
    d.now += 30
    a.check()
assert [k for k, _ in a.events] == ["error"] and "409" in a.public()["error"] and not a.public()["enforced"]
d.now += 10
assert a.due()
# il revient sans avoir redemarre (reglage garde) : rien a reimposer, retour signale
a.events = []
d.running = True
a.check()
assert a.public()["enforced"] and a.public()["applied"] == 2 and [k for k, _ in a.events] == ["anchor_ok", "favored"]

# OpenThread trop ancien
d2 = FakeDocker()
d2.old = True
a2 = ta.Anchor({"omr_prefix": P, "omr_preference": "med"}, docker=d2, clock=d2.clock)
a2.check()
d2.now += 30
a2.check()
assert [k for k, _ in a2.events] == ["error"] and "omrconfig" in a2.public()["error"]

# pas d'acces a Docker (mode protection actif)


class NoDocker:
    def exec(self, *a):
        raise ta.DockerError("[Errno 2] No such file or directory")

    started_at = exec


a3 = ta.Anchor({"omr_prefix": P}, docker=NoDocker())
a3.check()
assert "Docker" in a3.public()["error"] and not a3.restarted()

# ancien Supervisor : conteneur addon_<slug>, trouve puis garde ; autre add-on de border router
d4 = FakeDocker()
d4.name = "addon_abc_otbr"
a4 = ta.Anchor({"omr_prefix": P, "otbr_addon": "abc_otbr", "check_interval": 5}, docker=d4, clock=d4.clock)
a4.check()
assert a4.public()["enforced"] and a4.container == "addon_abc_otbr" and a4.interval == 10
assert a4.public()["otbr_addon"] == "abc_otbr"

# ---- date d'ancrage (anchored_since), gardee dans un fichier
tmp = tempfile.mkdtemp()
mem = os.path.join(tmp, "anchor.json")
CUSTOM = "custom (fdd7:20e4:8187:1:0:0:0:0/64, prf:high)"
# cas de la production : prefixe deja en place au premier passage (impose par un autre outil)
d5 = FakeDocker()
d5.config = CUSTOM
a5 = ta.Anchor({"omr_prefix": P}, docker=d5, clock=d5.clock, memory=mem)
assert a5.anchored_since is None and a5.check()
assert d5.calls == ["br omrconfig", "br omrprefix"], d5.calls
st = a5.public()
assert st["enforced"] and st["followed"] and st["applied"] == 0 and st["applied_at"] is None
assert [k for k, _ in a5.events] == ["anchor_ok", "favored"], a5.events
since = st["anchored_since"]
assert since and datetime.fromisoformat(since).tzinfo is not None, since
assert datetime.fromisoformat(since).timestamp() == d5.now
with open(mem, encoding="utf-8") as f:
    assert json.load(f) == {"prefix": P, "preference": "high", "anchored_since": since}
# les lectures suivantes ne la changent pas
d5.now += 30
a5.check()
assert a5.public()["anchored_since"] == since
# border router injoignable : pas constate perdu, la date reste ; il revient avec son reglage : pareil
d5.running = False
d5.now += 30
a5.check()
assert a5.public()["error"] and not a5.public()["enforced"] and a5.public()["anchored_since"] == since
d5.running = True
d5.now += 30
a5.check()
assert a5.public()["enforced"] and a5.public()["anchored_since"] == since
# redemarrage de l'add-on : relue du fichier, gardee tant que le prefixe est trouve en place
d5.now += 3600
a6 = ta.Anchor({"omr_prefix": P}, docker=d5, clock=d5.clock, memory=mem)
assert a6.anchored_since == since
a6.check()
assert a6.public()["anchored_since"] == since and a6.public()["applied"] == 0
# autre preference ou autre prefixe dans les options : la date gardee ne vaut plus
assert ta.Anchor({"omr_prefix": P, "omr_preference": "med"}, docker=d5, memory=mem).anchored_since is None
assert ta.Anchor({"omr_prefix": "fd00:1:2:3::/64"}, docker=d5, memory=mem).anchored_since is None
assert ta.Anchor({}, docker=d5, memory=mem).anchored_since is None
# ancrage constate perdu (border router redemarre) et impossible a remettre : null, aussi dans le fichier
d5.restart("2026-11-19T03:00:00Z")
d5.refuse = True
d5.now += 30
a6.check()
assert a6.public()["anchored_since"] is None and not a6.public()["enforced"] and a6.public()["error"]
with open(mem, encoding="utf-8") as f:
    assert json.load(f)["anchored_since"] is None
assert ta.Anchor({"omr_prefix": P}, docker=d5, memory=mem).anchored_since is None
# remis : nouvelle date, celle de ce passage
d5.refuse = False
d5.now += 10
a6.check()
since2 = a6.public()["anchored_since"]
assert a6.public()["enforced"] and a6.public()["applied"] == 1 and since2 != since
assert datetime.fromisoformat(since2).timestamp() == d5.now
# fichier illisible ou abime : pas de date, pas d'erreur
with open(mem, "w", encoding="utf-8") as f:
    f.write("{pas du json")
assert ta.Anchor({"omr_prefix": P}, docker=d5, memory=mem).anchored_since is None
with open(mem, "w", encoding="utf-8") as f:
    json.dump({"prefix": P, "preference": "high", "anchored_since": "hier"}, f)
assert ta.Anchor({"omr_prefix": P}, docker=d5, memory=mem).anchored_since is None
# dossier absent : l'ancrage marche quand meme, la date n'est qu'en memoire
d7 = FakeDocker()
a7 = ta.Anchor({"omr_prefix": P}, docker=d7, clock=d7.clock, memory=os.path.join(tmp, "absent", "anchor.json"))
a7.check()
assert a7.public()["enforced"] and a7.public()["anchored_since"]

# ---- le reseau suit-il ? (followed)
d8 = FakeDocker()
a8 = ta.Anchor({"omr_prefix": P}, docker=d8, clock=d8.clock)
d8.rival = ("fd00:aaaa:bbbb:1::/64", "high")
# passage qui impose : pas d'alerte tout de suite (le reseau a besoin d'un moment)
a8.check()
assert a8.public()["enforced"] and not a8.public()["followed"]
assert [k for k, _ in a8.events] == ["anchor_set", "favored"], a8.events
# passage suivant : une alerte, une seule par episode
a8.events = []
for _ in range(3):
    d8.now += 30
    a8.check()
assert [k for k, _ in a8.events] == ["follow_lost"] and "fd00:aaaa:bbbb:1::/64" in a8.events[0][1], a8.events
assert a8.public()["enforced"] and not a8.public()["followed"] and a8.public()["error"] is None
# le reseau suit de nouveau : dit une fois
a8.events = []
d8.rival = None
for _ in range(2):
    d8.now += 30
    a8.check()
assert [k for k, _ in a8.events] == ["favored", "follow_back"] and a8.public()["followed"], a8.events
# meme prefixe mais autre preference retenue : ne suit pas ; nouvel episode, nouvelle alerte
a8.events = []
d8.rival = (P, "low")
d8.now += 30
a8.check()
assert [k for k, _ in a8.events] == ["favored", "follow_lost"] and not a8.public()["followed"], a8.events
# observation seule : jamais « followed », jamais d'alerte
assert not a0.public()["followed"] and "follow_lost" not in [k for k, _ in a0.events]

# ---- MQTT : broker absent puis trouve, arret


class FakeInfo:
    def __init__(self, client):
        self.client = client

    def wait_for_publish(self, timeout=None):
        self.client.waited = timeout


class FakeClient:
    def __init__(self):
        self.sent, self.log, self.waited, self.fail_connect = [], [], None, False

    def username_pw_set(self, user, password):
        self.log.append(("user", user))

    def will_set(self, topic, payload, retain=False):
        self.log.append(("will", topic, payload, retain))

    def reconnect_delay_set(self, lo, hi):
        pass

    def connect_async(self, host, port, keepalive=60):
        if self.fail_connect:
            raise ValueError("Invalid host.")
        self.log.append(("connect", host, port))

    def loop_start(self):
        self.log.append(("loop_start",))

    def loop_stop(self):
        self.log.append(("loop_stop",))

    def disconnect(self):
        self.log.append(("disconnect",))

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload, retain))
        return FakeInfo(self)


class Broker:
    """Le service MQTT du Supervisor : absent, puis la."""
    def __init__(self):
        self.up, self.asked, self.now, self.clients, self.fail_connect = False, 0, 5000.0, [], False

    def service(self):
        self.asked += 1
        if not self.up:
            raise RuntimeError("HTTP Error 400: Bad Request")
        return {"host": "core-mosquitto", "port": 1883, "username": "addons", "password": "x"}

    def factory(self):
        c = FakeClient()
        c.fail_connect = self.fail_connect
        self.clients.append(c)
        return c

    def clock(self):
        return self.now


b = Broker()
mq = ta.Mqtt(a5, service=b.service, factory=b.factory, clock=b.clock)
assert mq.client is None and b.asked == 0
mq.publish()                                   # sans broker : rien, pas d'erreur
mq.stop()
assert not mq.start() and b.asked == 1 and mq.client is None
# pas redemande avant 60 s, meme appele a chaque tic
for _ in range(5):
    b.now += 5
    assert not mq.start()
assert b.asked == 1
b.now += 40
assert not mq.start() and b.asked == 2
# le service repond mais la connexion ne peut pas etre preparee : nouvel essai aussi
b.up, b.fail_connect = True, True
b.now += 60
assert not mq.start() and b.asked == 3 and mq.client is None
# le broker est la : client cree, testament pose, connexion lancee ; plus rien n'est redemande
b.fail_connect = False
b.now += 59
assert not mq.start() and b.asked == 3
b.now += 1
assert mq.start() and b.asked == 4 and mq.client is b.clients[-1]
c = mq.client
assert ("will", "thread_anchor/state/available", "offline", True) in c.log
assert ("connect", "core-mosquitto", 1883) in c.log and c.log[-1] == ("loop_start",) and ("user", "addons") in c.log
assert mq.start() and b.asked == 4
# connecte : en ligne, entites, etat (avec les nouveaux champs)
mq.on_connect(c, None, None, 0)
assert c.sent[0] == ("thread_anchor/state/available", "online", True)
assert [tp for tp, _, _ in c.sent[1:3]] == ["homeassistant/binary_sensor/thread_anchor/anchored/config",
                                           "homeassistant/sensor/thread_anchor/favored/config"]
tp, payload, retain = c.sent[-1]
state = json.loads(payload)
assert tp == "thread_anchor/state" and retain and state["version"] == ta.VERSION and state["updated"]
assert state["anchored_since"] == a5.public()["anchored_since"] and state["followed"] is True
# les champs lus par Mesh Guardian sont toujours la
for key in ("wanted", "preference", "mode", "current", "current_preference", "enforced", "favored",
            "favored_preference", "local", "applied", "applied_at", "otbr_started_at", "error", "version", "updated"):
    assert key in state, key
# arret propre : « offline » retenu, attendu, puis deconnexion ; l'etat retenu n'est pas reecrit
c.sent = []
mq.stop()
assert c.sent == [("thread_anchor/state/available", "offline", True)] and c.waited == 2
assert c.log[-2:] == [("disconnect",), ("loop_stop",)] and mq.client is None
mq.publish()
mq.stop()
assert c.sent == [("thread_anchor/state/available", "offline", True)]
print("OK")

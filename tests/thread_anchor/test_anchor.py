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

    def subscribe(self, topic):
        self.log.append(("subscribe", topic))

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
assert ("subscribe", "thread_anchor/diag/request") in c.log

# ---- diagnostic d'une node (lecture seule) : formats verifies dans la doc / le code d'OpenThread
assert ta.parse_rloc16("0xB45C") == ta.parse_rloc16("b45c") == ta.parse_rloc16(46172) == 0xB45C
for bad in ("0x10000", "zz", None, True, -1, ""):
    try:
        ta.parse_rloc16(bad)
        raise AssertionError(bad)
    except (ValueError, TypeError):
        pass
assert ta.rloc_address("fdde:ad00:beef:0::/64", 0xB45C) == "fdde:ad00:beef::ff:fe00:b45c"
assert ta.rloc_address("fdde:ad00:beef:0:0:0:0:0/64", 0xFC00) == "fdde:ad00:beef::ff:fe00:fc00"

PING_OK = ("16 bytes from fdde:ad00:beef:0:0:ff:fe00:b45c: icmp_seq=1 hlim=64 time=12ms\r\n"
           "1 packets transmitted, 1 packets received. Packet loss = 0.0%. "
           "Round-trip min/avg/max = 12/12.000/12 ms.\r\nDone\r\n")
PING_LOST = "1 packets transmitted, 0 packets received. Packet loss = 100.0%.\r\nDone\r\n"
assert ta.parse_ping(PING_OK) == {"ok": True, "rtt_ms": 12.0}
assert ta.parse_ping("1 packets transmitted, 1 packets received. Round-trip min/avg/max = 7/7.5/8 ms.\nDone\n") == \
    {"ok": True, "rtt_ms": 7.5}
assert ta.parse_ping(PING_LOST) == {"ok": False, "rtt_ms": None}
for bad in ("Error 13: InvalidState\r\n", "", "Done\r\n"):
    try:
        ta.parse_ping(bad)
        raise AssertionError(bad)
    except RuntimeError:
        pass

OLD = "fdc0:6359:d5be:1:aaaa:bbbb:cccc:dddd"
OMR = "fdd7:20e4:8187:1:1:2:3:4"
DIAG_OK = ("DIAG_GET.rsp/ans from fdde:ad00:beef:0:0:ff:fe00:b45c: 000800ca7a34808b66e461\r\n"
           "Ext Address: 'ca7a34808b66e461'\r\n"
           "IP6 Address List:\r\n"
           "    - fdde:ad00:beef:0:0:ff:fe00:b45c\r\n"
           f"    - {OLD}\r\n"
           f"    - {OMR}\r\n"
           "    - fdde:ad00:beef:0:1:2:3:4\r\n"
           "    - fe80:0:0:0:c87a:3480:8b66:e461\r\n"
           f"    - {OLD}\r\n"
           "Done\r\n")
d = ta.parse_diag(DIAG_OK)
assert d["answered"] and d["ext"] == "ca7a34808b66e461" and len(d["addresses"]) == 5, d   # sans doublon
assert d["addresses"][1] == OLD
assert ta.parse_diag("Done\r\n") == {"answered": False, "ext": None, "addresses": []}
assert ta.parse_diag("DIAG_GET.rsp/ans from fd00::1: 00\r\nExt Address: 'AABBCCDDEEFF0011'\r\nDone\r\n") == \
    {"answered": True, "ext": "aabbccddeeff0011", "addresses": []}
try:
    ta.parse_diag("Error 28: ResponseTimeout\r\n")
    raise AssertionError("Error")
except RuntimeError:
    pass

MLP = "fdde:ad00:beef::/64"
omr, other = ta.classify(d["addresses"], MLP, (P, None))
assert omr == [OMR] and other == [OLD], (omr, other)
assert ta.classify(["2001:db8::1", "fe80::1", "fdde:ad00:beef::1", "ff02::1", "::1"], MLP, (P,)) == ([], ["2001:db8::1"])
# prefixe voulu et prefixe retenu : tous deux comptent comme OMR
assert ta.classify([OLD, OMR], MLP, (P, "fdc0:6359:d5be:1::/64")) == ([OLD, OMR], [])


class Clk:
    now = 10000.0

    def __call__(self):
        return self.now


class FakeOtbr:
    """ot-ctl en lecture : ipaddr rloc, ping, networkdiagnostic get. Note tout ce qui est lance."""
    def __init__(self, clk):
        self.clk, self.calls, self.timeouts, self.running = clk, [], [], True
        self.ping_out, self.diag_out, self.ping_takes, self.diag_takes = PING_OK, DIAG_OK, 0, 0

    def started_at(self, container):
        return "2026-11-17T10:57:34Z"

    def exec(self, container, cmd, timeout=30):
        if container != "app_core_openthread_border_router":
            raise ta.DockerError(f"404 No such container: {container}")
        if not self.running:
            raise ta.DockerError("409 container is not running")
        assert cmd[0] == "ot-ctl", cmd
        self.calls.append(cmd[1:])
        self.timeouts.append(timeout)
        if cmd[1:3] == ["ipaddr", "rloc"]:
            return 0, "fdde:ad00:beef:0:0:ff:fe00:fc00\r\nDone\r\n"
        if cmd[1] == "ping":
            self.clk.now += self.ping_takes
            return 0, self.ping_out
        if cmd[1:3] == ["networkdiagnostic", "get"]:
            self.clk.now += self.diag_takes
            return 0, self.diag_out
        raise AssertionError(f"command not allowed in a diagnostic: {cmd}")


def make_diag(**kw):
    clk = Clk()
    otbr = FakeOtbr(clk)
    an = ta.Anchor({"omr_prefix": P}, docker=otbr, clock=clk)
    an.favored, an.favored_prf = P, "high"
    out = []
    dg = ta.Diag(an, lambda topic, res: out.append((topic, res)), clock=clk, spawn=kw.get("spawn", lambda fn: fn()))
    return clk, otbr, dg, out


def req(**kw):
    return json.dumps(dict({"id": "r1", "rloc16": "0xB45C", "ext": "ca7a34808b66e461", "ping": True}, **kw))


# cas normal : une node restee sur l'ancien prefixe
clk, otbr, dg, out = make_diag()
dg.submit(req())
assert len(out) == 1 and out[0][0] == "thread_anchor/diag/result/r1"
r = out[0][1]
assert r["id"] == "r1" and r["rloc16"] == "0xB45C" and r["rloc_address"] == "fdde:ad00:beef::ff:fe00:b45c"
assert r["ext"] == "ca7a34808b66e461" and r["ping"] == {"ok": True, "rtt_ms": 12.0} and r["error"] is None
assert len(r["addresses"]) == 5 and r["omr_addresses"] == [OMR] and r["other_prefix_addresses"] == [OLD]
assert datetime.fromisoformat(r["at"]).tzinfo is not None
assert otbr.calls == [["ipaddr", "rloc"], ["ping", "fdde:ad00:beef::ff:fe00:b45c", "16", "1"],
                      ["networkdiagnostic", "get", "fdde:ad00:beef::ff:fe00:b45c", "0", "8"]], otbr.calls
assert all(1 <= tm <= ta.DIAG_TIMEOUT_S for tm in otbr.timeouts), otbr.timeouts
assert not dg.running
# rien d'ecrit sur le border router : aucune des commandes n'est une ecriture
assert not [c for c in otbr.calls if c[0] not in ("ipaddr", "ping", "networkdiagnostic")]
# ping demande a faux : pas de ping, "ping": null
clk, otbr, dg, out = make_diag()
dg.submit(req(ping=False))
assert out[0][1]["ping"] is None and out[0][1]["error"] is None and not [c for c in otbr.calls if c[0] == "ping"]
# ping sans reponse : la node reste interrogee, ping ok=false
clk, otbr, dg, out = make_diag()
otbr.ping_out = PING_LOST
dg.submit(req())
assert out[0][1]["ping"] == {"ok": False, "rtt_ms": None} and out[0][1]["error"] is None and out[0][1]["addresses"]
# ping en erreur ot-ctl : ok=false, le diagnostic continue
clk, otbr, dg, out = make_diag()
otbr.ping_out = "Error 13: InvalidState\r\n"
dg.submit(req())
assert out[0][1]["ping"] == {"ok": False, "rtt_ms": None} and out[0][1]["addresses"]
# ext sans controle (absent) ; ext qui ne correspond pas : erreur, adresses rendues quand meme
clk, otbr, dg, out = make_diag()
dg.submit(req(ext=None))
assert out[0][1]["error"] is None and out[0][1]["ext"] == "ca7a34808b66e461"
clk, otbr, dg, out = make_diag()
dg.submit(req(ext="0011223344556677"))
assert "ca7a34808b66e461" in out[0][1]["error"] and "0011223344556677" in out[0][1]["error"] and out[0][1]["addresses"]
# pas de reponse au diagnostic, erreur de diagnostic, border router arrete
clk, otbr, dg, out = make_diag()
otbr.diag_out = "Done\r\n"
dg.submit(req())
assert out[0][1]["error"] == "no answer to the network diagnostic" and out[0][1]["addresses"] == []
assert out[0][1]["ping"]["ok"] is True
clk, otbr, dg, out = make_diag()
otbr.diag_out = "Error 28: ResponseTimeout\r\n"
dg.submit(req())
assert "ResponseTimeout" in out[0][1]["error"]
clk, otbr, dg, out = make_diag()
otbr.running = False
dg.submit(req())
assert "409" in out[0][1]["error"] and out[0][1]["rloc_address"] is None and not dg.running
# delai maximal de 15 s : le ping a tout pris, le diagnostic n'est pas lance
clk, otbr, dg, out = make_diag()
otbr.ping_takes = 16
dg.submit(req())
assert out[0][1]["error"] == "timeout (15 s)" and out[0][1]["ping"]["ok"] is True and out[0][1]["addresses"] == []
assert not [c for c in otbr.calls if c[0] == "networkdiagnostic"] and not dg.running
# demandes inutilisables : pas d'id -> rien ; rloc16 invalide -> reponse en erreur
clk, otbr, dg, out = make_diag()
for raw in ("pas du json", "null", "[]", "{}", json.dumps({"id": "", "rloc16": "0xb45c"}),
            json.dumps({"id": "a/b", "rloc16": "0xb45c"}), json.dumps({"id": "a#", "rloc16": "0xb45c"})):
    dg.submit(raw)
assert out == [] and otbr.calls == []
dg.submit(json.dumps({"id": "x", "rloc16": "zz"}))
dg.submit(json.dumps({"id": "y"}))
assert [(tp, r["error"][:14]) for tp, r in out] == [("thread_anchor/diag/result/x", "invalid rloc16"),
                                                    ("thread_anchor/diag/result/y", "invalid rloc16")]
assert otbr.calls == [] and "ping" in out[0][1] and out[0][1]["addresses"] == []
# une seule a la fois : « busy » ; au plus une par node toutes les 10 s : « too soon »
later = []
clk, otbr, dg, out = make_diag(spawn=later.append)
dg.submit(req(id="a"))
assert dg.running and out == [] and len(later) == 1
dg.submit(req(id="b", rloc16="0x1800"))
assert [(tp, r["error"]) for tp, r in out] == [("thread_anchor/diag/result/b", "busy")] and out[0][1]["rloc_address"] is None
later.pop()()
assert [tp for tp, _ in out] == ["thread_anchor/diag/result/b", "thread_anchor/diag/result/a"] and not dg.running
assert out[1][1]["error"] is None
clk.now += 9
dg.submit(req(id="c"))
assert out[-1][0] == "thread_anchor/diag/result/c" and out[-1][1]["error"] == "too soon" and len(later) == 0
dg.submit(req(id="d", rloc16="0x1800"))          # autre node : permis
assert len(later) == 1
later.pop()()
assert out[-1][1]["error"] is None and out[-1][1]["rloc_address"] == "fdde:ad00:beef::ff:fe00:1800"
clk.now += 2                                      # 11 s apres la premiere demande de B45C
dg.submit(req(id="e"))
assert len(later) == 1
later.pop()()
assert out[-1][0] == "thread_anchor/diag/result/e" and out[-1][1]["error"] is None
# demande refusee (« busy ») : pas comptee comme faite pour la node
clk, otbr, dg, out = make_diag(spawn=later.append)
dg.submit(req(id="f"))
dg.submit(req(id="g", rloc16="0x2000"))
later.pop()()
dg.submit(req(id="h", rloc16="0x2000"))
assert len(later) == 1 and out[0][1]["id"] == "g" and out[0][1]["error"] == "busy"
later.pop()()
assert out[-1][0] == "thread_anchor/diag/result/h" and out[-1][1]["error"] is None

# par MQTT : demande sur thread_anchor/diag/request, reponse non retenue
b2 = Broker()
b2.up = True
clk2 = Clk()
otbr2 = FakeOtbr(clk2)
an2 = ta.Anchor({"omr_prefix": P}, docker=otbr2, clock=clk2)
mq2 = ta.Mqtt(an2, service=b2.service, factory=b2.factory, clock=clk2)
mq2.diag.spawn = lambda fn: fn()
assert mq2.start()
c2 = mq2.client
assert c2.log.count(("subscribe", "thread_anchor/diag/request")) == 0     # a la connexion seulement
mq2.on_connect(c2, None, None, 0)
assert ("subscribe", "thread_anchor/diag/request") in c2.log


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


c2.sent = []
mq2.on_message(c2, None, Msg("thread_anchor/other", req(id="z").encode()))
assert c2.sent == []
mq2.on_message(c2, None, Msg("thread_anchor/diag/request", req(id="z").encode()))
assert [(tp, retain) for tp, _, retain in c2.sent] == [("thread_anchor/diag/result/z", False)]
res = json.loads(c2.sent[0][1])
assert res["id"] == "z" and res["other_prefix_addresses"] == [OLD] and res["error"] is None
print("OK")

"""Essais de Thread Anchor sans border router : conteneur et ot-ctl simules (redemarrage, arret,
version trop ancienne, autre nommage des conteneurs, prefixe deja en place, date d'ancrage gardee,
reseau qui ne suit pas, prefixe non local refuse, broker MQTT absent puis trouve, arret).
Lancer : python tests/thread_anchor/test_anchor.py thread_anchor"""
import json
import logging
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "thread_anchor"))
import thread_anchor as ta  # noqa: E402

P = "fd00:aaaa:bbbb:1::/64"

# reponses de la CLI OpenThread
assert ta.parse_omrconfig("auto\r\nDone\r\n") == ("auto", None, None)
assert ta.parse_omrconfig("disabled\nDone\n") == ("disabled", None, None)
assert ta.parse_omrconfig("custom (fd00:aaaa:bbbb:1:0:0:0:0/64, prf:high)\nDone\n") == ("custom", P, "high")
assert ta.parse_omrprefix("Local: fd00:1111:2222:1::/64\r\nFavored: fd00:aaaa:bbbb:1:0:0:0:0/64 prf:high\r\nDone\r\n") == \
    {"local": "fd00:1111:2222:1::/64", "favored": P, "favored_preference": "high"}
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


LINK_OUT = {      # sorties d'ot-ctl pour le lien du border router (enfant) avec son parent
    "rloc16": "6c05\r\nDone\r\n",
    "parent": ("Ext Addr: 5a6b7c8d9e0f1a2b\r\nRloc: 3400\r\nLink Quality In: 3\r\nLink Quality Out: 2\r\n"
               "Age: 17\r\nVersion: 5\r\nDone\r\n"),
    "neighbor table": (
        "| Role | RLOC16 | Age | Avg RSSI | Last RSSI |R|D|N| Extended MAC     |\r\n"
        "+------+--------+-----+----------+-----------+-+-+-+------------------+\r\n"
        "|   R  | 0x3400 |  17 |      -62 |       -64 |1|1|1| 5a6b7c8d9e0f1a2b |\r\n"
        "|   R  | 0x5800 |   3 |      -48 |       -47 |1|1|1| 1111111111111111 |\r\n"
        "|   R  | 0x9c00 |   9 |      -71 |       -70 |1|1|1| 2222222222222222 |\r\n"
        "|   R  | 0xb800 |  20 |      -55 |       -58 |1|1|1| 3333333333333333 |\r\n"
        "|   C  | 0x6c0a |  30 |      -40 |       -41 |0|0|0| 4444444444444444 |\r\nDone\r\n"),
    "router table": (
        "| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |\r\n"
        "+----+--------+----------+-----------+-------+--------+-----+------------------+------+\r\n"
        "|  7 | 0x3400 |       63 |         0 |     3 |      2 |  17 | 5a6b7c8d9e0f1a2b |    1 |\r\n"
        "| 22 | 0x5800 |       63 |         0 |     3 |      3 |   3 | 1111111111111111 |    1 |\r\nDone\r\n"),
    "counters mle": ("Role Disabled: 0\r\nRole Detached: 4\r\nRole Child: 5\r\nRole Router: 0\r\nRole Leader: 0\r\n"
                     "Attach Attempts: 6\r\nPartition Id Changes: 1\r\nBetter Partition Attach Attempts: 0\r\n"
                     "Parent Changes: 3\r\nDone\r\n"),
    # format reel d'OpenThread : les compteurs sont en retrait sous TxTotal / RxTotal
    "counters mac": ("TxTotal: 1034\r\n    TxUnicast: 1000\r\n    TxBroadcast: 34\r\n    TxAckRequested: 900\r\n"
                     "    TxAcked: 880\r\n    TxNoAckRequested: 134\r\n    TxData: 1000\r\n    TxDataPoll: 30\r\n"
                     "    TxBeacon: 2\r\n    TxBeaconRequest: 2\r\n    TxOther: 0\r\n    TxRetry: 21\r\n"
                     "    TxErrCca: 4\r\n    TxErrAbort: 1\r\n    TxErrBusyChannel: 2\r\n"
                     "RxTotal: 2210\r\n    RxUnicast: 2000\r\n    RxBroadcast: 210\r\n    RxData: 2100\r\n"
                     "    RxDataPoll: 0\r\n    RxBeacon: 4\r\n    RxBeaconRequest: 0\r\n    RxOther: 0\r\n"
                     "    RxAddressFiltered: 3\r\n    RxDestAddrFiltered: 5\r\n    RxDuplicated: 1\r\n"
                     "    RxErrNoFrame: 6\r\n    RxErrUnknownNeighbor: 0\r\n    RxErrInvalidSrcAddr: 0\r\n"
                     "    RxErrSec: 0\r\n    RxErrFcs: 7\r\n    RxErrOther: 0\r\nDone\r\n"),
}


class FakeDocker:
    """Le conteneur du border router : omrconfig vit en memoire et se perd au redemarrage ; le reseau
    retient le prefixe de plus haute preference (le notre une fois impose, sinon celui d'une Google TV)."""
    name = "app_core_openthread_border_router"

    def __init__(self):
        self.running, self.config, self.calls, self.old, self.now = True, "auto", [], False, 1000.0
        self.start, self.google = "2026-11-17T10:57:34Z", ("fd00:eeee:ffff:1::/64", "low")
        self.rival = None      # prefixe qu'un autre border router fait retenir malgre le notre
        self.refuse = False    # le border router refuse `omrconfig custom`
        self.role, self.router_ids = "child", "8 24 50"    # lectures du role (`state`, `router list`)
        self.reads = []        # ces lectures ; `calls` ne note que les `br ...`
        self.script = {}       # commande -> sorties a rendre d'abord (ex. "" : commande ignoree)
        self.attempts = []     # commandes servies par `script`
        self.link_reads = []   # lectures du lien avec le parent (locales, sans trafic radio)
        self.link_out = dict(LINK_OUT)
        # mesure de l'aller-retour jusqu'a la puce : le temps (virtuel) que prend chaque lecture
        self.perf, self.cmds, self.fail = None, [], {}      # horloge de mesure, toutes les commandes, commande -> erreur
        self.state_s, self.chip_s, self.nchip = 0.002, lambda k: 0.012, {"txpower": 0, "ccathreshold": 0}
        self.cc_s = lambda k: 0.015

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
        self.cmds.append(" ".join(cmd[1:]))
        queued = self.script.get(" ".join(cmd[1:]))
        if queued:
            self.attempts.append(" ".join(cmd[1:]))
            return 0, queued.pop(0)
        if cmd[1] in self.fail:
            return 1, self.fail[cmd[1]]
        if cmd[1:] in (["txpower"], ["ccathreshold"]):          # lectures d'un reglage de la puce (spinel)
            k = self.nchip[cmd[1]] = self.nchip[cmd[1]] + 1
            if self.perf is not None:
                self.perf.t += self.chip_s(k) if cmd[1] == "txpower" else self.cc_s(k)
            return 0, ("8 dBm" if cmd[1] == "txpower" else "-75 dBm") + "\r\nDone\r\n"
        if cmd[1:] == ["state"]:
            self.reads.append("state")
            if self.perf is not None:
                self.perf.t += self.state_s
            return 0, f"{self.role}\r\nDone\r\n"
        if cmd[1:] == ["router", "list"]:
            self.reads.append("router list")
            return 0, f"{self.router_ids}\r\nDone\r\n"
        if " ".join(cmd[1:]) in LINK_OUT:       # seules lectures locales permises en plus des `br ...`
            self.link_reads.append(" ".join(cmd[1:]))
            return 0, self.link_out[" ".join(cmd[1:])]
        assert cmd[:2] == ["ot-ctl", "br"], cmd
        self.calls.append(" ".join(cmd[1:]))
        if self.old:
            return 1, "Error 35: InvalidCommand\r\n"
        if cmd[2] == "omrprefix":
            fav = self.google
            if self.config.startswith("custom"):
                fav = (P, self.config.split("prf:")[1].rstrip(")"))
            fav = self.rival or fav
            return 0, f"Local: fd00:1111:2222:5555::/64\r\nFavored: {fav[0]} prf:{fav[1]}\r\nDone\r\n"
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
assert a0.public()["favored"] == "fd00:eeee:ffff:1::/64" and a0.public()["wanted"] is None

# options invalides
for opts in ({"omr_prefix": "fd00:aaaa:bbbb:1::/48"}, {"omr_prefix": "abc"}, {"omr_prefix": P, "omr_preference": "max"}):
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
a = ta.Anchor({"omr_prefix": "FD00:AAAA:BBBB:1::/64"}, docker=d, clock=d.clock)
assert a.enabled and a.prefix == P and a.preference == "high" and a.interval == 30 and a.due()
# premier passage : lu en auto, impose, relu, puis prefixe retenu par le reseau
assert a.check()
assert d.calls == ["br omrconfig", f"br omrconfig custom {P} high", "br omrconfig", "br omrprefix"], d.calls
st = a.public()
assert st["enforced"] and st["applied"] == 1 and st["favored"] == P and st["favored_preference"] == "high"
assert st["local"] == "fd00:1111:2222:5555::/64" and st["error"] is None
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
CUSTOM = "custom (fd00:aaaa:bbbb:1:0:0:0:0/64, prf:high)"
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
d8.rival = ("fd00:cccc:dddd:1::/64", "high")
# passage qui impose : pas d'alerte tout de suite (le reseau a besoin d'un moment)
a8.check()
assert a8.public()["enforced"] and not a8.public()["followed"]
assert [k for k, _ in a8.events] == ["anchor_set", "favored"], a8.events
# passage suivant : une alerte, une seule par episode
a8.events = []
for _ in range(3):
    d8.now += 30
    a8.check()
assert [k for k, _ in a8.events] == ["follow_lost"] and "fd00:cccc:dddd:1::/64" in a8.events[0][1], a8.events
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
# le role Thread : une entite en lecture seule, le nombre de routeurs en attribut
role_cfg = [json.loads(pl) for tp, pl, _ in c.sent if tp == "homeassistant/sensor/thread_anchor/thread_role/config"]
assert len(role_cfg) == 1 and role_cfg[0]["name"] == "Thread role" and "thread_role" in role_cfg[0]["value_template"]
assert role_cfg[0]["json_attributes_topic"] == "thread_anchor/state" and "command_topic" not in role_cfg[0]
assert state["thread_role"] == "child" and state["thread_routers"] == 3
assert state["thread_link"]["parent"]["rloc16"] == "0x3400"        # 0.1.9 : le lien est dans l'etat
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
assert ta.parse_rloc16("0x6C05") == ta.parse_rloc16("6c05") == ta.parse_rloc16(27653) == 0x6C05
for bad in ("0x10000", "zz", None, True, -1, ""):
    try:
        ta.parse_rloc16(bad)
        raise AssertionError(bad)
    except (ValueError, TypeError):
        pass
assert ta.rloc_address("fdde:ad00:beef:0::/64", 0x6C05) == "fdde:ad00:beef::ff:fe00:6c05"
assert ta.rloc_address("fdde:ad00:beef:0:0:0:0:0/64", 0xFC00) == "fdde:ad00:beef::ff:fe00:fc00"

PING_OK = ("16 bytes from fdde:ad00:beef:0:0:ff:fe00:6c05: icmp_seq=1 hlim=64 time=12ms\r\n"
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

OLD = "fd00:eeee:ffff:1:aaaa:bbbb:cccc:dddd"
OMR = "fd00:aaaa:bbbb:1:1:2:3:4"
DIAG_OK = ("DIAG_GET.rsp/ans from fdde:ad00:beef:0:0:ff:fe00:6c05: 0008001a2b3c4d5e6f7081\r\n"
           "Ext Address: '1a2b3c4d5e6f7081'\r\n"
           "IP6 Address List:\r\n"
           "    - fdde:ad00:beef:0:0:ff:fe00:6c05\r\n"
           f"    - {OLD}\r\n"
           f"    - {OMR}\r\n"
           "    - fdde:ad00:beef:0:1:2:3:4\r\n"
           "    - fe80:0:0:0:c87a:3480:8b66:e461\r\n"
           f"    - {OLD}\r\n"
           "Done\r\n")
d = ta.parse_diag(DIAG_OK)
assert d["answered"] and d["ext"] == "1a2b3c4d5e6f7081" and len(d["addresses"]) == 5, d   # sans doublon
assert d["addresses"][1] == OLD
assert ta.parse_diag("Done\r\n") == {"answered": False, "ext": None, "rloc16": None, "addresses": []}
assert ta.parse_diag("DIAG_GET.rsp/ans from fd00::1: 00\r\nExt Address: 'AABBCCDDEEFF0011'\r\nDone\r\n") == \
    {"answered": True, "ext": "aabbccddeeff0011", "rloc16": None, "addresses": []}
assert ta.parse_diag("DIAG_GET.rsp/ans from fd00::1: 00\r\nExt Address: 'aabbccddeeff0011'\r\nRloc16: 0x3000\r\n"
                     "IP6 Address List:\r\n    - fd00::5\r\nDone\r\n") == \
    {"answered": True, "ext": "aabbccddeeff0011", "rloc16": 0x3000, "addresses": ["fd00::5"]}
# adresse etendue : majuscules, 0x, espaces
assert ta.parse_ext(" 0x1A2B3C4D5E6F7081 ") == "1a2b3c4d5e6f7081"
for bad in ("1a2b3c4d5e6f708", "1a2b3c4d5e6f70811", "zz7a34808b66e461", "", None):
    try:
        ta.parse_ext(bad)
        raise AssertionError(bad)
    except ValueError:
        pass

TARGET, ML = "1a2b3c4d5e6f7081", "fdde:ad00:beef:0:2a3b:4c5d:6e7f:8091"
ADDR = "fdde:ad00:beef::ff:fe00:6c05"


def child_table(*rows):
    head = ("| ID  | RLOC16 | Timeout    | Age        | LQ In | C_VN |R|D|N|Ver|CSL|QMsgCnt|Suprvsn| Extended MAC     |\r\n"
            "+-----+--------+------------+------------+-------+------+-+-+-+---+---+-------+-------+------------------+\r\n")
    return head + "".join(f"|   1 | {r} |        240 |         44 |     3 |  237 |1|1|1|  3| 0 |     0 |   129 | {e} |\r\n"
                          for r, e in rows) + "Done\r\n"


def neighbor_table(*rows):
    head = ("| Role | RLOC16 | Age | Avg RSSI | Last RSSI | LQ In |R|D|N| Extended MAC     | Version |\r\n"
            "+------+--------+-----+----------+-----------+-------+-+-+-+------------------+---------+\r\n")
    return head + "".join(f"|    C | {r} |  12 |      -60 |       -61 |     3 |1|1|1| {e} |       4 |\r\n"
                          for r, e in rows) + "Done\r\n"


def router_table(*rows):
    head = ("| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |\r\n"
            "+----+--------+----------+-----------+-------+--------+-----+------------------+------+\r\n")
    return head + "".join(f"| 45 | {r} |       63 |         0 |     3 |      3 |   5 | {e} |    1 |\r\n"
                          for r, e in rows) + "Done\r\n"


assert ta.parse_table(child_table(("0xfc01", "3c4d5e6f70819203"), ("0x6c05", TARGET.upper()))) == \
    {"3c4d5e6f70819203": 0xFC01, TARGET: 0x6C05}
assert ta.parse_table(neighbor_table(("0x6c00", TARGET))) == {TARGET: 0x6C00}
assert ta.parse_table(router_table(("0x0800", "6f70819203142536"), ("0xb800", "5e6f708192031425"))) == \
    {"6f70819203142536": 0x0800, "5e6f708192031425": 0xB800}
assert ta.parse_table("Done\r\n") == {} and ta.parse_table(child_table()) == {}
assert ta.parse_table("| junk |\r\n| 1 | 2 |\r\nDone\r\n") == {}     # sans en-tete reconnu
try:
    ta.parse_table("Error 35: InvalidCommand\r\n")
    raise AssertionError("Error")
except RuntimeError:
    pass
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
assert ta.classify([OLD, OMR], MLP, (P, "fd00:eeee:ffff:1::/64")) == ([OLD, OMR], [])


HELP_OLD = "child\r\nneighbor\r\nping\r\nrouter\r\nDone\r\n"
HELP_MD = "child\r\nmeshdiag\r\nneighbor\r\nping\r\nrouter\r\nDone\r\n"


class Clk:
    now = 10000.0

    def __call__(self):
        return self.now


class FakeOtbr:
    """ot-ctl en lecture : ipaddr rloc, ping, networkdiagnostic get. Note tout ce qui est lance."""
    def __init__(self, clk):
        self.clk, self.calls, self.timeouts, self.running = clk, [], [], True
        self.ping_out, self.diag_out, self.ping_takes, self.diag_takes = PING_OK, DIAG_OK, 0, 0
        self.tables, self.table_takes = {}, 0     # "child" / "neighbor" / "router" -> sortie ot-ctl
        self.ml_out = "Done\r\n"                  # reponse a `networkdiagnostic get <ML-EID> 0 1 8`
        self.help_out = HELP_OLD                  # reponse a `help` (sans meshdiag par defaut)
        self.topology_out, self.childtables, self.scan_takes = "Done\r\n", {}, 0   # meshdiag
        self.topo_kids_out = "Done\r\n"           # `meshdiag topology children`
        self.child_diag, self.child_takes = {}, 0  # `networkdiagnostic get <RLOC enfant> 0` : adresse -> sortie
        self.script = {}                          # commande -> sorties a rendre d'abord (ex. "" : ignoree)
        self.attempts = []

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
        queued = self.script.get(" ".join(cmd[1:]))
        if queued:
            self.attempts.append(" ".join(cmd[1:]))
            return 0, queued.pop(0)
        if cmd[1:] == ["meshdiag", "topology", "children"]:
            self.clk.now += self.scan_takes
            return 0, self.topo_kids_out
        if cmd[1:3] == ["networkdiagnostic", "get"] and cmd[4:] == ["0"]:     # un enfant, TLV 0 seul
            self.clk.now += self.child_takes
            return 0, self.child_diag.get(cmd[3], "Error 28: ResponseTimeout\r\n")
        if cmd[1:3] == ["ipaddr", "rloc"]:
            return 0, "fdde:ad00:beef:0:0:ff:fe00:fc00\r\nDone\r\n"
        if cmd[1] == "ping":
            self.clk.now += self.ping_takes
            return 0, self.ping_out
        if cmd[1:3] == ["networkdiagnostic", "get"]:
            self.clk.now += self.diag_takes
            return 0, self.ml_out if cmd[4:] == ["0", "1", "8"] else self.diag_out
        if cmd[1] in ("child", "neighbor", "router") and cmd[2:] == ["table"]:
            self.clk.now += self.table_takes
            return 0, self.tables.get(cmd[1], "Done\r\n")
        if cmd[1:] == ["help"]:
            return 0, self.help_out
        if cmd[1:3] == ["meshdiag", "topology"] and len(cmd) == 3:
            self.clk.now += self.scan_takes
            return 0, self.topology_out
        if cmd[1:3] == ["meshdiag", "childtable"] and len(cmd) == 4:
            self.clk.now += self.scan_takes
            return 0, self.childtables.get(cmd[3], "Done\r\n")
        raise AssertionError(f"command not allowed in a diagnostic: {cmd}")


def make_diag(**kw):
    clk = Clk()
    otbr = FakeOtbr(clk)
    an = ta.Anchor({"omr_prefix": P}, docker=otbr, clock=clk)
    an.favored, an.favored_prf = P, "high"
    an.sleeps = []
    an.sleep = lambda s: (an.sleeps.append(s), setattr(clk, "now", clk.now + s))   # le temps passe sans attendre
    out = []
    dg = ta.Diag(an, lambda topic, res: out.append((topic, res)), clock=clk, spawn=kw.get("spawn", lambda fn: fn()))
    return clk, otbr, dg, out


def req(**kw):
    return json.dumps(dict({"id": "r1", "rloc16": "0x6C05", "ext": "1a2b3c4d5e6f7081", "ping": True}, **kw))


# cas normal : une node restee sur l'ancien prefixe
clk, otbr, dg, out = make_diag()
dg.submit(req())
assert len(out) == 1 and out[0][0] == "thread_anchor/diag/result/r1"
r = out[0][1]
assert r["id"] == "r1" and r["rloc16"] == "0x6C05" and r["rloc_address"] == "fdde:ad00:beef::ff:fe00:6c05"
assert r["ext"] == "1a2b3c4d5e6f7081" and r["ping"] == {"ok": True, "rtt_ms": 12.0} and r["error"] is None
assert len(r["addresses"]) == 5 and r["omr_addresses"] == [OMR] and r["other_prefix_addresses"] == [OLD]
assert datetime.fromisoformat(r["at"]).tzinfo is not None
assert otbr.calls == [["ipaddr", "rloc"], ["ping", "fdde:ad00:beef::ff:fe00:6c05", "16", "1"],
                      ["networkdiagnostic", "get", "fdde:ad00:beef::ff:fe00:6c05", "0", "8"]], otbr.calls
assert all(1 <= tm <= ta.DIAG_TIMEOUT_S for tm in otbr.timeouts), otbr.timeouts
assert not dg.running
# rien d'ecrit sur le border router : aucune des commandes n'est une ecriture
assert not [c for c in otbr.calls if c[0] not in ("ipaddr", "ping", "networkdiagnostic")]
assert r["rloc16_from"] == "request"
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
assert out[0][1]["error"] is None and out[0][1]["ext"] == "1a2b3c4d5e6f7081"
clk, otbr, dg, out = make_diag()
dg.submit(req(ext="0011223344556677"))
assert "1a2b3c4d5e6f7081" in out[0][1]["error"] and "0011223344556677" in out[0][1]["error"] and out[0][1]["addresses"]
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
for raw in ("pas du json", "null", "[]", "{}", json.dumps({"id": "", "rloc16": "0x6c05"}),
            json.dumps({"id": "a/b", "rloc16": "0x6c05"}), json.dumps({"id": "a#", "rloc16": "0x6c05"})):
    dg.submit(raw)
assert out == [] and otbr.calls == []
dg.submit(json.dumps({"id": "x", "rloc16": "zz"}))
dg.submit(json.dumps({"id": "y"}))
assert [(tp, r["error"][:14]) for tp, r in out] == [("thread_anchor/diag/result/x", "invalid rloc16"),
                                                    ("thread_anchor/diag/result/y", "rloc16, ext or")]
assert otbr.calls == [] and "ping" in out[0][1] and out[0][1]["addresses"] == []
for i, extra in enumerate(({"ext": "pas-une-ext"}, {"ext": "1a2b3c4d5e6f708"}, {"mleid": "pas-une-adresse"},
                           {"mleid": "fdde:ad00:beef::/64"}, {"rloc16": "zz", "ext": TARGET})):
    dg.submit(json.dumps(dict({"id": f"bad{i}"}, **extra)))
    assert out[-1][0] == f"thread_anchor/diag/result/bad{i}" and out[-1][1]["error"].split(":")[0].startswith("invalid"), out[-1]
assert otbr.calls == []

# ---- RLOC16 inconnu : retrouve depuis l'adresse etendue (ext) ou l'ML-EID (mleid)


def ask(otbr_setup=None, **kw):
    """Une demande sans rloc16 ; rend (resultat, appels ot-ctl, otbr)."""
    clk, otbr, dg, out = make_diag()
    if otbr_setup:
        otbr_setup(otbr)
    dg.submit(json.dumps(dict({"id": "t"}, **kw)))
    assert len(out) == 1 and not dg.running, out
    return out[0][1], otbr.calls, otbr


PING = ["ping", ADDR, "16", "1"]
DIAG = ["networkdiagnostic", "get", ADDR, "0", "8"]
OWN = ["ipaddr", "rloc"]
# dans la table des enfants : les autres tables ne sont pas lues ; ext en majuscules, ping et diagnostic suivent
r, calls, _ = ask(lambda o: o.tables.update(child=child_table(("0xfc01", "3c4d5e6f70819203"), ("0x6c05", TARGET))),
                  ext=TARGET.upper())
assert r["rloc16"] == "0x6c05" and r["rloc16_from"] == "child table" and r["rloc_address"] == ADDR and r["error"] is None
assert calls == [OWN, ["child", "table"], PING, DIAG], calls
assert r["ping"]["ok"] and r["ext"] == TARGET and r["other_prefix_addresses"] == [OLD] and len(r["addresses"]) == 5
# pas chez les enfants : table des voisins, puis table des routeurs
r, calls, _ = ask(lambda o: o.tables.update(child=child_table(("0xfc01", "3c4d5e6f70819203")),
                                            neighbor=neighbor_table(("0x6c05", TARGET))), ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["rloc16_from"] == "neighbor table" and r["error"] is None
assert calls == [OWN, ["child", "table"], ["neighbor", "table"], PING, DIAG], calls
r, calls, _ = ask(lambda o: o.tables.update(router=router_table(("0x6c05", TARGET))), ext=TARGET, ping=False)
assert r["rloc16_from"] == "router table" and r["ping"] is None and r["error"] is None
assert calls == [OWN, ["child", "table"], ["neighbor", "table"], ["router", "table"], DIAG], calls
# introuvable : « not found », ni ping ni diagnostic, rien d'autre que des lectures de tables
r, calls, _ = ask(ext=TARGET)
assert r["error"] == "not found" and r["rloc16"] is None and r["rloc16_from"] is None and r["rloc_address"] is None
assert r["ping"] is None and r["addresses"] == [] and r["ext"] is None
assert calls == [OWN, ["child", "table"], ["neighbor", "table"], ["router", "table"], ["help"]], calls
assert [(s["step"], s["result"], s["rows"]) for s in r["search"]] == [
    ("child table", "not_found", 0), ("neighbor table", "not_found", 0), ("router table", "not_found", 0),
    ("meshdiag", "not_supported", None)], r["search"]
assert r["alive"] is None and r["parent"] is None
# une table en erreur (OpenThread ancien…) : on passe a la suivante
r, calls, _ = ask(lambda o: o.tables.update(child="Error 35: InvalidCommand\r\n",
                                            router=router_table(("0x6c05", TARGET))), ext=TARGET)
assert r["rloc16_from"] == "router table" and r["error"] is None
# la meme adresse etendue ne vaut qu'une fois : le premier trouve gagne
r, _, _ = ask(lambda o: o.tables.update(child=child_table(("0x1111", TARGET)), router=router_table(("0x2222", TARGET))),
              ext=TARGET)
assert r["rloc16"] == "0x1111" and r["rloc_address"] == "fdde:ad00:beef::ff:fe00:1111"
# ML-EID : une seule requete donne ext, RLOC16 et adresses ; pas de seconde requete, pas de table
ML_OK = DIAG_OK.replace("Ext Address: '1a2b3c4d5e6f7081'\r\n", "Ext Address: '1a2b3c4d5e6f7081'\r\nRloc16: 0x6c05\r\n")
ML_CALL = ["networkdiagnostic", "get", ML, "0", "1", "8"]
r, calls, _ = ask(lambda o: setattr(o, "ml_out", ML_OK), mleid=ML, ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["rloc16_from"] == "mleid" and r["error"] is None and r["rloc_address"] == ADDR
assert calls == [OWN, ML_CALL, PING], calls
assert r["ext"] == TARGET and len(r["addresses"]) == 5 and r["other_prefix_addresses"] == [OLD]
# ML-EID seul (ext pas fourni) ; l'ancien nom ml_eid reste accepte
r, calls, _ = ask(lambda o: setattr(o, "ml_out", ML_OK), mleid=ML.upper())
assert r["rloc16_from"] == "mleid" and calls[1] == ML_CALL and r["error"] is None
r, calls, _ = ask(lambda o: setattr(o, "ml_out", ML_OK), ml_eid=ML)
assert r["rloc16_from"] == "mleid"
# l'adresse repond avec une autre ext : plus la bonne node -> les tables
r, calls, _ = ask(lambda o: (setattr(o, "ml_out", ML_OK.replace(TARGET, "0011223344556677")),
                             o.tables.update(child=child_table(("0x6c05", TARGET)))), mleid=ML, ext=TARGET)
assert r["rloc16_from"] == "child table" and r["error"] is None and calls == [OWN, ML_CALL, ["child", "table"], PING, DIAG]
# ML-EID sans reponse : tables si ext, sinon « not found »
r, calls, _ = ask(lambda o: o.tables.update(neighbor=neighbor_table(("0x6c05", TARGET))), mleid=ML, ext=TARGET)
assert r["rloc16_from"] == "neighbor table" and calls[:4] == [OWN, ML_CALL, ["child", "table"], ["neighbor", "table"]]
r, calls, _ = ask(mleid=ML)
assert r["error"] == "not found" and calls == [OWN, ML_CALL], calls
# ML-EID hors du prefixe mesh-local : refuse, aucune requete
r, calls, _ = ask(mleid="2001:db8::1", ext=TARGET)
assert r["error"] == "mleid is not in the mesh-local prefix" and calls == [OWN] and r["rloc16_from"] is None
# rloc16 fourni : il l'emporte, rien n'est cherche
r, calls, _ = ask(lambda o: setattr(o, "ml_out", ML_OK), rloc16="0x6C05", mleid=ML, ext=TARGET)
assert r["rloc16_from"] == "request" and calls == [OWN, PING, DIAG], calls
# delai de 15 s : lire les tables a tout pris
r, calls, _ = ask(lambda o: setattr(o, "table_takes", 16), ext=TARGET)
assert r["error"] == "timeout (15 s)" and calls == [OWN, ["child", "table"]] and r["rloc16_from"] is None
# limites : « too soon » par adresse etendue (dix secondes), « busy » comme avant
clk, otbr, dg, out = make_diag()
otbr.tables["child"] = child_table(("0x6c05", TARGET))
dg.submit(json.dumps({"id": "u1", "ext": TARGET}))
dg.submit(json.dumps({"id": "u2", "ext": TARGET.upper()}))
assert out[0][1]["error"] is None and out[1][1]["error"] == "too soon", out
clk.now += 10
dg.submit(json.dumps({"id": "u3", "ext": TARGET}))
assert out[2][1]["error"] is None and out[2][1]["rloc16"] == "0x6c05"
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
clk.now += 2                                      # 11 s apres la premiere demande de 6C05
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

# ---- journal des etapes (`search`), `alive`, et etape meshdiag
TOPO = ("id:02 rloc16:0x0800 ext-addr:6f70819203142536 ver:4 - me - leader\r\n"
        "   3-links:{ 22 45 }\r\n"
        "id:22 rloc16:0x5800 ext-addr:1111111111111111 ver:4\r\n"
        "   3-links:{ 02 }\r\n"
        "id:45 rloc16:0x6c00 ext-addr:2222222222222222 ver:4\r\n"
        "   3-links:{ 02 46 }\r\n"
        "id:46 rloc16:0xb800 ext-addr:3333333333333333 ver:4\r\n"
        "   3-links:{ 45 }\r\n"
        "Done\r\n")
CT_5800 = ("rloc16:0x5801 ext-addr:aaaaaaaaaaaaaaaa ver:4\r\n    timeout:120 age:36 supvn:129 q-msg:0\r\n"
           "    rx-on:no type:mtd full-net:no\r\nDone\r\n")
CT_6C00 = ("rloc16:0x6c01 ext-addr:2b3c4d5e6f708192 ver:4\r\n    timeout:120 age:19 supvn:129 q-msg:0\r\n"
           f"rloc16:0x6c05 ext-addr:{TARGET} ver:4\r\n    timeout:120 age:2 supvn:129 q-msg:0\r\n"
           "    rx-on:no type:mtd full-net:no\r\n    csl - sync:no period:0 timeout:0 channel:0\r\nDone\r\n")
assert ta.parse_help(HELP_MD) == {"child", "meshdiag", "neighbor", "ping", "router", "Done"} and "meshdiag" not in ta.parse_help(HELP_OLD)
topo = ta.parse_topology(TOPO)
assert [(r["rloc16"], r["ext"], r["me"]) for r in topo] == [
    (0x0800, "6f70819203142536", True), (0x5800, "1111111111111111", False),
    (0x6C00, "2222222222222222", False), (0xB800, "3333333333333333", False)], topo
assert ta.parse_childtable(CT_6C00) == {"2b3c4d5e6f708192": 0x6C01, TARGET: 0x6C05}
assert ta.parse_childtable("Done\r\n") == {} and ta.parse_topology("Done\r\n") == []
# avec « children » : les enfants n'ont pas d'ext, ils ne sont pas pris pour des routeurs
assert len(ta.parse_topology(TOPO.replace("   3-links:{ 22 45 }\r\n", "   children:\r\n       rloc16:0x0803 lq:0, mode:rn\r\n"))) == 4
for bad in ("Error 5: Busy\r\n", "Error 28: ResponseTimeout\r\n"):
    for fn in (ta.parse_topology, ta.parse_childtable, ta.parse_help):
        try:
            fn(bad)
            raise AssertionError((fn, bad))
        except RuntimeError:
            pass


def scan_diag(**kw):
    clk, otbr, dg, out = make_diag(**kw)
    otbr.help_out, otbr.topology_out = HELP_MD, TOPO
    otbr.childtables = {"0x5800": CT_5800, "0x6c00": CT_6C00}
    return clk, otbr, dg, out


def one(dg, out, **kw):
    n = len(out)
    dg.submit(json.dumps(dict({"id": f"q{n}"}, **kw)))
    assert len(out) == n + 1 and not dg.running
    return out[-1][1]


def steps(r):
    return [(s["step"], s["result"]) for s in r["search"]]


TABLES = [["child", "table"], ["neighbor", "table"], ["router", "table"]]
CT = lambda r: ["meshdiag", "childtable", r]  # noqa: E731
# l'ancien parent est donne (RLOC16 d'un enfant ou du routeur) : interroge en premier, arret des qu'on trouve
clk, otbr, dg, out = scan_diag()
r = one(dg, out, ext=TARGET, routers=["0x6C05", "0x9c00", "zz", None, 5000000])   # 0x9c00 n'est pas un routeur : ignore
assert r["rloc16"] == "0x6c05" and r["rloc16_from"] == "meshdiag" and r["parent"] == "0x6c00" and r["error"] is None
assert otbr.calls == [OWN, *TABLES, ["help"], ["meshdiag", "topology"], CT("0x6c00"), PING, DIAG], otbr.calls
assert steps(r) == [("child table", "not_found"), ("neighbor table", "not_found"), ("router table", "not_found"),
                    ("meshdiag topology", "not_found"), ("meshdiag childtable 0x6c00", "found"),
                    ("old RLOC16 0x6c05", "old_listed")], r["search"]
assert r["search"][5]["detail"] == "0x6c00"       # l'ancien RLOC16 est encore liste sous son routeur
assert r["search"][3]["rows"] == 4 and r["search"][4]["rows"] == 2 and r["search"][4]["detail"] == "0x6c05"
# `alive` : la liste d'un parent ne prouve rien, c'est la reponse du ping ou du diagnostic qui compte
assert r["alive"] is True and r["ping"]["ok"] and r["ext"] == TARGET
# sans indice : ordre de la topologie (le border router lui-meme est saute), le dernier routeur n'est pas interroge
clk, otbr, dg, out = scan_diag()
r = one(dg, out, ext=TARGET)
assert otbr.calls[4:9] == [["help"], ["meshdiag", "topology"], CT("0x5800"), CT("0x6c00"), PING], otbr.calls
assert not [c for c in otbr.calls if c == CT("0xb800") or c == CT("0x0800")]
# la node est un routeur : trouvee dans la topologie, pas de childtable ; pas de parent
clk, otbr, dg, out = scan_diag()
otbr.diag_out = DIAG_OK.replace(TARGET, "3333333333333333")
r = one(dg, out, ext="3333333333333333")
assert r["rloc16"] == "0xb800" and r["rloc16_from"] == "meshdiag" and r["parent"] is None and r["error"] is None
assert [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]] == [] and r["alive"] is True
# `alive` faux : trouvee dans une table mais ni ping ni diagnostic ne repondent
clk, otbr, dg, out = scan_diag()
otbr.ping_out, otbr.diag_out = PING_LOST, "Done\r\n"
r = one(dg, out, ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["alive"] is False and r["ping"] == {"ok": False, "rtt_ms": None}
assert r["error"] == "no answer to the network diagnostic" and r["parent"] == "0x6c00"
# ping perdu mais diagnostic repondu : vivante ; ping non demande et diagnostic muet : pas vivante
clk, otbr, dg, out = scan_diag()
otbr.ping_out = PING_LOST
assert one(dg, out, ext=TARGET)["alive"] is True
clk, otbr, dg, out = scan_diag()
otbr.diag_out = "Done\r\n"
r = one(dg, out, ext=TARGET, ping=False)
assert r["alive"] is False and r["ping"] is None
# une autre node repond a ce RLOC16 : pas la bonne, donc pas vivante
clk, otbr, dg, out = scan_diag()
otbr.diag_out = DIAG_OK.replace(TARGET, "0011223344556677")
r = one(dg, out, ext=TARGET)
assert r["alive"] is False and "0011223344556677" in r["error"]
# rloc16 fourni : meme champ `alive`, search vide ; refuse ou introuvable : null
clk, otbr, dg, out = make_diag()
r = one(dg, out, rloc16="0x6C05")
assert r["alive"] is True and r["search"] == [] and r["parent"] is None
assert one(dg, out, ext="zz")["alive"] is None and one(dg, out, mleid=ML)["alive"] is None
# introuvable partout : tous les routeurs interroges ; 5 min entre deux balayages
clk, otbr, dg, out = scan_diag()
r = one(dg, out, ext="4444444444444444")
assert r["error"] == "not found" and r["alive"] is None and r["rloc16_from"] is None and r["rloc16"] is None
assert [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]] == [CT("0x5800"), CT("0x6c00"), CT("0xb800")]
assert steps(r)[-1] == ("meshdiag childtable 0xb800", "not_found") and otbr.calls.count(["help"]) == 1
clk.now += 11                                   # seconde demande : la limite de 10 s par node est passee
n = len(otbr.calls)
r = one(dg, out, ext="4444444444444444")
assert otbr.calls[n:] == [OWN, *TABLES] and steps(r)[-1] == ("meshdiag", "too_soon") and r["search"][-1]["detail"] == 11
clk.now += 300
n = len(otbr.calls)
r = one(dg, out, ext="4444444444444444")
assert ["meshdiag", "topology"] in otbr.calls[n:] and otbr.calls.count(["help"]) == 1      # help retenu
# dernier balayage relu sans trafic : la node y avait ete trouvee
clk, otbr, dg, out = scan_diag()
assert one(dg, out, ext=TARGET)["parent"] == "0x6c00"
clk.now += 11
n = len(otbr.calls)
r = one(dg, out, ext=TARGET)
assert r["rloc16_from"] == "meshdiag" and r["parent"] == "0x6c00" and r["error"] is None
assert [c for c in otbr.calls[n:] if c[0] == "meshdiag" or c == ["help"]] == []
assert steps(r)[-1] == ("meshdiag", "found")
# meshdiag absent : « not supported » sans erreur, `help` pose une fois par demarrage de l'OTBR
clk, otbr, dg, out = make_diag()
r = one(dg, out, ext=TARGET)
assert r["error"] == "not found" and steps(r)[-1] == ("meshdiag", "not_supported") and otbr.calls.count(["help"]) == 1
clk.now += 11
one(dg, out, ext=TARGET)
assert otbr.calls.count(["help"]) == 1
dg.anchor.started_at = "2026-11-18T03:00:00Z"            # l'OTBR a redemarre : on redemande
clk.now += 11
one(dg, out, ext=TARGET)
assert otbr.calls.count(["help"]) == 2
# `scan: false` : rien de meshdiag, pas meme `help`
clk, otbr, dg, out = scan_diag()
r = one(dg, out, ext=TARGET, scan=False)
assert r["error"] == "not found" and not [c for c in otbr.calls if c[0] == "meshdiag" or c == ["help"]], otbr.calls
assert steps(r) == [("child table", "not_found"), ("neighbor table", "not_found"), ("router table", "not_found")]
# `help` en erreur : on reessaiera ; topologie en erreur : le balayage compte quand meme (5 min)
clk, otbr, dg, out = scan_diag()
otbr.help_out = "Error 1: Failed\r\n"
r = one(dg, out, ext="4444444444444444")
assert steps(r)[-1] == ("meshdiag help", "error") and r["error"] == "not found"
otbr.help_out = HELP_MD
otbr.topology_out = "Error 35: InvalidCommand\r\n"
clk.now += 11
r = one(dg, out, ext="4444444444444444")
assert steps(r)[-1] == ("meshdiag topology", "error") and "InvalidCommand" in r["search"][-1]["detail"]
clk.now += 11
r = one(dg, out, ext="4444444444444444")
assert steps(r)[-1] == ("meshdiag", "too_soon")
# un routeur occupe (Busy) arrete le balayage ; un routeur qui ne repond pas laisse passer au suivant
clk, otbr, dg, out = scan_diag()
otbr.childtables["0x5800"] = "Error 5: Busy\r\n"
r = one(dg, out, ext=TARGET)
assert r["error"] == "not found" and steps(r)[-1] == ("meshdiag childtable 0x5800", "error")
assert [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]] == [CT("0x5800")]
clk, otbr, dg, out = scan_diag()
otbr.childtables["0x5800"] = "Error 28: ResponseTimeout\r\n"
r = one(dg, out, ext=TARGET)
assert r["error"] is None and r["parent"] == "0x6c00" and ("meshdiag childtable 0x5800", "error") in steps(r)
# budget de 90 s : le balayage s'arrete, la demande finit « not found » (ce n'est pas une erreur de delai)
clk, otbr, dg, out = scan_diag()
otbr.scan_takes = 40
r = one(dg, out, ext="4444444444444444")
assert r["error"] == "not found" and steps(r)[-1] == ("meshdiag childtable 0xb800", "stopped")
assert [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]] == [CT("0x5800"), CT("0x6c00")]
assert r["search"][-1]["detail"] == "time budget used"
# trouve apres 80 s de balayage : le ping et le diagnostic ont leurs 15 s a eux, pas de delai
clk, otbr, dg, out = scan_diag()
otbr.scan_takes = 40
otbr.childtables["0x5800"] = CT_5800
r = one(dg, out, ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["error"] is None and r["alive"] is True and clk.now > 10000 + 90
# pas d'ext : pas de meshdiag (rien a chercher) ; ML-EID sans reponse ni ext : introuvable sans `help`
clk, otbr, dg, out = scan_diag()
r = one(dg, out, mleid=ML)
assert r["error"] == "not found" and [c for c in otbr.calls if c[0] == "meshdiag" or c == ["help"]] == []

# ---- routeurs qui ne repondent pas a `meshdiag childtable` : leurs enfants par `meshdiag topology children`
TIMEOUT = "Error 28: ResponseTimeout\r\n"
KIDS_OUT = ("id:02 rloc16:0x0800 ext-addr:6f70819203142536 ver:4 - me - leader\r\n   children:\r\n"
            "       rloc16:0x0803 lq:0, mode:rn\r\n"
            "id:22 rloc16:0x5800 ext-addr:1111111111111111 ver:4\r\n   children:\r\n"
            "       rloc16:0x5801 lq:3, mode:rn\r\n"
            "id:45 rloc16:0x6c00 ext-addr:2222222222222222 ver:4\r\n   children:\r\n"
            "       rloc16:0x6c01 lq:3, mode:rdn\r\n       rloc16:0x6c05 lq:2, mode:rn\r\n"
            "       rloc16:0x6c06 lq:1, mode:rn\r\n"
            "id:46 rloc16:0xb800 ext-addr:3333333333333333 ver:4\r\n   children:\r\nDone\r\n")
assert ta.parse_topology_children(KIDS_OUT) == (
    {0x0800: [0x0803], 0x5800: [0x5801], 0x6C00: [0x6C01, 0x6C05, 0x6C06], 0xB800: []}, None)
assert ta.parse_topology_children("Done\r\n") == ({}, None)
# partiel : ce qui est lu avant une erreur est garde ; sans routeur, les lignes d'enfants ne comptent pas
part = ta.parse_topology_children(KIDS_OUT.replace("Done\r\n", "Error 28: ResponseTimeout\r\n"))
assert part[0][0x6C00] == [0x6C01, 0x6C05, 0x6C06] and part[1] == "Error 28: ResponseTimeout"
assert ta.parse_topology_children("       rloc16:0x0803 lq:0, mode:rn\r\nDone\r\n") == ({}, None)
assert ta.parse_topology_children("Error 5: Busy\r\n") == ({}, "Error 5: Busy")
CHILD_A = "fdde:ad00:beef::ff:fe00:6c01"
CHILD_B = "fdde:ad00:beef::ff:fe00:6c05"      # la node cherchee
CHILD_C = "fdde:ad00:beef::ff:fe00:6c06"
KID = lambda a, e: f"DIAG_GET.rsp/ans from {a}: 00\r\nExt Address: '{e}'\r\nDone\r\n"  # noqa: E731
OTHER = "5555555555555555"


def kids_diag(**kw):
    """Le routeur 0x6c00 ne repond pas a childtable ; ses enfants repondent (6C01 : une autre node)."""
    clk, otbr, dg, out = scan_diag(**kw)
    otbr.childtables["0x6c00"] = TIMEOUT
    otbr.topo_kids_out = KIDS_OUT
    otbr.child_diag = {CHILD_A: KID(CHILD_A, OTHER), CHILD_B: KID(CHILD_B, TARGET)}
    return clk, otbr, dg, out


TKIDS = ["meshdiag", "topology", "children"]
ND = lambda a: ["networkdiagnostic", "get", a, "0"]  # noqa: E731
# le routeur de la demande se tait : ses enfants d'abord, l'ancien RLOC16 en premier (une demande par enfant)
clk, otbr, dg, out = kids_diag()
r = one(dg, out, ext=TARGET, routers=["0x6C06"])
assert r["rloc16"] == "0x6c05" and r["rloc16_from"] == "meshdiag" and r["parent"] == "0x6c00" and r["error"] is None
assert otbr.calls == [OWN, *TABLES, ["help"], ["meshdiag", "topology"], CT("0x6c00"), TKIDS, ND(CHILD_C), ND(CHILD_A),
                      ND(CHILD_B), PING, DIAG], otbr.calls
assert steps(r) == [("child table", "not_found"), ("neighbor table", "not_found"), ("router table", "not_found"),
                    ("meshdiag topology", "not_found"), ("meshdiag childtable 0x6c00", "error"),
                    ("meshdiag topology children", "kids"), ("children of 0x6c00", "found"),
                    ("old RLOC16 0x6c06", "old_listed")], steps(r)
assert r["search"][5]["rows"] == 4 and r["search"][6]["detail"] == "0x6c05" and r["search"][6]["rows"] == 3
assert r["alive"] is True and r["ext"] == TARGET
# sans indice : les routeurs qui repondent d'abord, puis les enfants du routeur muet, par RLOC16 croissant
clk, otbr, dg, out = kids_diag()
r = one(dg, out, ext=TARGET)
assert otbr.calls[4:] == [["help"], ["meshdiag", "topology"], CT("0x5800"), CT("0x6c00"), CT("0xb800"), TKIDS,
                          ND(CHILD_A), ND(CHILD_B), PING, DIAG], otbr.calls
assert r["rloc16"] == "0x6c05" and r["parent"] == "0x6c00" and r["alive"] is True
# les enfants qui ont repondu sont retenus 5 minutes : une autre node de la liste est retrouvee sans trafic
clk.now += 11
n = len(otbr.calls)
r = one(dg, out, ext=OTHER, ping=False)
assert r["rloc16"] == "0x6c01" and r["parent"] == "0x6c00" and steps(r)[-1] == ("meshdiag", "found")
assert [c for c in otbr.calls[n:] if c[0] == "meshdiag" or c == ["help"] or c[-1:] == ["0"]] == [], otbr.calls[n:]
# introuvable : « 3 interroges, 2 ont repondu » ; l'ancien RLOC16 n'est plus liste
clk, otbr, dg, out = kids_diag()
r = one(dg, out, ext="4444444444444444", routers=["0x6c07"])
assert r["error"] == "not found" and r["rloc16"] is None and r["alive"] is None
assert steps(r)[5:7] == [("meshdiag topology children", "kids"), ("children of 0x6c00", "asked")], steps(r)
assert steps(r)[-1] == ("old RLOC16 0x6c07", "old_gone")
assert r["search"][6]["rows"] == 3 and r["search"][6]["detail"] == 2 and r["search"][-1]["detail"] == "0x6c00"
# le routeur de la demande est traite tout de suite, les autres routeurs ensuite (leur childtable repond)
assert steps(r)[7:9] == [("meshdiag childtable 0x5800", "not_found"), ("meshdiag childtable 0xb800", "not_found")]
# le muet (6C06) est redemande une fois en fin de balayage, lui seul
assert [c for c in otbr.calls if c[0] == "networkdiagnostic"] == [ND(CHILD_A), ND(CHILD_B), ND(CHILD_C), ND(CHILD_C)]
assert ("children of 0x6c00 (again)", "asked") in steps(r) and r["silent_children"] == [{"rloc16": "0x6c06", "parent": "0x6c00"}]
assert steps(r)[-2:] == [("children of 0x6c00 (again)", "asked"), ("old RLOC16 0x6c07", "old_gone")]
# un enfant qui ne repond pas, ou dont la sortie est vide, ne casse rien
clk, otbr, dg, out = kids_diag()
otbr.child_diag[CHILD_A] = ""
r = one(dg, out, ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["error"] is None
# la liste des enfants manque (routeur absent de la sortie, ou commande en erreur) : dit, sans ancien RLOC16
clk, otbr, dg, out = kids_diag()
otbr.topo_kids_out = KIDS_OUT.replace("id:45 rloc16:0x6c00", "id:99 rloc16:0xd000")
r = one(dg, out, ext=TARGET, routers=["0x6c05"])
assert r["error"] == "not found" and steps(r)[5:7] == [("meshdiag topology children", "kids"), ("children of 0x6c00", "no_list")]
assert not [s for s in steps(r) if s[0].startswith("old")]
clk, otbr, dg, out = kids_diag()
otbr.childtables["0x5800"] = TIMEOUT                    # deux routeurs muets : une seule `topology children`
otbr.topo_kids_out = TIMEOUT
r = one(dg, out, ext=TARGET)
assert otbr.calls.count(TKIDS) == 1 and r["error"] == "not found"
assert ("meshdiag topology children", "error") in steps(r) and ("children of 0x6c00", "no_list") in steps(r)
assert ("children of 0x5800", "no_list") in steps(r) and not [s for s in steps(r) if s[0].startswith("old")]
# `topology children` partiel : ce qui est lu avant l'erreur sert
clk, otbr, dg, out = kids_diag()
otbr.topo_kids_out = KIDS_OUT.replace("Done\r\n", "Error 28: ResponseTimeout\r\n")
r = one(dg, out, ext=TARGET)
assert r["rloc16"] == "0x6c05"
assert [s["detail"] for s in r["search"] if s["step"] == "meshdiag topology children"] == [" (Error 28: ResponseTimeout)"]
# routeurs qui repondent tous a childtable : pas de `topology children`
clk, otbr, dg, out = scan_diag()
one(dg, out, ext="4444444444444444")
assert TKIDS not in otbr.calls
# budget de 90 s : l'interrogation des enfants s'arrete, sans erreur de delai
clk, otbr, dg, out = kids_diag()
otbr.child_takes = 50
r = one(dg, out, ext="4444444444444444")
assert r["error"] == "not found" and steps(r)[-1] == ("children of 0x6c00", "stopped")
assert [c for c in otbr.calls if c[0] == "networkdiagnostic"] == [ND(CHILD_A), ND(CHILD_B)]
# Busy : on n'insiste pas, pas de `topology children`
clk, otbr, dg, out = kids_diag()
otbr.childtables["0x5800"] = "Error 5: Busy\r\n"
r = one(dg, out, ext=TARGET)
assert r["error"] == "not found" and TKIDS not in otbr.calls
# la lecture seule reste vraie : que des lectures
assert not [c for c in otbr.calls if c[0] not in ("ipaddr", "ping", "networkdiagnostic", "help", "child", "neighbor", "router", "meshdiag")]

# ---- 0.1.6 : les enfants muets sont dits, redemandes une fois, et le balayage est repris la ou il s'est arrete
# sans balayage de reseau : champ present, vide
clk, otbr, dg, out = make_diag()
assert one(dg, out, rloc16="0x6C05")["silent_children"] == []
# les muets sont dits (RLOC16 et routeur), sans indice : pas de seconde demande
clk, otbr, dg, out = kids_diag()
r = one(dg, out, ext="4444444444444444")
assert r["silent_children"] == [{"rloc16": "0x6c06", "parent": "0x6c00"}] and "(again)" not in " ".join(s["step"] for s in r["search"])
assert [c for c in otbr.calls if c[0] == "networkdiagnostic"] == [ND(CHILD_A), ND(CHILD_B), ND(CHILD_C)]
# routeur nomme : ses muets sont redemandes une fois en fin de balayage (un enfant endormi repond a son reveil)
clk, otbr, dg, out = kids_diag()
otbr.child_diag = {CHILD_A: KID(CHILD_A, OTHER)}
otbr.script["networkdiagnostic get " + CHILD_C + " 0"] = [TIMEOUT, KID(CHILD_C, TARGET)]
r = one(dg, out, ext=TARGET, routers=["0x6c00"])
assert r["rloc16"] == "0x6c06" and r["parent"] == "0x6c00" and r["rloc16_from"] == "meshdiag", r
assert [s for s in steps(r) if s[0].startswith("children")] == [("children of 0x6c00", "asked"), ("children of 0x6c00 (again)", "found")]
assert [c for c in otbr.calls if c[:2] == ["networkdiagnostic", "get"] and c[3:] == ["0"] and len(c) == 4] == \
    [ND(CHILD_A), ND(CHILD_B), ND(CHILD_C), ND(CHILD_B), ND(CHILD_C)]
assert r["silent_children"] == [{"rloc16": "0x6c05", "parent": "0x6c00"}]
# un nommé qui repond a la 2e fois : plus de muets, routeur complet
clk, otbr, dg, out = kids_diag()
otbr.child_diag = {CHILD_A: KID(CHILD_A, OTHER), CHILD_B: KID(CHILD_B, "7777777777777777")}
otbr.script["networkdiagnostic get " + CHILD_C + " 0"] = [TIMEOUT, KID(CHILD_C, "8888888888888888")]
r = one(dg, out, ext="4444444444444444", routers=["0x6c00"])
assert r["silent_children"] == [] and 0x6C00 in dg.done and r["error"] == "not found"
assert [s for s in steps(r) if s[0].startswith("children")] == [("children of 0x6c00", "asked"), ("children of 0x6c00 (again)", "asked")]


# 0.1.7 : la redemande des muets du routeur nomme passe AVANT les enfants des autres routeurs muets,
# meme quand ceux-ci useraient tout le budget (20 s par enfant : 3 + 2 demandes = 100 s, puis plus de temps)
clk, otbr, dg, out = kids_diag()
otbr.childtables["0x5800"] = TIMEOUT                    # un autre routeur muet, avec un enfant
otbr.child_diag = {CHILD_A: KID(CHILD_A, OTHER)}
otbr.child_takes = 20
r = one(dg, out, ext="4444444444444444", routers=["0x6c00"])
kid_steps = [s for s in steps(r) if s[0].startswith("children")]
assert kid_steps == [("children of 0x6c00", "asked"), ("children of 0x6c00 (again)", "asked"),
                     ("children of 0x5800", "stopped")], kid_steps
assert [c for c in otbr.calls if c[:2] == ["networkdiagnostic", "get"] and len(c) == 4] == \
    [ND(CHILD_A), ND(CHILD_B), ND(CHILD_C), ND(CHILD_B), ND(CHILD_C)]       # rien n'a ete demande sous 0x5800
assert r["silent_children"] == [{"rloc16": "0x6c05", "parent": "0x6c00"}, {"rloc16": "0x6c06", "parent": "0x6c00"}]

# 0.1.8 : `meshdiag topology` expire (il interroge tous les routeurs d'un coup) : la recherche continue,
# routeur par routeur, avec la table des routeurs deja lue et les routeurs de la demande
RTAB = ("| ID | RLOC16 | Next Hop | Path Cost | LQ In | LQ Out | Age | Extended MAC     | Link |\r\n"
        "+----+--------+----------+-----------+-------+--------+-----+------------------+------+\r\n"
        "| 22 | 0x5800 |       63 |         0 |     0 |      0 |  10 | 1111111111111111 |    1 |\r\n"
        "| 45 | 0x6c00 |       63 |         0 |     0 |      0 |  10 | 2222222222222222 |    1 |\r\n"
        "| 46 | 0xb800 |       63 |         0 |     0 |      0 |  10 | 3333333333333333 |    1 |\r\nDone\r\n")
# table des routeurs lue : les routeurs sont pris dedans, childtable un par un, puis les enfants du muet
clk, otbr, dg, out = kids_diag()
otbr.topology_out = TIMEOUT
otbr.tables["router"] = RTAB
r = one(dg, out, ext=TARGET)
assert r["rloc16"] == "0x6c05" and r["parent"] == "0x6c00" and r["rloc16_from"] == "meshdiag" and r["alive"] is True
assert steps(r) == [("child table", "not_found"), ("neighbor table", "not_found"), ("router table", "not_found"),
                    ("meshdiag topology", "error"), ("routers from the router table", "fallback"),
                    ("meshdiag childtable 0x5800", "not_found"), ("meshdiag childtable 0x6c00", "error"),
                    ("meshdiag childtable 0xb800", "not_found"), ("meshdiag topology children", "kids"),
                    ("children of 0x6c00", "found")], steps(r)
assert r["search"][4]["rows"] == 3 and r["search"][3]["detail"] == "Error 28: ResponseTimeout"
# routeurs de la demande seuls (table des routeurs vide) : le routeur nomme est lu tout de suite
clk, otbr, dg, out = kids_diag()
otbr.topology_out = TIMEOUT
r = one(dg, out, ext=TARGET, routers=["0x6c06"])
assert r["rloc16"] == "0x6c05" and r["parent"] == "0x6c00"
assert ("routers from the router table", "fallback") in steps(r) and r["search"][4]["rows"] == 1
assert [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]] == [CT("0x6c00")]
# ni table des routeurs ni indice : rien a interroger, on le dit sans inventer de routeur
clk, otbr, dg, out = kids_diag()
otbr.topology_out = TIMEOUT
r = one(dg, out, ext=TARGET)
assert r["error"] == "not found" and steps(r)[-1] == ("meshdiag topology", "error")
assert not [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]]
# Busy sur `topology` : un autre meshdiag tourne, on n'insiste pas (pas de reprise par routeur)
clk, otbr, dg, out = kids_diag()
otbr.topology_out = "Error 5: Busy\r\n"
otbr.tables["router"] = RTAB
r = one(dg, out, ext=TARGET)
assert r["error"] == "not found" and steps(r)[-1] == ("meshdiag topology", "error")
assert not [c for c in otbr.calls if c[:2] == ["meshdiag", "childtable"]]
# `topology` qui repond : pas de reprise par la table des routeurs
clk, otbr, dg, out = kids_diag()
otbr.tables["router"] = RTAB
r = one(dg, out, ext=TARGET)
assert ("routers from the router table", "fallback") not in steps(r) and r["rloc16"] == "0x6c05"
# le budget de 90 s tient aussi dans la reprise
clk, otbr, dg, out = kids_diag()
otbr.topology_out, otbr.scan_takes = TIMEOUT, 40
otbr.tables["router"] = RTAB
r = one(dg, out, ext="4444444444444444")
assert r["error"] == "not found" and ("meshdiag childtable 0xb800", "stopped") in steps(r), steps(r)


def partial_diag():
    """Premier balayage arrete par le budget de 90 s sous 0x6c00 : A et B ont repondu, C n'a pas ete demande."""
    clk, otbr, dg, out = kids_diag()
    otbr.child_diag[CHILD_B] = KID(CHILD_B, "7777777777777777")
    otbr.child_diag[CHILD_C] = KID(CHILD_C, "6666666666666666")
    otbr.child_takes = 50
    r = one(dg, out, ext="4444444444444444")
    assert steps(r)[-1] == ("children of 0x6c00", "stopped") and dg.partial and r["silent_children"] == []
    assert dg.done == {0x5800, 0xB800} and dg.silent == {}
    otbr.child_takes = 0
    otbr.calls.clear()
    return clk, otbr, dg, out


# reprise : routeurs deja connus et enfants deja repondus ne sont pas redemandes, `help` non plus
clk, otbr, dg, out = partial_diag()
clk.now += 301
r = one(dg, out, ext="6666666666666666")
assert r["rloc16"] == "0x6c06" and r["parent"] == "0x6c00" and ("children of 0x6c00", "found") in steps(r)
assert otbr.calls[:8] == [OWN, *TABLES, ["meshdiag", "topology"], CT("0x6c00"), TKIDS, ND(CHILD_C)], otbr.calls
assert CT("0x5800") not in otbr.calls and CT("0xb800") not in otbr.calls and ["help"] not in otbr.calls
assert ND(CHILD_A) not in otbr.calls and ND(CHILD_B) not in otbr.calls
# un enfant qui avait repondu a l'ecoute precedente est retrouve sans traffic, meme apres 5 minutes
clk, otbr, dg, out = partial_diag()
clk.now += 301
r = one(dg, out, ext="7777777777777777", ping=False)
assert r["rloc16"] == "0x6c05" and r["parent"] == "0x6c00" and steps(r)[-1] == ("meshdiag", "found"), steps(r)
assert not [c for c in otbr.calls if c[0] == "meshdiag" and c != ["meshdiag", "topology"]]
# un routeur nomme est relu meme s'il etait connu ; les autres connus restent sautes
clk, otbr, dg, out = partial_diag()
clk.now += 301
r = one(dg, out, ext="6666666666666666", routers=["0x5800"])
assert CT("0x5800") in otbr.calls and CT("0xb800") not in otbr.calls and r["rloc16"] == "0x6c06"
assert otbr.calls.index(CT("0x5800")) < otbr.calls.index(CT("0x6c00"))
# la reprise n'est que de 30 minutes : ensuite, tout est redemande
clk, otbr, dg, out = partial_diag()
clk.now += 1801
r = one(dg, out, ext="6666666666666666")
assert CT("0x5800") in otbr.calls and CT("0xb800") in otbr.calls and ND(CHILD_A) in otbr.calls
# le border router a redemarre : plus rien n'est repris
clk, otbr, dg, out = partial_diag()
clk.now += 301
dg.anchor.started_at = "2026-11-18T03:00:00Z"
r = one(dg, out, ext="6666666666666666")
assert ["help"] in otbr.calls and CT("0x5800") in otbr.calls and ND(CHILD_A) in otbr.calls
# un balayage qui est alle au bout avec tous les routeurs connus n'est pas repris : le suivant est complet
clk, otbr, dg, out = scan_diag()
one(dg, out, ext="4444444444444444")
assert dg.partial is False and dg.done == {0x5800, 0x6C00, 0xB800}
clk.now += 301
n = len(otbr.calls)
one(dg, out, ext="4444444444444444")
assert [c for c in otbr.calls[n:] if c[:2] == ["meshdiag", "childtable"]] == [CT("0x5800"), CT("0x6c00"), CT("0xb800")]
# des muets qui restent : le balayage reste a reprendre, et ne redemande que eux
clk, otbr, dg, out = kids_diag()
one(dg, out, ext="4444444444444444")
assert dg.partial is True and dg.silent == {0x6C00: [0x6C06]}
clk.now += 301
otbr.calls.clear()
r = one(dg, out, ext="4444444444444444")
assert [c for c in otbr.calls if c[:2] == ["networkdiagnostic", "get"] and c[3:] == ["0"] and len(c) == 4] == [ND(CHILD_C)]
assert CT("0x5800") not in otbr.calls and r["silent_children"] == [{"rloc16": "0x6c06", "parent": "0x6c00"}]

# ---- une sortie vide d'ot-ctl = commande ignoree (une autre est en attente) : redemandee, jamais un echec
RETRY = ["ping", ADDR, "16", "1"]
clk, otbr, dg, out = make_diag()
otbr.script["ping " + ADDR + " 16 1"] = ["", ""]
dg.submit(req())
assert out[0][1]["ping"] == {"ok": True, "rtt_ms": 12.0} and out[0][1]["alive"] is True and out[0][1]["error"] is None
assert dg.anchor.sleeps == [3, 3] and otbr.attempts == ["ping " + ADDR + " 16 1"] * 2 and otbr.calls.count(RETRY) == 3
# vide a chaque fois : pas « ping ok:false », une erreur precise, `alive` inconnu
clk, otbr, dg, out = make_diag()
otbr.script["ping " + ADDR + " 16 1"] = ["", "", ""]
dg.submit(req())
r = out[0][1]
assert r["ping"] is None and r["alive"] is None and r["error"] == "ot-ctl: no answer (another command pending?)", r
assert dg.anchor.sleeps == [3, 3] and otbr.calls.count(RETRY) == 3 and not dg.running
assert not [c for c in otbr.calls if c[0] == "networkdiagnostic"]
# diagnostic vide : meme chose
clk, otbr, dg, out = make_diag()
otbr.script["networkdiagnostic get " + ADDR + " 0 8"] = ["", "", ""]
dg.submit(req())
assert out[0][1]["error"] == "ot-ctl: no answer (another command pending?)" and out[0][1]["ping"]["ok"] is True
# une table vide a chaque fois : etape en erreur, la recherche continue
r, calls, _ = ask(lambda o: (o.script.update({"child table": ["", "", ""]}), o.tables.update(router=router_table(("0x6c05", TARGET)))),
                  ext=TARGET)
assert r["rloc16_from"] == "router table" and r["search"][0]["result"] == "error" and "no answer" in r["search"][0]["detail"]
# le delai de la demande compte aussi les attentes : 15 s de nouvelles tentatives = delai
clk, otbr, dg, out = make_diag()
dg.anchor.sleep = lambda s: setattr(clk, "now", clk.now + 20)
otbr.script["ping " + ADDR + " 16 1"] = ["", "", ""]
dg.submit(req())
assert out[0][1]["error"] == "timeout (15 s)" and otbr.calls.count(RETRY) == 1, out[0][1]

# ---- le verrou : une seule commande a la fois, pris par commande (pas pour tout un balayage)
import threading  # noqa: E402
import time  # noqa: E402


class Slow(FakeDocker):
    """Compte les commandes en cours en meme temps."""
    def __init__(self):
        super().__init__()
        self.inflight = self.most = 0
        self.mu = threading.Lock()

    def exec(self, container, cmd):
        with self.mu:
            self.inflight += 1
            self.most = max(self.most, self.inflight)
        time.sleep(0.005)
        try:
            return super().exec(container, cmd)
        finally:
            with self.mu:
                self.inflight -= 1


ds = Slow()
an_s = ta.Anchor({"omr_prefix": P}, docker=ds, clock=ds.clock)
ds.now = time.time()


def hammer(fn):
    for _ in range(8):
        fn()


workers = [threading.Thread(target=hammer, args=(f,)) for f in (
    lambda: an_s.otctl("br", "omrprefix"), lambda: an_s.otctl("br", "omrconfig"), an_s.check,
    lambda: an_s.otctl("br", "omrprefix"))]
for w in workers:
    w.start()
for w in workers:
    w.join()
assert ds.most == 1, ds.most        # sans verrou, les quatre se chevauchent
# le verrou est rendu a chaque commande, meme en erreur : la suivante passe
an_s.docker.running = False
for _ in range(2):
    try:
        an_s.otctl("br", "omrconfig")
        raise AssertionError("no error")
    except ta.DockerError:
        pass
an_s.docker.running = True
assert an_s.otctl("br", "omrconfig").endswith("Done\r\n")
# la file : premier arrive, premier servi ; une attente trop longue rend la main sans bloquer les autres
g = ta.Gate()
assert g.acquire(1)
t0 = time.monotonic()
assert not g.acquire(0.05) and time.monotonic() - t0 >= 0.04 and g.queue == []
g.release()
assert g.acquire(1)
g.release()
order = []


def waiter(name):
    assert g.acquire(5)
    order.append(name)
    time.sleep(0.01)
    g.release()


assert g.acquire(1)
ths = []
for nm in ("a", "b", "c"):
    th = threading.Thread(target=waiter, args=(nm,))
    th.start()
    ths.append(th)
    time.sleep(0.05)       # arrivent dans cet ordre
g.release()
for th in ths:
    th.join()
assert order == ["a", "b", "c"], order

# ---- ancrage : sortie vide = commande ignoree ; 3 essais, puis un message precis (pas « injoignable »)
NOANS = "ot-ctl: no answer (another command pending?)"


def anchor_with(**kw):
    dd = FakeDocker()
    aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
    aa.sleeps = []
    aa.sleep = lambda s: (aa.sleeps.append(s), setattr(dd, "now", dd.now + s))
    return dd, aa


# la premiere sortie est vide (un meshdiag etait en attente), la suivante bonne : rien a signaler
dd, aa = anchor_with()
dd.script["br omrconfig"] = [""]
aa.check()
assert aa.public()["error"] is None and aa.public()["enforced"] and aa.sleeps == [3] and dd.attempts == ["br omrconfig"]
assert "error" not in [k for k, _ in aa.events], aa.events
# vide a chaque fois : message precis, ni « injoignable » ni « unexpected answer », ce qui etait lu reste
dd.now += 30
dd.script["br omrconfig"] = ["", "", ""]
aa.events, aa.sleeps = [], []
aa.check()
assert aa.public()["error"] == NOANS and aa.sleeps == [3, 3]
assert [k for k, _ in aa.events] == ["error"] and "injoignable" not in aa.public()["error"] and "unreachable" not in NOANS
assert aa.public()["enforced"] and aa.public()["mode"] == "custom" and aa.public()["favored"] == P
for _ in range(2):                                    # dit une fois
    dd.now += 10
    dd.script["br omrconfig"] = ["", "", ""]
    aa.check()
assert [k for k, _ in aa.events] == ["error"] and aa.public()["error"] == NOANS
# ensuite : retour a la normale, et plus vite (10 s) tant qu'il y a une erreur
dd.now += 10
assert aa.due()
aa.check()
assert aa.public()["error"] is None
# une ecriture ignoree ne passe jamais pour reussie
dd, aa = anchor_with()
dd.script[f"br omrconfig custom {P} high"] = ["", "", ""]
aa.check()
assert aa.public()["error"] == NOANS and aa.public()["applied"] == 0 and dd.config == "auto" and not aa.public()["enforced"]
assert not [k for k, _ in aa.events if k == "anchor_set"]
dd.now += 10
aa.check()
assert aa.public()["error"] is None and aa.public()["applied"] == 1 and aa.public()["enforced"]
# une ecriture ignoree une fois, puis prise : appliquee une seule fois
dd, aa = anchor_with()
dd.script[f"br omrconfig custom {P} high"] = [""]
aa.check()
assert aa.public()["error"] is None and aa.public()["applied"] == 1 and aa.sleeps == [3]
# une vraie erreur n'est pas redemandee : « Error … » sort tout de suite
dd, aa = anchor_with()
dd.old = True
aa.check()
assert "InvalidCommand" in aa.public()["error"] and aa.sleeps == []

# ---- rôle Thread de l'OTBR : lu et affiche, jamais change
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
aa.check()
st = aa.public()
assert st["thread_role"] == "child" and st["thread_routers"] == 3 and dd.reads == ["state", "router list"], (st, dd.reads)
assert not [c for c in dd.calls if "state" in c or "router" in c]            # rien d'ecrit : seulement `br ...`
dd.role, dd.router_ids = "leader", "0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21"
dd.now += 30
assert aa.check() and aa.public()["thread_role"] == "leader" and aa.public()["thread_routers"] == 22
dd.role, dd.router_ids, dd.reads = "detached", "", []                      # sans reseau : pas de nombre, pas de lecture
dd.now += 30
aa.check()
assert aa.public()["thread_role"] == "detached" and aa.public()["thread_routers"] is None and dd.reads == ["state"]
dd.role = "disabled"
dd.now += 30
aa.check()
assert aa.public()["thread_role"] == "disabled" and aa.public()["thread_routers"] is None
dd.role, dd.router_ids = "router", "8 24"
dd.now += 30
aa.check()
assert aa.public()["thread_role"] == "router" and aa.public()["thread_routers"] == 2
# role illisible : inconnu (None), l'ancrage n'en souffre pas
dd.role = "bizarre"
dd.now += 30
aa.check()
assert aa.public()["thread_role"] is None and aa.public()["thread_routers"] is None and aa.public()["error"] is None
assert aa.public()["enforced"]
# `state` ignore (sorties vides) : la derniere valeur reste, pas d'erreur
dd.role = "child"
dd.now += 30
aa.check()
aa.sleep = lambda s: None
dd.script["state"] = ["", "", ""]
dd.now += 30
aa.check()
assert aa.public()["thread_role"] == "child" and aa.public()["error"] is None
# border router arrete : plus de role
dd.running = False
dd.now += 30
aa.check()
assert aa.public()["thread_role"] is None and aa.public()["thread_routers"] is None and aa.public()["error"]
# anciens champs toujours la, memes noms
for key in ("otbr_addon", "wanted", "preference", "mode", "current", "current_preference", "enforced", "favored",
            "favored_preference", "local", "applied", "applied_at", "otbr_started_at", "error", "anchored_since", "followed"):
    assert key in aa.public(), key
# observation seule (sans omr_prefix) : le role est lu aussi
d0b = FakeDocker()
a0b = ta.Anchor({}, docker=d0b, clock=d0b.clock)
a0b.check()
assert a0b.public()["thread_role"] == "child" and d0b.calls == ["br omrconfig", "br omrprefix"]

# ---- 0.1.9 : lien du border router avec son parent (lectures locales, rien d'ecrit, pas de trafic radio)
assert ta.parse_parent("Done\r\n") is None
for fn in (ta.parse_parent, ta.parse_neighbors, ta.parse_router_rows):
    try:
        fn("Error 13: InvalidState\r\n")          # une erreur d'ot-ctl se leve, la lecture laisse cette partie de cote
        raise AssertionError(fn)
    except RuntimeError:
        pass
assert ta.parse_parent(LINK_OUT["parent"]) == {"rloc16": 0x3400, "ext": "5a6b7c8d9e0f1a2b", "lq_in": 3, "lq_out": 2, "age": 17}
assert ta.parse_parent("Ext Address: 0x5A6B7C8D9E0F1A2B\r\nRloc: 0x3400\r\nDone\r\n")["ext"] == "5a6b7c8d9e0f1a2b"
nb = ta.parse_neighbors(LINK_OUT["neighbor table"])
assert [(n["rloc16"], n["role"], n["rssi_avg"], n["rssi_last"], n["age"]) for n in nb] == [
    (0x3400, "R", -62, -64, 17), (0x5800, "R", -48, -47, 3), (0x9C00, "R", -71, -70, 9),
    (0xB800, "R", -55, -58, 20), (0x6C0A, "C", -40, -41, 30)]
assert ta.parse_neighbors("Done\r\n") == [] and ta.parse_neighbors("| a | b |\r\n| x | y |\r\n") == []
assert ta.parse_router_rows(LINK_OUT["router table"]) == {
    0x3400: {"lq_in": 3, "lq_out": 2, "path_cost": 0, "ext": "5a6b7c8d9e0f1a2b"},
    0x5800: {"lq_in": 3, "lq_out": 3, "path_cost": 0, "ext": "1111111111111111"}}
assert ta.parse_counters(LINK_OUT["counters mle"], ta.MLE_KEYS) == {
    "role_detached": 4, "role_child": 5, "role_router": 0, "role_leader": 0, "attach_attempts": 6,
    "partition_id_changes": 1, "better_partition_attach_attempts": 0, "parent_changes": 3}
assert ta.parse_counters(LINK_OUT["counters mac"], ta.MAC_KEYS) == {     # 0.1.10 : lignes en retrait comprises
    "tx_total": 1034, "tx_ack_requested": 900, "tx_acked": 880, "tx_retry": 21, "tx_err_cca": 4, "tx_err_abort": 1,
    "tx_err_busy_channel": 2, "rx_total": 2210, "rx_err_no_frame": 6, "rx_err_unknown_neighbor": 0, "rx_err_sec": 0,
    "rx_err_fcs": 7}
assert "tx_unicast" not in ta.parse_counters(LINK_OUT["counters mac"], ta.MAC_KEYS)       # seules les cles voulues
assert ta.parse_counters("TxTotal: 5\r\nTxRetry: 2\r\n", ta.MAC_KEYS) == {"tx_total": 5, "tx_retry": 2}   # a plat aussi
assert ta.parse_counters("Done\r\n", ta.MAC_KEYS) == {}
LINK_CMDS = ["rloc16", "parent", "neighbor table", "router table", "counters mle", "counters mac"]
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
aa.check()
lk = aa.public()["thread_link"]
assert dd.link_reads == LINK_CMDS, dd.link_reads
assert not [c for c in dd.calls if c.split()[0] != "br"]                      # aucune ecriture, que des `br ...`
assert lk["rloc16"] == "0x6c05" and lk["routers_heard"] == 4 and datetime.fromisoformat(lk["read_at"]).tzinfo
assert lk["parent"] == {"rloc16": "0x3400", "ext": "5a6b7c8d9e0f1a2b", "lq_in": 3, "lq_out": 2, "quality": "medium",
                        "age": 17, "rssi_avg": -62, "rssi_last": -64, "in_neighbor_table": True}
assert lk["parent_history"] == [] and lk["counters"]["mac"]["tx_err_busy_channel"] == 2
# les 3 meilleurs routeurs entendus, par RSSI moyen ; l'enfant (0x6c0a) n'en est pas un
assert [(b["rloc16"], b["rssi_avg"], b["is_parent"]) for b in lk["best"]] == [
    ("0x5800", -48, False), ("0xb800", -55, False), ("0x3400", -62, True)]
assert lk["best"][0]["lq_in"] == 3 and lk["best"][0]["lq_out"] == 3 and lk["best"][1]["lq_in"] is None
assert lk["counters"]["mle"]["parent_changes"] == 3 and lk["counters"]["mac"]["tx_retry"] == 21
assert json.dumps(aa.public())            # publiable en JSON
# au plus une lecture par minute
dd.now += 30
aa.check()
assert dd.link_reads == LINK_CMDS
dd.now += 31
aa.check()
assert dd.link_reads == LINK_CMDS * 2
# les valeurs qui bougent a chaque lecture (age, compteurs) ne font pas « changer » l'etat ; le parent, si
dd.link_out["counters mac"] = dd.link_out["counters mac"].replace("TxRetry: 21", "TxRetry: 40")
dd.link_out["parent"] = dd.link_out["parent"].replace("Age: 17", "Age: 40")
dd.now += 61
assert not aa.check() and aa.public()["thread_link"]["counters"]["mac"]["tx_retry"] == 40
dd.link_out["parent"] = dd.link_out["parent"].replace("Rloc: 3400", "Rloc: 5800")
dd.now += 61
assert aa.check() and aa.public()["thread_link"]["parent"]["rloc16"] == "0x5800"
assert ("parent_changed", "Parent of the border router changed: 0x3400 -> 0x5800") in aa.events
# lien faible : la qualite se lit sur le plus mauvais des deux sens
dd.link_out["parent"] = dd.link_out["parent"].replace("Link Quality Out: 2", "Link Quality Out: 1")
dd.now += 61
aa.check()
assert aa.public()["thread_link"]["parent"]["quality"] == "weak"
# une partie illisible est laissee de cote, les autres sont lues
dd.link_out["parent"] = "Error 13: InvalidState\r\n"
dd.link_out["counters mle"] = "Error 35: InvalidCommand\r\n"
dd.now += 61
aa.check()
lk = aa.public()["thread_link"]
assert lk["parent"] is None and lk["counters"] == {"mac": lk["counters"]["mac"]} and len(lk["best"]) == 3
# commande ignoree (sorties vides) : la derniere lecture reste, pas d'erreur
aa.sleep = lambda s: None
dd.script["counters mle"] = ["", "", ""]
dd.now += 61
aa.check()
assert aa.public()["thread_link"] == lk and aa.public()["error"] is None
# routeur : pas de `parent` (il n'en a pas) ; sans reseau (detached) : lu aussi ; desactive : rien
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
dd.role = "router"
aa.check()
assert "parent" not in dd.link_reads and aa.public()["thread_link"]["parent"] is None and aa.public()["thread_link"]["best"]
dd.role = "disabled"
dd.link_reads.clear()
dd.now += 61
aa.check()
assert aa.public()["thread_link"] is None and dd.link_reads == []
# le role a change : lecture tout de suite, sans attendre la minute
dd.role = "child"
dd.now += 1
aa.check()
assert dd.link_reads == LINK_CMDS and aa.public()["thread_link"]["parent"]["rloc16"] == "0x3400"
# border router arrete : plus de lien
dd.running = False
dd.now += 61
aa.check()
assert aa.public()["thread_link"] is None and aa.public()["error"]
# anciens champs toujours la
for key in ("thread_role", "thread_routers", "followed", "anchored_since"):
    assert key in aa.public(), key

# ---- 0.1.10 : RSSI du parent (par RLOC16, puis par ext, sinon dit absent) et historique des changements de parent
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
dd.link_out["parent"] = dd.link_out["parent"].replace("Rloc: 3400", "Rloc: 3800")     # RLOC16 inconnu, ext connue
aa.check()
par = aa.public()["thread_link"]["parent"]
assert par["rloc16"] == "0x3800" and par["rssi_avg"] == -62 and par["rssi_last"] == -64 and par["in_neighbor_table"] is True
# parent absent de la table des voisins : RSSI null, dit, et la table brute part dans le journal en mode debug
dd.link_out["parent"] = ("Ext Addr: 9999999999999999\r\nRloc: 7400\r\nLink Quality In: 3\r\nLink Quality Out: 3\r\n"
                         "Age: 5\r\nDone\r\n")
logged = []


class Catch(logging.Handler):
    def emit(self, record):
        logged.append(record.getMessage())


catch, old_level = Catch(), ta.LOG.level
ta.LOG.addHandler(catch)
ta.LOG.setLevel(logging.DEBUG)
dd.now += 61
aa.check()
ta.LOG.removeHandler(catch)
ta.LOG.setLevel(old_level)
par = aa.public()["thread_link"]["parent"]
assert par["rssi_avg"] is None and par["rssi_last"] is None and par["in_neighbor_table"] is False and par["quality"] == "good"
assert [m for m in logged if "not in the neighbor table" in m and "0x5800" in m and "0x7400" in m], logged
# table des voisins illisible : on ne sait pas (None), ce n'est pas « absent »
dd.link_out["neighbor table"] = "Error 13: InvalidState\r\n"
dd.now += 61
aa.check()
assert aa.public()["thread_link"]["parent"]["in_neighbor_table"] is None and aa.public()["thread_link"]["routers_heard"] is None

# historique : un changement = {at, from, to}, les 10 derniers seulement, gardes d'un redemarrage a l'autre
hist = os.path.join(tempfile.mkdtemp(), "parent_history.json")
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock, history=hist)
parents = [f"{0x9400 + 0x400 * i:04x}" for i in range(12)]      # 9400, 9800, 9c00, a000…


def read_with(a, d, rloc):
    d.link_out["parent"] = dd.link_out["parent"].split("Rloc: ")[0] + f"Rloc: {rloc}\r\n" + \
        dd.link_out["parent"].split("\r\n", 2)[2]
    d.now += 61
    a.check()
    return a.public()["thread_link"]["parent_history"]


assert read_with(aa, dd, parents[0]) == []          # le premier parent vu n'est pas un changement
assert read_with(aa, dd, parents[0]) == []
h = read_with(aa, dd, parents[1])
assert len(h) == 1 and h[0]["from"] == "0x9400" and h[0]["to"] == "0x9800" and datetime.fromisoformat(h[0]["at"]).tzinfo
assert read_with(aa, dd, parents[1]) == h           # pas de nouvelle ligne tant que le parent ne change pas
for rl in parents[2:]:
    h = read_with(aa, dd, rl)
assert len(h) == 10 and h[0]["from"] == "0x9800", h
assert h[-1]["from"] == "0x" + parents[-2] and h[-1]["to"] == "0x" + parents[-1]
assert [e for e in aa.events if e[0] == "parent_changed"].__len__() == 11
# un detachement puis le meme parent : pas un changement ; un autre parent : un changement
dd.role = "detached"
dd.now += 61
aa.check()
assert aa.public()["thread_link"]["parent"] is None and len(aa.public()["thread_link"]["parent_history"]) == 10
# redemarrage de l'add-on : l'historique et le dernier parent sont relus
aa2 = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock, history=hist)
assert aa2.last_parent == "0x" + parents[-1] and aa2.parent_log == h
dd.role = "child"
assert read_with(aa2, dd, parents[-1]) == h                       # meme parent qu'avant le redemarrage
assert read_with(aa2, dd, "7400")[-1]["from"] == "0x" + parents[-1] and len(aa2.parent_log) == 10
# fichier absent ou abime : historique vide, pas d'erreur
with open(hist, "w", encoding="utf-8") as f:
    f.write("{pas du json")
aa3 = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock, history=hist)
assert aa3.parent_log == [] and aa3.last_parent is None
assert ta.Anchor({"omr_prefix": P}, docker=dd, history=os.path.join(tempfile.mkdtemp(), "none.json")).parent_log == []
# sans fichier (tests, observation) : en memoire seulement
assert ta.Anchor({}, docker=dd).history is None

# ---- 0.1.11 : ce que l'add-on apprend des nodes, garde et publie (thread_anchor/children), sans lecture en plus
clk = Clk()
cpath = os.path.join(tempfile.mkdtemp(), "children.json")
ch = ta.Children(cpath, clock=clk)
assert not ch.due() and ch.public()["nodes"] == {} and ch.public()["count"] == 0     # rien appris : rien a publier
ch.note("zz", 0x6C05, 0x6C00, "child", "diagnostic")                                  # ext invalide : ignoree
ch.note(None, 0x6C05, 0x6C00, "child", "diagnostic")
assert ch.nodes == {} and not ch.changed
ch.note(TARGET.upper(), 0x6C05, 0x6C00, "child", "childtable")                         # l'ext est mise en minuscules
ch.note("2b3c4d5e6f708192", 0x5800, None, "router", "topology", {"rssi_avg": -55, "lq_in": 3})
pub = ch.public()
assert pub["version"] == 1 and pub["count"] == 2 and list(pub["nodes"]) == sorted(pub["nodes"])
assert datetime.fromisoformat(pub["updated"]).tzinfo
assert pub["nodes"][TARGET] == {"rloc16": "0x6c05", "parent": "0x6c00", "role": "child", "source": "childtable",
                                "read_at": pub["updated"]}, pub["nodes"][TARGET]
assert pub["nodes"]["2b3c4d5e6f708192"]["parent"] is None and pub["nodes"]["2b3c4d5e6f708192"]["role"] == "router"
assert pub["nodes"]["2b3c4d5e6f708192"]["signal"] == {"rssi_avg": -55, "lq_in": 3, "toward": "otbr"}   # signal vers l'OTBR
assert "signal" not in pub["nodes"][TARGET]                                           # pas de signal inventé
assert ch.due()
ch.published()
assert not ch.due() and os.path.exists(cpath)
# la meme chose revue plus tard : read_at rafraichi, rien a publier ; un autre parent : a publier
clk.now += 100
ch.note(TARGET, 0x6C05, 0x6C00, "child", "diagnostic")
assert not ch.due() and ch.nodes[TARGET]["source"] == "diagnostic" and ch.nodes[TARGET]["read_at"] != pub["updated"]
ch.note(TARGET, 0x5801, 0x5800, "child", "childtable")
assert ch.due()
ch.published()
# battement : republiee apres CHILDREN_S meme sans changement
clk.now += ta.CHILDREN_S - 1
assert not ch.due()
clk.now += 2
assert ch.due()
ch.published()
# gardee d'un redemarrage a l'autre ; fichier abime : vide ; entree trop ancienne : retiree
ch2 = ta.Children(cpath, clock=clk)
assert ch2.nodes == ch.nodes and ch2.seen == ch.seen
clk.now += ta.CHILDREN_KEEP_S + 1
ch2.note("3c4d5e6f70819203", 0x5801, 0x5800, "child", "diagnostic")           # celle-ci est fraiche
assert sorted(ch2.public()["nodes"]) == ["3c4d5e6f70819203"] and ch2.due()
with open(cpath, "w", encoding="utf-8") as f:
    f.write("{pas du json")
assert ta.Children(cpath, clock=clk).nodes == {} and ta.Children(None).nodes == {}

# alimentation par la recherche meshdiag : routeurs (topology), enfants (childtable), enfant qui repond (diagnostic)
clk, otbr, dg, out = scan_diag()
one(dg, out, ext=TARGET)
kn = dg.anchor.children.nodes
assert kn["1111111111111111"]["role"] == "router" and kn["1111111111111111"]["source"] == "topology"
assert kn["1111111111111111"]["rloc16"] == "0x5800" and kn["1111111111111111"]["parent"] is None
assert kn["aaaaaaaaaaaaaaaa"] == {**kn["aaaaaaaaaaaaaaaa"], "rloc16": "0x5801", "parent": "0x5800", "role": "child",
                                  "source": "childtable"}
assert kn["2b3c4d5e6f708192"]["parent"] == "0x6c00" and kn["2b3c4d5e6f708192"]["source"] == "childtable"
assert kn[TARGET] == {**kn[TARGET], "rloc16": "0x6c05", "parent": "0x6c00", "role": "child", "source": "diagnostic"}
assert dg.anchor.children.due() and not [c for c in otbr.calls if c[0] not in (
    "ipaddr", "ping", "networkdiagnostic", "help", "child", "neighbor", "router", "meshdiag")]      # rien en plus
# enfant d'un routeur muet : retrouve par `networkdiagnostic get`, parent = son routeur
clk, otbr, dg, out = kids_diag()
one(dg, out, ext=TARGET)
assert dg.anchor.children.nodes[OTHER]["parent"] == "0x6c00" and dg.anchor.children.nodes[OTHER]["rloc16"] == "0x6c01"
assert dg.anchor.children.nodes[TARGET]["parent"] == "0x6c00" and dg.anchor.children.nodes[TARGET]["source"] == "diagnostic"
# les tables de l'OTBR : routeurs de `router table` ; enfants de `child table` seulement si l'OTBR est routeur
clk, otbr, dg, out = make_diag()
otbr.tables["router"] = router_table(("0x6c00", "7777777777777777"))
otbr.tables["child"] = child_table(("0x0803", "8888888888888888"))
one(dg, out, ext="9999999999999999", scan=False)
kn = dg.anchor.children.nodes
assert kn["7777777777777777"] == {**kn["7777777777777777"], "rloc16": "0x6c00", "parent": None, "role": "router",
                                  "source": "router table"}
assert "8888888888888888" not in kn                            # l'OTBR (enfant ou inconnu) n'a pas d'enfant : pas de parent a dire
clk, otbr, dg, out = make_diag()
otbr.tables["child"] = child_table(("0x0803", "8888888888888888"))
dg.anchor.own_rloc16 = 0x0800                                  # l'OTBR est routeur : il est le parent de ses enfants
clk.now += 20
one(dg, out, ext="9999999999999999", scan=False)
assert dg.anchor.children.nodes["8888888888888888"] == {**dg.anchor.children.nodes["8888888888888888"],
    "rloc16": "0x0803", "parent": "0x0800", "role": "child", "source": "child table"}
# une node qui repond au diagnostic : RLOC16 d'enfant -> parent = RLOC16 & 0xFC00 ; RLOC16 de routeur -> pas de parent
clk, otbr, dg, out = make_diag()
one(dg, out, rloc16="0x6C05")
assert dg.anchor.children.nodes[TARGET] == {**dg.anchor.children.nodes[TARGET], "rloc16": "0x6c05", "parent": "0x6c00",
                                            "role": "child", "source": "diagnostic"}
clk, otbr, dg, out = make_diag()
one(dg, out, rloc16="0x5800")
assert dg.anchor.children.nodes[TARGET] == {**dg.anchor.children.nodes[TARGET], "rloc16": "0x5800", "parent": None, "role": "router"}
# sans reponse du diagnostic : rien n'est appris
clk, otbr, dg, out = make_diag()
otbr.diag_out = "Done\r\n"
one(dg, out, rloc16="0x6C05")
assert dg.anchor.children.nodes == {}

# alimentation par la lecture periodique du lien (tables deja lues : pas de commande en plus)
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
aa.check()
assert dd.link_reads == LINK_CMDS                               # les memes 6 lectures qu'avant la 0.1.11
kn = aa.children.nodes
assert kn["5a6b7c8d9e0f1a2b"] == {"rloc16": "0x3400", "parent": None, "role": "router", "source": "neighbor table",
                                  "read_at": kn["5a6b7c8d9e0f1a2b"]["read_at"],
                                  "signal": {"rssi_avg": -62, "rssi_last": -64, "lq_in": 3, "lq_out": 2, "toward": "otbr"}}
assert kn["1111111111111111"]["signal"] == {"rssi_avg": -48, "rssi_last": -47, "lq_in": 3, "lq_out": 3, "toward": "otbr"}
assert kn["2222222222222222"]["signal"] == {"rssi_avg": -71, "rssi_last": -70, "toward": "otbr"}   # pas dans la table des routeurs
assert "4444444444444444" not in kn and sorted(kn) == ["1111111111111111", "2222222222222222", "3333333333333333", "5a6b7c8d9e0f1a2b"]
# l'OTBR est routeur : ses enfants ont l'OTBR pour parent ; un routeur de la table des routeurs non entendu est note aussi
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
dd.role = "router"
dd.link_out["rloc16"] = "6c00\r\nDone\r\n"
dd.link_out["router table"] = dd.link_out["router table"].replace(
    "Done\r\n", "| 31 | 0x7800 |       63 |         0 |     2 |      1 |   4 | 6666666666666666 |    1 |\r\nDone\r\n")
aa.check()
kn = aa.children.nodes
assert kn["4444444444444444"] == {**kn["4444444444444444"], "rloc16": "0x6c0a", "parent": "0x6c00", "role": "child"}
assert kn["6666666666666666"] == {**kn["6666666666666666"], "rloc16": "0x7800", "parent": None, "source": "router table",
                                  "signal": {"lq_in": 2, "lq_out": 1, "toward": "otbr"}}
# border router arrete : ce qui est appris reste (c'est un registre, pas un etat)
n_known = len(aa.children.nodes)
dd.running = False
dd.now += 61
aa.check()
assert len(aa.children.nodes) == n_known and aa.public()["thread_link"] is None

# ---- 0.1.12 : variation horaire des compteurs du lien (LinkStats), capteurs et sujet thread_anchor/link_stats
H = 3600                                          # une heure
BASE = 1000 * H                                   # un instant sur une frontiere d'heure
MAC1 = {"tx_total": 1000, "tx_ack_requested": 900, "tx_acked": 880, "tx_retry": 0, "tx_err_cca": 10, "tx_err_abort": 40,
        "tx_err_busy_channel": 10, "rx_total": 2000, "rx_err_sec": 5, "rx_err_fcs": 0, "rx_err_no_frame": 0,
        "rx_err_unknown_neighbor": 0}
MLE1 = {"role_detached": 4, "role_child": 4, "role_router": 0, "parent_changes": 3, "attach_attempts": 2,
        "partition_id_changes": 1}
clk = Clk()
spath = os.path.join(tempfile.mkdtemp(), "link_stats.json")
ls = ta.LinkStats(spath, clock=clk)
clk.now = BASE + H + 30                                  # 1re lecture, juste apres l'heure : fenetre « alignee »
assert ls.update({**MAC1, **MLE1}, "start-1", "router") is None and ls.baseline["aligned"] and ls.last is None
clk.now = BASE + H + 90                                  # meme heure : rien
assert ls.update({**MAC1, **MLE1}, "start-1", "router") is None
# l'heure suivante : une fenetre, avec les variations, sans ack, et les parts en %
clk.now = BASE + 2 * H + 40
mac2 = dict(MAC1, tx_total=1900, tx_ack_requested=1700, tx_acked=1650, tx_err_abort=120, tx_err_cca=14, tx_retry=0,
            rx_total=4100)
rec = ls.update({**mac2, **dict(MLE1, role_detached=5, parent_changes=4)}, "start-1", "router")
assert rec == ls.last and rec["seconds"] == 3610 and rec["role"] == "router"
assert datetime.fromisoformat(rec["from"]).tzinfo and datetime.fromisoformat(rec["to"]) > datetime.fromisoformat(rec["from"])
assert (rec["tx_total"], rec["tx_err_abort"], rec["tx_err_cca"], rec["tx_retry"], rec["rx_total"]) == (900, 80, 4, 0, 2100)
assert (rec["role_detached"], rec["parent_changes"], rec["attach_attempts"]) == (1, 1, 0)
assert rec["tx_no_ack"] == (1700 - 1650) - (900 - 880) == 30                      # demandes d'ack sans ack, sur la fenetre
assert rec["tx_err_abort_pct"] == round(100 * 80 / 900, 2) == 8.89 and rec["tx_no_ack_pct"] == round(100 * 30 / 900, 2)
assert ls.fresh and ls.public()["last"] == rec and datetime.fromisoformat(ls.public()["since"]).tzinfo
ls.published()
assert not ls.fresh
# redemarrage de l'add-on (fichier) : la ligne de base et l'historique sont relus
ls2 = ta.LinkStats(spath, clock=clk)
assert ls2.baseline == ls.baseline and ls2.history == ls.history
# l'OTBR redemarre (compteurs remis a zero) : pas de fenetre, nouvelle ligne de base
clk.now = BASE + 3 * H + 20
assert ls2.update({**mac2, **MLE1}, "start-2", "router") is None and ls2.baseline["otbr"] == "start-2" and len(ls2.history) == 1
# un compteur qui baisse (meme demarrage) : pareil
clk.now = BASE + 4 * H + 20
assert ls2.update({**dict(mac2, tx_total=5), **MLE1}, "start-2", "router") is None and ls2.baseline["c"]["tx_total"] == 5
# ligne de base prise en milieu d'heure : la 1re fenetre n'est pas comptee (pas une heure pleine)
clk.now = BASE + 5 * H + 1800
assert ls2.update({**MAC1, **MLE1}, "start-3", "router") is None and not ls2.baseline["aligned"]
clk.now = BASE + 6 * H + 30
assert ls2.update({**mac2, **MLE1}, "start-3", "router") is None and len(ls2.history) == 1 and ls2.baseline["aligned"]
clk.now = BASE + 7 * H + 30                              # l'heure pleine suivante est comptee
assert ls2.update({**dict(mac2, tx_total=2500), **MLE1}, "start-3", "router")["tx_total"] == 600 and len(ls2.history) == 2
# add-on arrete trop longtemps : la fenetre n'est pas une heure, elle est ecartee
clk.now = BASE + 10 * H + 30
assert ls2.update({**dict(mac2, tx_total=3500), **MLE1}, "start-3", "router") is None and len(ls2.history) == 2
# compteurs absents (lecture partielle) : la fenetre ne porte que ceux lus des deux cotes
clk.now = BASE + 11 * H + 30
rec = ls2.update({"tx_total": 4500, "tx_err_abort": 200}, "start-3", "router")
assert rec is None or "role_detached" not in rec
# pas de pourcentage sans envoi, un fichier abime ou absent : repart a vide
ls3 = ta.LinkStats(None, clock=clk)
clk.now = BASE + 20 * H + 5
ls3.update({"tx_total": 0, "tx_err_abort": 0}, "s", "child")
clk.now = BASE + 21 * H + 5
assert "tx_err_abort_pct" not in ls3.update({"tx_total": 0, "tx_err_abort": 0}, "s", "child")
with open(spath, "w", encoding="utf-8") as f:
    f.write("{pas du json")
assert ta.LinkStats(spath, clock=clk).baseline is None and ta.LinkStats(spath, clock=clk).history == []
assert len(ta.LinkStats(None).history) == 0
for _ in range(80):                              # 72 fenetres au plus
    clk.now += H
    ls2.update({**dict(mac2, tx_total=int(clk.now - BASE)), **MLE1}, "start-3", "router")
    ls2.baseline["aligned"] = True
assert len(ls2.history) <= ta.LINK_HISTORY

# dans le lien et l'etat : l'ancre lit les memes compteurs qu'avant (aucune commande en plus) et publie la fenetre
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock, stats=os.path.join(tempfile.mkdtemp(), "s.json"))
dd.now = BASE + H + 30
dd.link_out["counters mle"] = "Role Detached: 4\r\nParent Changes: 3\r\nDone\r\n"
aa.check()
assert dd.link_reads == LINK_CMDS and aa.public()["thread_link"]["stats"] == {"last": None, "since": aa.stats.public()["since"]}
assert aa.public()["thread_link"]["counters"]["mac"]["tx_acked"] == 880 and aa.public()["thread_link"]["counters"]["mac"]["tx_ack_requested"] == 900
dd.link_out["counters mac"] = dd.link_out["counters mac"].replace("TxTotal: 1034", "TxTotal: 2034").replace(
    "TxErrAbort: 1", "TxErrAbort: 51").replace("TxAckRequested: 900", "TxAckRequested: 1500").replace("TxAcked: 880", "TxAcked: 1400")
dd.link_out["counters mle"] = "Role Detached: 6\r\nParent Changes: 4\r\nDone\r\n"
dd.now = BASE + 2 * H + 30
before = aa._signature()
assert aa.check() is not None
win = aa.public()["thread_link"]["stats"]["last"]
assert win["tx_total"] == 1000 and win["tx_err_abort"] == 50 and win["tx_no_ack"] == 100 - 20 and win["role_detached"] == 2
assert win["tx_err_abort_pct"] == 5.0 and win["parent_changes"] == 1
assert aa._signature() != before                                  # une nouvelle fenetre republie l'etat

# capteurs et sujet retenu
bs = Broker()
bs.up = True
mqs = ta.Mqtt(aa, service=bs.service, factory=bs.factory, clock=bs.clock)
assert mqs.start()
cs = mqs.client
mqs.on_connect(cs, None, None, 0)
cfgs = {tp: json.loads(pl) for tp, pl, _ in cs.sent if tp.startswith("homeassistant/sensor/thread_anchor/link_")}
assert sorted(cfgs) == sorted(f"homeassistant/sensor/thread_anchor/link_{k}/config" for k, *_ in ta.STAT_SENSORS)
abort = cfgs["homeassistant/sensor/thread_anchor/link_tx_err_abort/config"]
assert abort["state_class"] == "measurement" and abort["unique_id"] == "thread_anchor_link_tx_err_abort" and "json_attributes_topic" not in abort
assert cfgs["homeassistant/sensor/thread_anchor/link_tx_err_abort_pct/config"]["unit_of_measurement"] == "%"
assert "tx_err_abort" in abort["value_template"] and abort["state_topic"] == "thread_anchor/state"
mqs.publish_stats()                                               # a la connexion, l'historique garde est renvoye
sent = [(tp, json.loads(pl), rt) for tp, pl, rt in cs.sent if tp == "thread_anchor/link_stats"]
assert len(sent) == 1 and sent[0][2] is True and sent[0][1]["history"] == aa.stats.history and sent[0][1]["interval"] == "hour"
cs.sent = []
mqs.publish_stats()
assert cs.sent == []                                              # rien de neuf : rien d'envoye
aa.stats.fresh = True
mqs.publish_stats()
assert [tp for tp, _, _ in cs.sent] == ["thread_anchor/link_stats"] and not aa.stats.fresh

bc = Broker()
bc.up = True
dd = FakeDocker()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=bc.clock, children=os.path.join(tempfile.mkdtemp(), "c.json"))
mqc = ta.Mqtt(aa, service=bc.service, factory=bc.factory, clock=bc.clock)
mqc.publish_children()                                          # sans client : rien, pas d'erreur
assert aa.children.due() is False
aa.children.note(TARGET, 0x6C05, 0x6C00, "child", "diagnostic")
mqc.publish_children()                                          # a publier mais pas de client : reste a publier
assert aa.children.due()
assert mqc.start()
cc = mqc.client
cc.sent = []
mqc.publish_children()
sent = [(tp, json.loads(pl), rt) for tp, pl, rt in cc.sent]
assert [(tp, rt) for tp, _, rt in sent] == [("thread_anchor/children", True)]
assert sent[0][1]["count"] == 1 and sent[0][1]["version"] == 1 and sent[0][1]["add_on_version"] == ta.VERSION
assert sent[0][1]["nodes"][TARGET]["parent"] == "0x6c00" and not aa.children.due()
cc.sent = []
mqc.publish_children()
assert cc.sent == []                                            # rien de neuf : rien d'envoye
bc.now += ta.CHILDREN_S + 1
mqc.publish_children()
assert len(cc.sent) == 1                                        # battement
cc.sent = []
aa.children.note(TARGET, 0x5801, 0x5800, "child", "childtable")
mqc.publish_children()
assert len(cc.sent) == 1 and json.loads(cc.sent[0][1])["nodes"][TARGET]["parent"] == "0x5800"
assert "thread_anchor/children" not in json.dumps(aa.public())      # l'etat MQTT n'en est pas alourdi

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
# ---- 0.1.12 : aller-retour jusqu'a la puce, a la demande (lectures seules : state, txpower, ccathreshold, counters mac)
class Perf:
    """Chrono virtuel : le faux border router y ajoute le temps de chaque lecture."""
    t = 100.0

    def __call__(self):
        return self.t


assert ta._stats([]) is None and ta._stats([5.0]) == {"min": 5.0, "median": 5.0, "p95": 5.0, "max": 5.0}
assert ta._stats(list(range(1, 101)))["p95"] == 95 and ta._stats(list(range(1, 101)))["median"] == 50.5   # rang le plus proche


def latency_rig(**kw):
    dd = FakeDocker()
    dd.perf = Perf()
    aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=dd.clock)
    replies = []
    lt = ta.Latency(aa, lambda rid, payload: replies.append((rid, payload)), clock=dd.clock, spawn=kw.get("spawn", lambda fn: fn()),
                    perf=dd.perf, sleep=lambda s: dd.__setattr__("now", dd.now + s), busy=kw.get("busy", lambda: False))
    return dd, aa, lt, replies


# cas normal : 100 paires, txpower 10 ms plus lent que state ; nombre de trames et d'abandons avant / apres
dd, aa, lt, replies = latency_rig()
dd.script["counters mac"] = [LINK_OUT["counters mac"], LINK_OUT["counters mac"].replace("TxTotal: 1034", "TxTotal: 1534").replace(
    "TxErrAbort: 1", "TxErrAbort: 26")]
lt.submit(json.dumps({"id": "m1"}))
rid, res = replies[0]
assert rid == "m1" and res["state"] == "ok" and res["error"] is None and res["command"] == "txpower" and res["n"] == 100
assert res["errors"] == 0 and res["cached_suspected"] is False and res["interval_s"] == 1.0
assert res["diff_ms"] == {"min": 10.0, "median": 10.0, "p95": 10.0, "max": 10.0}
assert res["state_ms"]["median"] == 2.0 and res["chip_ms"]["median"] == 12.0 and res["spikes_count"] == 0 and res["spikes"] == []
assert res["counters"]["delta"] == {"tx_total": 500, "tx_err_abort": 25} and res["counters"]["abort_pct"] == 5.0
assert res["counters"]["before"] == {"tx_total": 1034, "tx_err_abort": 1}
assert datetime.fromisoformat(res["started"]).tzinfo and res["seconds"] >= 99          # une paire par seconde
assert not lt.running
assert set(dd.cmds) == {"counters mac", "state", "txpower"} and dd.cmds.count("txpower") == 105       # 5 d'essai + 100
assert not [c for c in dd.cmds if c.split()[0] not in ("state", "txpower", "ccathreshold", "counters")]   # que des lectures
# des pics sont dates et comptes
dd, aa, lt, replies = latency_rig()
dd.chip_s = lambda k: 0.012 + (0.08 if k in (30, 77) else 0)
lt.submit(json.dumps({"id": "m2", "count": 100, "interval_s": 1}))
res = replies[0][1]
assert res["spikes_count"] == 2 and [s["diff_ms"] for s in res["spikes"]] == [90.0, 90.0]
assert all(datetime.fromisoformat(s["at"]).tzinfo for s in res["spikes"]) and res["diff_ms"]["max"] == 90.0
assert res["diff_ms"]["median"] == 10.0 and res["diff_ms"]["p95"] == 10.0
# txpower repondu depuis un cache (aussi rapide que state) : ccathreshold essaye ; sinon dit « cache suspecte »
dd, aa, lt, replies = latency_rig()
dd.chip_s = lambda k: 0.0021
lt.submit(json.dumps({"id": "m3", "count": 10}))
res = replies[0][1]
assert res["command"] == "ccathreshold" and res["cached_suspected"] is False and res["diff_ms"]["median"] == 13.0 and res["n"] == 10
dd, aa, lt, replies = latency_rig()
dd.chip_s = lambda k: 0.0021
dd.cc_s = lambda k: 0.0022
lt.submit(json.dumps({"id": "m4", "count": 10}))
res = replies[0][1]
assert res["command"] == "txpower" and res["cached_suspected"] is True and res["state"] == "ok"
# txpower inconnu de ce firmware : la lecture suivante est essayee ; aucune ne repond : erreur dite, rien d'invente
dd, aa, lt, replies = latency_rig()
dd.fail["txpower"] = "Error 35: InvalidCommand\r\n"
lt.submit(json.dumps({"id": "m5", "count": 10}))
assert replies[0][1]["state"] == "ok" and replies[0][1]["command"] == "ccathreshold"
dd, aa, lt, replies = latency_rig()
dd.fail.update({"txpower": "Error 35: InvalidCommand\r\n", "ccathreshold": "Error 35: InvalidCommand\r\n"})
lt.submit(json.dumps({"id": "m6", "count": 10}))
assert replies[0][1]["state"] == "error" and replies[0][1]["error"] == "no read of the chip answered" and not lt.running
# border router arrete : erreur, pas d'exception
dd, aa, lt, replies = latency_rig()
dd.running = False
lt.submit(json.dumps({"id": "m7", "count": 10}))
assert replies[0][1]["state"] == "error" and "409" in replies[0][1]["error"] and not lt.running
# demandes refusees : id inutilisable (ignoree), bornes, deja en cours, diagnostic en cours
dd, aa, lt, replies = latency_rig()
for raw in ("pas du json", "{}", json.dumps({"id": "a/b"}), json.dumps({"id": ""})):
    lt.submit(raw)
assert replies == []
for bad in ({"count": 5}, {"count": 500}, {"interval_s": 0.1}, {"interval_s": 10}, {"count": "x"}):
    lt.submit(json.dumps(dict({"id": "b"}, **bad)))
assert [r[1]["state"] for r in replies] == ["refused"] * 5 and "interval_s" in replies[0][1]["error"] and dd.cmds == []
later = []
dd, aa, lt, replies = latency_rig(spawn=later.append)
lt.submit(json.dumps({"id": "c1", "count": 10}))
lt.submit(json.dumps({"id": "c2", "count": 10}))
assert len(later) == 1 and replies == [("c2", {"id": "c2", "state": "refused", "error": "busy"})] and lt.running
later.pop()()
assert replies[-1][0] == "c1" and replies[-1][1]["state"] == "ok" and not lt.running
dd, aa, lt, replies = latency_rig(busy=lambda: True)
lt.submit(json.dumps({"id": "d1"}))
assert replies == [("d1", {"id": "d1", "state": "refused", "error": "busy"})] and dd.cmds == []
# par MQTT : abonne, jamais lance seul, resultat non retenu + dernier retenu ; diagnostic et mesure s'excluent
bl = Broker()
bl.up = True
dd = FakeDocker()
dd.perf = Perf()
aa = ta.Anchor({"omr_prefix": P}, docker=dd, clock=bl.clock)
mql = ta.Mqtt(aa, service=bl.service, factory=bl.factory, clock=bl.clock)
mql.latency.spawn = lambda fn: fn()
mql.latency.perf, mql.latency.sleep = dd.perf, lambda s: None
assert mql.start()
cl = mql.client
mql.on_connect(cl, None, None, 0)
assert ("subscribe", "thread_anchor/latency/request") in cl.log and dd.cmds == []                 # rien sans demande
cl.sent = []
mql.on_message(cl, None, Msg("thread_anchor/latency/request", json.dumps({"id": "z1", "count": 10}).encode()))
tops = [(tp, rt) for tp, _, rt in cl.sent]
assert tops == [("thread_anchor/latency/result/z1", False), ("thread_anchor/latency/last", True)], tops
assert json.loads(cl.sent[0][1])["state"] == "ok" and json.loads(cl.sent[1][1])["id"] == "z1"
cl.sent = []
mql.on_message(cl, None, Msg("thread_anchor/latency/request", json.dumps({"id": "z2", "count": 3}).encode()))
assert [(tp, rt) for tp, _, rt in cl.sent] == [("thread_anchor/latency/result/z2", False)]      # refusee : pas retenue
mql.latency.running = True
cl.sent = []
mql.diag.submit(req(id="y1"))
assert json.loads(cl.sent[0][1])["error"] == "busy"               # pas de diagnostic pendant la mesure
mql.latency.running, mql.diag.running = False, True
cl.sent = []
mql.on_message(cl, None, Msg("thread_anchor/latency/request", json.dumps({"id": "z3", "count": 10}).encode()))
assert json.loads(cl.sent[0][1])["error"] == "busy"               # ni de mesure pendant un diagnostic
mql.diag.running = False
print("OK")

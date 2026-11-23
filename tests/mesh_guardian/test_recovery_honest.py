"""2.40.14: (a) after the pings gave up, a node is pinged again at a sign of life (counter at zero) and
slowly every SLOW_RETRY_S; (b) a recovery attempt on a node that answers the network ping sends nothing
heavier and waits for it, never "out of reach" for a node its neighbors hear; (c) every return is
counted after the action that preceded it (automatic ping, page, recovery attempt) or on its own.
Fake Matter Server and Home Assistant, made-up values only."""
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
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import healer as H  # noqa: E402
import reattach  # noqa: E402

TMP = tempfile.mkdtemp()
NID = "00000000000000AB"


class Watch:
    def __init__(self):
        self.lock, self.stop, self.events = threading.RLock(), threading.Event(), []
        self.matter, self.live, self.table, self.dirty = {}, None, None, False

    def emit(self, kind, text, **data):
        self.events.append((kind, text, data))

    def kinds(self):
        return [k for k, _, _ in self.events]


def healer(state="unavailable"):
    w = Watch()
    h = H.Healer(w, {"ping_after": 60, "ping_retry": 300, "ping_max_attempts": 6})
    h.state_file, h.outages_file = os.path.join(TMP, "state.json"), os.path.join(TMP, "outages.json")
    h.enabled, h.check_routing, h.backfill, h._backfilled = True, lambda: None, lambda d: None, True
    # down just now: the first cycle sends no ping of its own (ping_after not reached)
    h.items = [{"node": NID, "name": "Spot demo", "area": "Hall", "state": state, "since": time.time()}]
    h.fetch_ha_nodes = lambda: [dict(x) for x in h.items]
    h.pinged = []

    def cmd(command, args=None, timeout=60, timing=None):
        h.pinged.append(command)
        return {"fd00:aaaa::ab": False}
    h.matter_command = cmd
    return w, h


# ---- (a) given up: not for good
w, h = healer()
h.cycle()                               # first sight: no event, the node is known as unavailable
n = h.nodes[NID]
n.update({"gave_up": True, "gave_up_t": time.time() - 60, "pings": 6, "last_ping": time.time() - 60})
h.cycle()
assert h.pinged == [] and n["gave_up"], h.pinged                     # no sign, not 30 min yet: nothing
n["gave_up_t"] = n["last_ping"] = time.time() - H.SLOW_RETRY_S - 5
h.cycle()
assert h.pinged == ["ping_node"] and n["pings"] == 6 and n["gave_up"]  # one slow ping, not counted in the 6
assert any("every 30 min" in txt for k, txt, _ in w.events if k == "ping"), w.events
h.pinged.clear()
h.cycle()
assert h.pinged == []                                                 # the next one in 30 min
# a storm doubles the wait
h.storm = types.SimpleNamespace(active=True)
n["last_ping"] = time.time() - H.SLOW_RETRY_S - 5
h.cycle()
assert h.pinged == []
h.storm = None
# a sign of life since it gave up (its mDNS announcement came back): its pings again, counter at zero
w.matter[NID] = {"online": True, "since": time.time() - 10}
n["since"] = time.time() - 4000          # down for an hour
h.cycle()
assert not n["gave_up"] and n["pings"] == 1 and h.pinged == ["ping_node"], (n, h.pinged)
assert "ping_rearmed" in w.kinds()
# an older sign (before it gave up) does not count
w, h = healer()
h.cycle()
n = h.nodes[NID]
n.update({"gave_up": True, "gave_up_t": time.time() - 60, "pings": 6, "last_ping": time.time() - 60})
w.matter[NID] = {"online": True, "since": time.time() - 600}
h.cycle()
assert n["gave_up"] and h.pinged == []
# a ping of the page or of a recovery attempt that is answered is a sign of life too
h.note_sign(NID, "answers the ping")
n["since"] = time.time() - 4000
h.cycle()
assert not n["gave_up"] and n["pings"] == 1
# a Matter contact (passive contact or a ping answered) since it gave up
assert H.Healer.sign_of_life({"gave_up_t": 100.0}, [(150.0, "contact Matter")]) == "contact Matter"
assert H.Healer.sign_of_life({"gave_up_t": 100.0}, [(50.0, "contact Matter")]) is None


# ---- (c) every return counted after its action, or on its own
def back_after(kind, age):
    w, h = healer()
    h.cycle()
    if kind:
        h.nodes[NID]["action_t"], h.nodes[NID]["action"] = time.time() - age, kind
    h.items[0]["state"] = "on"
    h.items[0]["since"] = time.time()
    h.cycle()
    return h.last_24h(), [(k, txt, d) for k, txt, d in w.events if k.startswith("node_")]


d, ev = back_after("auto", 20)
assert d["recovered_by_ping"] == 1 and d["back_after_auto"] == 1 and d["back_on_their_own"] == 0, d
d, ev = back_after("manual", 60)
assert d["back_after_manual"] == 1 and ev[0][2]["after"] == "manual" and "from the page" in ev[0][1], ev
d, ev = back_after("attempt", 10)
assert d["back_after_attempt"] == 1 and "recovery attempt" in ev[0][1]
d, ev = back_after("auto", H.AFTER_ACTION_S + 30)     # too long ago: on its own
assert d["recovered_by_ping"] == 0 and d["back_on_their_own"] == 1, d
d, ev = back_after(None, 0)
assert d["back_on_their_own"] == 1 and ev[0][0] == "node_back_on_its_own"
# an action before the outage is not one on it
w, h = healer("on")
h.cycle()
h.note_action(NID, "manual")
h.items[0].update(state="unavailable", since=time.time())
h.cycle()
assert h.nodes[NID]["action_t"] is None


# ---- (b) the recovery attempt
class Live:
    connected = True

    def __init__(self):
        self.lock = threading.Lock()
        self.nodes = {NID: {"available": False, "attributes": {}}}
        self.heard = []

    def heard_by(self, ext):
        return self.heard


class RHealer:
    def __init__(self, ping):
        self.lock = threading.Lock()
        self.nodes = {NID: {"name": "Spot demo", "area": "Hall", "available": False}}
        self.ping, self.calls, self.signs, self.actions = ping, [], [], []

    def matter_command(self, command, args=None, timeout=60, timing=None):
        name = (args or {}).get("command_name", command)
        self.calls.append(name)
        if command == "ping_node":
            return self.ping
        raise TimeoutError("Operation aborted")

    def note_action(self, nid, kind):
        self.actions.append(kind)

    def note_sign(self, nid, why):
        self.signs.append(why)


def attempt(ping, heard=(), ext=0x1A2B3C4D5E6F7081, back=False):
    w, h = Watch(), RHealer(ping)
    w.matter = {NID: {"online": True}}
    r = reattach.Reattach(w, h)
    r.live = Live()
    r.live.heard = list(heard)
    reattach.PING_BACK_WAIT_S = 0.3
    if back:
        r.live.nodes[NID]["available"] = True
    r.busy.acquire()   # as recover_node does before starting _recover
    r._recover(NID, "Spot demo", "Hall", "bmV0", ext=ext)
    assert not r.busy.locked()
    res = r.results[NID]
    return h, res, [txt for k, txt, _ in w.events if k == "recover_result"]


# answers the network ping and comes back: nothing heavy sent, "back after the ping of the attempt"
h, res, txt = attempt({"fd00:aaaa::ab": True}, back=True)
assert "ArmFailSafe" not in h.calls and res["result"] == "back_ping", (h.calls, res)
assert h.actions == ["attempt"] and h.signs == ["answers the ping"]
# answers the ping, not back yet: "reachable", never "out of reach"
h, res, txt = attempt({"fd00:aaaa::ab": True})
assert "ArmFailSafe" not in h.calls and res["result"] == "reachable" and "out of reach" not in txt[-1], (res, txt)
# heard on the radio, no answer to the ping: the heavy way, and its failure is not "out of reach"
h, res, txt = attempt({"fd00:aaaa::ab": False}, heard=[("00000000000000CD", 60, -40)])
assert "ArmFailSafe" in h.calls and res["result"] == "unreachable" and "heard on the radio but no answer" in txt[-1], (h.calls, txt)
# neither heard nor answering: nothing sent
h, res, txt = attempt({"fd00:aaaa::ab": False})
assert "ArmFailSafe" not in h.calls and "nothing sent" in txt[-1], (h.calls, txt)
# its radio address not known (no radio test possible): the heavy way as before
h, res, txt = attempt({"fd00:aaaa::ab": False}, ext=None)
assert "ArmFailSafe" in h.calls and "out of reach" in txt[-1]

# French texts
src = open(os.path.join(MG, "i18n.py"), encoding="utf-8").read()
for fr in ("joignable sur le réseau, session Matter en reprise", "de retour après le ping de la tentative",
           "signe de vie ({why}), pings relancés", "{n} revenues seules", "Retours après une action"):
    assert fr in src, fr
print("OK")

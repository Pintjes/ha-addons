"""2.40.16 (audits of 24 and 25 November): (A) the node prefixes count the Thread nodes only: the LAN
prefix of a Wi-Fi node is not one, and its change says nothing nor speeds the pings up; (B) a Thread
node without the Thread diagnostics cluster (a lock) is in the radio survey, without role, neighbors
nor counters; (C) the node counts are not published before the first read of Home Assistant; (D) the
date "since the anchoring" is kept while the same prefix is fixed. Made-up values only."""
import ast
import base64
import json
import os
import sys
import tempfile
import threading
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import anchor as A  # noqa: E402
import healer as H  # noqa: E402
import nodetable  # noqa: E402

src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Watch")


def extract(names, ns):
    body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in names]
    assert len(body) == len(names), [m.name for m in body]
    mod = ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)
    return ns["W"]


THREAD_LAN, LAN, LAN2 = "fd00:aaaa:bbbb:1::/64", "fd00:eeee:ffff:1::/64", "fd00:eeee:ffff:2::/64"
THREAD_ITF = [{"7": 4, "4": base64.b64encode(bytes.fromhex("1a2b3c4d5e6f7081")).decode()}]

# ---- (A) node prefixes: Thread only
assert "if p and not self._not_thread(k):" in src
W = extract(("_not_thread", "check_node_prefixes"), {"is_thread": nodetable.is_thread, "t": lambda s, **k: s})
w = W()
live = {"01": {"attributes": {"0/53/1": 5}}, "02": {"attributes": {"0/51/0": [{"7": 1}], "0/54/4": -50}},
        "03": {"attributes": {"0/51/0": THREAD_ITF}}, "04": {"attributes": {}}}
w.live = types.SimpleNamespace(nodes=live)
assert [w._not_thread(k) for k in ("01", "02", "03", "04", "05")] == [False, True, False, False, False]
w.live = types.SimpleNamespace(nodes={})           # link lost: the Wi-Fi node stays known as such
assert w._not_thread("02") and not w._not_thread("01")
w.live = types.SimpleNamespace(nodes=live)

# the LAN prefix of the Wi-Fi node changes: no event, no fast pings
prefixes = {"01": THREAD_LAN, "02": LAN}


def summary():
    out = {}
    for k, p in prefixes.items():
        if not w._not_thread(k):
            out[p] = out.get(p, 0) + 1
    return {"node_prefixes": out}


events, fast = [], []
w.summary, w.quiet, w._prefixes_dirty, w.prev_node_prefixes = summary, False, False, None
w.emit = lambda kind, *a, **k: events.append(kind)
w.healer = types.SimpleNamespace(prefix_changed=lambda: fast.append(1))
w.check_node_prefixes()
prefixes["02"] = LAN2
w.check_node_prefixes()
assert events == [] and fast == [] and w.prev_node_prefixes == (THREAD_LAN,), (events, fast)

# ---- (B) the radio survey keeps a Thread node without the Thread diagnostics cluster
import radio  # noqa: E402

radio.TOPOLOGY_FILE = os.path.join(tempfile.mkdtemp(), "topology.json")
r = radio.Radio.__new__(radio.Radio)
nodes = [{"node_id": 0xF001, "available": True, "attributes": {"0/53/1": 5, "0/51/0": THREAD_ITF, "0/51/1": 3}},
         {"node_id": 0xF002, "available": True, "attributes": {"0/51/0": THREAD_ITF, "0/51/1": 7, "0/51/2": 100}},
         {"node_id": 0xF003, "available": True, "attributes": {"0/51/0": [{"7": 1}], "0/54/4": -40}}]
r.live = types.SimpleNamespace(connected=True, snapshot=lambda: nodes, known_since=lambda *a: 0)
r.h = types.SimpleNamespace(lock=threading.RLock(), nodes={})
r.history, r.advisor, r.last, r.ok = [], None, None, False
r._names, r._save = lambda: {}, lambda: None
said = []
r.w = types.SimpleNamespace(lock=threading.RLock(), br={}, dirty=False, set_ha_networks=lambda n: None,
                            emit=lambda *a, **k: said.append(a))
r._survey()
assert r.last["thread_nodes"] == 2, r.last           # the lock counted, the Wi-Fi node not
assert None not in r.last["roles"] and sum(r.last["roles"].values()) == 1, r.last["roles"]
snap = r.history[-1]["nodes"][f"{0xF002:016X}"]
assert snap["r"] == 7 and snap["u"] == 100 and all(v is None for v in snap["c"].values()), snap
nodes[1]["attributes"]["0/51/1"] = 9                  # two restarts since: listed, with no role
r.history[0]["t"] -= 7200
r._survey()
u = [x for x in r.last["unstable"] if x["reboots"]]
assert len(u) == 1 and u[0]["reboots"] == 2 and u[0]["role"] is None, r.last["unstable"]
assert r.summary()["unstable_list"]                  # its line is written without a role

# ---- (C) no counts published before the first read of Home Assistant
wsrc = src[src.index("    def publish_states("):src.index('self.mqtt.publish(f"{BASE}/radio"')]
assert 'getattr(self.healer, "ha_read", True)' in wsrc
tmp = tempfile.mkdtemp()
hw = types.SimpleNamespace(lock=threading.RLock(), matter={}, live=None, table=None, dirty=False, events=[],
                           emit=lambda *a, **k: None, stop=threading.Event())
h = H.Healer(hw, {})
h.state_file, h.outages_file = os.path.join(tmp, "s.json"), os.path.join(tmp, "o.json")
h.check_routing, h.backfill = lambda: None, lambda d: None
h.fetch_ha_nodes = lambda: None                      # Home Assistant not answering yet
assert h.ha_read is False
h.cycle()
assert h.ha_read is False
h.fetch_ha_nodes = lambda: [{"node": "00000000000000AB", "name": "Prise demo", "area": "Cave", "state": "on"}]
h.cycle()
assert h.ha_read is True and h.summary()["available"] == 1

# ---- (D) the anchoring date is kept for the same prefix
A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
P, Q = THREAD_LAN, "fd11:2222:3333:1::/64"
T0 = 1763370000.0
clock = [T0]


def new():
    aw = types.SimpleNamespace(lock=threading.RLock(), br={}, matter={}, usb_links=None, dirty=False,
                               emit=lambda *a, **k: None, _omr_now=lambda: {P})
    return A.Anchor(aw, clock=lambda: clock[0])


def state(prefix, since, enforced=True):
    return json.dumps({"wanted": prefix, "enforced": enforced, "current": prefix, "favored": prefix, "error": None,
                       "anchored_since": __import__("datetime").datetime.fromtimestamp(since).astimezone().isoformat()
                       if since else None})


a = new()
a.on_state(state(P, T0))
assert a.anchored_since == T0
a.on_state(state(P, None, enforced=False))           # radio cut
a.on_state(state(P, T0 + 5000))                      # Thread Anchor starts its date again, same prefix
assert a.anchored_since == T0, a.anchored_since
assert new().anchored_since == T0 and new().anchored_prefix == P     # kept across a restart
a.on_state(state(P, T0 - 100))                       # an earlier date is better knowledge
assert a.anchored_since == T0 - 100
a.on_state(state(Q, T0 + 9000))                      # another prefix fixed: a new anchoring
assert a.anchored_since == T0 + 9000 and a.anchored_prefix == Q
# file of an older version (no prefix): the date kept, the prefix noted
with open(A.ANCHOR_FILE, "w") as f:
    json.dump({"anchored_since": T0}, f)
a = new()
a.on_state(state(P, T0 + 5000))
assert a.anchored_since == T0 and a.anchored_prefix == P
print("OK")

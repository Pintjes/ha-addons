"""2.40.12: no false Thread leader published while the add-on starts. During the quiet start (and until
Home Assistant gave the names), the leader found in the mesh (roles kept from before the restart, the
leader read at +30 s, named "0x.." before the names) is not published: the leader published before the
restart is kept, else "unknown". Then the real leader, named, without a false "leader change".
summary, _settle, check_global extracted from watcher.py (zeroconf absent). Made-up values only."""
import ast
import os
import sys
import tempfile
import threading
import time
import types

MG = sys.argv[1]
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Watch")
want = ("summary", "_names_loaded", "_load_leader", "_save_leader", "_settle", "check_global", "_check_global")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
mod = ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
store = {}
LF = os.path.join(tempfile.mkdtemp(), "leader.json")
ns = {"time": time, "t": lambda s, **k: s.format(**k) if k else s, "SETTLE_S": 30, "LEADER_FILE": LF,
      "now_iso": lambda: "x", "OMR_LEFT_KEEP_S": 1, "LOG": types.SimpleNamespace(warning=lambda *a, **k: None),
      "load_json": lambda f: store.get(f), "save_json": lambda f, v, **k: store.__setitem__(f, dict(v))}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

NAMES = {"0000000000000013": "Lampadaire demo", "000000000000002C": "Prise demo"}


class Radio:
    """Like radio.mesh_leaders: the key is stable, the name is the one known now."""
    nid = None

    def mesh_leaders(self):
        if not self.nid:
            return []
        name = NAMES[self.nid] if w.healer.nodes[self.nid]["name"] else "0x" + self.nid.lstrip("0")
        return [(f"node:{self.nid}", name)]


def watch(quiet=True, names=False):
    w = ns["W"]()
    w.lock, w.global_lock = threading.RLock(), threading.RLock()
    w._own_nodes = lambda: set()
    w.br = {"b1": {"online": True, "role": "router", "partition": "p1", "interface": "active", "omr": "fd00::/64"}}
    w.br_relevant = lambda b: True
    w.br_label = lambda b: "BR demo"
    w.matter, w.cast, w.pending = {}, {}, {}
    w.bursts_count = w.events_count = 0
    w.last_event = None
    w.omr_episodes_24h = lambda: 0
    w._settled, w._unsettled, w._short_detaches = None, None, []
    w.flush_short_detaches = lambda: None
    w.prev_leaders = w.prev_partitions = w.prev_omr = None
    w.events = []
    w.emit = lambda kind, *a, **k: w.events.append(kind)
    w.radio = Radio()
    w.healer = types.SimpleNamespace(nodes={k: {"name": v if names else None} for k, v in NAMES.items()})
    w.leader_saved = None
    w._load_leader()
    w.quiet = quiet
    return w


# a first start, nothing published before: "unknown" during the start, whatever the mesh says
w = watch()
for nid in ("000000000000002C", "0000000000000013"):       # roles kept from before, then the read at +30 s
    w.radio.nid = nid
    s = w.summary()
    assert s["leader"] == "unknown" and s["leader_keys"] == [], s["leader"]
    w.check_global()
assert LF not in store                                     # nothing saved during the start

# start over, names known: the real leader is published and saved
w.quiet = False
for n in w.healer.nodes:
    w.healer.nodes[n]["name"] = NAMES[n]
w.radio.nid = "0000000000000013"
w._settled = None                                          # first value outside the start: taken at once
s = w.summary()
assert s["leader"] == "Lampadaire demo", s
w.check_global()
assert w.events == []                                      # from "unknown": no leader change
assert store[LF] == {"keys": ["node:0000000000000013"], "text": "Lampadaire demo"}

# restart: the leader published before is kept while the mesh says 0x2C then 0x13 in hex
w = watch()
for nid in ("000000000000002C", "0000000000000013"):
    w.radio.nid = nid
    s = w.summary()
    assert s["leader"] == "Lampadaire demo" and s["leader_keys"] == ["node:0000000000000013"], s["leader"]
    w.check_global()

# start over but the names not there yet: still kept (never "0x13" published)
w.quiet = False
s = w.summary()
assert s["leader"] == "Lampadaire demo", s["leader"]
# names there: same leader, same key, no event
for n in w.healer.nodes:
    w.healer.nodes[n]["name"] = NAMES[n]
s = w.summary()
w.check_global()
assert s["leader"] == "Lampadaire demo" and w.events == [], (s, w.events)

# a real change after the start is still reported (once it held SETTLE_S)
w.radio.nid = "000000000000002C"
w.summary()
w._unsettled["raw_t"] -= 31
s = w.summary()
w.check_global()
assert s["leader"] == "Prise demo" and w.events == ["leader_change"], (s, w.events)
assert store[LF]["text"] == "Prise demo"

# a border router leader (known from mDNS) is not touched during the start
w = watch()
w.br["b1"]["role"] = "leader"
s = w.summary()
assert s["leader"] == "BR demo" and s["leaders_count"] == 1
print("OK")

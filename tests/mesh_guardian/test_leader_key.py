"""2.40.5 : le leader trouve en interrogeant un routeur est retenu par une cle stable (id de la node),
son nom est pris au moment de l'affichage. Un leader trouve avant que Home Assistant donne les noms
s'affiche d'abord par son id, puis par son nom, SANS alerte de changement de leader ; un vrai
changement de node donne une alerte. Valeurs fictives uniquement."""
import ast
import os
import sys
import threading
import time
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import radio as R  # noqa: E402

A, B = "0000000000000013", "0000000000000027"

# --- radio: key kept, name taken when shown
r = R.Radio.__new__(R.Radio)
r.h = types.SimpleNamespace(lock=threading.RLock(), nodes={})            # names of Home Assistant not read yet
r.w = types.SimpleNamespace(lock=threading.RLock(), br={"brk": {"xa": 0x99}}, br_label=lambda b: "Routeur demo")
r.live = types.SimpleNamespace(connected=True, leaders=lambda: [])
r.last = None
r.leader_key, r.leader_t, r.leader_partitions = f"node:{A}", time.time(), ("p",)
assert r.mesh_leaders() == [(f"node:{A}", "0x13")] and r.leader_name == "0x13"
r.h.nodes = {A: {"name": "Lampe demo"}}                                  # the names arrive
assert r.mesh_leaders() == [(f"node:{A}", "Lampe demo")] and r.leader_name == "Lampe demo"
assert r.leader_label("br:brk") == "Routeur demo" and r.leader_label("router 9 (0x2400)") == "router 9 (0x2400)"
# fresh roles: keyed by node id too
r.leader_key = None
r.live = types.SimpleNamespace(connected=True, leaders=lambda: [A])
assert r.mesh_leaders() == [(f"node:{A}", "Lampe demo")]
# check_leader hands keys, not names, to resolve_leader
src = open(os.path.join(MG, "radio.py"), encoding="utf-8").read()
cl = src[src.index("    def check_leader("):src.index("    def run_leader(")]
assert 'keys[ext] = f"node:{n[\'node_id\']:016X}"' in cl and "resolve_leader(keys)" in cl and "h.nodes" not in cl

# --- watcher: _settle and check_global, extracted (zeroconf absent)
wsrc = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cls = next(n for n in ast.parse(wsrc).body if isinstance(n, ast.ClassDef) and n.name == "Watch")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("_settle", "check_global", "_check_global")]
assert len(body) == 3
ns = {"time": time, "t": lambda s, **k: s.format(**k) if k else s, "SETTLE_S": 60}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body,
                                                                       decorator_list=[])], type_ignores=[])), "w", "exec"), ns)
w = ns["W"]()
w._settled, w._unsettled, w._short_detaches, w.quiet = None, None, [], False
w.global_lock = threading.RLock()
w.prev_leaders = w.prev_partitions = w.prev_omr = None
events = []
w.emit = lambda kind, text, **k: events.append((kind, text))
w.flush_short_detaches = lambda: None
cur = {}


def summary():
    raw = {"parts": ["p"], "leader_keys": cur["keys"], "leader": cur["txt"], "leaders_count": 0}
    st = w._settle(raw, {})
    return {"leader_keys": st["leader_keys"], "leader": st["leader"], "partition_ids": st["parts"], "omr_list": []}


w.summary = summary
cur.update(keys=[f"node:{A}"], txt="0x13")
w.check_global()                                      # first value (start)
cur.update(txt="Lampe demo")                          # same node, its name now known
w.check_global()
assert not [e for e in events if e[0] == "leader_change"], events
assert summary()["leader"] == "Lampe demo"             # shown at once, nothing to settle
cur.update(keys=[f"node:{B}"], txt="Autre lampe demo")   # a real change of node
w._unsettled = None
w._settled = None                                      # (settling is tested elsewhere: take it at once)
w.prev_leaders = ((f"node:{A}",), "Lampe demo")
w.check_global()
assert [e for e in events if e[0] == "leader_change"] == [("leader_change", "Thread leader: Lampe demo → Autre lampe demo")], events
print("OK")

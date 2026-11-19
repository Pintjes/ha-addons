"""2.40.3 : le leader Thread n'est tire que d'un role lu par Mesh Guardian il y a moins de 2 h, jamais du
cache du Matter Server (qui ne suit pas les changements de role : faux changement de leader au demarrage).
Sans role frais : « inconnu », et aucun changement de leader n'est signale depuis « inconnu ».
Premier releve du leader 30 s apres le demarrage. Valeurs fictives uniquement."""
import os
import sys
import threading
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import matterlive as M  # noqa: E402
import radio as R  # noqa: E402

NOW = 1_800_000_000.0
live = M.MatterLive.__new__(M.MatterLive)
live.lock = threading.RLock()
live.nodes = {
    "00000000000000A1": {"attributes": {"0/53/1": 6}, "available": True},   # leader in the cache only
    "00000000000000A2": {"attributes": {"0/53/1": 5}, "available": True},   # read as leader 30 min ago
    "00000000000000A3": {"attributes": {"0/53/1": 6}, "available": True},   # read as leader 3 h ago
    "00000000000000A4": {"attributes": {"0/53/1": 6}, "available": False},  # read as leader, unavailable
    "00000000000000A5": {"attributes": {"0/53/1": 6}, "available": True},   # read as router just now
}
live.fresh = {
    ("00000000000000A2", "0/53/1"): (NOW - 1800, 6),
    ("00000000000000A3", "0/53/1"): (NOW - 3 * 3600, 6),
    ("00000000000000A4", "0/53/1"): (NOW - 60, 6),
    ("00000000000000A5", "0/53/1"): (NOW - 10, 5),
}
assert live.leaders(now=NOW) == ["00000000000000A2"], live.leaders(now=NOW)
assert M.LEADER_FRESH_S == 2 * 3600
# nothing read yet (just after a start, before the first reads): no leader from the cache
live.fresh = {}
assert live.leaders(now=NOW) == []

# radio.mesh_leader: the leader found by asking a router first, else the fresh roles, else the last survey
r = R.Radio.__new__(R.Radio)
r.live = types.SimpleNamespace(connected=True, leaders=lambda: [])
r.h = types.SimpleNamespace(lock=threading.RLock(), nodes={})
r.leader_name, r.leader_t, r.last = None, 0, None
assert r.mesh_leader() == []                          # unknown upstream (watcher: t("unknown"))
r.live = types.SimpleNamespace(connected=True, leaders=lambda: ["00000000000000A2"])
r.h.nodes = {"00000000000000A2": {"name": "Lampe demo"}}
assert r.mesh_leader() == ["Lampe demo"]
assert R.LEADER_FIRST_S == 30

# no leader change is reported from "unknown" (watcher.check_global)
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
body = src[src.index("    def check_global("):]
body = body[:body.index('self.emit("leader_change"')]
assert 'self.prev_leaders[1] != t("unknown")' in body
# the first search waits LEADER_FIRST_S, not 120 s
rsrc = open(os.path.join(MG, "radio.py"), encoding="utf-8").read()
run = rsrc[rsrc.index("    def run_leader("):]
assert "time.sleep(LEADER_FIRST_S)" in run[:200]
print("OK")

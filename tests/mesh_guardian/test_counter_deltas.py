"""2.40.12: the detaches of the last 24 h are computed by one function for the node table and the radio
survey. A restart is judged on the reboot counter (0/51/1), never on the uptime: a stale uptime of the
Matter Server cache (smaller than the one of 24 h ago, no restart) counted every detach since the boot
of the node (e.g. 275) as the last 24 h. Made-up values only."""
import os
import sys
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import nodetable  # noqa: E402

cd = nodetable.counter_deltas
yes = lambda name: True   # noqa: E731

# no restart (same reboot counter): the difference, whatever the uptime says
d, r = cd({"detached": 280, "parent_changes": 12}, {"detached": 275, "parent_changes": 10}, yes, 4, 4)
assert d == {"detached": 5, "parent_changes": 2} and r == 0, d
# a restart (reboot counter + 1): the counters restarted from 0, the value now is what came since
d, r = cd({"detached": 3}, {"detached": 275}, yes, 5, 4)
assert d == {"detached": 3} and r == 1
# reboot counter unknown: never the whole counter
d, r = cd({"detached": 280}, {"detached": 275}, yes, None, 4)
assert d == {"detached": 5} and r == 0
# an old value not the node's own (Matter Server cache), or a value missing: unknown, not a count
d, _ = cd({"detached": 280, "parent_changes": None}, {"detached": 2, "parent_changes": 1}, lambda n: n != "detached", 4, 4)
assert d == {"detached": None, "parent_changes": None}
d, _ = cd({"detached": 280}, None, yes, 4, 4)
assert d == {"detached": None}

# both callers use it, and nothing judges a restart on the uptime any more
nt = open(os.path.join(MG, "nodetable.py"), encoding="utf-8").read()
rd = open(os.path.join(MG, "radio.py"), encoding="utf-8").read()
assert nt.count("counter_deltas(") == 2 and rd.count("counter_deltas(") == 2
assert 'old.get("u") or 0) > uptime' not in nt
assert '(c.get("u") or 0) < (p.get("u") or 0)' not in rd

# the radio survey, end to end: stale uptime in the cache, no restart -> 5, not 275
import radio  # noqa: E402

r = radio.Radio.__new__(radio.Radio)
r.live = None   # no Matter Server link: every value counts as the node's own
r.history = [{"t": 1000.0, "nodes": {"0A": {"c": {"detached": 270}, "u": 900000, "r": 4}}},
             {"t": 2000.0, "nodes": {"0A": {"c": {"detached": 275}, "u": 50, "r": 4}}}]
assert r.own_detaches({"t": 1000.0}) == {"0A": 5}
r.history[1]["nodes"]["0A"].update({"c": {"detached": 2}, "r": 5})   # a real restart: 2 since
assert r.own_detaches({"t": 1000.0}) == {"0A": 2}
print("OK")

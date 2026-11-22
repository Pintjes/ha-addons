"""2.40.12: a stop (or restart) of Thread Anchor is not a loss of the OMR prefix. While the border
routers still announce the prefix: no error, no "recovery paused", no "no longer in place (now: the
same prefix)"; after the grace time "Thread Anchor stopped: OMR prefix … still published, no longer
imposed"; nothing at all for a restart within the grace time. A prefix no longer announced while
Thread Anchor is stopped is a real loss, said at once. Made-up values only."""
import ast
import json
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

import anchor as A  # noqa: E402

A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
P, G = "fd00:aaaa:bbbb:1::/64", "fd11:2222:3333:1::/64"
OK = {"wanted": P, "mode": "custom", "current": P, "enforced": True, "favored": P, "error": None}

# watcher.omr_fixed, extracted (zeroconf absent)
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "Watch")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == "omr_fixed"]
mod = ast.Module(body=[ast.ClassDef(name="F", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
ns = {"time": time, "t": lambda s, **k: s.format(**k), "OMR_FIXED_GRACE_S": 60}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)


class W(ns["F"]):
    def __init__(self):
        self.lock, self.events, self.dirty, self.usb_links, self.matter = threading.RLock(), [], False, None, {}
        self.br = {"ha": {"omr": P}, "tv": {"omr": P}}
        self.omr_fixed_off, self.omr_fixed_said = None, False

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def _omr_now(self):
        return {b["omr"] for b in self.br.values()}

    def kinds(self):
        return [k for k, _ in self.events]


T0 = 1763370000.0
clock = [T0]


def start():
    w = W()
    a = A.Anchor(w, clock=lambda: clock[0])
    a.on_state(json.dumps(OK))
    a.on_available("online")
    w.events.clear()
    return w, a


# a restart of Thread Anchor within the grace time: nothing said, no pause
clock[0] = T0
w, a = start()
a.on_available("offline")
assert a.blocked() is None and w.events == [], w.events
o = a.omr()
assert o["stopped"] and not o["enforced"] and o["error"] is None and o["current"] == P
assert a.public()["error"] == "Thread Anchor is stopped"        # the page says why it is no longer imposed
clock[0] = T0 + 30
a.update(now=clock[0])
a.on_state(json.dumps(OK))
a.on_available("online")
clock[0] = T0 + 200
a.update(now=clock[0])
assert w.events == [], w.events

# stopped for good, prefix still announced: after the grace time, one short and true line, no pause
clock[0] = T0
w, a = start()
a.on_available("offline")
clock[0] = T0 + 61
a.update(now=clock[0])
assert w.kinds() == ["omr_fixed_lost"] and a.blocked() is None, w.events
txt = w.events[0][1]
assert txt == f"Thread Anchor stopped: OMR prefix {P} still published, no longer imposed", txt
assert "now:" not in txt
a.on_available("online")
a.on_state(json.dumps(OK))
assert w.kinds() == ["omr_fixed_lost", "omr_fixed_back"]

# stopped and the prefix no longer announced: a real loss, said at once, recovery paused
clock[0] = T0
w, a = start()
w.br = {"tv": {"omr": G}}
a.on_available("offline")
assert "recovery_paused" in w.kinds() and "omr_fixed_lost" in w.kinds(), w.events
lost = next(x for k, x in w.events if k == "omr_fixed_lost")
assert f"(now: {G})" in lost and "Thread Anchor is stopped" in lost, lost

# a retained "offline" at the start of MG, prefix gone: still waits RETAINED_GRACE_S (2.40.8)
clock[0] = T0
w = W()
w.br = {"tv": {"omr": G}}
a = A.Anchor(w, clock=lambda: clock[0])
a.on_state(json.dumps(OK), retained=True)
a.on_available("offline", retained=True)
assert w.events == [] and a.blocked() is None

# French text
i18n = open(os.path.join(MG, "i18n.py"), encoding="utf-8").read()
assert "Thread Anchor arrêté : préfixe OMR {p} encore publié, plus imposé" in i18n
print("OK")

"""2.40.8: (1) a retained thread_anchor/state (sent again by the broker when MG connects, e.g. after a
restart of Home Assistant) with a prefix error waits RETAINED_GRACE_S for a live state: no
"recovery paused" nor "prefix no longer in place" then "back" in the same second; a live state is
handled at once as before, and a retained error still there after the grace time is said. (2) the
restart note says "1 node of 25" in the singular. Made-up values only."""
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
import i18n  # noqa: E402

A.ANCHOR_FILE = os.path.join(tempfile.mkdtemp(), "anchor.json")
P = "fd00:aaaa:bbbb:1::/64"
OK = {"wanted": P, "enforced": True, "favored": P, "error": None}
BAD = {"wanted": P, "enforced": False, "favored": P, "current": None, "error": "border router not answering"}


class W:
    def __init__(self):
        self.lock, self.events, self.dirty, self.usb_links, self.br, self.matter = threading.RLock(), [], False, None, {}, {}
        self.fixed = []

    def emit(self, kind, text, **data):
        self.events.append(kind)

    def omr_fixed(self, omr, now=None):
        self.fixed.append(bool(omr and omr.get("error")))

    def _omr_now(self):
        return set()


T0 = 1763370000.0
clock = [T0]


def anchor():
    w = W()
    return w, A.Anchor(w, clock=lambda: clock[0])


# (1a) start of MG: retained state with an error, then the live state within the second
w, a = anchor()
a.on_state(json.dumps(BAD), retained=True)
assert w.events == [] and a.blocked() is None and True not in w.fixed, (w.events, w.fixed)
a.on_state(json.dumps(OK))                       # live: the prefix is in place
clock[0] += 120
a.update(now=clock[0])
assert "recovery_paused" not in w.events and "recovery_resumed" not in w.events and True not in w.fixed, w.events

# (1b) the retained error is still the truth after the grace time: said then (recovery cycle)
clock[0] = T0
w, a = anchor()
a.on_state(json.dumps(BAD), retained=True)
a.update(now=T0 + A.RETAINED_GRACE_S - 1)
assert w.events == [] and a.blocked() is None
a.update(now=T0 + A.RETAINED_GRACE_S + 1)
assert w.events == ["recovery_paused"] and a.blocked() and w.fixed[-1] is True, (w.events, w.fixed)

# (1c) a live state with an error: at once, as before
clock[0] = T0
w, a = anchor()
a.on_state(json.dumps(BAD))
assert w.events == ["recovery_paused"] and w.fixed[-1] is True

# (1d) a retained "offline" availability: the stopped add-on waits too, a live "online" ends it
clock[0] = T0
w, a = anchor()
a.on_state(json.dumps(OK), retained=True)
a.on_available("offline", retained=True)
assert w.events == [] and a.blocked() is None
a.on_available("online")
a.update(now=T0 + 120)
assert w.events == [] and a.blocked() is None

# watcher passes the retain flag of the message
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
assert 'retained=bool(getattr(msg, "retain", False))' in src

# (2) restart note: singular and plural
i18n._LANG = "fr"
one = i18n.tn("{n} node out of {total} did not come back", "{n} of {total} nodes did not come back", 1, total=25)
two = i18n.tn("{n} node out of {total} did not come back", "{n} of {total} nodes did not come back", 2, total=25)
assert one == "1 node sur 25 n'est pas revenue" and two == "2 nodes sur 25 ne sont pas revenues", (one, two)
one = i18n.tn("{n} node out of {total} is reconnecting, nothing to do", "{n} of {total} nodes are reconnecting, nothing to do", 1, total=25)
assert one == "1 node sur 25 se reconnecte, rien à faire", one
i18n._LANG = "en"
assert i18n.tn("{n} node out of {total} did not come back", "{n} of {total} nodes did not come back", 1, total=25) == \
    "1 node out of 25 did not come back"
nt = open(os.path.join(MG, "nodetable.py"), encoding="utf-8").read()
assert 'tn("{n} node out of {total} did not come back"' in nt and 'tn("{n} node out of {total} is reconnecting, nothing to do"' in nt
print("OK")

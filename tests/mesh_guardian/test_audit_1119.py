"""2.40.7 (audit of 19 November): (1) a Wi-Fi node that exhausted its recovery pings gets no Thread
advice; (2) check_global under a lock (one change said once); (3) the recovery log lines go through
the translations; (4) the OMR prefix still published but no longer imposed is said so, not "no
longer in place (now: the same prefix)"; (5) a Google Cast / AirPlay device offline says its kind.
Made-up values only."""
import os
import sys
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import advice  # noqa: E402

src_i18n = open(os.path.join(MG, "i18n.py"), encoding="utf-8").read()


def advice_of(row, **ctx):
    c = {"now": 2000.0, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
         "gave_up": {"0x4D"}, "ghosts": [], "omr_changes": 0}
    c.update(ctx)
    advice.advise([row], [], c)
    return row["advice"] or ""


# (1) Wi-Fi: power, never the Thread diagnostic; Thread: unchanged
base = {"id": "0x4D", "name": "Prise demo", "area": "Cave", "available": False, "battery": False, "since": 1000.0}
wifi = advice_of(dict(base, network="wifi"))
assert wifi == advice.t("Check its power") and "Thread" not in wifi, wifi
assert advice_of(dict(base, network="thread")) == advice.t("Unreachable: Thread diagnostic to do")

# (2) one lock around the comparison with the previous values
w = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
cg = w[w.index("    def check_global("):w.index("    def _check_global(")]
assert "with self.global_lock:" in cg and "self._check_global()" in cg
assert "self.global_lock = threading.RLock()" in w

# (3) no recovery log line written in English only
r = open(os.path.join(MG, "reattach.py"), encoding="utf-8").read()
assert 'LOG.info("recovery of' not in r and 'LOG.warning("recovery of' not in r
for key in ("Recovery of {node}: back, fail-safe not closed (it expires by itself)", "Recovery of {node}: {err}",
            "Recovery of {node}: no answer to ArmFailSafe ({err})", "Recovery of {node}: ArmFailSafe refused ({res})",
            "Recovery of {node}: ConnectNetwork refused ({res})"):
    assert f't("{key}"' in r and f'"{key}"' in src_i18n, key

# (4) the network note when the prefix is still published but no longer imposed
P = "fd00:aaaa:bbbb:1::/64"
still = advice.t("OMR prefix {p} still published, no longer imposed: the other border routers (Google TV…) can publish "
                 "their prefixes again and the network change its prefix", p=P)
assert "{p}" not in still and P in still
a = open(os.path.join(MG, "advice.py"), encoding="utf-8").read()
assert 'omr.get("current") == omr.get("wanted")' in a and "still published, no longer imposed" in a
assert 'omr.get("current") == omr.get("wanted")' in w and 't("OMR prefix {p} still published, no longer imposed"' in w

# (5) kind of the device in the offline event
assert 'Google Cast "{name}" offline' in w and 'AirPlay "{name}" offline' in w
assert "Google Cast « {name} » hors ligne" in src_i18n and "AirPlay « {name} » hors ligne" in src_i18n
print("OK")

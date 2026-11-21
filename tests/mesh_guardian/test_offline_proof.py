"""2.40.9: "check its power / its batteries" for an offline Thread node only with proof (no answer to the
ping and no neighbor heard it recently); otherwise "cause unknown". Made-up values only."""
import sys
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import advice  # noqa: E402


def advice_of(**kw):
    row = {"id": "0x4D", "name": "Prise demo", "area": "Cave", "network": "thread", "available": False,
           "battery": False, "since": 1000.0}
    row.update(kw)
    advice.advise([row], [], {"now": 2000.0, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {},
                              "history": lambda rid: [], "gave_up": set(), "ghosts": [], "omr_changes": 0})
    return row["advice"] or ""


unknown = advice.t("Offline: cause unknown, the recovery attempt looks for it")
# proof: the ping got no answer, nobody heard it
assert advice_of(ping_ok=False) == advice.t("Check its power")
assert advice_of(ping_ok=False, battery=True) == advice.t("Check its batteries")
# no proof: no ping result yet, or absent from the topology only
assert advice_of(ping_ok=None) == unknown
assert advice_of() == unknown
# heard by a neighbor: never a power advice
assert "power" not in advice_of(ping_ok=False, heard_by={"by": "Voisine", "ago_s": 60, "rssi": -70}).lower()
# French text exists
src = open(MG + "/i18n.py", encoding="utf-8").read()
assert "Hors ligne : cause inconnue" in src
print("OK")

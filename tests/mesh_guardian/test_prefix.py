"""Essai du diagnostic « restee sur l'ancien prefixe » : les border routers changent le prefixe OMR,
une node ne suit pas ; journal, conseil, note reseau, tentative de recuperation expliquee.
Methodes extraites de watcher.py (zeroconf et paho absents ici)."""
import ast
import logging
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

import advice  # noqa: E402
import reattach  # noqa: E402
from i18n import t  # noqa: E402

src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
want = ("_omr_now", "stale_prefix", "omr_episodes_24h", "_load_prefixes", "_save_prefixes", "matter_gone")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
consts = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("OMR_LEFT_KEEP_S", "OMR_EPISODE_S")]
assert len(consts) == 2
import json  # noqa: E402

TMP = tempfile.mkdtemp()


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def save_json(path, data, **kw):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, **kw)


mod = ast.Module(body=consts + [ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
ns = {"LOG": logging.getLogger("x"), "time": time, "t": t, "load_json": load_json, "save_json": save_json,
      "PREFIXES_FILE": os.path.join(TMP, "prefixes.json")}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

OLD, NEW = "fdc0:6359:d5be:1::/64", "fdd7:20e4:8187:1::/64"


class W(ns["W"]):
    def __init__(self):
        self.lock, self.events, self.healer, self.dirty = threading.RLock(), [], None, False
        self.br = {"salon": {"online": True, "omr": NEW}, "cuisine": {"online": True, "omr": NEW}}
        self.matter = {"000000000000005A": {"online": True, "prefix": OLD},
                       "0000000000000036": {"online": True, "prefix": NEW},
                       "00000000000000AA": {"online": True, "prefix": "fd59:30d4:9210:dc15::/64"}}   # Wi-Fi
        self.omr_left, self.omr_changes = {}, []

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def br_relevant(self, b):
        return True

    def node_disp(self, node):
        return "Prise Lave-linge Miele [0x5A]"

    def node_name(self, node):
        return "Prise Lave-linge Miele (Buanderie)"


w = W()
at = time.mktime(time.strptime("2026-11-17 06:17:38", "%Y-%m-%d %H:%M:%S"))
w.omr_left[OLD] = (at, "Google TV Salon")
# la node restee sur l'ancien prefixe est reconnue ; celle qui a suivi et la node Wi-Fi non
st = w.stale_prefix("5A")
assert st == {"prefix": OLD, "br": "Google TV Salon", "t": at, "at": "06:17"}, st
assert w.stale_prefix("36") is None and w.stale_prefix("AA") is None and w.stale_prefix("FF") is None
# perte de l'annonce mDNS : l'evenement dit la cause
w.matter_gone("000000000000005A", "removed")
kinds = [k for k, _ in w.events]
assert kinds == ["matter_offline", "node_stale_prefix"], kinds
assert "fdc0:6359:d5be:1::/64" in w.events[1][1] and "Google TV Salon" in w.events[1][1] and "06:17" in w.events[1][1]
# si un border router publie de nouveau l'ancien prefixe, ce n'est plus la cause
w.br["salon"]["omr"] = OLD
assert w.stale_prefix("5A") is None
w.br["salon"]["omr"] = NEW
# conserve entre deux demarrages
w._save_prefixes()
w2 = W()
w2.matter["000000000000005A"]["prefix"] = None
w2._load_prefixes()
assert w2.stale_prefix("5A")["br"] == "Google TV Salon"

# changements de prefixe : une rafale de 30 min compte pour un
now = time.time()
w.omr_changes = [now - 20 * 3600 + i * 60 for i in range(13)] + [now - 11 * 3600, now - 600, now - 30 * 3600]
assert w.omr_episodes_24h() == 3, w.omr_episodes_24h()

# conseil d'une node indisponible : la cause, pas « verifier l'alimentation »
row = {"id": "0x5A", "name": "Prise Lave-linge Miele", "area": "Buanderie", "network": "thread", "available": False,
       "since": now - 3600, "stale_prefix": st}
other = {"id": "0x36", "name": "Prise Chauffe Eau", "area": "Buanderie", "network": "thread", "available": True}
ctx = {"now": now, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 3}
notes = advice.advise([row, other], [], ctx)
assert row["advice"] == t("Stayed on the old address prefix after {br} changed it at {at}", br="Google TV Salon", at="06:17")
assert OLD in row["advice_detail"]
assert any(lvl == "warn" and "3" in txt for lvl, txt in notes), notes
ctx["omr_changes"] = 1
assert not any(lvl == "warn" for lvl, _ in advice.advise([dict(row)], [], ctx))

# tentative de recuperation : pas tentee, la raison est rendue a la page
r = reattach.Reattach.__new__(reattach.Reattach)
r.recovering, r.busy, r.results = set(), threading.Lock(), {}


class H:
    lock = threading.Lock()
    nodes = {"000000000000005A": {"name": "Prise Lave-linge Miele", "area": "Buanderie"}}


r.h, r.w, r.live = H(), w, None
r._cached = lambda nid: {"0/49/1": [{"networkID": "AAA=", "connected": True}], "0/49/65529": [reattach.CONNECT_NETWORK]}
res = r.recover_node("000000000000005A")
assert res == {"result": "stale", "prefix": OLD, "br": "Google TV Salon", "at": "06:17"}, res
assert not r.busy.locked() and not r.recovering
print("OK")

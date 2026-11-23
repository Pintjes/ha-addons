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
want = ("_omr_now", "stale_prefix", "omr_episodes_24h", "_load_prefixes", "_save_prefixes", "matter_gone", "usb_link",
        "omr_fixed", "favored_omr")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
consts = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("OMR_LEFT_KEEP_S", "OMR_EPISODE_S", "OMR_FIXED_GRACE_S")]
assert len(consts) == 3
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
ns = {"LOG": logging.getLogger("x"), "time": time, "t": t, "load_json": load_json, "save_json": save_json, "json": json,
      "PREFIXES_FILE": os.path.join(TMP, "prefixes.json")}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

OLD, NEW = "fd00:cccc:dddd:1::/64", "fd00:aaaa:bbbb:1::/64"


class W(ns["W"]):
    def __init__(self):
        self.lock, self.events, self.healer, self.dirty = threading.RLock(), [], None, False
        self.br = {"salon": {"online": True, "omr": NEW}, "cuisine": {"online": True, "omr": NEW}}
        self.matter = {"000000000000004D": {"online": True, "prefix": OLD},
                       "0000000000000036": {"online": True, "prefix": NEW},
                       "00000000000000AA": {"online": True, "prefix": "fd00:eeee:ffff:1::/64"}}   # Wi-Fi
        self.omr_left, self.omr_changes, self.usb_links = {}, [], None
        self.omr_fixed_off, self.omr_fixed_said = None, False

    def emit(self, kind, text, **data):
        self.events.append((kind, text))

    def br_relevant(self, b):
        return True

    def node_disp(self, node):
        return "Prise Exemple [0x4D]"

    def node_name(self, node):
        return "Prise Exemple (Cave)"


w = W()
at = time.mktime(time.strptime("2026-11-17 06:17:38", "%Y-%m-%d %H:%M:%S"))
w.omr_left[OLD] = (at, "Routeur tiers A")
# la node restee sur l'ancien prefixe est reconnue ; celle qui a suivi et la node Wi-Fi non
st = w.stale_prefix("4D")
assert st == {"prefix": OLD, "br": "Routeur tiers A", "t": at, "at": "06:17"}, st
assert w.stale_prefix("36") is None and w.stale_prefix("AA") is None and w.stale_prefix("FF") is None
# perte de l'annonce mDNS : l'evenement dit la cause
w.matter_gone("000000000000004D", "removed")
kinds = [k for k, _ in w.events]
assert kinds == ["matter_offline", "node_stale_prefix"], kinds
assert "fd00:cccc:dddd:1::/64" in w.events[1][1] and "Routeur tiers A" in w.events[1][1] and "06:17" in w.events[1][1]
# si un border router publie de nouveau l'ancien prefixe, ce n'est plus la cause
w.br["salon"]["omr"] = OLD
assert w.stale_prefix("4D") is None
w.br["salon"]["omr"] = NEW
# conserve entre deux demarrages
w._save_prefixes()
w2 = W()
w2.matter["000000000000004D"]["prefix"] = None
w2._load_prefixes()
assert w2.stale_prefix("4D")["br"] == "Routeur tiers A"

# changements de prefixe : une rafale de 30 min compte pour un
now = time.time()
w.omr_changes = [now - 20 * 3600 + i * 60 for i in range(13)] + [now - 11 * 3600, now - 600, now - 30 * 3600]
assert w.omr_episodes_24h() == 3, w.omr_episodes_24h()

# conseil d'une node indisponible : la cause, pas « verifier l'alimentation »
row = {"id": "0x4D", "name": "Prise Exemple", "area": "Cave", "network": "thread", "available": False,
       "since": now - 3600, "stale_prefix": st}
other = {"id": "0x36", "name": "Prise Voisine", "area": "Cave", "network": "thread", "available": True}
ctx = {"now": now, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 3}
notes = advice.advise([row, other], [], ctx)
assert row["advice"] == t("Stayed on the old address prefix after {br} changed it at {at}", br="Routeur tiers A", at="06:17")
assert OLD in row["advice_detail"]
assert any(lvl == "warn" and "3" in txt for lvl, txt in notes), notes
ctx["omr_changes"] = 1
assert not any(lvl == "warn" for lvl, _ in advice.advise([dict(row)], [], ctx))

# tentative de recuperation : pas tentee, la raison est rendue a la page
r = reattach.Reattach.__new__(reattach.Reattach)
r.recovering, r.busy, r.results = set(), threading.Lock(), {}


class H:
    lock = threading.Lock()
    nodes = {"000000000000004D": {"name": "Prise Exemple", "area": "Cave"}}


r.h, r.w, r.live, r.table = H(), w, None, None
r._cached = lambda nid: {"0/49/1": [{"networkID": "AAA=", "connected": True}], "0/49/65529": [reattach.CONNECT_NETWORK]}
r.h.matter_command = lambda cmd, args, timeout=0: {"fd00:cccc:dddd:1:e:f:1:2": False}


class Live:
    def heard_by(self, ext):
        assert ext == 0x1A2B3C4D5E6F7081
        return [("0000000000000031", 42.0, -69)]


H.nodes["0000000000000031"] = {"name": "Spot Entree 2"}
r.live = Live()
import base64  # noqa: E402

r._cached = lambda nid: {"0/49/1": [{"networkID": "AAA=", "connected": True}], "0/49/65529": [reattach.CONNECT_NETWORK],
                         "0/51/0": [{"7": 4, "4": base64.b64encode(bytes.fromhex("1a2b3c4d5e6f7081")).decode()}]}
w.events.clear()
res = r.recover_node("000000000000004D")
assert res == {"result": "pending"}, res
deadline = time.time() + 5
while r.recovering and time.time() < deadline:
    time.sleep(0.05)
assert not r.busy.locked() and not r.recovering
assert [k for k, _ in w.events] == ["recover_node", "recover_alive", "recover_result"], w.events
alive_txt = w.events[1][1]
assert "Spot Entree 2 (-69 dBm)" in alive_txt and "42 s" in alive_txt and "fd00:cccc:" in alive_txt, alive_txt
assert r.results["000000000000004D"]["result"] == "stale" and OLD in r.results["000000000000004D"]["text"]

# il repond au ping mais ne s'annonce plus : annoncee a sa place (essai), puis retiree
w.br["salon"]["omr"], w.br["cuisine"]["omr"] = OLD, OLD   # plus d'ancien prefixe : pas « stale »
w.matter["000000000000004D"]["online"] = False
calls = []
w.proxy_announce = lambda nid, ips: calls.append(("announce", nid, ips)) or True
w.proxy_withdraw = lambda nid: calls.append(("withdraw", nid))
w.stop = threading.Event()
reattach.PROXY_SETTLE_S = 0
r.h.matter_command = lambda cmd, args, timeout=0: {"fd00:cccc::1": True}
sent = []


def command(node_id, cluster, name, payload, timeout=90):
    sent.append(name)
    raise RuntimeError("Operation aborted")


r._command = command
r._is_back = lambda nid: False
reattach.PING_BACK_WAIT_S = 0
w.events.clear()
assert r.recover_node("000000000000004D") == {"result": "pending"}
deadline = time.time() + 5
while r.recovering and time.time() < deadline:
    time.sleep(0.05)
assert calls == [("announce", "000000000000004D", ["fd00:cccc::1"]), ("withdraw", "000000000000004D")], calls
# 2.40.14: it answers the network ping, so nothing heavier is sent (no ArmFailSafe), never "out of reach"
assert sent == [] and "recover_proxy" in [k for k, _ in w.events], sent
assert r.results["000000000000004D"]["result"] == "reachable", r.results["000000000000004D"]

# lien USB/IP coupe (add-on USB/IP Link) : note reseau rouge avec la raison ; rien quand il est attache
ctx = {"now": now, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 0,
       "usb_links": {"server": "192.168.1.10", "server_ok": False,
                     "devices": [{"name": "ZBT-2", "attached": False, "since": at, "error": None}]}}
notes = advice.advise([], [], ctx)
assert notes == [("bad", t("{name}: USB/IP link cut since {at}, the radio it carries is out", name="ZBT-2", at="06:17")
                  + " (" + t("{server} does not answer", server="192.168.1.10") + ")")], notes
ctx["usb_links"]["devices"][0]["attached"] = True
assert advice.advise([], [], ctx) == []
# evenements : rien au premier etat attache, puis coupe, puis retabli
wu = W()
st_on = json.dumps({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "attached": True}]})
st_off = json.dumps({"server": "192.168.1.10", "devices": [{"name": "ZBT-2", "attached": False, "error": "x"}]})
wu.usb_link(st_on)
wu.usb_link(st_on)
wu.usb_link(st_off)
wu.usb_link(st_off)
wu.usb_link(st_on)
assert [k for k, _ in wu.events] == ["usb_link_lost", "usb_link_back"], wu.events
wu2 = W()
wu2.usb_link(st_off)   # premier etat deja coupe : dit tout de suite
assert [k for k, _ in wu2.events] == ["usb_link_lost"]

# prefixe OMR impose par USB/IP Link (cle "omr" de usbip_link/state)
P = "fd00:aaaa:bbbb:1::/64"
ok = {"wanted": P, "preference": "high", "mode": "custom", "current": P, "enforced": True, "error": None}
gap = dict(ok, mode="auto", current=None, enforced=False)              # creux sans erreur (OTBR qui redemarre)
err = dict(gap, mode=None, error="404 No such container")              # OTBR arrete
wo = W()
wo.omr_fixed(ok, now=1000)
assert wo.events == []                                   # premier etat en place : rien
wo.omr_fixed(gap, now=1010)
wo.omr_fixed(gap, now=1050)
assert wo.events == []                                   # creux court : rien
wo.omr_fixed(ok, now=1060)
assert wo.events == [] and wo.omr_fixed_off is None      # reimpose dans la minute : toujours rien
wo.omr_fixed(gap, now=2000)
wo.omr_fixed(gap, now=2061)                              # toujours absent apres 60 s : dit une fois
wo.omr_fixed(gap, now=2100)
assert [k for k, _ in wo.events] == ["omr_fixed_lost"], wo.events
assert "auto" in wo.events[0][1]
wo.omr_fixed(ok, now=2200)
assert [k for k, _ in wo.events] == ["omr_fixed_lost", "omr_fixed_back"]
wo2 = W()
wo2.omr_fixed(err, now=10)                               # erreur : dit tout de suite, avec la cause
assert [k for k, _ in wo2.events] == ["omr_fixed_lost"] and "404" in wo2.events[0][1]
wo3 = W()
wo3.usb_link(json.dumps({"server": "s", "devices": [], "omr": err}))   # lu depuis usbip_link/state
assert [k for k, _ in wo3.events] == ["omr_fixed_lost"]
wo3.usb_link(json.dumps({"server": "s", "devices": []}))               # option videe : plus rien a surveiller
assert wo3.omr_fixed_off is None and len(wo3.events) == 1
# note A faire : rouge avec erreur, orange apres 60 s sans erreur, rien pendant le creux ou en place
ctx = {"now": 5000, "tried": {}, "forced": {}, "weak_since": {}, "unstable": {}, "history": lambda rid: [],
       "gave_up": set(), "ghosts": [], "omr_changes": 0, "usb_links": {"server": "s", "devices": [], "omr": err},
       "omr_fixed_off": 4990}
notes = advice.advise([], [], ctx)
assert len(notes) == 1 and notes[0][0] == "bad" and "404" in notes[0][1] and P in notes[0][1], notes
ctx["usb_links"]["omr"] = gap
assert advice.advise([], [], ctx) == []
ctx["omr_fixed_off"] = 4900
assert [n[0] for n in advice.advise([], [], ctx)] == ["warn"]
ctx["usb_links"]["omr"] = ok
assert advice.advise([], [], ctx) == []

# ecritures simultanees du meme fichier (2.28.0 : « No such file » au demarrage) : aucune ne perd
import store  # noqa: E402
path, errors = os.path.join(TMP, "same.json"), []


def writer(i):
    for _ in range(30):
        try:
            store.save_json(path, {"i": i})
        except OSError as err:
            errors.append(err)


ths = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
[x.start() for x in ths]
[x.join() for x in ths]
assert not errors, errors[:2]
assert store.load_json(path)["i"] in range(6) and not [f for f in os.listdir(TMP) if f.endswith(".tmp")]
print("OK")

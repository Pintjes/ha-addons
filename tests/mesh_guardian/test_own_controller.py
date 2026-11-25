"""2.40.17: the controller node of the Matter Server of Home Assistant announces itself on the fabric
from this machine (LAN address of the host). It is not a node of the network: left out of the node
prefixes, of the counts of known / online / missing nodes and of the file of known nodes.
Methods extracted from watcher.py (zeroconf absent). Made-up values only."""
import ast
import os
import sys
import threading
import time
import types

MG = sys.argv[1]
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("own_announcement", "_int16")]
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
want = ("summary", "_own_nodes", "_save_known", "prune_gone")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(funcs) == 2 and len(body) == len(want)
mod = ast.Module(body=funcs + [ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])],
                 type_ignores=[])
HOST, THREAD, LAN = "fd00:eeee:ffff:1::5", "fd00:aaaa:bbbb:1::/64", "fd00:eeee:ffff:1::/64"
saved = []
ns = {"time": time, "t": lambda s, **k: s.format(**k) if k else s, "local_addresses": lambda: {HOST},
      "now_iso": lambda: "x", "KNOWN_FILE": "known.json", "save_json": lambda f, v, **k: saved.append(list(v)),
      "LOG": types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

w = ns["W"]()
w.lock = threading.RLock()
w.br, w.cast, w.pending, w.bursts_count, w.events_count, w.last_event = {}, {}, {}, 0, 0, None
w.br_relevant = lambda b: True
w.omr_episodes_24h = lambda: 0
w.radio, w.leader_saved, w.quiet = None, None, False
w._settle = lambda raw, mine: raw
w._not_thread = lambda k: False
NODE, CTRL, OFF = "000000000000F001", "000000000000F002", "000000000000F003"
w.matter = {NODE: {"online": True, "prefix": THREAD, "addrs": ["fd00:aaaa:bbbb:1::1"]},
            CTRL: {"online": True, "prefix": LAN, "addrs": [HOST + "%eth0"]},
            OFF: {"online": False, "prefix": THREAD, "addrs": []}}

s = w.summary()
assert s["node_prefixes"] == {THREAD: 1}, s["node_prefixes"]             # no LAN prefix any more
assert (s["matter_online"], s["matter_known"], s["matter_missing"]) == (1, 2, 1), s
assert s["matter_missing_ids"] == ["0xF003"]
w.matter[CTRL]["online"] = False                                          # gone from mDNS: not "missing" either
s = w.summary()
assert s["matter_missing"] == 1 and s["matter_known"] == 2
w.matter[CTRL]["online"] = True

# the file of known nodes: without it
w._save_known()
assert saved[-1] == [NODE, OFF], saved[-1]
# saved first before its addresses were known (new node), saved again once it is recognized
saved.clear()
w.healer = types.SimpleNamespace(prune=lambda ids: 0)
w.live = types.SimpleNamespace(connected=True, node_ids=lambda: {0xF001, 0xF003}, prune=lambda ids: 0)
w.ghosts, w.reattach, w.advisor = [], None, None
w.prune_gone()
assert saved == [[NODE, OFF]] and w.ghosts == [], (saved, w.ghosts)
w.prune_gone()
assert len(saved) == 1                                                    # nothing changed: not written again
print("OK")

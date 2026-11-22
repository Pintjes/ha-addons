"""2.40.11: "Remove from the list" works for a border router online too (its Thread turned off on purpose
while it still announces itself). It leaves the list and its entity; its announcements are ignored while
it is announced as it was, and it comes back as a new border router when its announcement went away and
returned, or when its Thread role changes. Methods extracted from watcher.py (zeroconf absent).
Made-up values only."""
import ast
import os
import sys
import tempfile
import threading
import time
import types

MG = sys.argv[1]
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
want = ("forget_br", "_drop_br", "_clear_br_entity", "_br_still_forgotten", "_save_br_forgotten",
        "_load_br_forgotten", "handle_removed")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
mod = ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
store = {}
d = tempfile.mkdtemp()
ns = {"time": time, "T_MESHCOP": "_meshcop._udp.local.", "T_MATTER": "_matter._tcp.local.", "COMPANIONS": (),
      "DISCOVERY": "homeassistant", "BASE": "mesh_guardian", "BR_SILENT_S": 900, "BR_FORGOTTEN_KEEP_S": 30 * 86400,
      "BR_FORGOTTEN_FILE": os.path.join(d, "br_forgotten.json"), "t": lambda s, **k: s.format(**k),
      "LOG": types.SimpleNamespace(warning=lambda *a, **k: None),
      "save_json": lambda f, v, **k: store.__setitem__(f, __import__("json").loads(__import__("json").dumps(v))),
      "load_json": lambda f: store.get(f)}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

# update_br checks the removed list first, before anything else is touched
ub = src[src.index("    def update_br("):src.index("    def ", src.index("    def update_br(") + 10)]
assert ub.index("_br_still_forgotten(key, role") < ub.index("self.br_by_name[name] = key")


class Mqtt:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload, retain))


KEY = "a1b2c3d4e5f60718"
NAME = "Demo TV._meshcop._udp.local."


def watch():
    w = ns["W"]()
    w.lock, w.dirty, w.mqtt = threading.RLock(), False, Mqtt()
    w.br = {KEY: {"online": True, "role": "child", "label": "TV demo"}}
    w.br_names = {KEY: {"name": "TV demo", "detached": []}}
    w.br_by_name = {NAME: KEY}
    w.published = {f"homeassistant/sensor/mesh_guardian/br_{KEY}/config"}
    w.discovered_br = {(KEY, "x")}
    w.br_forgotten = {}
    w._save_br_names = lambda: None
    w.br_label = lambda b: b.get("label")
    w.events = []
    w.emit = lambda kind, *a, **k: w.events.append(kind)
    w.gone = []
    w.br_gone = lambda key, reason: w.gone.append(key)
    return w


# an online border router can be removed: list, name, entity (empty retained discovery) all cleared
w = watch()
assert w.forget_br(KEY) is True
assert KEY not in w.br and KEY not in w.br_names and NAME not in w.br_by_name
assert ("homeassistant/sensor/mesh_guardian/br_" + KEY + "/config", b"", True) in w.mqtt.sent
assert not w.published and not w.discovered_br and w.events == ["br_removed"]
assert w.br_forgotten[KEY]["role"] == "child" and w.br_forgotten[KEY]["names"] == [NAME]
assert store[ns["BR_FORGOTTEN_FILE"]][KEY]["role"] == "child"      # kept across a restart
assert w.forget_br("unknown") is False

# still announced as it was: ignored (no new entry, no "appeared")
now = time.time()
assert w._br_still_forgotten(KEY, "child", now + 60) is True
assert w._br_still_forgotten(KEY, "child", now + 400) is True       # the 5-min rebrowse keeps it fresh
# its Thread role changes: it comes back
assert w._br_still_forgotten(KEY, "router", now + 500) is False and KEY not in w.br_forgotten
assert KEY not in store[ns["BR_FORGOTTEN_FILE"]]

# nothing heard for longer than BR_SILENT_S: its next announcement is a return
w = watch()
w.forget_br(KEY)
assert w._br_still_forgotten(KEY, "child", time.time() + 901) is False

# its announcement withdrawn: removed from the list of the forgotten, no "offline" alert
w = watch()
w.forget_br(KEY)
w.handle_removed(ns["T_MESHCOP"], NAME, "withdrawn")
assert w.gone == [] and KEY not in w.br_forgotten

# an offline one removed: nothing kept, its next announcement is simply new
w = watch()
w.br[KEY]["online"] = False
assert w.forget_br(KEY) is True and w.br_forgotten == {}

# a restart keeps the removal (time of the last announcement reset to the start)
w2 = watch()
store[ns["BR_FORGOTTEN_FILE"]] = {KEY: {"names": [NAME], "role": "child", "t": time.time() - 3600, "seen": 0}}
w2._load_br_forgotten()
assert w2._br_still_forgotten(KEY, "child", time.time() + 10) is True
store[ns["BR_FORGOTTEN_FILE"]] = {KEY: {"names": [NAME], "role": "child", "t": time.time() - 31 * 86400}}
w2._load_br_forgotten()
assert w2.br_forgotten == {}                                          # forgotten after 30 days

# the page: the button for an online border router too
page = open(os.path.join(MG, "web", "index.html"), encoding="utf-8").read()
assert "const remove = `<div" in page and "br_remove_online" not in page
assert "if (!b || !confirm(" in page
print("OK")

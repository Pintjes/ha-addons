"""Merging of the announcements of one border router (methods extracted from watcher.py, which
cannot be imported here: zeroconf and paho are missing). Made-up values only (documentation
address ranges)."""
import ast
import logging
import sys

src = open(sys.argv[1] + "/watcher.py", encoding="utf-8").read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and any(
    isinstance(m, ast.FunctionDef) and m.name == "_br_twin" for m in n.body))
want = ("_br_addrs", "_br_twin", "_br_replaced", "_br_take_over", "_br_fold_stale")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in want]
assert len(body) == len(want), [m.name for m in body]
mod = ast.Module(body=[ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
ns = {"LOG": logging.getLogger("x")}
exec(compile(ast.fix_missing_locations(mod), "watcher_extract", "exec"), ns)


class W(ns["W"]):
    def __init__(self):
        self.br, self.br_names, self.cleared, self.saves = {}, {}, [], 0

    def _save_br_names(self):
        self.saves += 1

    def _clear_br_entity(self, key):
        self.cleared.append(key)

    def _drop_br(self, key):
        self.br.pop(key, None)
        self.br_names.pop(key, None)
        self._clear_br_entity(key)

    def br_label(self, b):
        return b.get("label") or "?"


ROUTER_A = {"addrs": ["192.0.2.10", "2001:db8::a", "fe80::1"], "ext_pan": "abcd", "online": True}
ROUTER_B = {"addrs": ["192.0.2.20", "2001:db8::b", "fe80::2"], "ext_pan": "abcd", "online": True}

# new announcement of the same device: it takes over the card, its name and its history
w = W()
w.br = {"old": dict(ROUTER_A, label="Router A"), "b": dict(ROUTER_B, label="Router B")}
w.br_names = {"old": {"name": "Router A", "detached": [1.0]}, "b": {"name": "Router B", "detached": []}}
new = dict(ROUTER_A, addrs=["192.0.2.10", "fe80::1"])
assert w._br_twin("new", new) == "old" and w._br_twin("new", dict(new, ext_pan="other")) is None
assert w._br_twin("new", {"addrs": ["fe80::1"], "ext_pan": "abcd"}) is None      # link-local only: tells nothing
assert w._br_twin("b", ROUTER_B) is None
w._br_take_over("old", "new")
assert set(w.br) == {"new", "b"} and w.br["new"]["label"] == "Router A"
assert w.br_names["new"] == {"name": "Router A", "detached": [1.0], "replaces": ["old"]} and w.cleared == ["old"]
# the old announcement, still on the network, is ignored while the new one is online
assert w._br_replaced("old") and not w._br_replaced("new") and not w._br_replaced("b")
w.br["new"]["online"] = False
assert not w._br_replaced("old")                                                   # otherwise it can come back
# ... and if it comes back, it takes the card over in turn, without a loop
w._br_take_over("new", "old")
assert set(w.br) == {"old", "b"} and w.br_names["old"]["replaces"] == ["new"]

# duplicate already there (earlier versions): the offline card is folded into the online one
w = W()
w.br = {"old": dict(ROUTER_A, online=False), "new": dict(ROUTER_A), "b": dict(ROUTER_B, online=False)}
w.br_names = {"old": {"name": "Router A", "detached": [1.0, 2.0]}, "new": {"name": None, "detached": [3.0]}}
assert w._br_fold_stale() and set(w.br) == {"new", "b"}                             # B offline without a twin: stays
assert w.br_names["new"] == {"name": "Router A", "detached": [1.0, 2.0, 3.0], "replaces": ["old"]}
assert w.br["new"]["label"] == "Router A" and not w._br_fold_stale()
# two cards online: nothing is guessed
w = W()
w.br = {"a": dict(ROUTER_A), "b2": dict(ROUTER_A)}
assert not w._br_fold_stale() and len(w.br) == 2
print("OK")

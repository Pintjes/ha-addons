"""2.40.10: an mDNS name conflict renames a Matter instance "<fabric>-<node> (5)". It is still the same
node: no "unknown to Home Assistant", no "unknown to the Matter Server", and the removal of the renamed
copy does not say the node is gone. A key that is not 16 hex digits is dropped from the known file.
Methods extracted from watcher.py (zeroconf absent). Made-up values only."""
import ast
import ipaddress
import os
import re
import sys
import threading
import time
import types

MG = sys.argv[1]
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
consts = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("NODE_HEX", "CONFLICT_SUFFIX")]
assert len(consts) == 2
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("matter_instance", "short", "prefix64", "txt_of")]
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("update_matter", "handle_removed", "_load_known")]
assert len(body) == 3
mod = ast.Module(body=consts + funcs + [ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])],
                 type_ignores=[])
FAB = "0011223344556677"
saved = {"known": None}
ns = {"re": re, "time": time, "ipaddress": ipaddress, "T_MATTER": "_matter._tcp.local.", "T_MESHCOP": "_meshcop._udp.local.",
      "COMPANIONS": (), "FABRIC": FAB, "PROXY_HOST": "mg-proxy-", "IPVersion": types.SimpleNamespace(All=0),
      "t": lambda s, **k: s, "fmt_duration": str, "KNOWN_FILE": "known.json", "LOG": types.SimpleNamespace(
          info=lambda *a, **k: None, warning=lambda *a, **k: None),
      "load_json": lambda f: saved["known"]}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)
mi = ns["matter_instance"]

# the parsing itself
assert mi(f"{FAB}-00000000000000AB") == (FAB, "00000000000000AB", False)
assert mi(f"{FAB}-00000000000000ab (5)") == (FAB, "00000000000000AB", True)
assert mi(f"{FAB}-00000000000000AB (12)") == (FAB, "00000000000000AB", True)
assert mi(f"{FAB}-00000000000000AB(5)") is None          # not a conflict suffix
assert mi(f"{FAB}-AB") is None and mi("no-dash-here") is None and mi("nodash") is None

w = ns["W"]()
w.lock, w.matter, w.quiet, w.dirty = threading.RLock(), {}, False, False
w._save_known = lambda: None
events, gone = [], []
w.emit = lambda kind, *a, **k: events.append(kind)
w.node_name = lambda node: "Lampe demo" if node == "00000000000000AB" else None
w.node_disp = lambda node: node
w.matter_gone = lambda node, reason: gone.append(node)


class Info:
    server = "AABBCCDDEEFF0011.local."
    port = 5540
    properties = {b"SII": b"2000"}

    @staticmethod
    def parsed_addresses(version):
        return ["fd00:aaaa:bbbb:1::23"]


# the node announces itself, then a renamed copy of its announcement shows up
w.update_matter(f"{FAB}-00000000000000AB._matter._tcp.local.", Info())
w.update_matter(f"{FAB}-00000000000000AB (5)._matter._tcp.local.", Info())
assert list(w.matter) == ["00000000000000AB"], w.matter               # one node, no "… (5)" key
assert "matter_appeared" not in events, events                      # never "unknown to Home Assistant"

# a renamed copy alone (its own name withdrawn) still keeps the node, under its real id
w.matter.clear()
w.update_matter(f"{FAB}-00000000000000CD (2)._matter._tcp.local.", Info())
assert list(w.matter) == ["00000000000000CD"]

# removal: the renamed copy going away is not the node going away
w.handle_removed(ns["T_MATTER"], f"{FAB}-00000000000000AB (5)._matter._tcp.local.", "removed")
assert gone == []
w.handle_removed(ns["T_MATTER"], f"{FAB}-00000000000000AB._matter._tcp.local.", "removed")
assert gone == ["00000000000000AB"]

# the known file: a key left by an older version is dropped at load
saved["known"] = ["00000000000000AB", "00000000000000AB (5)", "xyz"]
w.matter = {}
w._load_known()
assert list(w.matter) == ["00000000000000AB"], w.matter
print("OK")

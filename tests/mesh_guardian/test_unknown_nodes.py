"""Node annoncee sur le fabric mais inconnue du Matter Server (2.38.0) : ce que dit son annonce mDNS
(hote, adresses, port, TXT, premiere et derniere vue) est garde et rendu par /api/table (unknown_nodes)
et sous la note de la page. Rien de plus sur la radio. Methodes extraites de watcher.py (zeroconf absent).
Valeurs fictives uniquement."""
import ast
import ipaddress
import os
import sys
import threading
import time
import types

MG = sys.argv[1]
src = open(os.path.join(MG, "watcher.py"), encoding="utf-8").read()
tree = ast.parse(src)
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("txt_of", "unknown_records", "short", "prefix64",
                                                                              "local_addresses", "own_announcement")]
assert len(funcs) == 6, [f.name for f in funcs]
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Watch")
body = [m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name in ("update_matter", "unknown_nodes")]
assert len(body) == 2
mod = ast.Module(body=funcs + [ast.ClassDef(name="W", bases=[], keywords=[], body=body, decorator_list=[])], type_ignores=[])
FAB = "0011223344556677"
ns = {"time": time, "ipaddress": ipaddress, "T_MATTER": "_matter._tcp.local.", "FABRIC": FAB, "PROXY_HOST": "mg-proxy-",
      "IPVersion": types.SimpleNamespace(All=0), "t": lambda s, **k: s, "fmt_duration": str}
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)

w = ns["W"]()
w.lock, w.matter, w.quiet, w.dirty = threading.RLock(), {}, True, False
w._save_known = lambda: None
w.emit = lambda *a, **k: None
w.node_name = lambda node: None
w.node_disp = lambda node: node


class Info:
    server = "1A2B3C4D5E6F7081.local."
    port = 5540
    properties = {b"SII": b"5000", b"SAI": b"300", b"T": b"0", b"X": None, b"BIG": b"x" * 100}

    @staticmethod
    def parsed_addresses(version):
        return ["fd00:aaaa:bbbb:1:a:b:c:d", "fd00:9999:8888:0:1:2:3:4"]


name = f"{FAB}-000000000001B669._matter._tcp.local."
w.update_matter(name, Info())
n = w.matter["000000000001B669"]
assert n["host"] == "1A2B3C4D5E6F7081.local" and n["port"] == 5540, n
assert n["txt"] == {"SII": "5000", "SAI": "300", "T": "0", "X": ""}, n["txt"]   # valeur trop longue laissee de cote
first = n["first"]
time.sleep(0.01)
w.update_matter(name, Info())
assert n["first"] == first and n["last"] > first                                 # premiere vue gardee

# rendu : seulement les nodes de la liste « inconnues »
w.ghosts = []
assert w.unknown_nodes() == []
w.ghosts = ["000000000001B669"]
u = w.unknown_nodes()
assert len(u) == 1 and u[0]["id"] == "0x1B669" and u[0]["instance"] == f"{FAB}-000000000001B669", u
assert u[0]["host"] == "1A2B3C4D5E6F7081.local" and u[0]["addresses"] == sorted(Info.parsed_addresses(0))
assert u[0]["txt"]["SII"] == "5000" and u[0]["first"] == first

# une node inconnue sans annonce gardee (connue d'avant le demarrage) : les champs vides, pas d'erreur
w.matter["00000000000000FE"] = {"online": True, "addrs": []}
w.ghosts = ["00000000000000FE"]
u = w.unknown_nodes()
assert u[0]["host"] is None and u[0]["addresses"] == [] and u[0]["txt"] == {} and u[0]["first"] is None

# 2.40.1 : une annonce faite depuis cette machine (le noeud controleur du Matter Server de HA) n'est pas
# une node inconnue : ses adresses sont les notres (lues dans /proc/net/if_inet6 et fib_trie)
import tempfile  # noqa: E402

d = tempfile.mkdtemp()
with open(os.path.join(d, "if_inet6"), "w", encoding="ascii") as f:
    f.write("fd005959000000000000000000000020 02 40 00 80 eth0\n00000000000000000000000000000001 01 80 10 80 lo\n")
with open(os.path.join(d, "fib_trie"), "w", encoding="ascii") as f:
    f.write("Main:\n  +-- 0.0.0.0/0 3 0 5\n     |-- 192.168.10.20\n        /32 host LOCAL\n     |-- 192.168.10.255\n"
            "        /32 link BROADCAST\n     |-- 127.0.0.1\n        /32 host LOCAL\n")
own = ns["local_addresses"](os.path.join(d, "if_inet6"), os.path.join(d, "fib_trie"))
assert own == {"fd00:5959::20", "192.168.10.20"}, own
assert ns["own_announcement"]({"addrs": ["192.168.10.20", "fd00:5959::20"]}, own)
assert ns["own_announcement"]({"addrs": ["fd00:5959::20%eth0"]}, own)
assert not ns["own_announcement"]({"addrs": ["fd00:aaaa:bbbb:1:a:b:c:d"]}, own)
assert not ns["own_announcement"]({"addrs": ["192.168.10.20"]}, set())          # adresses locales inconnues : rien d'exclu
assert ns["local_addresses"](os.path.join(d, "absent"), os.path.join(d, "absent")) == set()

# la page affiche ces infos sous la note qui nomme la node
page = open(os.path.join(MG, "web", "index.html"), encoding="utf-8").read()
assert "function unknownInfo(" in page and "unknownInfo(txt)" in page and "D.unknown_nodes" in page
print("OK")

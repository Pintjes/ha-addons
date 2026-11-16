"""Essai de la fusion des annonces d'un meme border router (methodes extraites de watcher.py,
qui ne s'importe pas ici : zeroconf et paho absents)."""
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
exec(compile(ast.fix_missing_locations(mod), "watcher_extrait", "exec"), ns)


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


SALON = {"addrs": ["192.168.3.241", "fd59::c3b6", "fe80::62f5"], "ext_pan": "106d", "online": True}
CUISINE = {"addrs": ["192.168.3.252", "fd59::c1ad", "fe80::d640"], "ext_pan": "106d", "online": True}

# nouvelle annonce du meme appareil : elle reprend la carte, son nom et son historique
w = W()
w.br = {"old": dict(SALON, label="Google TV Salon"), "cui": dict(CUISINE, label="Google TV Cuisine")}
w.br_names = {"old": {"name": "Google TV Salon", "detached": [1.0]}, "cui": {"name": "Google TV Cuisine", "detached": []}}
new = dict(SALON, addrs=["192.168.3.241", "fe80::62f5"])
assert w._br_twin("new", new) == "old" and w._br_twin("new", dict(new, ext_pan="autre")) is None
assert w._br_twin("new", {"addrs": ["fe80::62f5"], "ext_pan": "106d"}) is None      # lien-local seul : ne dit rien
assert w._br_twin("cui", CUISINE) is None
w._br_take_over("old", "new")
assert set(w.br) == {"new", "cui"} and w.br["new"]["label"] == "Google TV Salon"
assert w.br_names["new"] == {"name": "Google TV Salon", "detached": [1.0], "replaces": ["old"]} and w.cleared == ["old"]
# l'ancienne annonce, encore sur le reseau, est ignoree tant que la nouvelle est en ligne
assert w._br_replaced("old") and not w._br_replaced("new") and not w._br_replaced("cui")
w.br["new"]["online"] = False
assert not w._br_replaced("old")                                                   # sinon elle peut revenir
# ... et si elle revient, elle reprend la carte a son tour, sans boucle
w._br_take_over("new", "old")
assert set(w.br) == {"old", "cui"} and w.br_names["old"]["replaces"] == ["new"]

# doublon deja present (versions precedentes) : la carte hors ligne est absorbee par celle en ligne
w = W()
w.br = {"old": dict(SALON, online=False), "new": dict(SALON), "cui": dict(CUISINE, online=False)}
w.br_names = {"old": {"name": "Google TV Salon", "detached": [1.0, 2.0]}, "new": {"name": None, "detached": [3.0]}}
assert w._br_fold_stale() and set(w.br) == {"new", "cui"}                           # Cuisine hors ligne sans double : reste
assert w.br_names["new"] == {"name": "Google TV Salon", "detached": [1.0, 2.0, 3.0], "replaces": ["old"]}
assert w.br["new"]["label"] == "Google TV Salon" and not w._br_fold_stale()
# deux cartes en ligne : rien n'est devine
w = W()
w.br = {"a": dict(SALON), "b": dict(SALON)}
assert not w._br_fold_stale() and len(w.br) == 2
print("OK")

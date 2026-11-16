"""Essai de nodetable.identity_of (fonction extraite : nodetable importe des modules absents ici)
et controle que le rapport anonymise ne contient aucune de ces valeurs."""
import ast
import base64
import sys

src = open(sys.argv[1] + "/nodetable.py", encoding="utf-8").read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "identity_of")
ns = {"base64": base64}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "extrait", "exec"), ns)
identity_of = ns["identity_of"]

a = {"0/40/15": "SN123", "0/40/18": "UID9", "0/40/10": "1.4.6", "0/51/0": [{"4": None}, {"4": base64.b64encode(bytes.fromhex("7A5C7FDEA1DB3E34")).decode()}]}
assert identity_of(a) == {"serial": "SN123", "unique_id": "UID9", "hw_address": "7A:5C:7F:DE:A1:DB:3E:34", "firmware": "1.4.6"}, identity_of(a)
assert identity_of({}) == {"serial": None, "unique_id": None, "hw_address": None, "firmware": None}
assert identity_of({"0/40/15": "", "0/51/0": [{"4": "pas du base64 !"}], "0/40/10": 85})["firmware"] == "85"
assert src.count("**identity_of(a),") == 2                      # les deux sortes de lignes (Thread, Wi-Fi/Ethernet)

sys.path.insert(0, sys.argv[1])
import report  # noqa: E402

row = {"name": "Prise", "model": "Plug", "role": "router", "serial": "SN123", "unique_id": "UID9",
       "hw_address": "7A:5C:7F:DE:A1:DB:3E:34", "firmware": "1.4.6"}
txt = report.build({"rows": [row]}, "x")
assert not any(v in txt for v in ("SN123", "UID9", "7A:5C", "1.4.6")), txt
print("OK")

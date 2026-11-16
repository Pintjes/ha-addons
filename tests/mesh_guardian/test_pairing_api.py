"""Essai de l'API des codes d'appairage de webui.py, avec un faux tableau (aucun reseau)."""
import os
import sys
import tempfile

sys.path.insert(0, sys.argv[1])
import pairing  # noqa: E402

pairing.FILE = os.path.join(tempfile.mkdtemp(), "codes.json")
import webui  # noqa: E402

webui.Pairing = lambda: pairing.Pairing(pairing.FILE)
ATTRS = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/40/15": "SN1"}


class Table:
    nodes = [{"node_id": 0xAB, "attributes": ATTRS}, {"node_id": 0xCD, "attributes": {}}]

    def _nodes(self):
        return self.nodes

    def get(self, force=False):
        return {"rows": [{"id": "0xAB", "name": "Prise test", "area": "Salon", "model": "Plug"}]}


ui = webui.WebUI(None, Table())
assert ui.pairing_get("00000000000000AB") == {"code": None, "free": []}
for bad, why in (("123", "format"), ("34970112333", "check"), ("MT:-24J042C00KA0648G00", "device")):
    try:
        ui.pairing_post({"id": "0xAB", "code": bad})
        raise AssertionError(bad)
    except ValueError as err:
        assert str(err) == why, err
try:
    ui.pairing_post({"id": "0xEF", "code": "34970112332"})
    raise AssertionError("node absente acceptee")
except ValueError as err:
    assert str(err) == "node"
res = ui.pairing_post({"id": "0xAB", "code": "MT:Y.K9042C00KA0648G00"})
assert res["ok"] and res["code"]["manual"] == "34970112332" and res["code"]["name"] == "Prise test"
assert ui.pairing_get("00000000000000AB")["code"]["qr"] == "MT:Y.K9042C00KA0648G00"
assert ui.pairing_get(None) == {"free": [], "count": 1}
Table.nodes = [{"node_id": 0xCD, "attributes": {}}]              # la node est remise a zero : elle sort du tableau
libres = ui.pairing_get(None)["free"]
assert [c["name"] for c in libres] == ["Prise test"] and libres[0]["manual"] == "34970112332"
assert [c["key"] for c in ui.pairing_get("00000000000000CD")["free"]] == [libres[0]["key"]]
Table.nodes.append({"node_id": 0x1AB, "attributes": ATTRS})      # elle revient avec un nouvel id
assert ui.pairing_get("00000000000001AB")["code"]["qr"] and ui.pairing_get(None)["free"] == []
assert ui.pairing_post({"delete": res["code"]["key"]}) == {"ok": True} and ui.pairing_get(None)["count"] == 0

# nouvelle node sans code : signalee pendant 24 h, plus apres ; pas signalee si son code est conserve
from datetime import datetime, timedelta, timezone  # noqa: E402

now = datetime.now()
assert webui._recent(now.isoformat()) and webui._recent(datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
assert webui._recent(datetime.now(timezone.utc).isoformat()) and webui._recent(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
assert not webui._recent((now - timedelta(days=2)).isoformat()) and not webui._recent(None) and not webui._recent("x")
Table.nodes = [{"node_id": 0xAB, "attributes": ATTRS}, {"node_id": 0xCD, "attributes": {}}]
rows = [{"id": "0xAB", "name": "Neuve", "area": "Salon", "added": now.isoformat()},
        {"id": "0xCD", "name": "Ancienne", "added": (now - timedelta(days=30)).isoformat()},
        {"id": "0xEE", "name": "Absente", "added": now.isoformat()}]
assert ui.pairing_new(rows) == [{"id": "0xAB", "name": "Neuve", "area": "Salon"}], ui.pairing_new(rows)
ui.pairing_post({"id": "0xAB", "code": "34970112332"})
assert ui.pairing_new(rows) == [] and ui.pairing_new(None) == []
print("OK")

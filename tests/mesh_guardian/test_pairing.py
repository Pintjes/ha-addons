"""Essai de pairing.py : decodage des codes et survie a une remise a zero."""
import os
import sys
import tempfile

sys.path.insert(0, sys.argv[1])
import pairing  # noqa: E402

# vecteurs connus du SDK Matter : passcode 20202021, discriminateur 3840
for qr, vid, pid in (("MT:Y.K9042C00KA0648G00", 0xFFF1, 0x8000), ("MT:-24J042C00KA0648G00", 0xFFF1, 0x8001)):
    c = pairing.parse(qr)
    assert c["manual"] == "34970112332" and (c["vid"], c["pid"]) == (vid, pid), c
assert pairing.parse(" 3497-011-2332 ")["manual"] == "34970112332"
assert pairing.parse("texte mt:Y.K9042C00KA0648G00 autour")["qr"] == "MT:Y.K9042C00KA0648G00"
for bad, why in (("34970112333", "check"), ("1234", "format"), ("MT:ABC", "format"), ("bonjour", "format"), ("", "format")):
    try:
        pairing.parse(bad)
        raise AssertionError(bad)
    except ValueError as err:
        assert str(err) == why, (bad, err)

path = os.path.join(tempfile.mkdtemp(), "codes.json")
p = pairing.Pairing(path)
A = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/40/15": "SN1", "0/51/0": [{"4": "aGFyZHdhcmU="}], "0/40/18": "U1"}
B = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/51/0": [{"4": "YXV0cmU="}], "0/40/18": "U2"}   # sans numero de serie
p.set("0A", A, {"0A", "0B"}, "MT:Y.K9042C00KA0648G00", "Prise A", "Salon", "Plug")
p.set("0B", B, {"0A", "0B"}, "34970112332", "Prise B", "Cave", "Plug")
try:
    p.set("0A", A, {"0A"}, "MT:-24J042C00KA0648G00")
    raise AssertionError("autre produit accepte")
except ValueError as err:
    assert str(err) == "device"
assert p.of("0A", A, {"0A", "0B"})["qr"] and p.of("0B", B, {"0A", "0B"})["qr"] is None
assert p.of("0C", {}, {"0A", "0B", "0C"}) is None and p.free({"0A", "0B"}) == []

p = pairing.Pairing(path)                      # redemarrage de l'add-on
# A remise a zero : nouvel id 1A, adresse et unique id changes, meme numero de serie
A2 = dict(A, **{"0/51/0": [{"4": "bm91dmVhdQ=="}], "0/40/18": "U9"})
assert [e["name"] for e in p.free({"0B"})] == ["Prise A"]          # visible pendant le re-appairage
assert p.of("1A", A2, {"0B", "1A"})["name"] == "Prise A" and p.free({"0B", "1A"}) == []
# B remise a zero : rien ne permet de la reconnaitre -> rattachement a la main
B2 = dict(B, **{"0/51/0": [{"4": "eA=="}], "0/40/18": "U8"})
assert p.of("1B", B2, {"1A", "1B"}) is None
libres = p.free({"1A", "1B"}, vid=0xFFF1, pid=0x8000)
assert [e["name"] for e in libres] == ["Prise B"] and p.free({"1A", "1B"}, vid=1, pid=2) == []
p.attach(libres[0]["key"], "1B", B2, "Prise B bis")
assert p.of("1B", B2, {"1A", "1B"})["name"] == "Prise B bis" and p.count() == 2
# une node encore presente ne se fait pas prendre son code par une autre de meme numero de serie
assert p.of("2A", A, {"1A", "1B", "2A"}) is None
assert p.delete(p.of("1A", A2, {"1A"})["key"]) and p.count() == 1 and pairing.Pairing(path).count() == 1

# --- cas vecu : prise sans numero de serie, QR enregistre, reinitialisee, revenue, code RESSAISI a la main
path = os.path.join(tempfile.mkdtemp(), "codes.json")
p = pairing.Pairing(path)
P1 = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/51/0": [{"4": "YQ=="}], "0/40/18": "U1"}
P2 = {"0/40/2": 0xFFF1, "0/40/4": 0x8000, "0/51/0": [{"4": "Yg=="}], "0/40/18": "U2"}
p.set("55", P1, {"55"}, "MT:Y.K9042C00KA0648G00", "Prise TV", "Bureau", "Plug")
c = p.set("9B", P2, {"9B"}, "3497-011-2332", "Prise TV", "Bureau", "Plug")
assert c["qr"] == "MT:Y.K9042C00KA0648G00" and p.count() == 1, c       # a la saisie : le QR conserve est repris
# meme situation deja enregistree par une version precedente (deux entrees) : reparee a la lecture
p.items["old"] = {"node": "55", "qr": "MT:Y.K9042C00KA0648G00", "manual": "34970112332", "vid": 0xFFF1, "pid": 0x8000}
p.items[c["key"]]["qr"] = None
c = p.of("9B", P2, {"9B"})
assert c["qr"] == "MT:Y.K9042C00KA0648G00" and p.count() == 1 and p.free({"9B"}) == []
# un QR d'un autre code ou d'une node encore presente n'est jamais repris
p.items["x"] = {"node": "77", "qr": "MT:Y.K9042C00KA0648G00", "manual": "34970112332", "vid": 0xFFF1, "pid": 0x8000}
p.items[c["key"]]["qr"] = None
assert p.of("9B", P2, {"9B", "77"})["qr"] is None

# --- rattachement tout seul apres le bouton Reinitialiser
path = os.path.join(tempfile.mkdtemp(), "codes.json")
p = pairing.Pairing(path)
p.set("55", P1, {"55", "56"}, "MT:Y.K9042C00KA0648G00", "Prise TV", "Bureau", "Plug")
assert p.of("9B", P2, {"9B"}) is None                                  # node partie sans le bouton : pas de devinette
p.mark_reset("55")
assert pairing.Pairing(path).items and p.of("40", P2, {"40"}) is None  # node plus ancienne que la reinitialisee : non
assert p.of("9B", dict(P2, **{"0/40/4": 1}), {"9B"}) is None           # autre produit : non
c = p.of("9B", P2, {"9B"})
assert c and c["auto"] and c["name"] == "Prise TV" and p.free({"9B"}) == []
assert p.of("9C", P2, {"9B", "9C"}) is None and p.of("9B", P2, {"9B", "9C"})["auto"]
# deux prises du meme modele reinitialisees : on ne choisit pas a la place de l'utilisateur
p.set("56", P1, {"56", "9B"}, "MT:Y.K9042C00KA0648G00")
p.set("57", P1, {"56", "57", "9B"}, "MT:Y.K9042C00KA0648G00")
p.mark_reset("56")
p.mark_reset("57")
assert p.of("A0", P2, {"9B", "A0"}) is None and len(p.free({"9B", "A0"})) == 2

# --- code scanne juste avant l'appairage : il attend la node que l'appairage amene
path = os.path.join(tempfile.mkdtemp(), "codes.json")
p = pairing.Pairing(path)
try:
    p.scan("34970112332", {"9B"})
    raise AssertionError("code saisi accepte")
except ValueError as err:
    assert str(err) == "typed"
p.scan("MT:Y.K9042C00KA0648G00", {"55", "9B"})
c = p.scan("MT:Y.K9042C00KA0648G00", {"55", "9B"})                      # scanne deux fois : garde une fois
assert c["scanned"] and p.count() == 1 and [e["scanned"] for e in p.free({"55", "9B"})] == [True]
assert p.of("55", P1, {"55", "9B"}) is None                            # node deja la au moment du scan : non
assert p.of("A0", dict(P2, **{"0/40/4": 1}), {"55", "9B", "A0"}) is None   # autre produit : non
c = pairing.Pairing(path).of("A0", P2, {"55", "9B", "A0"})             # la node amenee par l'appairage, apres redemarrage
assert c and c["qr"] and not c["scanned"] and not c["auto"], c
p = pairing.Pairing(path)
assert p.free({"A0"}) == [] and p.of("A1", P2, {"A0", "A1"}) is None and p.count() == 1
print("OK")

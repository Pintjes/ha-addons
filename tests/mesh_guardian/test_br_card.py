"""Carte du border router (2.39.0) : la ligne « Préfixe réseau imposé » (Actif / Pas en place / Non imposé) remplace
la pastille « OMR forcé », la fiche dit la même chose, « primaire » est une icône (pas la couronne du leader) avec son
« i ». Textes en anglais et en français. Lecture de la page seulement."""
import os
import re
import sys

MG = sys.argv[1]
page = open(os.path.join(MG, "web", "index.html"), encoding="utf-8").read()

for fn in ("function ancLine(", "function ancState(", "function ancTip("):
    assert fn in page, fn
assert "ancBadge(" not in page and "anc_short_" not in page, "the old badge and its texts are gone"
assert "ancLine(D.anchor)" in page and "IC.primary" in page and 'tipI(L("br_primary_tip"))' in page

# chaque texte nouveau existe dans les deux langues
keys = ("anc_label", "anc_st_on", "anc_st_out", "anc_st_none", "anc_tip_on", "anc_tip_since", "anc_tip_out", "anc_tip_none", "anc_tip_prop")
for k in keys:
    assert len(re.findall(r"\b%s:\"" % k, page)) == 2, k
assert 'anc_label:"Préfixe réseau imposé"' in page and 'anc_st_on:"Actif"' in page and 'anc_st_none:"Non imposé"' in page
assert 'anc_in:"Préfixe réseau imposé · Actif · {p}"' in page
# plus de « OMR forcé » nulle part dans les textes de la page
assert "OMR forcé" not in page and "OMR forced" not in page
print("OK")

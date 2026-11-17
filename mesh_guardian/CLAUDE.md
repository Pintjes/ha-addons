# Mesh Guardian — consignes techniques

Add-on Home Assistant `mesh_guardian` : surveille un réseau Thread/Matter, diagnostique les nodes qui décrochent et
les récupère à distance. Périmètre de l'agent : `mesh_guardian/`, `tests/mesh_guardian/` et la ligne Mesh Guardian de
`.github/workflows/ci.yml`.

## Règles

- Débrancher une node est le dernier recours (voir `CLAUDE.md` à la racine). Le seul cas où l'add-on évoque une
  coupure de courant est `frozen` : aucune réponse au diagnostic Thread, pas de ping, entendue récemment par une
  entrée fiable (enfant < 15 min, routeur < 2 min) et pas `alive: true`. Tout autre cas : jamais ce conseil.
- Après un diagnostic, jamais ArmFailSafe / ConnectNetwork. `alive: false` → jamais d'annonce à la place.
- Règles génériques uniquement : aucune valeur propre à une installation (noms, préfixes, adresses) dans le code
  ni dans les tests ; valeurs de test fictives.
- Thread Anchor (`thread_anchor/state`, `thread_anchor/diag`) : lire les champs sans supposer qu'ils existent tous
  (versions différentes) ; repli sur `usbip_link/state["omr"]`.
- Textes d'interface en anglais et en français (`i18n.py`, `translations/`) ; code et tests commentés en anglais.

## Vérifications avant commit

```bash
python tests/mesh_guardian/run_all.py
python -m ruff check --no-cache --select E9,F63,F7,F82,F401,F811 mesh_guardian tests/mesh_guardian
python -m yamllint -d "{extends: relaxed, rules: {line-length: disable}}" mesh_guardian/config.yaml mesh_guardian/translations
```

## Version

Une nouvelle version = `config.yaml` + `VERSION` (constante dans `watcher.py`) + `CHANGELOG.md` (+ `DOCS.md`,
traductions si besoin), un commit « Mesh Guardian X.Y.Z: … ». Nouveau fichier `.py` : le Dockerfile copie déjà
`*.py`, mais l'ajouter à la liste d'imports du test de démarrage de la CI (`.github/workflows/ci.yml`).

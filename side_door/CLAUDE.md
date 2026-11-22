# Side Door — consignes pour l'agent (add-on Home Assistant)

Dépôt public `Pintjes/ha-addons`, dossier `side_door/`. Cette fiche est publique : aucune adresse du réseau privé, aucun secret, aucune donnée personnelle ici ni dans le dépôt. Les consignes générales du dépôt sont dans `../CLAUDE.md`.

## Rôle

Side Door ouvre des applications web du réseau local dans la barre latérale de Home Assistant (ingress, nginx + njs, script injecté `web/shim.js`). L'agent Side Door ne touche qu'à `side_door/` et à ses tests (et aux lignes Side Door de la CI).

## Règles de travail

- Corriger la famille de comportements, jamais le cas d'une application précise : aucune règle « si c'est Plex » dans le code. Ce qui est propre à l'installation de l'utilisateur reste dans la configuration.
- Chaque correctif : test unitaire (`tests/test_build.py`) et, si le comportement réseau change, test live (`tests/test_live.py`), puis `CHANGELOG.md`, `DOCS.md`, `translations/` et la version dans `config.yaml`.
- Commits : auteur et committer `Pintjes <Pintjes@users.noreply.github.com>`, jamais de Co-Authored-By ni de mention d'un assistant. Licence propriétaire © 2026 Pintjes (CLUF dans `LICENSE`, depuis la 2.8.0 ; les versions antérieures restent sous GPL-3.0-or-later). Jamais le vrai nom de l'auteur : seulement « Pintjes ». Aucune dépendance sous GPL.
- Avant un commit : `git fetch origin "+refs/heads/main:refs/remotes/origin/main"` puis rebase sur `origin/main`. Jamais `git pull` (historique réécrit le 2026-11-17).
- Push uniquement avec l'accord de l'utilisateur, ou celui du Leader citant sa réponse.

## Vérifications (comme la CI)

```
ruff check --select E9,F63,F7,F82,F401,F811 side_door
python -m unittest discover -s side_door/tests -p "test_build.py" -v
python side_door/run.py --check   # dans l'image : nginx -t sur la config générée
```

Test live (docker) : `side_door/tests/upstream.py` (application de test, port 8000) puis `side_door/tests/test_live.py`, avec `tests/options_live.json`, voir l'étape « Live test (Side Door) » de `.github/workflows/ci.yml`. Le test d'arrêt (SIGTERM, SIGQUIT, `docker stop` : code 0 en moins de 5 s) y est aussi.

## Pièges connus

- L'arrêt : le Supervisor envoie SIGQUIT (image nginx) ; `run.py` doit l'attraper (corrigé en 2.4.2).
- Les réponses compressées, partielles (206) ou non UTF-8 ne sont pas réécrites ; les ETag sont liés à la marque de version.
- Le stockage du navigateur est cloisonné par application (depuis 2.2.0) : une application ouverte sans compte peut cacher des fonctions tant qu'on ne s'y est pas connecté dans Side Door.
- Le réglage « barre latérale » de HA n'est pas modifiable par l'API des add-ons.

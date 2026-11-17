# Thread Anchor — consignes techniques

Add-on Home Assistant `thread_anchor` : ancre le préfixe OMR du réseau Thread via le border router OpenThread de HA, et fournit le diagnostic Thread (utilisé par Mesh Guardian). Périmètre de l'agent : `thread_anchor/` et `tests/thread_anchor/` uniquement.

## Règles

- Lecture seule sur la production : jamais de promotion de rôle Thread, rien d'intrusif sans accord. Débrancher une node est le dernier recours (voir `CLAUDE.md` à la racine).
- Un seul point d'entrée pour `ot-ctl` (`Anchor.otctl`) : verrou par commande ; une sortie vide avec code 0 (sans « Done ») = commande ignorée, redemandée 3 fois, puis message précis ; jamais « Border router injoignable » sur une sortie vide.
- Ajouter des champs aux réponses sans renommer l'existant (Mesh Guardian les lit).
- Textes d'interface en anglais et en français (`TEXTS`) ; code et tests commentés en anglais.

## Vérifications avant commit

```bash
python tests/thread_anchor/test_anchor.py thread_anchor
python -m ruff check --no-cache --select E9,F63,F7,F82,F401,F811 thread_anchor tests/thread_anchor
python -m yamllint -d "{extends: relaxed, rules: {line-length: disable}}" thread_anchor/config.yaml thread_anchor/translations
```

## Version

Une nouvelle version = `config.yaml` + `VERSION` (constante dans `thread_anchor.py`) + `CHANGELOG.md` + `DOCS.md` (+ traductions si besoin), une branche `thread-anchor-0.1.x` depuis `origin/main`, un commit « Thread Anchor 0.1.x: … ».

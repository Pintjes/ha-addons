# Voice Agent Bridge — règles techniques

Add-on Home Assistant (bêta) : point d'accès compatible OpenAI (`/v1/models`, `/v1/chat/completions`) qui répond aux requêtes Assist avec l'agent Claude Code (`claude -p`), relié à Home Assistant par un serveur ha-mcp local. Un panneau (ingress, port 8791) montre les conversations et les notes de la maison.

## Périmètre

- Uniquement `voice_agent_bridge/` et `tests/voice_agent_bridge/` (ce dossier n'existe pas encore). Ne pas toucher aux autres add-ons du dépôt.
- Fichiers : `gateway.py` (serveur, appel de l'agent, historique, journal), `prompts.py` (textes envoyés), `web/index.html` (panneau), `config.yaml` + `translations/` (options, en/fr), `Dockerfile`, `README.md`, `DOCS.md`, `CHANGELOG.md`.
- Pas de donnée privée dans ce dossier ni dans les commits (jetons, clés, adresses, noms de pièces ou d'appareils de l'installation).

## Contrôles avant un commit

```
ruff check --select E9,F63,F7,F82,F401,F811 voice_agent_bridge
yamllint -d "{extends: relaxed, rules: {line-length: disable}}" voice_agent_bridge/config.yaml voice_agent_bridge/translations
```

- La CI lance aussi hadolint sur `voice_agent_bridge/Dockerfile` (règles ignorées : DL3008, DL3013) et construit l'image en amd64 et aarch64.
- La CI n'exécute aucun test de cet add-on pour l'instant ; tout test va dans `tests/voice_agent_bridge/` et doit être ajouté à la CI.

## Fichiers et options

- Un nouveau fichier `.py` s'ajoute à la ligne `COPY` du `Dockerfile` et au contrôle ruff de la CI (`.github/workflows/ci.yml`).
- Une option se déclare à trois endroits : `options` et `schema` de `config.yaml`, puis `translations/en.yaml` et `translations/fr.yaml`. Les documenter dans `DOCS.md`.
- Versions de Claude Code et de ha-mcp : arguments `CLAUDE_CODE_VERSION` et `HA_MCP_VERSION` du `Dockerfile`, volontairement épinglés.
- Le panneau et le logo gardent le bleu commun du dépôt (#1f6feb).

## Version et commits

- Version : `config.yaml` (`version`) et une entrée en tête de `CHANGELOG.md` (format Keep a Changelog, versionnage sémantique). Il n'y a pas de constante de version dans `gateway.py`.
- Message : « Voice Agent Bridge X.Y.Z: … » (une correction de documentation seule peut ne pas changer la version).
- Auteur : `Pintjes <Pintjes@users.noreply.github.com>` seul ; aucune ligne `Co-Authored-By`, aucune mention d'outil ou d'assistant dans les messages, le code, le CHANGELOG ou la doc.
- Avant chaque commit : `git fetch origin "+refs/heads/main:refs/remotes/origin/main"` puis rebase sur `origin/main`. Jamais de `git pull` (historique réécrit). Push en avance rapide uniquement, jamais en force, et seulement avec l'accord de l'utilisateur.

## Sécurité à ne pas affaiblir

- Pas d'outils shell ni fichiers pour l'agent ; option lecture seule ; budget par requête.
- Aucun déverrouillage, ouverture ou désarmement sans un « oui » explicite de l'utilisateur (texte de `prompts.py`).
- Les secrets (jeton du plan, clé API, clé de la passerelle) restent des options de type mot de passe : jamais écrits dans les journaux, le panneau ni le dépôt.

# USB/IP Link — règles techniques

- Cet add-on (`usbip_link/` et `tests/usbip_link/`, plus sa ligne de CI) appartient à l'agent USB/IP Link ; ne pas y toucher depuis une autre session.
- Contrôles avant commit : `python tests/usbip_link/test_link.py usbip_link`, `ruff check --select E9,F63,F7,F82,F401,F811 usbip_link`, yamllint sur `config.yaml` et `translations`. Version, CHANGELOG et DOCS mis à jour ensemble.
- Le mode protection est volontairement désactivé (`full_access`, `apparmor: false`, rôle `manager` pour `restart_addons`) ; toute évolution passe par la décision de l'utilisateur via le Leader.
- Le préfixe OMR fixe est géré par Thread Anchor depuis 0.3.0 ; les options `omr_*` restent inutilisées pour qu'une configuration enregistrée se charge encore (retrait prévu en 0.4).
- Commits au nom de Pintjes seul, sans mention de Claude, sur `main` ; fetch + rebase avant chaque commit.

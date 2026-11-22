# Consignes permanentes — ha-addons

## Principe directeur de Mesh Guardian

**Débrancher / rebrancher une node (coupure de courant) est le DERNIER recours.**

- Un réseau Thread/Matter peut compter de nombreuses nodes, certaines peu accessibles, d'autres alimentant des appareils qu'on ne veut pas couper.
- La raison d'être de Mesh Guardian : un réseau stable et le moins d'interventions manuelles possible.
- Ne jamais proposer le débranchement comme réponse par défaut. Épuiser d'abord toutes les voies à distance (diagnostic de cause, récupération Matter, ré-annonce mDNS, correction de la cause réseau : préfixes OMR, border routers…).
- Le débranchement n'est légitime qu'une fois **prouvé** qu'aucune autre voie n'existe, et il faut le dire explicitement avec la preuve.

## Licence (décision du 22/11/2026)

- Les add-ons passent en **licence propriétaire** « © 2026 Pintjes. Tous droits réservés. » (CLUF en français, qui fait foi, puis traduction anglaise, dans le `LICENSE` de chaque add-on ; droit belge). Le dépôt reste public, en lecture. Chaque add-on change de licence dans sa propre version : les versions déjà publiées restent sous GPL-3.0-or-later et le disent (CHANGELOG, article « Versions antérieures » du CLUF).
- En-têtes de fichiers : « © 2026 Pintjes. All rights reserved. See LICENSE. » ; étiquette d'image `org.opencontainers.image.licenses="LicenseRef-Proprietary"`.
- **Aucune dépendance GPL ou AGPL ne doit être ajoutée** (incompatible avec une licence propriétaire). Une dépendance LGPL est à examiner d'abord : elle reste possible si elle est installée telle quelle, sans modification, comme paquet distinct et remplaçable (ex. zeroconf, LGPL-2.1-ou-ultérieure) et citée dans les composants tiers du CLUF. Toute nouvelle dépendance : vérifier sa licence dans ses métadonnées (PyPI, METADATA) et l'ajouter à la liste des composants tiers du `LICENSE` de l'add-on.
- **Plan futur, pas encore codé** : clé de licence signée Ed25519 (clé privée gardée par l'auteur, seule la clé publique dans le logiciel ; nom du client et éventuellement date de fin dans la clé) ; date de début d'essai de 30 jours gardée dans les données de l'app ; à la fin de l'essai sans clé : lecture seule, jamais de données bloquées ; un endroit dans les réglages pour coller la clé et voir l'état. En attendant, garder **un point unique** par où passent les écritures vers l'extérieur (commandes, services, MQTT), pour pouvoir y brancher la vérification sans toucher au reste.

## Dépôt public

- Aucun détail propre à une installation (noms de machines, hyperviseur, nombre de nodes, appareils, préfixes, adresses) dans ce dépôt : code, tests, documentation et CLAUDE.md restent génériques. Les détails d'une installation vont dans des notes privées, hors dépôt.
- Une cause fréquente de chutes : des border routers tiers qui changent souvent de préfixe OMR ; remède possible : un border router OpenThread imposant un préfixe stable (Thread Anchor), éventuellement avec une radio transmise par USB/IP (USB/IP Link).
- Commits au nom de Pintjes, sur `main`.

# Consignes permanentes — ha-addons

## Principe directeur de Mesh Guardian

**Débrancher / rebrancher une node (coupure de courant) est le DERNIER recours.**

- Un réseau Thread/Matter peut compter de nombreuses nodes, certaines peu accessibles, d'autres alimentant des appareils qu'on ne veut pas couper.
- La raison d'être de Mesh Guardian : un réseau stable et le moins d'interventions manuelles possible.
- Ne jamais proposer le débranchement comme réponse par défaut. Épuiser d'abord toutes les voies à distance (diagnostic de cause, récupération Matter, ré-annonce mDNS, correction de la cause réseau : préfixes OMR, border routers…).
- Le débranchement n'est légitime qu'une fois **prouvé** qu'aucune autre voie n'existe, et il faut le dire explicitement avec la preuve.

## Dépôt public

- Aucun détail propre à une installation (noms de machines, hyperviseur, nombre de nodes, appareils, préfixes, adresses) dans ce dépôt : code, tests, documentation et CLAUDE.md restent génériques. Les détails d'une installation vont dans des notes privées, hors dépôt.
- Une cause fréquente de chutes : des border routers tiers qui changent souvent de préfixe OMR ; remède possible : un border router OpenThread imposant un préfixe stable (Thread Anchor), éventuellement avec une radio transmise par USB/IP (USB/IP Link).
- Commits au nom de Pintjes, sur `main`.

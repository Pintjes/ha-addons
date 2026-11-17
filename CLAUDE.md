# Consignes permanentes — ha-addons

## Principe directeur de Mesh Guardian

**Débrancher / rebrancher une node (coupure de courant) est le DERNIER recours.**

- Le réseau compte 81 nodes Thread/Matter, certaines peu accessibles, d'autres alimentant des appareils qu'on ne veut pas couper.
- La raison d'être de Mesh Guardian : un réseau stable et le moins d'interventions manuelles possible.
- Ne jamais proposer le débranchement comme réponse par défaut. Épuiser d'abord toutes les voies à distance (diagnostic de cause, récupération Matter, ré-annonce mDNS, correction de la cause réseau : préfixes OMR, border routers…).
- Le débranchement n'est légitime qu'une fois **prouvé** qu'aucune autre voie n'existe, et il faut le dire explicitement avec la preuve.

## Contexte de l'installation

- Home Assistant tourne dans une VM Hyper-V sur le PC Windows « Desktop-Serveur » ; le ZBT-2 y est branché et doit être transmis à HA par USB/IP (usbipd-win → add-on `usbip_link`).
- Cause racine identifiée des chutes quotidiennes : changements fréquents de préfixe OMR par les border routers Google TV ; piste de remède : border router OpenThread (ZBT-2) imposant un préfixe stable.
- Commits au nom de Pintjes, sur `main`.

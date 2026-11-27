# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# © 2026 Pintjes. All rights reserved. See LICENSE.
"""Translations of the log, events and entity names (option "language").

Source strings are English. t("text {x}", x=1) returns the translation in the
selected language (English if missing) with the values filled in.
"""

_LANG = "en"

# technical codes (roles, interface states) shown to humans
CODES_EN = {
    "detached": "detached", "child": "end device", "router": "router", "leader": "leader router",
    "unspecified": "unspecified", "unassigned": "unassigned", "sleepy_end_device": "sleepy end device",
    "end_device": "end device", "reed": "end device", "not_initialized": "not initialized", "inactive": "inactive",
    "active": "active", "unknown": "unknown", "offline": "offline",
}

FR = {
    # codes
    "detached": "détaché", "child": "appareil final", "router": "routeur", "leader": "routeur leader",
    "unspecified": "non précisé", "unassigned": "non attribué", "sleepy_end_device": "appareil final dormant",
    "end_device": "appareil final", "reed": "appareil final", "not_initialized": "non initialisée", "inactive": "inactive",
    "active": "active", "unknown": "inconnu", "offline": "hors ligne",
    # restart of the Matter Server / Home Assistant
    'The Matter Server restarted at {t}': 'Le Matter Server a redémarré à {t}',
    'Home Assistant restarted at {t}': 'Home Assistant a redémarré à {t}',
    'Home Assistant or the Matter Server restarted at {t}': 'Home Assistant ou le Matter Server a redémarré à {t}',
    'The Matter Server was restarted at {t}': 'Le Matter Server a été redémarré à {t}',
    'The Matter Server was updated to {v} at {t}': 'Le Matter Server a été mis à jour en {v} à {t}',
    'The Matter Server crashed at {t} (code {code})': 'Le Matter Server a planté à {t} (code {code})',
    'The Matter Server crashed at {t}': 'Le Matter Server a planté à {t}',
    'The Matter Server started at {t}': 'Le Matter Server a démarré à {t}',
    'Home Assistant was updated to {v} at {t}': 'Home Assistant a été mis à jour en {v} à {t}',
    'Supervisor log: {n} lines read, {r} restarts found': 'Journal du Supervisor : {n} lignes lues, {r} redémarrages trouvés',
    'Supervisor log not readable (HTTP {code}): restarts are detected by the live link only':
        'Journal du Supervisor illisible (HTTP {code}) : les redémarrages sont détectés par le lien direct seulement',
    '{n} node out of {total} is reconnecting, nothing to do': '{n} node sur {total} se reconnecte, rien à faire',
    '{n} of {total} nodes are reconnecting, nothing to do': '{n} nodes sur {total} se reconnectent, rien à faire',
    '{n} node out of {total} did not come back': "{n} node sur {total} n'est pas revenue",
    '{n} of {total} nodes did not come back': "{n} nodes sur {total} ne sont pas revenues",
    'all {total} nodes came back': 'les {total} nodes sont revenues',
    # advice
    'Advice: {n} nodes': 'Conseils : {n} nodes',
    'Advice: {n} node': 'Conseils : {n} node',
    '{child}: new parent {parent} ({rssi}dBm), before {old} ({old_rssi}dBm) {verdict}': "{child} : nouveau parent {parent}, avant {old} ({old_rssi} → {rssi} dBm) {verdict}",
    "yes ({n} spontaneous change(s) seen)": "oui ({n}×)",
    "Cannot save the radio advice state: {err}": "Sauvegarde des conseils radio impossible : {err}",
    '▲ better': '▲ meilleur',
    "after the node rebooted (battery removed or power cycled)": "après redémarrage de la node (pile retirée ou remise sous tension)",
    "not seen in {h}h of observation": "non ({h} h)",
    "under observation ({h}h)": "en observation ({h} h)",
    '▼ worse': '▼ moins bon',
    '≈ similar': '≈ équivalent',
    "its old parent disappeared or rebooted": "son ancien parent avait disparu ou redémarré",
    "spontaneous change": "changement spontané",
    ", battery": ", pile",
    " (battery)": " (pile)",
    ": ": " : ",
    "becomes primary": "devient primaire",
    "Matter Server log: followed per node": "Journal du Matter Server : suivi par node",
    "Matter Server log not readable (HTTP {code}): no per-node counts": "Journal du Matter Server illisible (HTTP {code}) : pas de compteurs par node",
    'Matter Server log level is "{level}": the per-node counts need "info"': 'Niveau de journal du Matter Server « {level} » : les compteurs par node demandent « info »',
    "Border router {name} removed from the list": "Border router {name} retiré de la liste",
    "no longer primary": "n'est plus primaire",
    "New Thread partition": "Nouvelle partition Thread",
    "{p} ({n} node)": "{p} ({n} node)",
    "{p} ({n} nodes)": "{p} ({n} nodes)",
    "{n} border router": "{n} border router",
    "{n} border routers": "{n} border routers",
    "leader {leader}": "leader {leader}",
    "{n} node unavailable": "{n} node indisponible",
    "{n} nodes unavailable": "{n} nodes indisponibles",
    "{n} recovery": "{n} récupération",
    "{n} recoveries": "{n} récupérations",
    ", most unstable: {name} ({d})": ", plus instable : {name} ({d})",
    "{n} detach": "{n} décrochage",
    "{n} detaches": "{n} décrochages",
    "Add a router near {area}": "Ajouter un routeur près de {area}",
    "{n} min ago": "il y a {n} min",
    "{n} h ago": "il y a {n} h",
    "{n} d ago": "il y a {n} j",
    "Comes back with {parent}": "Revient avec {parent}",
    "its parent {parent} is unavailable too": "son parent {parent} est aussi indisponible",
    "Power cut in {area}?": "Coupure de courant dans {area} ?",
    "{n} other mains-powered nodes of the room dropped at the same time": "{n} autres nodes sur secteur de la pièce sont tombées au même moment",
    "Remove the battery for 10s": "Retirer la pile 10 s",
    "Unplug it for 10s": "Débrancher 10 s",
    "it did not come back after the recovery pings": "pas revenue après les pings de récupération",
    "Check its batteries": "Vérifier les piles",
    "Check its power": "Vérifier l'alimentation",
    "Offline: cause unknown, the recovery attempt looks for it": "Hors ligne : cause inconnue, la tentative de récupération la cherche",
    "Answers now and then: unplug it for 10s": "Répond par intermittence : débrancher 10 s",
    "Answers now and then: remove the battery for 10s": "Répond par intermittence : retirer la pile 10 s",
    "Answers now and then: try the recovery attempt": "Répond par intermittence : lancer la tentative de récupération",
    "Thread diagnostic under way": "Diagnostic Thread en cours",
    "Unreachable: Thread diagnostic to do": "Injoignable : diagnostic Thread à faire",
    "it did not come back after the recovery pings; nothing proves yet that it is stuck: the recovery attempt asks the mesh for it":
        "pas revenue après les pings de récupération ; rien ne prouve encore qu'elle est figée : la tentative de récupération interroge le maillage",
    "Weak Wi-Fi signal with {ap}": "Signal Wi-Fi faible avec {ap}",
    "Weak Wi-Fi signal": "Signal Wi-Fi faible",
    "{rssi} dBm: move the node or an access point closer": "{rssi} dBm : rapprocher la node ou une borne",
    "Find a new link: {name}, {signal} now": "Rechercher un nouveau lien : {name}, {signal} maintenant",
    "it hears {name} better than its parent": "elle entend {name} mieux que son parent",
    "Find a new link: {name}, {signal} {ago}": "Rechercher un nouveau lien : {name}, {signal} {ago}",
    "it had a good link with {name} {ago}": "elle avait un bon lien avec {name} {ago}",
    "Find a new link ({n} router in the room)": "Rechercher un nouveau lien ({n} routeur dans la pièce)",
    "Find a new link ({n} routers in the room)": "Rechercher un nouveau lien ({n} routeurs dans la pièce)",
    "routers of {area} it could attach to": "routeurs de {area} auxquels elle peut se rattacher",
    "Find a new link ({n} router on the floor)": "Rechercher un nouveau lien ({n} routeur à l'étage)",
    "Find a new link ({n} routers on the floor)": "Rechercher un nouveau lien ({n} routeurs à l'étage)",
    "routers of the same floor it could attach to": "routeurs du même étage auxquels elle peut se rattacher",
    "Find a new link": "Rechercher un nouveau lien",
    "it attaches again and picks the best parent it hears": "elle se rattache et choisit le meilleur parent qu'elle entend",
    "Move the node: the router of the room does not hear it well": "Déplacer la node : le routeur de la pièce ne l'entend pas bien",
    "Move the node: none of the {n} routers of the room hears it well": "Déplacer la node : aucun des {n} routeurs de la pièce ne l'entend bien",
    "Add a router in {area}": "Ajouter un routeur dans {area}",
    "no better parent found by the search of {when}": "aucun meilleur parent trouvé par la recherche du {when}",
    "this node loses its parent each time": "cette node perd son parent à chaque fois",
    " · {n} node depends on it": " · {n} node en dépend",
    " · {n} nodes depend on it": " · {n} nodes en dépendent",
    "Add a router between {a} and {b}": "Ajouter un routeur entre {a} et {b}",
    "weak link with {peer}: a router has no parent to change, it needs a closer router": "lien faible avec {peer} : un routeur n'a pas de parent à changer, il lui faut un routeur plus proche",
    "Restarts ({n}× in 24h): update its firmware": "Redémarre ({n}× en 24 h) : mettre à jour son firmware",
    "last restart: {reason}": "dernier redémarrage : {reason}",
    "Restarts ({n}× in 24h): check its power": "Redémarre ({n}× en 24 h) : vérifier son alimentation",
    "no reason reported by the node": "aucune raison indiquée par la node",
    " · {n} node goes through it": " · {n} node passe par lui",
    " · {n} nodes go through it": " · {n} nodes passent par lui",
    "{name} is offline: check its power and its network": "{name} est hors ligne : vérifier son alimentation et son réseau",
    "{names} detached in the last 24h, the last time at {t}": "{names} : décroché dans les dernières 24 h, la dernière fois à {t}",
    "{names} detached in the last 24h": "{names} : décroché dans les dernières 24 h",
    "{name} detaches ({n}× in 24h): check its power and its network": "{name} décroche ({n}× en 24 h) : vérifier son alimentation et son réseau",
    "Announced on the fabric, unknown to the Matter Server: {ids}": "Annoncée sur le fabric, inconnue du Matter Server : {ids}",
    "{node}: {action}": "{node} : {action}",
    "{parent} restarts ({n}× in 24h): finding a new link could improve the situation":
        "{parent} redémarre ({n}× en 24 h) : rechercher un nouveau lien pourrait améliorer la situation",
    "{parent} detaches ({n}× in 24h): finding a new link could improve the situation":
        "{parent} décroche ({n}× en 24 h) : rechercher un nouveau lien pourrait améliorer la situation",
    "Change the batteries": "Changer les piles",
    "none": "aucun",
    # healer
    '{time} sweep: {ok}/{total}': '{time} balayage : {ok}/{total}',
    '7-day history: {n} outages': 'Historique 7 jours : {n} coupures',
    "Statistics reset": "Statistiques réinitialisées",
    "Reset statistics": "Réinitialiser les statistiques",
    "Cleanup failed: {err}": "Nettoyage impossible : {err}",
    "Forgotten nodes: {n}": "Nodes oubliées : {n}",
    'Prefix changed: fast pings for 10min': 'Préfixe changé : pings rapides 10 min',
    "Matter Server unreachable ({err})": "Matter Server injoignable ({err})",
    "answers": "répond",
    "does not answer": "ne répond pas",
    'Ping {i}/{max} {name}: {result}': 'Ping {i}/{max} {name} : {result}',
    'Sweep: {ok}/{total} answer': 'Balayage : {ok}/{total} répondent',
    ' ({n} heard within the hour, not pinged)': ' ({n} entendues dans l\'heure, pas pingées)',
    'Sweep: nothing to ping ({n} heard within the hour)': 'Balayage : rien à pinguer ({n} entendues dans l\'heure)',
    '{time} sweep: nothing to ping': '{time} balayage : rien à pinguer',
    'Automatic recovery on': 'Récupération automatique activée',
    'Automatic recovery off': 'Récupération automatique désactivée',
    '{n} nodes unavailable together: pings paused 5min': "{n} nodes indisponibles ensemble : pings suspendus 5 min",
    '{n} nodes back together': "{n} nodes de nouveau disponibles",
    "Cannot save state: {err}": "Sauvegarde de l'état impossible : {err}",
    "Cannot save statistics: {err}": "Sauvegarde des statistiques impossible : {err}",
    'Cannot read the history: {err}': 'Historique illisible : {err}',
    "Cannot ping {node} {name}: {err}": "Ping de {node} {name} impossible : {err}",
    "Sweep interrupted: {err}": "Balayage interrompu : {err}",
    "Sweep failed: {err}": "Balayage en erreur : {err}",
    "Cannot read the nodes from Home Assistant: {err}": "Lecture des nodes dans Home Assistant impossible : {err}",
    "Cannot rebuild statistics: {err}": "Reconstruction des statistiques impossible : {err}",
    "Radio survey: parents not found ({err})": "Relevé radio : parents non trouvés ({err})",
    "{node}: recovery attempt not started ({err})": "{node} : tentative de récupération non lancée ({err})",
    '{name}: no answer after {max} pings': '{name} : aucune réponse après {max} pings',
    "Recovery cycle failed: {err}": "Cycle de récupération en erreur : {err}",
    '{name} unavailable': '{name} indisponible',
    '{name} back after ping {i} ({m}min)': "{name} de nouveau disponible après le ping {i} ({m} min)",
    '{name} back on its own ({m}min)': "{name} de nouveau disponible, sans action juste avant ({m} min)",
    # 2.40.14: pings again after giving up, returns counted after an action or on their own
    "{name} back {s} s after a ping every 30 min ({m}min)": "{name} de nouveau disponible {s} s après un ping toutes les 30 min ({m} min)",
    "{name} back {s} s after a ping from the page ({m}min)": "{name} de nouveau disponible {s} s après un ping depuis la page ({m} min)",
    "{name} back {s} s after the recovery attempt ({m}min)": "{name} de nouveau disponible {s} s après la tentative de récupération ({m} min)",
    "{name}: sign of life ({why}), pings again": "{name} : signe de vie ({why}), pings relancés",
    "Ping every 30 min {name}: {result}": "Ping toutes les 30 min {name} : {result}",
    "every 30 min": "toutes les 30 min",
    "Matter contact": "contact Matter",
    "mDNS announcement back": "annonce mDNS revenue",
    "heard by {by}": "entendue par {by}",
    "answers the ping": "répond au ping",
    "{n} back after an action": "{n} de retour après une action",
    "{n} back on its own": "{n} revenue seule",
    "{n} back on their own": "{n} revenues seules",
    "Back after an action": "Retours après une action",
    'Statistics start from zero': 'Statistiques à zéro',
    # labels
    'Renamed: "{before}" → "{after}"': 'Renommée : « {before} » → « {after} »',
    '{name} not renamed: {err}': '{name} non renommée : {err}',
    "(empty)": "(vide)",
    # radio
    "Cannot save the radio history: {err}": "Sauvegarde de l'historique radio impossible : {err}",
    'Radio survey: {n} nodes, {weak}': 'Relevé radio : {n} nodes, {weak}',
    '{n} weak link': '{n} lien faible',
    '{n} weak links': '{n} liens faibles',
    "{name} ({area}, {role}): {d} detaches, {p} parent changes, {q} partition changes":
        "{name} ({area}, {role}) : {d} décrochages, {p} changements de parent, {q} changements de partition",
    "Cannot compute radio advice: {err}": "Conseils radio impossibles : {err}",
    " (worst: {a} ↔ {b} {rssi}dBm)": " (pire : {a} ↔ {b} {rssi} dBm)",
    "Radio survey failed: {err}": "Relevé radio impossible : {err}",
    " [rebooted]": " [redémarrée]",
    # watcher
    "Starting": "Démarrage",
    'mDNS burst: {parts} re-announced': 'Rafale mDNS : {parts} réannoncés',
    "Matter node {id}": "Node Matter {id}",
    "Unavailable nodes": "Nodes indisponibles",
    "Available nodes": "Nodes disponibles",
    "Recoveries by ping": "Récupérations par ping",
    "Weak links": "Liens faibles",
    "Thread parents": "Parents Thread",
    "Automatic recovery": "Récupération automatique",
    "Network quality": "Qualité du réseau",
    "Wi-Fi": "Wi-Fi",
    "Ethernet": "Ethernet",
    "Announced on the Matter fabric but unknown to the Matter Server: {ids}": "Nodes inconnues du Matter Server : {ids}",
    "Passive contact unavailable: {err}": "Contact passif indisponible : {err}",
    "Passive contact on: every packet of a node counts as a contact": "Contact passif activé",
    "Passive contact stopped: {err}": "Contact passif arrêté : {err}",
    "not seen for {m}min": "plus vu depuis {m} min",
    "Thread network partitioned": "Réseau Thread partitionné",
    "Border router {name}": "Border router {name}",
    "Summary": "Bilan",
    'Connected to MQTT': 'Connecté à MQTT',
    'mDNS listening started': 'Écoute mDNS démarrée',
    "Stopping": "Arrêt",
    "{n} known Matter nodes loaded": "{n} nodes Matter connues chargées",
    'Thread network: {nets}{others}': 'Réseau Thread : {nets}{others}',
    "{n} Matter nodes": "{n} nodes Matter",
    "{n} Matter node": "{n} node Matter",
    "{n} border routers": "{n} border routers",
    "{n} border router": "{n} border router",
    "{n} smart speakers": "{n} enceintes connectées",
    "{n} smart speaker": "{n} enceinte connectée",
    '{node} missing from mDNS': "{node} : annonce mDNS perdue",
    '"{name}" offline': '« {name} » hors ligne',
    'Google Cast "{name}" offline': 'Google Cast « {name} » hors ligne',
    'AirPlay "{name}" offline': 'AirPlay « {name} » hors ligne',
    "Recovery of {node}: back, fail-safe not closed (it expires by itself)":
        "Récupération de {node} : revenue, fail-safe non refermé (il expire de lui-même)",
    "Recovery of {node}: {err}": "Récupération de {node} : {err}",
    "Recovery of {node}: no answer to ArmFailSafe ({err})": "Récupération de {node} : pas de réponse à ArmFailSafe ({err})",
    "Recovery of {node}: ArmFailSafe refused ({res})": "Récupération de {node} : ArmFailSafe refusé ({res})",
    "Recovery of {node}: ConnectNetwork refused ({res})": "Récupération de {node} : ConnectNetwork refusé ({res})",
    "OMR prefix {p} still published, no longer imposed": "Préfixe OMR {p} encore publié, plus imposé",
    "OMR prefix {p} still published, no longer imposed: the other border routers (Google TV…) can publish "
    "their prefixes again and the network change its prefix":
        "Préfixe OMR {p} encore publié, plus imposé : les autres border routers (Google TV…) peuvent republier "
        "leurs préfixes et le réseau changer de préfixe",
    "Thread leader: {before} → {after}": "Leader Thread : {before} → {after}",
    "Thread partitions: {before} → {after}": "Partitions Thread : {before} → {after}",
    "Border router {name}: detach ({d}s)": "Border router {name} : décrochage ({d} s)",
    "Thread tables read again: {n}/{total} nodes": "Tables Thread relues : {n}/{total} nodes",
    "OMR prefix: {before} → {after}": "Préfixe OMR : {before} → {after}",
    'Node prefixes: {before} → {after}': 'Préfixes des nodes : {before} → {after}',
    "Border routers online": "Border routers en ligne",
    "Thread leader": "Leader Thread",
    "Thread partitions": "Partitions Thread",
    "OMR prefix": "Préfixe OMR",
    "Last event": "Dernier événement",
    "Cannot read {file}: {err}": "Lecture de {file} impossible : {err}",
    "Cannot write {file}: {err}": "Écriture de {file} impossible : {err}",
    "announcement withdrawn, no answer": "annonce retirée, plus de réponse",
    'Border router {name} offline': 'Border router {name} hors ligne',
    "🧹 obsolete entity removed: {topic}": "🧹 entité obsolète supprimée : {topic}",
    "Home Assistant Matter fabric detected: {fabric}": "Fabric Matter de Home Assistant détectée : {fabric}",
    'Matter fabric not found: every node followed': 'Fabric Matter introuvable : toutes les nodes suivies',
    "Cannot write the event log: {err}": "Écriture du journal des événements impossible : {err}",
    "Border router renamed: \"{before}\" → \"{after}\"": "Border router renommé : « {before} » → « {after} »",
    "Border router {name} appeared ({role})": "Border router {name} apparu ({role})",
    "role": "rôle",
    "partition": "partition",
    "Thread interface": "interface Thread",
    "primary BBR": "BBR primaire",
    '{node} back in mDNS ({d})': "{node} : annonce mDNS revenue ({d})",
    '"{name}" appeared': '« {name} » apparue',
    " (restart likely)": " (redémarrage probable)",
    "Cannot process {name}: {err}": "Traitement de {name} impossible : {err}",
    "no answer to {n} probes": "ne répond plus depuis {n} sondages",
    "Cannot check the removals: {err}": "Vérification des retraits impossible : {err}",
    ' ({n} other networks ignored)': ' ({n} autres réseaux ignorés)',
    'Border router {name} back ({d})': 'Border router {name} de retour ({d})',
    "Border router {name}: ": "Border router {name} : ",
    'Node 0x{id} unknown to Home Assistant': "Node 0x{id} inconnue de Home Assistant",
    '"{name}" back ({d})': '« {name} » de retour ({d})',
    "Cannot write the hourly summary: {err}": "Bilan horaire impossible : {err}",
    "Cannot publish to MQTT: {err}": "Publication MQTT impossible : {err}",
    # web / node table
    'Node table ready': 'Tableau des nodes prêt',
    "Node table unavailable: port {port} in use": "Tableau des nodes indisponible : port {port} occupé",
    "Live link to the Matter Server: {n} nodes": "Lien direct avec le Matter Server : {n} nodes",
    # start / stop / switch
    'Mesh Guardian {v} starting': 'Démarrage de Mesh Guardian {v}',
    'Monitoring ready: {br} border routers, leader {leader}, automatic recovery {auto}': 'Surveillance prête : {br} border routers, leader {leader}, récupération automatique {auto}',
    'Stopping ({signal})': 'Arrêt ({signal})',
    "on": "activée",
    "off": "désactivée",
    "default": "par défaut",
    "last state saved, set by the switch": "dernier état enregistré, réglé par l'interrupteur",
    "switch.mesh_guardian_auto_recovery in Home Assistant": "switch.mesh_guardian_auto_recovery dans Home Assistant",
    'Automatic recovery already {state}': 'Récupération automatique déjà {state}',
    # leader
    "Ping all nodes": "Pinguer toutes les nodes",
    "Rename nodes": "Renommer les nodes",
    "Nodes to rename": "Nodes à renommer",
    'No node to rename': 'Aucune node à renommer',
    '{n} nodes renamed': '{n} nodes renommées',
    '{n} node renamed': '{n} node renommée',
    "; not renamed: {names}": " ; non renommées : {names}",
    "unavailable": "indisponible",
    "the button in Home Assistant": "le bouton dans Home Assistant",
    'Ping of all nodes already running': 'Ping de toutes les nodes déjà en cours',
    'Ping of all nodes: {n} nodes': 'Ping de toutes les nodes : {n} nodes',
    'Ping of all nodes interrupted: {err}': 'Ping de toutes les nodes interrompu : {err}',
    '{time} ping of all nodes: {ok}/{total}': '{time} ping de toutes les nodes : {ok}/{total}',
    'Ping of all nodes: {ok}/{total} answer': 'Ping de toutes les nodes : {ok}/{total} répondent',
    "; no answer: {names}": " ; sans réponse : {names}",
    # parent search
    "Find better parents": "Chercher de meilleurs parents",
    "Last parent search": "Dernière recherche de parents",
    "after a parent search requested with the button": "après une recherche de parent demandée avec le bouton",
    "{node}: looking for a better parent": "{node} : recherche d'un meilleur parent",
    "{node}: new parent not known yet": "{node} : résultat en attente de la node",
    "{node}: no answer from the node": "{node} : pas de réponse de la node",
    "{node}: Thread restart of a router (trial), first link {link}": "{node} : relance du Thread d'un routeur (essai), premier lien {link}",
    "{node}: Thread restart of the leader (trial), first link {link}": "{node} : relance du Thread du leader (essai), premier lien {link}",
    "{node}: Thread restarted, waiting for the result…": "{node} : Thread relancé, en attente du résultat…",
    "{node}: Thread restarted, router again, first link {link} (before: {before})": "{node} : Thread relancé, de nouveau routeur, premier lien {link} (avant : {before})",
    "{node}: Thread restarted, still an end device, first link {link} (before: {before})": "{node} : Thread relancé, encore appareil final, premier lien {link} (avant : {before})",
    "{node}: same parent {link}": "{node} : même parent {link}",
    "{node}: new parent {link}": "{node} : nouveau parent {link}",
    'Parent search already running': 'Recherche de parents déjà en cours',
    'Parent search skipped: the network is re-forming, try again later':
        'Recherche de parents annulée : le réseau se reforme, réessayer plus tard',
    'Parent search interrupted: {err}': 'Recherche de parents interrompue : {err}',
    'Parent search: checking the link of {n} end devices': "Recherche de parents : {n} appareils finaux",
    '{node}: parent search refused: {err}': "{node} : recherche de parent refusée : {err}",
    'Parent search: {n} poor link, {better} better now': "Recherche de parents : {better}/{n} lien amélioré",
    'Parent search: {n} poor links, {better} better now': "Recherche de parents : {better}/{n} liens améliorés",
    'Parent search: no poor link among {n} end devices': "Recherche de parents : aucun lien à améliorer parmi {n} appareils finaux",
    # recovery attempt
    "{node}: recovery attempt": "{node} : tentative de récupération",
    "{node}: Thread restarted, waiting for it to come back": "{node} : Thread relancé, en attente de son retour",
    "{node}: back after the recovery attempt": "{node} : de retour après la tentative de récupération",
    "{node}: still unavailable after the recovery attempt": "{node} : toujours indisponible après la tentative de récupération",
    "{node}: out of reach, the recovery attempt could not be sent":
        "{node} : hors de portée, la tentative de récupération n'a pas pu être envoyée",
    "{node}: heard on the radio but no answer to the recovery attempt":
        "{node} : entendue à la radio, mais pas de réponse à la tentative de récupération",
    "{node}: not heard on the radio and no answer to the network ping: nothing sent":
        "{node} : pas entendue à la radio et pas de réponse au ping réseau : rien n'est envoyé",
    "{node}: reachable on the network, Matter session coming back": "{node} : joignable sur le réseau, session Matter en reprise",
    "{node}: back after the ping of the recovery attempt": "{node} : de retour après le ping de la tentative",
    "{node}: reachable on the network, not back in Home Assistant yet":
        "{node} : joignable sur le réseau, pas encore revenue dans Home Assistant",
    "{node}: recovery attempt refused": "{node} : tentative de récupération refusée",
    "{node}: no longer announced on the network, its address is not known: the recovery attempt could not be sent":
        "{node} : ne s'annonce plus sur le réseau, son adresse n'est pas connue : la tentative de récupération n'a pas pu être envoyée",
    # USB/IP Link add-on (radio plugged into another computer)
    "{name}: USB/IP link back ({server})": "{name} : lien USB/IP rétabli ({server})",
    "{name}: USB/IP link cut ({server})": "{name} : lien USB/IP coupé ({server})",
    "{server} does not answer": "{server} ne répond pas",
    # USB/IP Link: latency of the link that carries the radio
    "USB/IP link to {server} slow: {avg} ms on average (worst {max} ms), the radio of the border router "
    "can drop: check the network between Home Assistant and that computer (Wi-Fi, cable, load)":
        "Lien USB/IP vers {server} lent : {avg} ms en moyenne (pire {max} ms), la radio du border router "
        "peut décrocher : vérifier le réseau entre Home Assistant et cet ordinateur (Wi-Fi, câble, charge)",
    "USB/IP link to {server} with peaks: {max} ms at worst for {avg} ms on average, the radio of the border "
    "router can drop: check the network between Home Assistant and that computer (Wi-Fi, cable, load)":
        "Lien USB/IP vers {server} avec des pics : jusqu'à {max} ms pour {avg} ms en moyenne, la radio du border "
        "router peut décrocher : vérifier le réseau entre Home Assistant et cet ordinateur (Wi-Fi, câble, charge)",
    # Thread Anchor: pause, catch-up, takeover, proposal
    "Thread Anchor is stopped": "Thread Anchor est arrêté",
    "Thread Anchor stopped: OMR prefix {p} still published, no longer imposed":
        "Thread Anchor arrêté : préfixe OMR {p} encore publié, plus imposé",
    "radio {names} cut off (USB/IP)": "radio {names} coupée (USB/IP)",
    "OMR prefix no longer in place ({err})": "préfixe OMR plus en place ({err})",
    "Recovery of lost nodes paused: {why}": "Récupération des nodes perdues en pause : {why}",
    "Recovery of lost nodes resumed after {m} min: {n} node that dropped meanwhile pinged in {s} s":
        "Récupération des nodes perdues reprise après {m} min : {n} node tombée entre-temps sera relancée dans {s} s",
    "Recovery of lost nodes resumed after {m} min: {n} nodes that dropped meanwhile pinged in {s} s":
        "Récupération des nodes perdues reprise après {m} min : {n} nodes tombées entre-temps seront relancées dans {s} s",
    "The other border routers took over the OMR prefix: {fav} instead of {wanted}":
        "Les autres border routers ont repris la main sur le préfixe OMR : {fav} au lieu de {wanted}",
    "OMR prefix {wanted} favored again on the network ({m} min)":
        "Préfixe OMR {wanted} de nouveau retenu sur le réseau ({m} min)",
    "Thread Anchor: OMR prefix {p} fixed, app restarted": "Thread Anchor : préfixe OMR {p} imposé, app redémarrée",
    "Sweep skipped: {why}": "Balayage sauté : {why}",
    "Catch-up after the cut: every node that dropped is back": "Rattrapage après la coupure : toutes les nodes tombées sont revenues",
    "Catch-up after the cut: {n} nodes pinged ({names})": "Rattrapage après la coupure : {n} nodes relancées ({names})",
    "The other border routers (Google TV…) took over the OMR prefix: {fav} instead of {wanted}; "
    "{n} node took it, it comes back to {wanted} with the border router of Home Assistant":
        "Les autres border routers (Google TV…) ont repris la main sur le préfixe OMR : {fav} au lieu de {wanted} ; "
        "{n} node l'a pris, elle reviendra sur {wanted} avec le border router de Home Assistant",
    "The other border routers (Google TV…) took over the OMR prefix: {fav} instead of {wanted}; "
    "{n} nodes took it, they come back to {wanted} with the border router of Home Assistant":
        "Les autres border routers (Google TV…) ont repris la main sur le préfixe OMR : {fav} au lieu de {wanted} ; "
        "{n} nodes l'ont pris, elles reviendront sur {wanted} avec le border router de Home Assistant",
    "Recovery of lost nodes paused while {why}: the nodes that drop meanwhile are pinged once it is back":
        "Récupération des nodes perdues en pause, cause : {why} ; les nodes qui tombent entre-temps seront relancées à son retour",
    "Fixed OMR prefix {p} back in place on the border router":
        "Préfixe OMR imposé {p} de nouveau en place sur le border router",
    "Fixed OMR prefix {p} no longer in place on the border router (now: {cur})":
        "Préfixe OMR imposé {p} plus en place sur le border router (actuellement : {cur})",
    "Fixed OMR prefix {p} no longer in place on the border router (now: {cur}): the other border "
    "routers (Google TV…) can publish their prefixes again and the network change its prefix":
        "Préfixe OMR imposé {p} plus en place sur le border router (actuellement : {cur}) : les autres border "
        "routers (Google TV…) peuvent republier leurs préfixes et le réseau changer de préfixe",
    "{name}: USB/IP link cut since {at}, the radio it carries is out":
        "{name} : lien USB/IP coupé depuis {at}, la radio qu'il porte est hors service",
    # alive test of the recovery attempt, announcement in a node's place (trial)
    "{node}: alive test: {radio}; {ping}": "{node} : test de vie : {radio} ; {ping}",
    "heard on the radio by {who} {ago} ago": "entendue à la radio par {who} il y a {ago}",
    "not heard on the radio by its neighbors": "pas entendue à la radio par ses voisins",
    "radio not checked (address of its radio not known)": "radio non vérifiée (adresse radio inconnue)",
    "answers the network ping on {ip}": "répond au ping réseau sur {ip}",
    "no answer to the network ping ({ips})": "pas de réponse au ping réseau ({ips})",
    "no address to ping": "aucune adresse à pinguer",
    "{node}: announced in its place on {ip} (trial), for the recovery attempt":
        "{node} : annoncée à sa place sur {ip} (essai), pour la tentative de récupération",
    "{node}: recovery attempt not sent: stayed on the old prefix {prefix} after {br} changed it at {at}, its new address is not known":
        "{node} : tentative de récupération non envoyée : restée sur l'ancien préfixe {prefix} après le changement fait par {br} à {at}, sa nouvelle adresse n'est pas connue",
    # node left on an OMR prefix the border routers no longer publish
    "{node}: stayed on the old prefix {prefix} after {br} changed it at {at}: its new address is not known":
        "{node} : restée sur l'ancien préfixe {prefix} après le changement fait par {br} à {at} : sa nouvelle adresse n'est pas connue",
    # gentle way: announcement kept, automatic diagnostic
    "{node}: announced in its place on {ip}, waiting for it to come back (the announcement stays until it "
    "announces itself; its radio is not restarted)":
        "{node} : annoncée à sa place sur {ip}, en attente de son retour (l'annonce reste jusqu'à ce qu'elle "
        "s'annonce elle-même ; sa radio n'est pas redémarrée)",
    "{node}: the Thread diagnostic gave no way to reach it, nothing else sent":
        "{node} : le diagnostic Thread n'a donné aucun moyen de la joindre, rien d'autre n'est envoyé",
    "Automatic Thread diagnostic failed: {err}": "Diagnostic Thread automatique en échec : {err}",
    "{node}: automatic Thread diagnostic: {diag}": "{node} : diagnostic Thread automatique : {diag}",
    "{node}: back once announced in its place on its current address":
        "{node} : revenue une fois annoncée à sa place sur son adresse actuelle",
    "{node}: announces itself again on {prefix}, announcement in its place withdrawn":
        "{node} : s'annonce de nouveau elle-même sur {prefix}, annonce à sa place retirée",
    "{node}: still not announcing itself on the prefix of the network after 24 h, announcement in its place withdrawn":
        "{node} : ne s'annonce toujours pas elle-même sur le préfixe du réseau après 24 h, annonce à sa place retirée",
    # Thread diagnostic by Thread Anchor (recovery attempt)
    "Network stack stuck: last resort, cut its power for 10s (your call)":
        "Pile réseau figée : dernier recours, couper son alimentation 10 s (à toi de décider)",
    "Only has the old address prefix: a remedy on the border router is possible":
        "N'a que l'ancien préfixe d'adresse : un remède sur le border router est possible",
    "no answer from Thread Anchor": "pas de réponse de Thread Anchor",
    "Thread diagnostic ({where}) failed: {why}": "Diagnostic Thread ({where}) impossible : {why}",
    "answers through the mesh ({ms} ms)": "répond par le maillage ({ms} ms)",
    "no answer through the mesh": "pas de réponse par le maillage",
    "not pinged": "pas de ping",
    "no routable address": "aucune adresse routable",
    "Thread diagnostic ({where}): {ping}; addresses: {addrs}":
        "Diagnostic Thread ({where}) : {ping} ; adresses : {addrs}",
    "{node}: announced in its place on {ip} (address given by the Thread diagnostic)":
        "{node} : annoncée à sa place sur {ip} (adresse donnée par le diagnostic Thread)",
    "{node}: only has the old prefix ({addrs}): it did not take the prefix of the network. A remedy on the "
    "border router of Home Assistant is possible (a route to the old prefix for a while), with your agreement":
        "{node} : n'a que l'ancien préfixe ({addrs}) : elle n'a pas pris le préfixe du réseau. Un remède sur le "
        "border router de Home Assistant est possible (une route vers l'ancien préfixe pendant un moment), avec ton accord",
    "{node}: heard by {who} but no answer through the mesh: its network stack is stuck. No remote way "
    "is left: cutting its power for 10 s is the last resort, your call":
        "{node} : entendue par {who} mais aucune réponse par le maillage : sa pile réseau est figée. Plus aucune voie "
        "à distance : couper son alimentation 10 s est le dernier recours, à toi de décider",
    "{node}: recovery attempt not sent: stayed on the old prefix {prefix}, its new address is not known":
        "{node} : tentative de récupération non envoyée : restée sur l'ancien préfixe {prefix}, sa nouvelle adresse n'est pas connue",
    "Stayed on an old address prefix, no longer used on the network":
        "Restée sur un ancien préfixe d'adresse, plus utilisé sur le réseau",
    "heard by {name} {m} min ago ({rssi} dBm)": "entendue par {name} il y a {m} min ({rssi} dBm)",
    "Alive but unreachable: try the recovery attempt": "Vivante mais injoignable : lancer la tentative de récupération",
    "{alive}: it has power and its radio works, it cannot be reached at its address (announcement or prefix out of date)":
        "{alive} : elle a du courant et sa radio fonctionne, mais elle est injoignable à son adresse (annonce ou préfixe périmé)",
    "Stayed on the old address prefix after {br} changed it at {at}":
        "Restée sur l'ancien préfixe d'adresse après le changement fait par {br} à {at}",
    "{prefix}: its new address is not known, no command reaches it until it announces itself again":
        "{prefix} : sa nouvelle adresse n'est pas connue, aucune commande ne l'atteint tant qu'elle ne s'annonce pas à nouveau",
    "The border routers changed the address prefix {n}× in 24h: each time every node must take a new address, the ones that do not follow drop":
        "Les border routers ont changé le préfixe d'adresse {n}× en 24 h : à chaque fois, toutes les nodes doivent prendre une nouvelle adresse, celles qui ne suivent pas décrochent",
    "{node}: reset from a distance, to pair again": "{node} : réinitialisée à distance, à appairer à nouveau",
    "{node}: removed from Home Assistant": "{node} : supprimée de Home Assistant",
    "{what} failed, started again: {err}": "{what} en échec, relancé : {err}",
    "Active probes": "Sondage actif",
    "MQTT publishing": "Publication MQTT",
    "MQTT connection: {err}": "Connexion MQTT : {err}",
    "MQTT connection refused: {err}": "Connexion MQTT refusée : {err}",
    "MQTT settings read again from the Supervisor": "Réglages MQTT relus auprès du Supervisor",
    "MQTT message on {topic}: {err}": "Message MQTT sur {topic} : {err}",
    "Cannot read {file} ({err}): kept as {bad}, starting without it": "Lecture de {file} impossible ({err}) : fichier conservé sous {bad}, démarrage sans lui",
    # storm
    "Thread storm": "Tempête Thread",
    "Thread storm: {why}": "Tempête Thread : {why}",
    "{n} partition splits in 15min": "{n} partitions en 15 min",
    "{n} OMR prefixes at the same time": "{n} préfixes OMR en même temps",
    "{n} nodes unavailable in 15min": "{n} nodes indisponibles en 15 min",
    'End of the Thread storm ({m}min, {n} nodes dropped)': "Fin de la tempête Thread ({m} min, {n} nodes indisponibles)",
    'Sweep skipped (storm)': "Balayage suspendu (tempête)",
    "Storm check failed: {err}": "Détection de tempête en erreur : {err}",
    # routing
    'Thread nodes unreachable from Home Assistant: no route to the Thread network ({bad} nodes)': "{bad} nodes Thread injoignables : pas de route depuis Home Assistant",
    '; border routers on another network: {names}': " ; border routers sur un autre sous-réseau : {names}",
    'Thread nodes reachable again': 'Nodes Thread de nouveau joignables',
}


def set_language(value):
    global _LANG
    _LANG = "fr" if str(value or "").lower().startswith("fr") else "en"


def lang():
    return _LANG


def t(text, **kw):
    if _LANG == "fr":
        s = FR.get(text, CODES_EN.get(text, text))
    else:
        s = CODES_EN.get(text, text)
    return s.format(**kw) if kw else s


def tn(one, many, n, **kw):
    """t() with the singular or plural source text for the count n (French: singular for 0 and 1)."""
    single = n <= 1 if _LANG == "fr" else n == 1
    return t(one if single else many, n=n, **kw)

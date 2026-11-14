# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Translations of the log, events and entity names (option "language").

Source strings are English. t("text {x}", x=1) returns the translation in the
selected language (English if missing) with the values filled in.
"""

_LANG = "en"

# technical codes (roles, interface states) shown to humans
CODES_EN = {
    "detached": "detached", "child": "end device", "router": "router", "leader": "routeur leader",
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
    # advice
    'Advice: {n} nodes': 'Conseils : {n} nodes',
    'Advice: {n} node': 'Conseils : {n} node',
    '{child}: new parent {parent} ({rssi}dBm), before {old} ({old_rssi}dBm) {verdict}': "{child} : nouveau parent {parent}, {old_rssi} → {rssi} dBm",
    "yes ({n} spontaneous change(s) seen)": "oui ({n}×)",
    "Cannot save the radio advice state: {err}": "Sauvegarde des conseils radio impossible : {err}",
    '▲ better': '▲ meilleur',
    "after the node rebooted (battery removed or power cycled)": "après redémarrage de la node (pile retirée ou remise sous tension)",
    "its parent {parent} is unstable (reboots / detaches): check its power supply":
        "son parent {parent} est instable (redémarrages / décrochages) : vérifier son alimentation",
    "not seen in {h}h of observation": "non ({h} h)",
    "under observation ({h}h)": "en observation ({h} h)",
    '▼ worse': '▼ moins bon',
    '≈ similar': '≈ équivalent',
    "its old parent disappeared or rebooted": "son ancien parent avait disparu ou redémarré",
    "spontaneous change": "changement spontané",
    "add a mains-powered Thread router (e.g. a Matter smart plug) near \"{area}\": the node already had a chance to find a better parent and did not":
        "Ajouter un routeur sur secteur (prise connectée) près de {area} : aucun meilleur parent à portée.",
    '{node}: {action} (parent {parent}, {rssi}dBm)': '{node} : {action} (parent {parent}, {rssi} dBm)',
    "remove the battery for 10s and put it back: it will pick the best parent available":
        "retirer la pile 10 s puis la remettre : elle choisira le meilleur parent du moment",
    "unplug it for 10s and plug it back: it will pick the best parent available":
        "la débrancher 10 s puis la rebrancher : elle choisira le meilleur parent du moment",
    ", battery": ", pile",
    "Add a router near {area}": "Ajouter un routeur près de {area}",
    "Remove the battery 10s": "Retirer la pile 10 s",
    "Finding a new parent could improve the situation": "Rechercher un nouveau parent pourrait améliorer la situation",
    "press Find a new parent on its line: it attaches again and picks the best parent it hears (if it refuses: remove the battery or unplug it for 10s)": "Bouton « Recherche d'un nouveau parent ». Si refus : couper son alimentation 10 s.",
    "{parent} restarts ({n}× in 24h): finding a new parent could improve the situation":
        "{parent} redémarre ({n}× en 24 h) : rechercher un nouveau parent pourrait améliorer la situation",
    "{parent} detaches ({n}× in 24h): finding a new parent could improve the situation":
        "{parent} décroche ({n}× en 24 h) : rechercher un nouveau parent pourrait améliorer la situation",
    "Press Find a new parent on its line so it picks a steadier parent": "Rechercher un nouveau parent.",
    "Unplug 10s": "Débrancher 10 s",
    "Unstable parent": "Parent instable",
    "{parent} restarts ({n}× in 24h): change the parent": "{parent} redémarre ({n}× en 24 h) : changer de parent",
    "{parent} detaches ({n}× in 24h): change the parent": "{parent} décroche ({n}× en 24 h) : changer de parent",
    "{parent} restarted {n} times in 24h": "{parent} a redémarré {n}× en 24 h",
    "{parent} detached {n} times in 24h": "{parent} a décroché {n}× en 24 h",
    ": this node loses its parent each time. ": ". ",
    "Remove its battery for 10s so it picks a steadier parent": "Retirer sa pile 10 s pour qu'elle choisisse un parent plus stable",
    "Unplug it for 10s so it picks a steadier parent": "La débrancher 10 s pour qu'elle choisisse un parent plus stable",
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
    '{name}: no answer after {max} pings': '{name} : aucune réponse après {max} pings',
    "Recovery cycle failed: {err}": "Cycle de récupération en erreur : {err}",
    '{name} unavailable': '{name} indisponible',
    '{name} back after ping {i} ({m}min)': "{name} de nouveau disponible après le ping {i} ({m} min)",
    '{name} back on its own ({m}min)': "{name} de nouveau disponible ({m} min)",
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
    ', most unstable: {name} ({d} detaches)': ', plus instable : {name} ({d} décrochages)',
    ', most unstable: {name} ({d} detach)': ', plus instable : {name} ({d} décrochage)',
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
    "best link {rssi}dBm: add a mains-powered Thread router (e.g. a Matter smart plug) between this node and the rest of the mesh": "Meilleur lien {rssi} dBm : ajouter un routeur sur secteur plus près.",
    "Ethernet": "Ethernet",
    "Announced on the Matter fabric but unknown to the Matter Server (removed without a factory reset?): {ids}": "Nodes inconnues du Matter Server : {ids}",
    "Passive contact unavailable: {err}": "Contact passif indisponible : {err}",
    "Passive contact on: every packet of a node counts as a contact": "Contact passif activé",
    "Passive contact stopped: {err}": "Contact passif arrêté : {err}",
    "not seen for {m}min": "plus vu depuis {m} min",
    "Thread network partitioned": "Réseau Thread partitionné",
    "Border router {name}": "Border router {name}",
    "Summary": "Bilan",
    '{br} border routers, leader {leader}, {down} unavailable, {rec} recoveries, {weak} weak links': '{br} border routers, leader {leader}, {down} indisponibles, {rec} récupérations, {weak} liens faibles',
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
    "Thread leader: {before} → {after}": "Leader Thread : {before} → {after}",
    "{what}: {before} → {after} partitions": "{what} : {before} → {after} partitions",
    'network partitioned': 'réseau partitionné',
    "Thread partition": "partition Thread",
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
    "{node}: new parent not known yet": "{node} : nouveau parent pas encore connu",
    "{node}: same parent, {parent}, {after} dBm": "{node} : même parent, {parent}, {after} dBm",
    "{node}: new parent {parent}, {before} → {after} dBm": "{node} : nouveau parent {parent}, {before} → {after} dBm",
    'Parent search already running': 'Recherche de parents déjà en cours',
    'Parent search skipped: the network is re-forming, try again later':
        'Recherche de parents annulée : le réseau se reforme, réessayer plus tard',
    'Parent search interrupted: {err}': 'Recherche de parents interrompue : {err}',
    'Parent search: checking the link of {n} end devices': "Recherche de parents : {n} appareils finaux",
    '{node}: looking for a better parent (now {rssi}dBm, LQI {lqi})':
        '{node} : recherche d\'un meilleur parent (actuellement {rssi} dBm, LQI {lqi})',
    '{node}: parent search refused: {err}': "{node} : recherche de parent refusée",
    '{node}: better parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})':
        '{node} : meilleur parent, {before} dBm → {after} dBm (LQI {lqi_before} → {lqi})',
    '{node}: weaker parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})':
        '{node} : parent moins bon, {before} dBm → {after} dBm (LQI {lqi_before} → {lqi})',
    '{node}: similar parent, {before}dBm → {after}dBm (LQI {lqi_before} → {lqi})':
        '{node} : parent équivalent, {before} dBm → {after} dBm (LQI {lqi_before} → {lqi})',
    '{node}: same parent kept, {after}dBm (LQI {lqi}): no better router in range':
        '{node} : même parent conservé, {after} dBm (LQI {lqi}) : pas de meilleur routeur à portée',
    '{node}: parent search sent, new link not read yet': '{node} : recherche de parent envoyée, nouveau lien pas encore lu',
    'Parent search: {n} poor link, {better} better now': "Recherche de parents : {better}/{n} lien amélioré",
    'Parent search: {n} poor links, {better} better now': "Recherche de parents : {better}/{n} liens améliorés",
    'Parent search: no poor link among {n} end devices': "Recherche de parents : aucun lien à améliorer",
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

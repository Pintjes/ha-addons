# Mesh Guardian

Mesh Guardian watches over your Thread / Matter network, brings lost Matter
nodes back automatically and tells you which radio links are weak and what to
do about them.

## Contents

- [How it works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Notifications](#notifications)
- [Events](#events)
- [Radio advice](#radio-advice)
- [Names Home Assistant → Matter](#names-home-assistant--matter)
- [Find better parents](#find-better-parents)
- [Node table](#node-table)
- [Wi-Fi and Ethernet nodes](#wi-fi-and-ethernet-nodes)
- [Network quality](#network-quality)
- [Thread storms](#thread-storms)
- [Supervisor access](#supervisor-access)
- [FAQ and troubleshooting](#faq-and-troubleshooting)
- [Known limitations](#known-limitations)

## How it works

```text
            mDNS (_meshcop, _matter, _googlecast, _airplay)
 Border routers ─────────────────────────────────────┐
 Matter nodes   ─────────────────────────────────────┤
                                                     ▼
 Home Assistant ── node availability ──▶  Mesh Guardian ── MQTT ──▶ Home Assistant entities
 Matter Server  ◀── ping_node / get_nodes ──┘        │
                                                     └──▶ app log, /share/mesh_guardian/events.jsonl
```

1. **Listening.** The app follows the mDNS announcements of the Thread border
   routers (`_meshcop._udp`, any vendor), of the Matter nodes of your Home
   Assistant fabric (`_matter._tcp`) and of smart speakers / hubs (`_googlecast._tcp`,
   `_airplay._tcp`). Every known service is also probed actively, so a device
   that is unplugged or crashes is detected even if it does not say goodbye.
2. **Recovery.** Every 15 seconds it reads which Matter nodes are unavailable in
   Home Assistant. A node unavailable for 2 minutes (30 seconds right after a
   prefix change) is pinged through the Matter Server, then every 5 minutes, at
   most 6 times. A ping makes the Matter Server resolve the node again and reach
   it on its current address. When many nodes drop at once (Home Assistant or
   Matter Server restart), pinging pauses for 5 minutes.
3. **Radio survey.** Every 30 minutes it reads the Thread diagnostics that the
   Matter Server already has in cache (no radio traffic): neighbor tables,
   parents, roles and counters. After a start of the app, the neighbor and
   route tables of the mains-powered nodes are first read again, one node every
   few seconds (the cache can be hours old); the first survey waits for it
   (5 to 10 minutes, at most 20). Battery nodes are not read then: the values
   read from them in the last 2 hours (role, tables, addresses) are kept across
   a restart instead.
4. **Statistics.** Outages are counted per node over 7 days. On first start,
   the last 7 days are rebuilt from the Home Assistant history.
5. **Restarts.** A restart of the Matter Server or of Home Assistant is read in
   the Supervisor log: when it happened and why (restarted, updated, crashed).
   The nodes it took down share one card for 5 minutes instead of one card
   each. See [Supervisor access](#supervisor-access).

By default, only the Thread network used by your Matter nodes is followed;
border routers of other networks (e.g. a neighbor's) are ignored.

## Installation

> **Requirements:** an MQTT broker (the **Mosquitto broker** app) and the
> **MQTT** integration. Without them no entity is created.

1. Add the repository `https://github.com/Pintjes/ha-addons` to Home Assistant
   (**Settings → Apps → Install app → ⋮ → Repositories**).
2. Install **Mesh Guardian** and start it.
3. Pick your **language** in the *Configuration* tab and restart the app.
4. Enable **Start on boot** and **Watchdog**.

After about 2½ minutes the log shows `Monitoring ready`, and a **Mesh
Guardian** device with its entities appears in the MQTT integration.

**Requirements:** Home Assistant OS or Supervised, the Matter integration with
the Matter Server app, the Mosquitto broker app and the MQTT integration.

## Configuration

| Option | Default | Description |
|---|---|---|
| `language` | `en` | Language of the log, events and entity names: `en` or `fr`. |
| `ping_after` | `120` | Seconds a node must be unavailable before the first ping (30s for 10 minutes after a prefix change). |
| `ping_retry` | `300` | Seconds between two pings of the same node. |
| `ping_max_attempts` | `6` | Pings before reporting that the node needs attention. |
| `ping_all_interval` | `60` | Minutes between two sweeps of the mains-powered nodes (`0` = never). |
| `radio_interval` | `30` | Minutes between two radio surveys. |
| `rebuild_history` | `true` | On first start or after a reinstall, rebuild 7 days of per-node outage statistics from the Home Assistant history. Turn off to start from zero. |
| `all_thread_networks` | `false` | Also follow Thread networks not used by your Matter nodes. |
| `log_events_to_file` | `true` | Also write events to `/share/mesh_guardian/events.jsonl` (rotated at 5 MB). |
| `advice` | `true` | Give advice for the available nodes (*Find a new link*, *Add a router*…): cards, *Advice* column, log and `advice` events. Off: none of them. An unavailable node keeps what to do about it, and the notes about the network stay. |
| `thread_diag_recovery` | `true` | With the Thread Anchor app: an unavailable mains node that a neighbor hears, whose address is not known or on an old prefix, is reached through the mesh and announced in its place on its current address (its radio is not restarted). At most once per node every 30 min and 5 nodes per hour, not during a pause (radio or prefix out) or a Thread storm. |
| `passive_contact` | `false` | Count every IPv6 packet sent by a node and seen on the host as a contact (*Last contact*), including the reports the Matter Server does not forward because their value did not change, and the answers to pings sent by Home Assistant. Only the source address of the packets is read. Uses the `NET_RAW` privilege. |
| `matter_fabric` | *(empty)* | Advanced: compressed fabric id of Home Assistant. Detected automatically when empty. |
| `matter_server_url` | *(empty)* | Advanced: WebSocket address of the Matter Server (e.g. `ws://192.168.1.10:5580/ws`) when it does not run as the Matter Server app (Docker container, other machine). Defaults to the Matter Server app. |

Automatic recovery is switched on and off with
`switch.mesh_guardian_auto_recovery` (off at first start: turn it on to let the app ping lost nodes).

## Entities

All entities belong to the **Mesh Guardian** device (MQTT integration).
"Current" means the value describes the present state: there is nothing to
reset.

**Network** — mDNS listened to continuously, every known service probed every
minute, border routers browsed again every 5 minutes.

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_border_routers_online` | border routers online; role of each in `border_routers` | every announcement or probe | current |
| `sensor.mesh_guardian_br_<id>` | one per border router: `leader`, `router`, `child`, `detached` or `offline` (offline only after 15 minutes without any answer); `key`, `detached_24h`, `last_detached`, `same_subnet_as_home_assistant`, `last_contact`, partition, OMR prefix, addresses | same | `detached_24h`: sliding 24h |
| `sensor.mesh_guardian_thread_leader` | name of the Thread leader (border router or any router of the mesh) | when it changes, once the new leader held 30s | current |
| `sensor.mesh_guardian_thread_partitions` | number of partitions (1 = normal) | when it changes, once the new state held 30s | current |
| `binary_sensor.mesh_guardian_thread_network_partitioned` | problem when there is more than one partition or leader | same | current |
| `sensor.mesh_guardian_omr_prefix` | OMR prefix(es); several at once is an anomaly | same | current |
| `binary_sensor.mesh_guardian_thread_storm` | problem during a Thread storm; start, duration, nodes, border routers detached, prefixes | every 5s over a sliding 15 minutes | ends after 15 quiet minutes |
| `sensor.mesh_guardian_last_event` | text of the last event (its history is the event log) | every event | event counter reset when the app restarts |

**Recovery** — Home Assistant read every 15 seconds.

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_matter_nodes_unavailable` | nodes unavailable in Home Assistant; `routing` problem if detected | every 15s | current |
| `sensor.mesh_guardian_matter_nodes_available` | nodes available in Home Assistant | every 15s | current |
| `sensor.mesh_guardian_recovered_by_ping` | nodes back less than 3 min after an action on them: a ping (automatic or from the page) or a recovery attempt (total). This does not prove the action brought them back. Attributes: `back_on_their_own`, `gave_up`, `pings_sent`, and the same counters `since_start` and over `last_24h`, with `back_after_auto` / `back_after_manual` / `back_after_attempt` | every return | total: on reinstall or with the reset button; `since_start`: when the app restarts; `last_24h`: sliding |
| `switch.mesh_guardian_auto_recovery` | automatic recovery on / off (off at first start) | when switched | kept across restarts |
| `button.mesh_guardian_ping_all_nodes` | pings every node now, battery and unavailable nodes included; result in the `ping_all_done` event | when pressed | — |
| `sensor.mesh_guardian_network_quality` | network quality in % over the last hour (see [Network quality](#network-quality)); `parts`, `score_24h`, `parts_24h`, `capped`, `median_response_ms` | every minute | with the reset button |
| `button.mesh_guardian_reset_statistics` | resets every statistic: counters, outages, 24h/7d columns, last contacts, border router detaches, past storms (names, settings and the switch are kept); no 7-day history taken over afterwards | when pressed | — |

**Radio** — survey every 30 minutes (values cached by the Matter Server, no radio traffic).

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_weak_radio_links` | weak links among the links in use (child → parent, router → its first hop to the border router): link quality 1 or 0 | every survey | current |
| `sensor.mesh_guardian_thread_parents` | number of children; parent and signal of each | every survey | current |
| `button.mesh_guardian_find_better_parents` | reads the parent link of every end device and asks those with a poor link to attach again (see [Find better parents](#find-better-parents)) | when pressed | — |
| `sensor.mesh_guardian_parent_search` | date of the last parent search; `checked`, `poor_links`, `better`, `nodes` | after each search | kept until the next search |

**Names**

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_nodes_to_rename` | nodes whose Matter name differs from Home Assistant; `nodes`, `in_sync`, `checked`, `last_rename` | every 5 minutes (compares, writes nothing) | current |
| `button.mesh_guardian_rename_nodes` | writes the Home Assistant name into these nodes | when pressed | — |

Per-node details (outages, detaches, parent changes, advice, battery) are in
the node table.

## Notifications

Two automation blueprints are in the repository (import them with
**Settings → Automations → Blueprints → Import blueprint** and the raw URL):

- `blueprints/mesh_guardian_node_unavailable.yaml` — nodes unavailable for longer than a delay, with their names;
- `blueprints/mesh_guardian_network_alert.yaml` — border router offline, network partitioned, or quality below a threshold.

Pick any notification action; the text is in the variable `message`.

## Events

Every event is written to the app log, published on the MQTT topic
`mesh_guardian/event` (JSON) and, optionally, appended to
`/share/mesh_guardian/events.jsonl`.

| Event | Meaning |
|---|---|
| `startup`, `addon_stop` | monitoring ready (with the version and the state of the automatic recovery), app stopping (with the signal received) |
| `br_appeared`, `br_back`, `br_offline`, `br_change`, `br_renamed`, `br_removed` | border router life (role, partition, prefix…); a role change is reported once it held 60s |
| `br_detach` | a border router left the network and came back within 30s (alone in its own partition): reported as a short detach of that border router, counted in its `detached_24h` and as a partition split for storms |
| `leader_change`, `partition_change`, `omr_change`, `node_prefix_change` | network-wide changes — the usual cause of lost nodes; leader and partitions once the new state held 30s |
| `matter_offline`, `matter_back`, `matter_appeared` | Matter node missing from / back in mDNS (not reported for a battery node still available in Home Assistant) |
| `usb_link_lost`, `usb_link_back` | the USB/IP Link app lost / attached again a device (a radio plugged into another computer) |
| `recovery_paused`, `recovery_resumed`, `recovery_catchup` | lost nodes not pinged while the radio of the border router is cut off (USB/IP Link) or its fixed OMR prefix is out with an error; once back, one targeted ping of the nodes that dropped meanwhile |
| `omr_takeover`, `omr_takeover_end` | the other border routers favor their own OMR prefix instead of the one Thread Anchor fixes (`favored`, `wanted`) / the fixed one is favored again |
| `omr_anchor_set` | the proposed OMR prefix was written into the options of Thread Anchor from the page |
| `omr_fixed_lost`, `omr_fixed_back` | the OMR prefix Thread Anchor (formerly USB/IP Link) keeps the OpenThread border router on (option `omr_prefix`) is no longer / again in place: at once with an error (border router stopped, no Docker access…), else after 60s (a restart of the border router is set again within the minute) (`prefix`, `current`, `mode`, `error`) |
| `node_stale_prefix` | a node missing from mDNS is still on an OMR prefix the border routers no longer publish: it did not take the new prefix, its address is not known (`prefix`, `br`) |
| `mdns_burst` | services withdrawn then re-announced within seconds (no real absence); only in the event file and on MQTT, counted in `mdns_bursts` |
| `speaker_appeared`, `speaker_back`, `speaker_offline` | smart speaker / hub online state (restart detection) |
| `node_unavailable`, `node_recovered_by_ping` (back after an action: `after` = `auto` / `manual` / `attempt`), `node_back_on_its_own`, `ping`, `ping_gave_up`, `ping_rearmed` (sign of life after giving up: pings again), `ping_error` | automatic recovery; after `ping_gave_up`, one ping every 30 min while the node stays unavailable |
| `global_outage`, `global_return` | many nodes at once (Home Assistant / Matter Server restart) |
| `server_restart` | restart of the Matter Server or of Home Assistant read in the Supervisor log, with `who` (`matter` / `ha`), `cause` (`requested`, `update`, `crash`, `start`), exit `code` and `version` |
| `storm_start`, `storm_end` | Thread storm (see below) |
| `stats_reset` | statistics reset by the button |
| `routing_problem`, `routing_ok` | nodes announced in mDNS but unreachable from Home Assistant |
| `sweep` | periodic ping of mains-powered nodes (the nodes that did not answer are in `bad`) |
| `ping_all`, `ping_all_done` | ping of every node requested with the button |
| `radio_survey`, `radio_advice`, `parent_change` | radio quality and advice (also shown in the node table) |
| `names`, `name_synced` | names Home Assistant → Matter (Rename nodes button) |
| `reattach`, `reattach_node`, `reattach_result`, `reattach_done` | parent search (Find better parents button): start, node asked to attach again, its link before and after (`result`: `better`, `worse`, `similar`, `same`, `unknown`, then `noanswer` if the node never answered; `unsupported` or `failed` when the node refuses; `restarted` for the Thread restart of a router, a trial), summary |
| `recover_node`, `recover_alive`, `recover_proxy`, `recover_result` | recovery attempt on an unavailable node (button of the node table): start; alive test (`heard`: routers that hear it on the radio, `ping_ok` / `ping_ko`: addresses); announcement in its place when it answers the ping without announcing itself (trial), or on the address the Thread diagnostic of Thread Anchor found (a node heard on the radio whose address is not known or on an old prefix: reached through the mesh by its RLOC16 or its mesh-local EID; that announcement is kept until the node announces itself again on the prefix of the network); once the Thread diagnostic ran, the fail-safe and ConnectNetwork are never sent; then `result`: `back_announce` (back once announced in its place), `announced` (announced in its place, not back yet: the announcement stays), `unknown` (the Thread diagnostic gave no way to reach it), `back`, `noanswer` (command sent, node still unavailable), `unreachable` (nothing got through), `failed` (refused by the node), `stale` (still on an old OMR prefix: not sent), `old_prefix_only` (the Thread diagnostic finds only old-prefix addresses: a remedy on the border router is possible, with the user's agreement), `frozen` (heard on the radio, no answer through the mesh: only then is cutting its power suggested, as the last resort) |
| `auto_diag` | automatic recovery by the Thread diagnostic (option `thread_diag_recovery`): an unavailable mains node whose address is not known or on an old prefix, heard by a neighbor in the last 15 min (every 30 min at most) or, when nobody hears it, asked by its mesh-local EID (every 2 h at most); then the announcement in its place on its current address. Never the restart of its radio; 5 nodes per hour, not during a pause or a storm. Cutting the power of a node is only ever suggested after the diagnostic proved its network stack stuck (`frozen`: heard by a neighbor in the last 15 min, no answer through the mesh) |
| `proxy_released`, `proxy_expired` | an announcement made in a node's place is withdrawn: the node announces itself again on the prefix of the network / still not after 24 h |
| `node_reset` | a node was reset from a distance (Reset button of the node panel), with the fabrics it left and `result` (`reset`, or `unsure` when it did not confirm leaving Home Assistant) |
| `node_removed` | a node was removed from Home Assistant (Remove button) |
| `statistics`, `auto_recovery` | statistics rebuilt, recovery switched on / off (with who switched it) |

You can trigger automations on them, for example a notification when a node
needs attention:

```yaml
triggers:
  - trigger: mqtt
    topic: mesh_guardian/event
    value_template: "{{ value_json.type }}"
    payload: ping_gave_up
actions:
  - action: notify.notify
    data:
      message: "{{ trigger.payload_json.msg }}"
```

## Radio advice

In Thread, a device picks its parent when it joins the network. Some firmwares
look for a better parent when the signal drops; many stay on a weak parent as
long as the link holds, and nobody can force a parent remotely.

The advice is computed every time the table is shown, from what is known right
now. Four rules: one proof per advice (shown in its detail), the cheapest action
first (the button before moving a node, moving before buying a router), the
cause before the symptom, and the room and the floor of Home Assistant as hints
(the radio always decides).

**End device with a weak link** (link quality 1 or 0):

1. a better parent is known — a router it hears better, or a parent it had a
   good link with in the last 7 days: *Find a new link: X, LQI 3, 36 min ago*;
2. other routers are in its room, or on its floor: *Find a new link (4 routers
   in the room)*; none known: *Find a new link*;
3. a search made since the link is weak found nothing better, and routers are in
   the room: *Move the node: none of the 4 routers of the room hears it well*;
4. same, without any router in the room: *Add a router in <room>*.

A search made before the link became weak proves nothing and does not count. No
link advice is shown while a search is under way.

**Router with a weak link** (a router has no parent to change): *Add a router
between <room> and <room of the other end>*.

**Unstable parent** (ℹ️, a risk rather than a problem now): the node loses its
parent each time it restarts or detaches: *Find a new link*. A parent is
unstable when it crashed at least twice in 24h or detached at least 3 times
(detaches shared by many nodes in one survey interval are a network episode and
are not counted). The advice is hidden for 24h after a search.

**Restarts** — a power cut is never instability. A restart counts as a crash
when the node reports one (watchdog, brown-out, software reset); *power on*, a
software update, or several mains nodes restarting within 5 minutes are a power
cut and are ignored. Without any reason reported, an isolated restart is not
held against a parent; from 3 in 24h the node itself gets *Restarts: check its
power*. Two crashes or more: *Restarts: update its firmware*.

**Other advice:** a Wi-Fi node at -85 dBm or below; *Change the batteries*.
An advice always names an action: an observation alone (parent changes,
detaches without a weak link) stays in the technical details of the node.

**Unavailable node** — the cause first: *Comes back with <parent>* when its
parent is unavailable too; *Power cut in <room>?* when several mains nodes of
the room dropped together; *Change the batteries* when they were low; *Remove
the battery / unplug it for 10s* once the recovery pings are exhausted;
otherwise *Check its batteries / its power*.

**Network notes**, above the cards: a border router offline or detaching 3
times or more in 24h (with the number of nodes going through it). As
information (*Good to know*): border routers that
detached once or twice in 24h — the border router cards only show the state
now — and a node announced on the fabric but unknown to the Matter Server.
Every card (notes, advice, unavailable nodes) has a *Seen* button that hides
it in this browser; it comes back when it changes (one more detach, another
advice, the node unavailable again). The table and the summary still show
everything.

Every parent change is then reported with the signal before / after (✅ better,
≈ similar, ⚠️ worse, ? when a signal is unknown) and its probable cause. Over time, the app also learns
which battery models change parent on their own.

## Names Home Assistant → Matter

Every 5 minutes the app compares the name of every device **you renamed in
Home Assistant** with the name stored in its Matter node (NodeLabel attribute,
Basic Information cluster), without writing anything:
`sensor.mesh_guardian_nodes_to_rename` gives the nodes that differ. Press
**Rename nodes** to write the Home Assistant names into them. Tools that
read Matter directly (such as the Matter Server dashboard) then show the same
names as Home Assistant. Names are cut to 32 bytes (Matter limit). Other
ecosystems (Google Home, Apple Home…) keep their own names.

## Find better parents

A Thread end device (most battery sensors and remotes) picks its parent when
it attaches, and many firmwares keep it as long as the link holds, even when a
much better router is now in range. The usual fix is to remove the battery for
10 seconds.

**Find better parents** does it remotely. When pressed, Mesh Guardian:

1. reads the parent link of every available end device (one small read each);
2. keeps those whose link is weak: link quality (LQI) 1 or 0 — the same rule as
   the table and the advice;
3. asks each of them to connect again to the Thread network it is already on
   (Matter commands `ArmFailSafe`, `ConnectNetwork`, `CommissioningComplete`).
   The node restarts its Thread interface and attaches again, choosing a
   parent among the routers it hears. It does not reboot and its configuration
   is unchanged;
4. reads the link again 25 seconds later and reports the result.

What to know:

- Thread chooses the parent, not Mesh Guardian. The new link is usually
  better, sometimes the same parent is kept (no better router in range), and
  it can be weaker. There is no way back to the previous parent. This is why
  nodes with a good link are never touched.
- This button never touches a router: a router has no parent. A mains-powered
  device attached as a child (*End* in the table) has one and can be moved.
  (*Find a new link* in the node table can restart the Thread interface of a
  router, as a trial: see *Actions on one node*.)
- When the result is not known right away (a sleepy node answers at its next
  wake-up), the node and its parent are read again every 30 s for 5 minutes;
  the page shows the result as soon as it is known.
- After a search, the advice follows at once (see Radio advice).
- If a node answers with an error, the fail-safe is cancelled and the node
  keeps the network configuration it had. If it does not answer (it may be
  attaching again), the fail-safe is left armed: the node goes back to its
  configuration by itself after 2 minutes if it failed, and the result is
  followed for 5 minutes.
- The search is skipped during a Thread storm or right after a global outage.
- A sleeping node that does not answer the first read is skipped.
- Seen working on IKEA TIMMERFLOTTE and KLIPPBOK. A node that does not accept
  `ConnectNetwork` is reported as `unsupported` and left alone.

## Node table

Open **Mesh Guardian** in the Home Assistant sidebar (tick **Show in sidebar**
on the *Info* tab of the app if it is not there). The page follows the light
or dark theme of Home Assistant and adapts to phones.

**At the top** — a one-line verdict (*All good*, *1 node unavailable*, *2
actions advised*…), the counters (available nodes per network, border routers,
partitions, leader, automatic recovery) and the network quality score with its
five parts; a small mark on each bar gives its value over 24 hours.

**To handle** — one card per problem, most serious first: unavailable nodes,
silent nodes (see below), advice. A click opens the node.

**Border routers** — online, role, primary, detaches over 24 hours, last contact.
A card opens a panel with everything known about the border router (Thread
network, prefix, detaches of the last 7 days, nodes going through it, model,
addresses). A border router that you took away or whose Thread you turned off
on purpose, online or not, can be removed there with **Remove**: it leaves the
list, the alerts, the quality score and the entities. It comes back by itself
as a new border router when its announcement goes away and returns, or when its
Thread role changes (its Thread turned on again).

**Nodes** — problems first by default. Filters: all, to handle, Thread, Wi-Fi,
Ethernet, on battery; a search box (name, area, model, id). Default columns:

- *Node* — name, area, model, network;
- *Status · Role* — available / silent / unavailable, and the Thread role
  (Leader router, Router, End, Sleepy end);
- *Attachment · signal* — the node this one sends through: for an end device
  its parent, for a router the first hop of its route to the border router (a
  router has no parent). One signal: the weakest direction of that link (a link
  only works as well as its worst direction), as RSSI in dBm and Thread link
  quality (LQI). The link quality decides the color and the word: 3 good and
  2 fair in green, 1 weak and 0 very weak in orange (without link quality: weak
  at -90 dBm or below). A link quality of 0 on the link with the parent is a
  measure, not a missing value: the signal is no higher than the noise. The
  route table of a (sleepy) end device is not kept up to date by the node: its
  link quality is only used when the neighbor table has no entry for the parent. Only one direction is known when the other end is a border router.
  For a Wi-Fi node its access point and channel;
- *Border router* — the border router the node most likely reaches Home
  Assistant through, and the number of hops (full path on hover and in the node
  panel);
- *Response* — last read and average (no answer in red);
- *Power* — mains, or the battery with its charge (green > 50 %, orange
  20–50 %, red < 20 %);
- *Last contact*, *Advice*;
- *Actions* — ping, find a new link (recovery attempt when the node is
  unavailable), interview again, remove.

More columns with the button next to the filters (neighbors, weak links,
detaches, parent changes, outages, downtime, reboots, uptime, RLOC16, id…).
Drag a header (or a line of the column list) to move a column. Click a header to
sort, again to reverse; the column menu brings the default order back. Sort,
filter, columns and their order are remembered by your browser. The page
refreshes itself every minute; **Refresh** does it at once.

Opening the page and **Refresh** also make the app read every available node
again, battery ones included: response time, uptime and contact, plus role and
Thread tables (a battery node only gives its role and parent link, and only if it
answers). Three nodes at a time, mains nodes first, at most once every
5 minutes, never during a storm. The green dot blinks while the nodes are read
(also after a start of the app, see Radio survey); the lines update as the
answers come in.

**Node panel** — click a node. On top, always shown: its name, area and model,
its state, network, role and power, the advice, six facts (signal, response,
parent or first hop, border router and hops, last contact, outages over 24 hours
and 7 days) and the everyday actions (ping, find a new link or recovery attempt,
interview). Then sections that fold with their arrow; what you open or fold is
remembered by your browser:

- *Signal and response* — the curves of the last 7 days (centered on their
  average, the weak threshold drawn when it is in range);
- *Pairing* — the pairing code with its QR code (see *Pairing codes*), and the
  two actions that cannot be undone: **Reset** and **Remove**;
- *History* — outages and parent changes (the five latest, older ones unfold);
- *Technical details* (folded at first) — identity (id, firmware, serial number,
  pairing date, unique id, hardware address), Thread (full path, RLOC16,
  neighbors, counters), running (uptime, reboots, last boot reason, downtime),
  contact (sign of life, source, longest silence) and what the Matter Server log
  says of the node over 24 hours.

After an action the panel shows the new values without moving, and waits while
you are typing in it or answering a question.

**Report** — an anonymized Markdown report (models, roles, signals, counters; no
names, areas, addresses or prefixes) to copy or download and paste in an issue.

### Actions on one node

- **Ping** — through the Matter Server; the answer counts as a contact.
- **Find a new link** — an end device attaches again and picks the best parent
  it hears now (see *Find better parents*), even when its link is not poor (you
  are asked to confirm: the new parent can be weaker). Trial, provisional: on a
  router or on the leader the button restarts its Thread interface, after a
  warning (stronger for the leader: the network elects a new one); its end devices drop and attach elsewhere, and no better link is
  expected since a router picks its routes by itself. The result comes as
  soon as the node is a router again (its role is read every 20 seconds), and
  after 3 minutes at the latest.
- **Recovery attempt** — replaces "Find a new link" on a Thread node that is
  unavailable (router or end device). The app pings the node, then sends it
  the same command: if it gets through, the node restarts its
  Thread connection and picks its neighbors again. "Unavailable" means the
  Matter Server could not set up its subscription again, a long exchange; one
  command is much shorter and can get through a link that loses most messages.
  The result comes within a few minutes: back, still unavailable, or out of
  reach (nothing got through: cut its power for 10 s). Needs the Matter Server
  based on matter.js (app 9 and later): the older one refuses any command
  to an unavailable node, and the result is then "out of reach".
- **Interview** — the Matter Server reads again everything the node describes
  (endpoints, clusters, attributes); useful after a firmware update.
- **Remove** — the node leaves Home Assistant (the Matter Server removes it). On
  most devices, leaving their last ecosystem is a factory reset: the
  confirmation warns when the pairing code of the node is not kept. Event
  `node_removed`.

### Pairing codes

A node cannot be asked for the code it was paired with, and Home Assistant
does not keep it: after a factory reset the label of the device is the only
way back, and the device may be in a wall box or on a ceiling. The node panel
has a **Pairing code** block to keep it:

- take a photo of the QR code from your phone (the button opens its camera),
  or drop a photo on the panel (or choose one, or paste it): the QR code is
  read in your browser, the photo is not sent anywhere;
- or type the code (11 or 21 digits, or the `MT:…` text of the QR code). A
  mistyped digit is refused, and so is the QR code of another product.

A node paired in the last 24 hours whose code is not kept is shown first under
**To handle**, as "New node": the moment to photograph its label is while you
are still in front of it. "Seen" hides the card. The code cannot be picked up
during the pairing itself: the phone keeps it and only hands a temporary code
to Home Assistant.

The panel then shows the QR code and the code in digits, with a Copy button.
From a typed code only the digits are shown: they do not hold what a QR code
needs.

The codes are kept by the app (`/data/pairing_codes.json`), not in the
Matter Server: they survive the reset or the removal of the node, an update
and a restart of the app. They are lost if the app is uninstalled, and
they are part of its backup. They are never written to the log, the events or
the report.

A device that is paired again gets a new node id. Its code follows it when
the device reports a serial number; otherwise by its hardware address or
unique id, which some devices change at a reset. When nothing matches, the
code waits under **Pairing codes** (a button at the top of the page, shown
only while a code waits), where you read it to pair the device again, and the panel of the new node offers to attach it.

Anyone who can open the Mesh Guardian page can read these codes: a pairing
code gives full control of a device once it is reset.

### Pair a device from the page

The **Pair** button (top of the page) starts the pairing of a new or reset
device without leaving Mesh Guardian. Such a device only speaks Bluetooth, so
the phone does the pairing, next to the device:

- in the Home Assistant app on a phone, the QR code reader of the app opens
  first: aim at the label, and the code is kept for the node this pairing will
  bring (it attaches to it by itself when the node shows up; "Pair without
  scanning" skips this). The code in digits is copied, to paste in the pairing
  screen. The pairing of the phone cannot hand the code over itself: it only
  tells whether it succeeded. The same reader is offered in the panel of a
  node, next to the photo;
- then the button starts the same pairing as
  the "Add Matter device" screen of Home Assistant. The page asks the app
  through the Home Assistant page it is shown in, and hands over the Thread
  network Home Assistant prefers, exactly as that screen does;
- once the device is in Home Assistant, the page asks its name and its area
  and saves them in Home Assistant (that step belongs to the "Add Matter
  device" screen, which is not open here). "Later" leaves them as they are;
- in a browser, the "Add Matter device" screen of Home Assistant opens.

Under **Pairing codes**, "Pair with this code" does the same after copying
the code: paste it in the pairing screen instead of scanning the label. The
new node then shows up in the table by itself.

### Reset from a distance

The **Reset** button of the node panel makes a node go back to its factory
state without touching it. Matter has no reset command, but a node that
leaves its last fabric (its last ecosystem) erases everything it learnt since
it was paired, and most devices then restart, ready to be paired again. The
app removes the node from every fabric it is in — the other ecosystems
first (Google Home, Apple Home…), Home Assistant last.

- Only for an available node whose pairing code is kept (see above): the
  panel shows the fabrics it will leave and its code, and asks you to tick a
  box. It cannot be undone.
- The node then has to be paired again within Bluetooth range, with its code,
  which waits under **Pairing codes**. Nothing has to be pressed on the device.
- In the other ecosystems the device stays listed as offline: delete it there.
- What a device does once out of its last fabric is its maker's choice. If it
  does not offer itself for pairing, it has only left the ecosystems and needs
  its button after all. Tried on an IKEA GRILLPLATS plug: it goes back to
  pairing by itself.
- A Thread router that is reset leaves the nodes that went through it without
  their route for a few minutes. Wait 2 to 3 minutes before pairing it again:
  pairing while the network settles may fail.
- If the pairing stops halfway (the device no longer blinks but is not in Home
  Assistant), it stayed paired with the phone only. Remove it there, which
  resets it again, then pair it once more: on Android, Settings → Google →
  Devices & sharing → Matter devices; on iPhone, Settings → General → Matter
  Accessories. **Remove only the entry of that device**: this list holds every
  device ever paired with the phone, and each entry removed makes its device
  leave every ecosystem, Home Assistant included. If you cannot tell which
  entry it is, use the button of the device instead.
- For some days the border routers still announce the old identity of the
  node. Mesh Guardian does not report it as unknown; nothing can withdraw it
  but time. Its code follows the node: when it comes back, the only code of
  that product waiting since a reset is attached to it by itself (the panel
  says so; replace it if it is another device).

### Silent nodes

A node gives a sign of life at a steady pace (about every minute for most mains
nodes, the liveness interval of its Matter subscription). With
`passive_contact` the app sees every packet and learns that pace (*Sign of
life* in the technical details). A node silent for much longer is shown
**silent** — probably without power — minutes before the Matter Server declares
it unavailable. No radio traffic is added. The availability, the outages and the
quality score still follow the Matter Server.

### Where the values come from

The app keeps a live link with the Matter Server and receives every report as
it arrives. Some nodes stop reporting their Thread diagnostics (role, neighbors)
after a change of role, so the Matter Server keeps old values: mains nodes are
read again once an hour (role, neighbor and route tables, addresses, counters).
Battery nodes are read once an hour too (role, neighbor table, addresses),
right after the read of their response time, while they are awake: no wake-up
is added. The response time comes from a read of the uptime every 15
minutes (mains) or every hour (battery); after a failed read the node is read
again 2 minutes after it is back. A contact is any report, event, read, ping
answer or (with `passive_contact`) packet of the node.

**Old values.** The app remembers when a node gave each value (a report or
a read). A value given more than 2 hours ago, or taken from the Matter Server
cache without anyone knowing when the node gave it, is old: it is shown in
grey, without colour or signal bars, with its age in the tooltip, and no
advice is drawn from it. This applies to the link (parent, signal, border
router and path — a link is as old as the oldest table it was read from), the
24h counters, the uptime, the response time and the Wi-Fi signal. Right after
the first start, values turn from grey to current as the nodes are read
(minutes for mains nodes, up to an hour for battery nodes; opening the page
reads them at once).

The border router of a node and its path come from the route tables of the
routers: the border router with the lowest path cost (1 per good hop, up to 4
for a weak link). It is the most likely way out of the mesh, not the path of
every packet; route tables can be a few minutes old.

## Wi-Fi and Ethernet nodes

Matter nodes on Wi-Fi or Ethernet are listed too (column *Network*). They have no
mesh: the *Parent* column shows their link (Wi-Fi with its channel, or Ethernet)
and *RSSI* the Wi-Fi signal. Availability, outages, reboots, uptime, response
time and last contact work as for Thread nodes; radio advice and the radio part
of the quality score only concern Thread.

## Network quality

One score in %, shown at the top right of the node table (green ≥ 90, orange
80–89.9, red below 80, details in the tooltip) and in
`sensor.mesh_guardian_network_quality`. One sample per minute; the score
covers the last hour, the 24-hour score is in the attributes.

| Part | Weight | 100 % when… | 0 % when… |
|---|---|---|---|
| Availability | 50 % | every node available in Home Assistant | 20 % of the nodes unavailable the whole time |
| Radio | 25 % | no weak link among the links in use (parent of a child, first hop of a router) | half of them weak (link quality 1 or 0) |
| Outages | 10 % | no node became unavailable | 1 outage per 10 nodes per hour |
| Backbone | 10 % | every border router online and a leader known | no border router online |
| Partition | 5 % | a single partition | partitioned the whole time |

A network partitioned for 5 minutes or more is capped at 70 %. Not measured:
global outages (Home Assistant or Matter Server restart), Home Assistant
unreachable. A score of
100 % is rare: it leaves room to see an improvement.

## Thread storms

A storm is a period where the mesh keeps falling apart: the network splits
into partitions again and again, several OMR prefixes coexist and many nodes
drop. A storm starts when, over 15 minutes, there are more than 3 partition
splits (short border router detaches included), more than 3 OMR prefixes at the same time, or more than 15 nodes
becoming unavailable (mass drops caused by a restart of Home Assistant are not
counted). It ends after 15 quiet minutes.

During a storm, pings are three times further apart and limited to two per
cycle, and the hourly sweep is skipped: pinging only adds traffic while the
mesh re-forms. `binary_sensor.mesh_guardian_thread_storm` shows the storm, with
its start, duration, the nodes that dropped, the border routers that went
detached and the prefixes seen.

## Supervisor access

The app asks for the Supervisor role `manager` (security rating 4 instead
of 5), because the Supervisor log cannot be read with a lower role.

What it reads:

- the Supervisor log, through one stream kept open (no polling). Only the
  lines about a stop, an exit, an update or a start of the Matter Server or of
  Home Assistant are used; nothing else is kept;
- the name, version and log level of the Matter Server app;
- the log of the Matter Server, through one stream kept open. A line is read,
  counted and dropped: no text of the log is kept, only numbers per node and
  per hour, and the last address the Matter Server used for the node.

What it never does: start, stop, restart, update or configure another app,
or read another app's options.

If the log cannot be read, restarts are still detected by the app's live
link to the Matter Server, without the cause.

**Matter Server · 24h** (node panel, and the optional *Losses 24h* column).
Home Assistant only shows a node as unavailable after a while. Before that,
the Matter Server already wrote what went wrong; the app counts it per node
over 24 hours:

| Count | Meaning |
|-------|---------|
| Subscriptions lost | the node sent no report in the time it had promised |
| Sessions closed | the node stopped answering, the Matter Server closed its session |
| Offline for the Matter Server | how many times and for how long, even a few seconds |
| Address unreachable | the address of the node could not be reached or was not known |
| Pings without answer | a ping of the node got no answer |

A node with many of these and no outage in Home Assistant has a fragile link.
The counts need the Matter Server log level `info` (its default). They only
cover the time the log was read: the panel says since when, and for how long
it was not read. `/api/supervisor` (through
ingress) shows what was read: state of the stream, number of lines, restarts
found.

## FAQ and troubleshooting

**No entities appear.**
Check that the MQTT integration is set up with the Mosquitto broker, and look at
the app log for `Connected to MQTT`.

**"Matter Server unreachable".**
The Matter Server app must be running. If you run it elsewhere, set
`matter_server_url` (for example `ws://192.0.2.10:5580/ws`).

**A border router has a technical name such as "Speaker #92ED".**
Friendly names come from Google Cast or Apple AirPlay announcements at the same
IP address. Other vendors keep their mDNS name. You can still rename the entity
in Home Assistant.

**Many "unavailable" events after a Home Assistant restart.**
That is a global outage: pings are paused for 5 minutes and these outages are
not counted in the per-node statistics.

**Does pinging drain batteries?**
Recovery pings only target unavailable nodes; the periodic sweep never pings
battery-powered nodes.

**Can I turn off a feature?**
Yes: the **Automatic recovery** switch, `ping_all_interval: 0` for the sweep, `advice: false` for the advice. Node names are only
written when you press **Rename nodes**, and nodes are only asked to attach
again when you press **Find better parents**, **Find a new link** or
**Recovery attempt**.

**A border router shows offline although it works.**
Some border routers do not always answer mDNS queries. A border router is only
reported offline when it stops answering mDNS **and** no Matter node has heard
it over the radio for 3 minutes; to know it, the app reads the neighbor table
of one or two routers next to it.

**Why is the parent of a node "?".**
The node does not publish its RLOC16 (some smart plug
firmwares) and no Matter node lists it as its child: its parent is then usually a
border router, whose tables are not readable.

**"Thread nodes are announced but unreachable".**
Most nodes are unavailable, they are still announced in mDNS, but none answers
a ping: Home Assistant has no route to the Thread network. The usual cause is a
border router on another network or VLAN than Home Assistant, or IPv6 routing
(router advertisements) blocked between them. The event lists the border
routers whose IPv4 address is outside the networks of Home Assistant.

**How are border routers named?**
Each border router is identified by its border agent id, which never changes.
Its friendly name is taken from the Google Cast / AirPlay device at the same
address, kept in `/data`, and only changed after the same new name was seen
five times in a row with an exact address match — so speakers that re-announce
at the same time no longer swap names.

## Known limitations

- Border router role and partition come from their announcements; if a vendor
  does not publish them, the role shows `?` and only presence is followed.
- Matter over Wi-Fi nodes are recovered and counted, but have no Thread radio
  data.
- During the first 2½ minutes after start, the app stays quiet while it
  discovers the network.

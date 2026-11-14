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
- [Node table](#node-table)
- [Wi-Fi and Ethernet nodes](#wi-fi-and-ethernet-nodes)
- [Network quality](#network-quality)
- [Thread storms](#thread-storms)
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
                                                     └──▶ add-on log, /share/mesh_guardian/events.jsonl
```

1. **Listening.** The add-on follows the mDNS announcements of the Thread border
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
   parents, roles and counters.
4. **Statistics.** Outages are counted per node over 7 days. On first start,
   the last 7 days are rebuilt from the Home Assistant history.

By default, only the Thread network used by your Matter nodes is followed;
border routers of other networks (e.g. a neighbor's) are ignored.

## Installation

> **Requirements:** an MQTT broker (the **Mosquitto broker** add-on) and the
> **MQTT** integration. Without them no entity is created.

1. Add the repository `https://github.com/Pintjes/ha-addons` to the add-on store
   (**Settings → Add-ons → Add-on store → ⋮ → Repositories**).
2. Install **Mesh Guardian** and start it.
3. Pick your **language** in the *Configuration* tab and restart the add-on.
4. Enable **Start on boot** and **Watchdog**.

After about 2½ minutes the log shows `Monitoring ready`, and a **Thread
Guardian** device with its entities appears in the MQTT integration.

**Requirements:** Home Assistant OS or Supervised, the Matter integration with
the Matter Server add-on, the Mosquitto broker add-on and the MQTT integration.

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
| `passive_contact` | `false` | Count every IPv6 packet sent by a node and seen on the host as a contact (*Last contact*), including the reports the Matter Server does not forward because their value did not change, and the answers to pings sent by Home Assistant. Only the source address of the packets is read. Uses the `NET_RAW` privilege. |
| `matter_fabric` | *(empty)* | Advanced: compressed fabric id of Home Assistant. Detected automatically when empty. |
| `matter_server_url` | *(empty)* | Advanced: WebSocket address of the Matter Server (e.g. `ws://192.168.1.10:5580/ws`) when it does not run as the Matter Server add-on (Docker container, other machine). Defaults to the Matter Server add-on. |

Automatic recovery is switched on and off with
`switch.mesh_guardian_auto_recovery` (off at first start: turn it on to let the add-on ping lost nodes).

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
| `sensor.mesh_guardian_thread_leader` | name of the Thread leader (border router or any router of the mesh) | when it changes | current |
| `sensor.mesh_guardian_thread_partitions` | number of partitions (1 = normal) | same | current |
| `binary_sensor.mesh_guardian_thread_network_partitioned` | problem when there is more than one partition or leader | same | current |
| `sensor.mesh_guardian_omr_prefix` | OMR prefix(es); several at once is an anomaly | same | current |
| `binary_sensor.mesh_guardian_thread_storm` | problem during a Thread storm; start, duration, nodes, border routers detached, prefixes | every 5s over a sliding 15 minutes | ends after 15 quiet minutes |
| `sensor.mesh_guardian_last_event` | text of the last event (its history is the event log) | every event | event counter reset when the add-on restarts |

**Recovery** — Home Assistant read every 15 seconds.

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_matter_nodes_unavailable` | nodes unavailable in Home Assistant; `routing` problem if detected | every 15s | current |
| `sensor.mesh_guardian_matter_nodes_available` | nodes available in Home Assistant | every 15s | current |
| `sensor.mesh_guardian_recovered_by_ping` | nodes back thanks to a ping (total); `back_on_their_own`, `gave_up`, `pings_sent`, and the same counters `since_start` and over `last_24h` | every return | total: on reinstall or with the reset button; `since_start`: when the add-on restarts; `last_24h`: sliding |
| `switch.mesh_guardian_auto_recovery` | automatic recovery on / off (off at first start) | when switched | kept across restarts |
| `button.mesh_guardian_ping_all_nodes` | pings every node now, battery and unavailable nodes included; result in the `ping_all_done` event | when pressed | — |
| `sensor.mesh_guardian_network_quality` | network quality in % over the last hour (see [Network quality](#network-quality)); `parts`, `score_24h`, `parts_24h`, `capped`, `median_response_ms` | every minute | with the reset button |
| `button.mesh_guardian_reset_statistics` | resets every statistic: counters, outages, 24h/7d columns, last contacts, border router detaches, past storms (names, settings and the switch are kept); no 7-day history taken over afterwards | when pressed | — |

**Radio** — survey every 30 minutes (values cached by the Matter Server, no radio traffic).

| Entity | State and role | Updated | Reset |
|---|---|---|---|
| `sensor.mesh_guardian_weak_radio_links` | weak links among the links in use (child → parent, router → its first hop to the border router): link quality 1 | every survey | current |
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

Every event is written to the add-on log, published on the MQTT topic
`mesh_guardian/event` (JSON) and, optionally, appended to
`/share/mesh_guardian/events.jsonl`.

| Event | Meaning |
|---|---|
| `startup`, `addon_stop` | monitoring ready (with the version and the state of the automatic recovery), add-on stopping (with the signal received) |
| `br_appeared`, `br_back`, `br_offline`, `br_change`, `br_renamed` | border router life (role, partition, prefix…); a role change is reported once it held 60s |
| `leader_change`, `partition_change`, `omr_change`, `node_prefix_change` | network-wide changes — the usual cause of lost nodes |
| `matter_offline`, `matter_back`, `matter_appeared` | Matter node missing from / back in mDNS (not reported for a battery node still available in Home Assistant) |
| `mdns_burst` | services withdrawn then re-announced within seconds (no real absence); only in the event file and on MQTT, counted in `mdns_bursts` |
| `speaker_appeared`, `speaker_back`, `speaker_offline` | smart speaker / hub online state (restart detection) |
| `node_unavailable`, `node_recovered_by_ping`, `node_back_on_its_own`, `ping`, `ping_gave_up`, `ping_error` | automatic recovery |
| `global_outage`, `global_return` | many nodes at once (Home Assistant / Matter Server restart) |
| `storm_start`, `storm_end` | Thread storm (see below) |
| `stats_reset` | statistics reset by the button |
| `routing_problem`, `routing_ok` | nodes announced in mDNS but unreachable from Home Assistant |
| `sweep` | periodic ping of mains-powered nodes (the nodes that did not answer are in `bad`) |
| `ping_all`, `ping_all_done` | ping of every node requested with the button |
| `radio_survey`, `radio_advice`, `parent_change` | radio quality and advice (also shown in the node table) |
| `names`, `name_synced` | names Home Assistant → Matter (Rename nodes button) |
| `reattach`, `reattach_node`, `reattach_result`, `reattach_done` | parent search (Find better parents button): start, node asked to attach again, its link before and after (`result`: `better`, `worse`, `similar`, `same`, `unknown`), summary |
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

After each radio survey, Mesh Guardian lists the nodes whose parent link is weak
(link quality 1) or unstable, and suggests the action:

- **battery device:** remove the battery for 10 seconds and put it back — it
  rejoins and picks the best parent available;
- **mains device:** unplug it for 10 seconds;
- **already tried:** add a mains-powered Thread router (e.g. a Matter smart
  plug) near that area;
- **unstable parent** (shown with ℹ️, a risk rather than a problem now): the node loses its
  parent each time the parent restarts or detaches; remove the battery of the node (or
  unplug it) for 10 seconds so it picks a steadier parent. A parent is unstable when it
  restarted at least twice over about 24h (reboot counter of the node; software updates
  excluded), or detached at least 3 times; detaches shared by many nodes in the same
  survey interval (one network episode) are not counted. A node that just moved to a
  better parent gets no such advice for 24h.

Every parent change is then reported with the signal before / after (✅ better,
≈ similar, ⚠️ worse, ? when a signal is unknown) and its probable cause. Over time, the add-on also learns
which battery models change parent on their own.

## Names Home Assistant → Matter

Every 5 minutes the add-on compares the name of every device **you renamed in
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
2. keeps those whose link is weak: link quality (LQI) 1 — the same rule as
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
- Routers (mains-powered devices) are never touched: a router has no parent.
- If a node does not confirm, the fail-safe is cancelled and the node keeps
  the network configuration it had.
- The search is skipped during a Thread storm or right after a global outage.
- A sleeping node that does not answer the first read is skipped.
- Seen working on IKEA TIMMERFLOTTE and KLIPPBOK. A node that does not accept
  `ConnectNetwork` is reported as `unsupported` and left alone.

## Node table

Open **Mesh Guardian** in the Home Assistant sidebar (tick **Show in sidebar**
on the *Info* tab of the add-on if it is not there). The page follows the light
or dark theme of Home Assistant and adapts to phones.

**At the top** — a one-line verdict (*All good*, *1 node unavailable*, *2
actions advised*…), the counters (available nodes per network, border routers,
partitions, leader, automatic recovery) and the network quality score with its
five parts; a small mark on each bar gives its value over 24 hours.

**To handle** — one card per problem, most serious first: unavailable nodes,
silent nodes (see below), advice. A click opens the node.

**Border routers** — online, role, primary, detaches over 24 hours, last contact.

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
  2 fair in green, 1 weak in orange (without link quality: weak at -90 dBm or
  below). Only one direction is known when the other end is a border router.
  For a Wi-Fi node its access point and channel;
- *Border router* — the border router the node most likely reaches Home
  Assistant through, and the number of hops (full path on hover and in the node
  panel);
- *Response* — last read and average (no answer in red);
- *Power* — mains, or the battery with its charge (green > 50 %, orange
  20–50 %, red < 20 %);
- *Last contact*, *Advice*;
- *Actions* — ping, find a better parent (end devices), interview again.

More columns with the button next to the filters (neighbors, weak links,
detaches, parent changes, outages, downtime, reboots, uptime, RLOC16, id…).
Drag a header (or a line of the column list) to move a column. Click a header to
sort, again to reverse; the column menu brings the default order back. Sort,
filter, columns and their order are remembered by your browser. The page
refreshes itself every minute; **Refresh** does it at once.

**Node panel** — click a node: status and advice, attachment explained, border
router and cost of the path, response, power, the three actions, the signal and
response curves of the last 7 days (centered on their average, the weak
threshold drawn when it is in range), outages, parent changes, and the
technical details (full path, RLOC16, neighbors, counters, sign of life…).

**Report** — an anonymized Markdown report (models, roles, signals, counters; no
names, areas, addresses or prefixes) to copy or download and paste in an issue.

### Actions on one node

- **Ping** — through the Matter Server; the answer counts as a contact.
- **Find a better parent** — end devices only: the node attaches again and
  picks the best parent it hears now (see *Find better parents*), even when its
  link is not poor (you are asked to confirm: the new parent can be weaker).
- **Interview** — the Matter Server reads again everything the node describes
  (endpoints, clusters, attributes); useful after a firmware update.

### Silent nodes

A node gives a sign of life at a steady pace (about every minute for most mains
nodes, the liveness interval of its Matter subscription). With
`passive_contact` the add-on sees every packet and learns that pace (*Sign of
life* in the technical details). A node silent for much longer is shown
**silent** — probably without power — minutes before the Matter Server declares
it unavailable. No radio traffic is added. The availability, the outages and the
quality score still follow the Matter Server.

### Where the values come from

The add-on keeps a live link with the Matter Server and receives every report as
it arrives. Some nodes stop reporting their Thread diagnostics (role, neighbors)
after a change of role, so the Matter Server keeps old values: mains nodes are
read again once an hour (role, neighbor table, addresses), battery nodes never
(their batteries). The response time comes from a read of the uptime every 15
minutes (mains) or every hour (battery); after a failed read the node is read
again 2 minutes after it is back. A contact is any report, event, read, ping
answer or (with `passive_contact`) packet of the node.

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
| Radio | 25 % | no weak link among the links in use (parent of a child, first hop of a router) | half of them weak (link quality 1) |
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
splits, more than 3 OMR prefixes at the same time, or more than 15 nodes
becoming unavailable (mass drops caused by a restart of Home Assistant are not
counted). It ends after 15 quiet minutes.

During a storm, pings are three times further apart and limited to two per
cycle, and the hourly sweep is skipped: pinging only adds traffic while the
mesh re-forms. `binary_sensor.mesh_guardian_thread_storm` shows the storm, with
its start, duration, the nodes that dropped, the border routers that went
detached and the prefixes seen.

## FAQ and troubleshooting

**No entities appear.**
Check that the MQTT integration is set up with the Mosquitto broker, and look at
the add-on log for `Connected to MQTT`.

**"Matter Server unreachable".**
The Matter Server add-on must be running. If you run it elsewhere, set
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
Yes: `auto_ping` (or the switch), `ping_all_interval: 0`. Node names are only
written when you press **Rename nodes**, and nodes are only asked to attach
again when you press **Find better parents**.

**A border router shows offline although it works.**
Some border routers do not always answer mDNS queries. A border router is only
reported offline when it stops answering mDNS **and** no Matter node has heard
it over the radio for 3 minutes; to know it, the add-on reads the neighbor table
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
- During the first 2½ minutes after start, the add-on stays quiet while it
  discovers the network.

# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.6.1] - 2026-11-14

### Fixed

- Node panel: a parent change made by a parent search shows in "Parent changes" at once.

## [2.6.0] - 2026-11-14

### Added

- Parent search: when the result is not known right away (sleepy node), the add-on reads the node and its parent again every 30 s for 5 minutes, then shows the result (new or same parent, link quality, RSSI), or that the node did not answer.

### Changed

- After a parent search, the advice follows at once: an unstable-parent advice is hidden for 24 h; a weak link that kept the same parent becomes "Add a router near …". The last searches are kept across restarts.

## [2.5.6] - 2026-11-14

### Fixed

- Sorting on "Attachment · signal" follows the link quality, then the RSSI.

## [2.5.5] - 2026-11-14

### Fixed

- Mains-powered children whose route table gives no link quality with their parent are recognised too.

## [2.5.4] - 2026-11-14

### Fixed

- Parent of some battery nodes shown as "router 0"; mains-powered children whose route table keeps an old next hop for their parent are recognised.

## [2.5.3] - 2026-11-14

### Fixed

- A mains-powered node attached as a child (it keeps links with several routers but sends everything through its parent) was shown as a router: it is now an end device with its parent, and can look for a new parent.
- "Find better parents" also covers these nodes.

## [2.5.2] - 2026-11-14

### Added

- Diagnostics: the Thread tables of a node as received (`api/raw?id=`).

## [2.5.1] - 2026-11-14

### Fixed

- The route table of mains-powered nodes is read again every hour, with the neighbor table: the first hop of a router no longer comes from an old route.

## [2.5.0] - 2026-11-14

### Changed

- "Attachment · signal": one signal per node, the weakest direction of the link it sends through (RSSI and link quality).
- A router shows the first hop of its route to the border router; nothing when the route is not known.
- One rule for a weak link everywhere (color, advice, "Find better parents", score): link quality 1, or -90 dBm when it is not known.
- Signal colors: good and fair in green, weak in orange; red is kept for unavailable nodes.
- Parent search result: the parent (new or same) with its link quality and RSSI.

## [2.4.6] - 2026-11-14

### Fixed

- Summary: the number of advised actions matches the cards in "To handle" (identical advice counted once).
- Page header shows the add-on logo.

## [2.4.5] - 2026-11-14

### Fixed

- "new" badge: the date a node was added was not passed to the table.

## [2.4.4] - 2026-11-14

### Added

- "new" badge next to a node added to Matter less than 24 h ago.

## [2.4.3] - 2026-11-14

### Changed

- "To handle": the same advice for several nodes is shown as one card listing the nodes.

## [2.4.2] - 2026-11-14

### Changed

- Screenshot of the page (demo data) in the README and the add-on store.
- Same light bulb icon for every advice in the node list.

## [2.4.1] - 2026-11-14

### Changed

- Router attachment: the neighbor it really sends through (first hop of its
  route to the border router) and that link's signal, instead of its strongest
  neighbor.

## [2.4.0] - 2026-11-14

### Changed

- One kind of advice, *Action advised*, in blue (no more orange nor "Good to
  know"); the verdict of actions is blue too.

### Fixed

- A value read directly from a node (after a parent search, or by the hourly
  read) is no longer overwritten by the older copy the Matter Server keeps: it
  stays until the node reports that attribute, or 2 hours.

## [2.3.4] - 2026-11-14

### Fixed

- Node panel curves end on the current values of the table ("now" was the last
  15-minute point).

## [2.3.3] - 2026-11-14

### Added

- A node that goes silent gets one ping in the background: if it answers, it is
  no longer silent.

## [2.3.2] - 2026-11-14

### Fixed

- Parent search result: only the signal of the table is given (no other source);
  "same parent" when the parent did not change even if the node got a new
  address; the node addresses are read again after the search.
- Attachment signal: when the parent does not give it, the one read on the node
  side is kept instead of "—".

## [2.3.1] - 2026-11-14

### Changed

- Silent nodes: only their status (with its tooltip) shows it, no card in *To
  handle* nor line in the verdict (often short-lived).

## [2.3.0] - 2026-11-14

Texts audit: short and to the point.

### Fixed

- Ping without answer showed "error"; failed actions showed a raw Python error.
- Parent search: the log, the Home Assistant entity and the result now give the
  parent and the signal of the table (received by the parent); a sleeping node
  gives "no answer" instead of "a router has no parent"; same weak threshold as
  the advice (-85 dBm); a router-eligible end device can be asked too.
- "1 others" in the verdict: the unavailable nodes are listed (3 at most).
- The node panel shows the new values after an action.

### Changed

- Shorter texts everywhere (verdict, silent nodes, storm, advice, parent search,
  events, confirmations); "available again" instead of "back"; units written
  "-84 dBm", "24 h", "5 min" in French; no internal event type in the log; the
  advice count is logged only when it changes.
- The result of an action stays until clicked.
- A *Clear* button appears when a filter or a search is active.
- "Good to know" title when there is nothing to handle.

## [2.2.0] - 2026-11-14

### Added

- *Remove* action on a node (after confirmation): removes it from the Matter
  network through the Matter Server. Actions laid out in two rows.

## [2.1.3] - 2026-11-14

### Changed

- Parent search result in a few words: new or same parent and its signal.

## [2.1.2] - 2026-11-14

### Changed

- Parent search from the table: the result gives the signal of the table (received
  by the parent) before and after; the neighbor table of the new parent is read
  at once.

## [2.1.1] - 2026-11-14

### Changed

- Counts written 6× instead of ×6.

## [2.1.0] - 2026-11-14

### Changed

- Advice: *Finding a new parent could improve the situation* (button on the line)
  replaces *Remove the battery 10s* / *Unplug 10s* / *change the parent*; when a
  parent search found nothing better in the last 7 days, *Add a router near…*.
- Fewer columns: the id is in the *Node* column, the link quality (LQI) next to
  the signal, outages 24h and 7d in one column.
- Parent search result: says that the signal is the one received by the node.

## [2.0.2] - 2026-11-14

### Changed

- Quality score parts: the gain over the 24h value is drawn in green, the loss in
  red.

## [2.0.1] - 2026-11-14

### Fixed

- Signal of a link: some firmwares report an impossible average RSSI (e.g. -21dBm
  for a link heard at -77dBm); the last RSSI is used instead. Affected the parent
  search result and the attachment column.

### Changed

- Parent search result names the old and the new parent.
- Shorter tooltips on the action buttons.

## [2.0.0] - 2026-11-14

### Changed

- The new view replaces the old one (no more beta badge or switch).

### Added

- *Actions* column and buttons in the node panel: ping, find a better parent
  (end devices, one node, after confirmation) and interview again.
- Advice for a router whose best link is weak: add a router nearby.

### Fixed

- Path to a border router ending on another router id of the same border router
  was shown as incomplete (*at least N hops*).
- Thread leader shown as unknown when the router asked was the leader itself, or
  when the first routers asked did not answer.

## [1.9.0] - 2026-11-14

### Added

- **Find better parents** button: reads the parent link of every Thread end
  device and asks those whose link is poor (LQI 2 or less, or -80dBm or less)
  to attach again, so they pick a parent among the routers they hear now. The
  node does not reboot and keeps its configuration. Routers and nodes with a
  good link are left alone. Result per node in the `reattach_result` event and
  in `sensor.mesh_guardian_parent_search`. Nothing is sent until the button is
  pressed.
- A parent change that follows this button is no longer counted as a
  spontaneous change of the model.

## [1.8.0] - 2026-11-14

### Added

- Rhythm of each node: its usual silence between two signs of life, measured
  from every contact (with passive contact, close to the liveness interval of
  the Matter subscription). In the API (`rhythm_s`, `silent_limit_s`,
  `silent_s`) and in the technical details of the beta view.
- Beta view: a node silent for much longer than usual is shown *silent* (probably
  without power), minutes before the Matter Server declares it unavailable. No
  extra radio traffic; needs passive contact. The availability, the outages and
  the quality score still follow the Matter Server.

## [1.7.1] - 2026-11-14

### Fixed

- Weak-link advice hidden as soon as the link shown is no longer weak.
- A node announced as a child whose fresh neighbor table has no link with that
  parent but links with several routers is shown as a router (its role and
  address were out of date).

## [1.7.1] - 2026-11-14

### Fixed

- Weak-link advice disappears as soon as the link is above the weak threshold
  again, without waiting for the next radio survey.
- Mains nodes: the hourly read also refreshes their addresses, so the RLOC16
  (and the parent derived from it) follows a change of role.

## [1.7.0] - 2026-11-14

### Added

- Wi-Fi access points can be named in the node panel (beta view); the name is
  used for every node on that access point when Home Assistant does not know it.

### Fixed

- Missing link signal for mains end devices: their role and neighbor table are
  read again at most hourly (some nodes never report them again, so the Matter
  Server kept an old table). Battery nodes are not read.

## [1.6.0] - 2026-11-14

### Added

- Wi-Fi nodes: access point they are connected to (BSSID matched against the
  MAC addresses of the Home Assistant devices, e.g. UniFi access points), shown
  in the attachment column; the BSSID is on hover and in the API (`bssid`,
  `access_point`).

### Changed

- Beta view: *Power* column (mains or battery), battery icon filled with its
  charge (green > 50 %, orange 20–50 %, red < 20 %).
- Beta view: the column button moved next to the filters (it covered the last
  header); narrower default columns so they fit without scrolling.

## [1.5.2] - 2026-11-14

### Changed

- Beta view curves: scale centered on the 7-day average (dashed line), ±5 dBm at
  least (±50 % for response times), widened by whole steps to fit every point;
  the weak-signal threshold is drawn only when it is within the scale, otherwise
  noted as off scale.

## [1.5.1] - 2026-11-14

### Changed

- Beta view: status and role in one column (*Status · Role*), shorter role names
  (*Sleepy end*, *End*…).

### Fixed

- Beta view: the column button no longer covers the last header; with many
  columns the table scrolls sideways instead of overflowing the card.

## [1.5.0] - 2026-11-14

### Added

- *Border router* column (beta view, shown by default): the border router each
  node reaches Home Assistant through, with the number of hops; the full path is
  in the technical details of the node panel. The API `route` now has `path`,
  `hops` and `complete`.
- Beta view: columns can be moved by dragging their header, or in the column
  list (which follows the same order).

### Changed

- Beta view: no ↔ sign in the attachment column any more; the meaning (parent
  of an end device, best neighbor router of a router) is explained on hover and
  in the node panel.
- Sorting has two states (click, click again to reverse); the default order
  (problems first) is in the column menu.

## [1.4.0] - 2026-11-14

### Added

- Beta view: column picker (small button at the right of the column headers):
  role, path to Home Assistant, link quality, neighbors, weak links, detaches,
  parent changes, outages, downtime, reboots, uptime, RLOC16, id. Remembered per
  browser; the phone cards keep their fixed layout.

### Changed

- Beta view sorting: *Status* sorts available / unavailable, *Attachment ·
  signal* sorts by signal strength, names sort alphabetically (accents ignored).

## [1.3.5] - 2026-11-14

### Changed

- Beta view: the 24h quality score is shown next to the trend, and each part of
  the score has a mark at its 24h value (exact values on hover).

### Fixed

- Response time: after a failed read (node switched off…), the node is read again
  2 minutes after it is back, then with a growing delay, instead of showing
  "no answer" until the next regular read (15 min, 60 min on battery).

## [1.3.4] - 2026-11-14

### Added

- Beta view: sort by clicking a column header (ascending, descending, then back
  to problems first); remembered per browser.

## [1.3.3] - 2026-11-14

### Fixed

- Node table: advice about a parent disappears as soon as the node has left that
  parent for a good link, without waiting for the next radio survey.

## [1.3.2] - 2026-11-14

### Fixed

- Path to the border router: an end device always goes through its parent (its
  own route table can be stale); routers whose link quality to the next hop is
  not published get a path too.

## [1.3.1] - 2026-11-14

### Fixed

- Path to the border router: the route table cost starts at the next hop, the
  link to the next hop is now added (and direct links are taken into account).

## [1.3.0] - 2026-11-14

### Added

- Path to Home Assistant of every Thread node, from the route tables: nearest
  border router (lowest path cost), next hop and cost; end devices go through
  their parent. In the API (`route`) and in the beta view (tooltip of the link
  and node panel).

### Changed

- Beta view: link column renamed *Attachment · signal*, with an explanation.

## [1.2.0] - 2026-11-14

### Added

- New view (beta), reachable from the classic view: summary with verdict and
  quality score parts, list of what to handle, border routers, node list with
  problems first and quick filters, side panel with the 7-day curves and the
  technical details. Follows the Home Assistant light or dark theme, adapted to
  phones. The last view used is kept per browser; the classic view is unchanged.

## [1.1.2] - 2026-11-14

### Fixed

- Nodes shown per network: total of that network instead of all nodes.

## [1.1.1] - 2026-11-14

### Changed

- Network panel: nodes shown counted per network (Thread, Wi-Fi, Ethernet); a
  network without nodes is not listed.

## [1.1.0] - 2026-11-14

### Added

- Matter nodes on Wi-Fi and Ethernet in the node table (column *Network*): link
  and Wi-Fi signal, availability, outages, reboots, uptime, response time, last
  contact, 7-day panel.

## [1.0.0] - 2026-11-14

### Added

- Border router monitoring (any brand): online state, role, partition, network
  prefix, leader, network splits, Thread storms, routing problems (VLAN, IPv6).
- Automatic recovery of lost Matter nodes by ping (off at first start).
- Node table in the sidebar: role, parent or best link with its signal,
  neighbors, detaches, outages, reboots, battery, uptime, last contact, response
  time, advice; compact layout on phones; 7-day panel per node; anonymized report.
- Network quality score (sensor and badge) over the last hour and 24 hours.
- Response time of every node (timed uptime read) and optional passive contact.
- Notification blueprints, MQTT entities, event log, English and French.

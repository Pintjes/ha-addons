# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.9.8] - 2026-11-16

### Added

- The "Seen" button also hides the orange network notes (e.g. a border router that detaches). A hidden note comes back when it changes.

## [2.9.7] - 2026-11-15

### Fixed

- Many nodes dropping together no longer show "Home Assistant or the Matter Server restarted" when the Supervisor log shows that nothing restarted: it is a network problem, and each node keeps its own card.

## [2.9.6] - 2026-11-15

### Changed

- A restart of the Matter Server or of Home Assistant is now read in the Supervisor log instead of being deduced from a dropped link: the card gives the exact time and the cause ("was restarted", "was updated to 9.3.1", "crashed (code 1)"). It also works when Mesh Guardian restarted at the same time, which the live link missed. Without access to the log, the detection by the live link remains.
- The add-on keeps the Supervisor role "manager" for this. It only reads the Supervisor log and the name of the Matter Server; see "Supervisor access" in the documentation.

### Added

- Event `server_restart` (who, cause, exit code, version).

### Removed

- The Supervisor API test of 2.9.3 – 2.9.5.

## [2.9.5] - 2026-11-15

### Changed

- Test of the Supervisor API with the role "manager" (to compare with "default").

## [2.9.4] - 2026-11-15

### Fixed

- 2.9.3 did not start (a file missing from the image).

## [2.9.3] - 2026-11-15

### Added

- Access to the Supervisor API (role "default"), as a test: at start, the add-on tries the Supervisor calls it could use (Matter Server state and log, Home Assistant state, network…) and logs which ones its role allows. Only the status codes are kept, never the content.

## [2.9.2] - 2026-11-15

### Fixed

- A restart of the Matter Server is now detected by Mesh Guardian itself (its live link drops and comes back), no longer through Home Assistant: 2.9.1 missed it when Home Assistant restarted at the same time.
- While Home Assistant starts, an incomplete list of nodes no longer makes their names and outage times disappear ("0x14", "Since ?").

### Changed

- The nodes taken down by a restart get their own card again after 5 minutes (was 30).

## [2.9.1] - 2026-11-15

### Changed

- After a restart of the Matter Server (or of Home Assistant), the nodes it took down no longer get one red card each: a single card says when it restarted and how many nodes are still reconnecting. A node still unavailable 30 minutes later gets its own card again.

## [2.9.0] - 2026-11-15

### Fixed

- An unavailable node showed its parent, signal ("good"), border router and response time read before the outage, as if they were current: they are now left empty.
- The nodes the recovery pings gave up on are kept across a restart ("Remove the battery for 10s" no longer becomes "Check its batteries").

## [2.8.9] - 2026-11-15

### Changed

- One section again, now called "Good to know", with every card (things to do and notes); "Nothing to report" when empty.

## [2.8.8] - 2026-11-15

### Changed

- "Good to know" notes under their own title, below "To handle", shown only when there is one.

## [2.8.7] - 2026-11-15

### Changed

- Border router cards show the state now (online, offline, other subnet). Detaches of the last 24h are a "good to know" note in "To handle", one for all border routers, with a "Seen" button; from 3 detaches, a note with an action, as before.

## [2.8.6] - 2026-11-15

### Changed

- Round values without decimals in the page: 100 %, 2 h, 1 s (not 100,0 %).

## [2.8.5] - 2026-11-15

### Added

- "Good to know" notes have a "Seen" button that hides them in this browser; a note that changes comes back.

## [2.8.4] - 2026-11-15

### Changed

- Status line: "reading the nodes… n/N" instead of "updating…", which suggested an update of the add-on.

## [2.8.3] - 2026-11-15

### Changed

- Status line: "connecting to the Matter Server…" while the dot is orange, then "updating… n/N" while the nodes are read again, then the time of the update.

## [2.8.2] - 2026-11-15

### Fixed

- An advice always names an action: "Changes parent n× in 24h" and "Detaches n× in 24h" were observations, not advice, and are removed (the figures stay in the node panel).

## [2.8.1] - 2026-11-15

### Fixed

- No advice when the table had been prepared by the background refresh.

## [2.8.0] - 2026-11-15

### Changed

- Advice rewritten: computed every time the table is shown (no longer every 30 minutes), each with its proof in the detail.
- Weak link of an end device: "Find a new parent" first, naming a better parent when one is known (a router it hears better, or a past parent with a good link) or the routers of its room or floor; "Move the node" or "Add a router in <room>" only after a search made since the link is weak found nothing better.
- Weak link of a router: "Add a router between <room> and <room>".
- Restarts: a power cut is no longer instability (power on reported, or several mains nodes restarting together); only crashes reported by the node count against a parent.
- Unavailable node: the cause first (parent unavailable too, power cut in the room, low batteries, recovery pings exhausted).

### Added

- Advice for a node that crashes or keeps restarting, a router that detaches (with the nodes that depend on it), a node hesitating between two parents, a weak Wi-Fi signal.
- Network notes: border router offline or detaching, node announced but unknown to the Matter Server.

### Fixed

- No link advice from a state read in the middle of a parent search.

## [2.7.3] - 2026-11-15

### Fixed

- Parent search: no answer to the connect command is no longer shown as "refused" (the node may be attaching again): the fail-safe is left armed, the result is followed as for a sleepy node. "Refused" only when the node answers with an error.
- A node whose route table says it has no link with the parent it routes through (read during a parent change) shows no parent instead of a wrong one.

### Changed

- While the nodes are read again, the status line says "updating… n/N" instead of the time of the last update.

## [2.7.2] - 2026-11-15

### Fixed

- After a restart, battery nodes showed the Matter Server cache again (old parent and signal) until the page was opened: the values read from the nodes in the last 2 hours (role, tables, addresses) are now kept across a restart.
- Parent of an end device shown from an old address with the signal of its new parent (e.g. during a parent search): its neighbor table and its addresses are now always read together, and the route table of a (sleepy) end device, not kept up to date by the node, is no longer used for its link quality.
- "Parent search refused" now gives the reason in French too.

## [2.7.1] - 2026-11-15

### Fixed

- A link quality of 0 between a child and its parent was taken as unknown: the stale value of the route table of a sleepy end device (3) was shown instead, and a link at the limit of reception was neither weak, advised nor counted in the score. It is now shown as "very weak" (orange, no bar) and counted as a weak link; the parent search also works on such a node.

## [2.7.0] - 2026-11-15

### Added

- Opening the page and Refresh read every available node again, battery ones included (response time, uptime, contact, role and Thread tables): three nodes at a time, mains nodes first, at most once every 5 minutes, never during a storm. The green dot blinks while the nodes are read, also during the reread after a start.

## [2.6.5] - 2026-11-15

### Fixed

- After a start, the first radio survey no longer uses neighbor and route tables hours old from the Matter Server cache (wrong parent changes, weak links missed): the tables of the mains-powered nodes are read again first, and the survey waits for it.
- A border router alone in its own partition for a few seconds is reported as a short detach of that border router (counted in its detaches and for storms), not as a network partition and a leader change.

### Changed

- Thread partitions and leader change once the new state held 30 seconds.
- One text for every partition change: "Thread partitions: 1 → 2".

## [2.6.4] - 2026-11-15

### Fixed

- A border router offline before a restart stays offline after it: it is no longer counted online for 15 minutes, then reported offline a second time.

## [2.6.3] - 2026-11-14

### Changed

- Node list: the "Clear" button is removed; "All" shows every node again and also clears the text filter.

## [2.6.2] - 2026-11-14

### Fixed

- Path to the border router: a loop between route tables read at different times (a node shown in its own path) now ends the path, marked as incomplete.

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

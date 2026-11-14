# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

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

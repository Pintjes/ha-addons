# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

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

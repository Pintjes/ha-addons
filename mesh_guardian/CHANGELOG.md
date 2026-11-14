# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

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

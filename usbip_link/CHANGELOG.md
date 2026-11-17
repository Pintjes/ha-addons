# Changelog

## [0.3.1] - 2026-11-17

### Fixed

- At each start of the add-on, a device attached already was published as not attached
  before the first check (Mesh Guardian then wrote "link cut" and "back" in the same
  second): the state is now published only after the first check.
- *Link latency* entity: without a measure it reads unknown (payload `None`) instead of the
  text `unknown`, which Home Assistant takes as not numeric.
- Server silent: the latency (`latency_ms`, `latency_avg_ms`, `latency_max_ms`) is unknown
  and its 5-minute window emptied, instead of the average of before.
- `server` given as a name: `usbip port` shows the address, so an attached device was not
  recognised and attached again in a loop; the name is resolved (again at each check until
  it resolves) and the device recognised under its address.

### Changed

- First attachment of a device (start of Home Assistant): the add-ons of `restart_addons`
  that already run, or are in error, are restarted once, the border router having perhaps
  started before the device was there. A device found attached already (restart of this
  add-on) restarts nothing; an attachment after a loss restarts them all, as before.
- A change of the latency alone is published at most every 60 s (the heartbeat stays 5 min).

### Docs

- Windows: the installer of usbipd-win adds a firewall rule `usbipd` (local subnet) that
  adds up with the one limited to Home Assistant: to be disabled or limited too.

## [0.3.0] - 2026-11-17

### Added

- Latency of the link: the time the server takes to answer (TCP connection to its USB/IP
  port) at every check, published in `usbip_link/state` (`latency_ms`, `latency_avg_ms` over
  5 min, `latency_max_ms`, and per device) and as a *Link latency* entity.

### Removed

- The fixed OMR prefix (`omr_prefix`, `omr_preference`, `otbr_addon`, the *OMR prefix* entity
  and `omr` in the state): moved to its own add-on, Thread Anchor, which serves any OpenThread
  border router. The options stay in the schema, unused, so that a saved configuration still
  loads; a filled `omr_prefix` gives a warning in the log. `docker_api` removed.

## [0.2.3] - 2026-11-17

### Changed

- Presentation page: what sets the add-on apart from a client that attaches once at start,
  and a section on the stable OMR prefix (the problem, how it works, its price).

## [0.2.2] - 2026-11-17

### Fixed

- `omr_prefix`: the border router container is `app_<slug>` since add-ons became apps (it was
  looked for as `addon_<slug>`, the name of older Supervisors, still tried after it).

## [0.2.1] - 2026-11-17

### Changed

- License: GPL-3.0-or-later, like the other add-ons of the repository (0.1.0 and 0.2.0 were
  published under MIT). The add-on keeps the idea of rogerfar/ha-usbip-client but none of its
  code (shell scripts there, Python written anew here).
- Icon, logo and presentation page.

## [0.2.0] - 2026-11-17

### Added

- Optional `omr_prefix` / `omr_preference`: the OpenThread border router is kept on a fixed
  OMR prefix with a higher preference than the prefixes the other border routers generate
  (Google TV…), so the Thread network stops changing its OMR prefix. Read again every 30 s
  and set again after each start of the border router (`ot-ctl br omrconfig`, Docker API).
  State on MQTT (`omr` in `usbip_link/state`) and a *OMR prefix* entity.

### Changed

- `docker_api: true` (needed by `omr_prefix` only).

## [0.1.0] - 2026-11-17

### Added

- First version: USB devices of a USB/IP server (usbipd-win on Windows) attached and kept
  attached (again after a restart of the server, a dead link freed), found by `VID:PID`,
  add-ons restarted after a new attachment, state on MQTT with one entity per device, read
  by Mesh Guardian. Based on the idea of rogerfar/ha-usbip-client (MIT), rewritten in Python.

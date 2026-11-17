# Changelog

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

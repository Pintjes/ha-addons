# Changelog

## [0.1.1] - 2026-11-17

### Added

- `anchored_since` in the state: since when the prefix has been in place without a break
  (date and time with the time zone). Filled also when the prefix is found already in place,
  kept over a restart of the add-on, emptied when the prefix is read and is no longer in place.
- `followed` in the state: the whole network favors the anchored prefix, with its preference.
  A warning in the log when the prefix is in place but the network favors another one (once
  per episode), and a line when it follows again.

### Changed

- An `omr_prefix` that is not a local prefix (ULA, `fc00::/7`) is refused: nothing is set.
- The MQTT broker is looked for again every 60 s when it was not found at start.
- At a clean stop, `offline` is published on `thread_anchor/state/available` at once.

## [0.1.0] - 2026-11-17

### Added

- First version: the OpenThread border router of Home Assistant kept on a fixed OMR prefix
  with a higher preference than the prefixes the other border routers generate (Google TV…),
  so the Thread network stops changing its OMR prefix (`ot-ctl br omrconfig`, Docker API).
  Set again at once when the border router container restarts, read every 30 s; the prefix
  the network favors read too (`br omrprefix`). Watch-only without a prefix. State on MQTT
  (`thread_anchor/state`) with two entities, read by Mesh Guardian. Moved out of USB/IP Link
  (its `omr_prefix` option of 0.2.x), so that it serves any OpenThread border router.

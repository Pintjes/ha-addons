# Changelog

## [0.1.0] - 2026-11-17

### Added

- First version: the OpenThread border router of Home Assistant kept on a fixed OMR prefix
  with a higher preference than the prefixes the other border routers generate (Google TV…),
  so the Thread network stops changing its OMR prefix (`ot-ctl br omrconfig`, Docker API).
  Set again at once when the border router container restarts, read every 30 s; the prefix
  the network favors read too (`br omrprefix`). Watch-only without a prefix. State on MQTT
  (`thread_anchor/state`) with two entities, read by Mesh Guardian. Moved out of USB/IP Link
  (its `omr_prefix` option of 0.2.x), so that it serves any OpenThread border router.

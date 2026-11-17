# Changelog

## [0.1.5] - 2026-11-17

### Fixed

- A false "Border router unreachable: unexpected answer: (empty)". The command
  interpreter of OpenThread is unique: a command received while an asynchronous one
  (`meshdiag`, `networkdiagnostic get`, `ping`) is waiting is ignored without a word,
  and the check of the anchor, sent in the middle of a scan, got an empty output.
  Every `ot-ctl` command of the add-on (anchor and diagnostic) now goes through one
  entry point with a gate taken for ONE command (never for a whole scan): the anchor
  waits only for the command in progress. An empty output with exit code 0 is a
  command that was ignored: asked again, 3 tries 3 s apart, then the precise message
  `ot-ctl: no answer (another command pending?)`, and what was read before stays as it
  was (the border router is not declared unreachable). A write (`br omrconfig custom`)
  that was ignored never passes for done. In the diagnostic, a ping with no output is
  no longer `ping.ok: false`: the answer says `ot-ctl: no answer…`, `ping` and `alive`
  stay `null`.

### Added

- The children of the routers that do not answer `meshdiag childtable` (a
  `ResponseTimeout`, probably a firmware without the Diagnostic Query): in the
  meshdiag step, their children are read with `meshdiag topology children` (RLOC16
  only), then each child is asked for its extended address (`networkdiagnostic get
  <RLOC address> 0`), one by one, the old RLOC16 of the request first. Same limits (90 s,
  one scan every 5 minutes, `busy`); `search`, `parent` and `alive` as before. The
  routers named in the request are dealt with first.
- `search` says whether the old RLOC16 given in `routers` (`"0xB45C"`) is still listed
  under its router (`old RLOC16 0xb45c`: `old_listed` / `old_gone`).
- The role of the border router in the Thread network, shown only: `thread_role`
  (`disabled`, `detached`, `child`, `router`, `leader`) and `thread_routers` (routers
  in its router table) in `thread_anchor/state`, and an entity *Thread role*. Two small
  reads per check (`state`, `router list`), no radio traffic. Thread Anchor never tries
  to change that role. No existing field is renamed.

## [0.1.4] - 2026-11-17

### Added

- The search for an unknown RLOC16 says what it did: one line of the log per step (ML-EID,
  `child table`, `neighbor table`, `router table`, with the number of rows read) and a `search`
  list in the answer.
- A **meshdiag** step when the tables do not have the node: the other routers are asked, one by
  one, for their children (`ot-ctl meshdiag topology`, then `meshdiag childtable <router>`),
  the routers named in the request's `routers` first, until the extended address is found, 90 s
  at most, one scan every 5 minutes (the last one is read again in between). `help` is read first,
  once per start of the border router: without `meshdiag` the step says `not supported` and the
  answer is `not found`. `"scan": false` skips it. The answer says the router in `parent`.
- `alive` in the answer: true only when the ping or the network diagnostic answered. A node
  listed in a child table is not proved alive, a parent keeps its children a while.

### Changed

- The ping and the diagnostic that follow a search have their own 15 s; the search no longer
  eats into them.

## [0.1.3] - 2026-11-17

### Added

- Diagnostic of a node whose RLOC16 is not known: leave `rloc16` out of the request and give
  `ext` (extended address) and / or `mleid` (mesh-local address). The RLOC16 is found from the
  `mleid` with one network diagnostic (dropped when the extended address received is not the
  one asked), then from the tables of the border router (`child table`, `neighbor table`,
  `router table`), else the answer is `not found`. The answer says how in `rloc16_from`.
  Reads only; the search counts in the 15 s limit.
- A request with a wrong `ext`, `mleid` or `rloc16`, or with none of the three, gets an answer
  with the reason in `error`.

## [0.1.2] - 2026-11-17

### Added

- Diagnostic of one Thread node, on request over MQTT (`thread_anchor/diag/request`, answer on
  `thread_anchor/diag/result/<id>`): ping of its RLOC address and its IPv6 addresses read with a
  network diagnostic, sorted into addresses in the OMR prefix and addresses on another prefix
  (a node that kept an old one). Read only: nothing is set on the border router. One request at a
  time, at most one per node every 10 s, 15 s at most each; one line in the log per diagnostic.

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

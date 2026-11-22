# Changelog

## [0.1.14] - 2026-11-22

### Changed

- License changed: proprietary from this version (end user license agreement in `LICENSE`, French text
  prevailing, with an English translation; © 2026 Pintjes. All rights reserved); earlier versions stay under
  GPL-3.0-or-later. No change in behavior.
## [0.1.13] - 2026-11-22

### Changed

- The `error` of `thread_anchor/state` is now a **short message** per kind of failure (no more raw Docker
  text such as an OCI runtime message): *cannot run a command in its container (restarting?)*, *no answer in
  time*, *no access to the Docker API; turn Protection mode off*, *container not found or stopped*, *border
  router unreachable*. The raw text of the failure only goes to the add-on log.

### Added

- `error_kind` in the state, next to `error`: `exec_failed`, `timeout`, `access_denied`, `not_found`, `other`,
  `no_answer`, `too_old`; `null` when there is no error. `error` stays a string, so readers that copy it keep working.
## [0.1.12] - 2026-11-17

### Added

- The change of the counters of the link **hour by hour**, to follow the radio over days: in the state
  (`thread_link.stats.last`, with the derived `tx_no_ack` and the shares of aborted frames), on
  `thread_anchor/link_stats` (retained, the last 72 hours, kept over a restart) and as 7 Home Assistant
  sensors with a long history (*TX aborted per hour*, *TX CCA errors per hour*, *TX without ack per hour*,
  *TX retries per hour*, *Detachments per hour*, *Parent changes per hour*, *TX abort ratio*). Nothing is read
  for it: it uses the counters the link reading already gets. An hour in which the border router restarted, or
  a counter went down, is not counted.
- `tx_ack_requested` and `tx_acked` in the MAC counters, so that `tx_no_ack` can be told: `tx_retry` stays 0
  on a radio co-processor that retries by itself.
- Round trip to the radio chip, **on request only** (`thread_anchor/latency/request`): 100 pairs of reads
  (`ot-ctl state` against `ot-ctl txpower`, or `ccathreshold` when `txpower` looks cached), one a second, each
  timed; the answer gives min / median / p95 / max of the difference, the times above 50 ms and the frames sent
  and aborted before / after. Reads only, no radio emission, one at a time, never while a diagnostic runs.

## [0.1.11] - 2026-11-17

### Added

- `thread_anchor/children` (retained JSON): what the add-on already learns about the nodes, published as it
  comes, to fill the attachment of the nodes in Mesh Guardian. For each extended address: RLOC16, parent
  (RLOC16 & 0xFC00 for a child, `null` for a router), role, how it was learned (`source`) and when (`read_at`);
  a `signal` only when it was read, marked `"toward": "otbr"` (measured toward the border router, not the
  parent). It comes from the meshdiag scans, the tables of the border router read by the searches, the
  answers of the diagnostics, and the periodic reading of the link of 0.1.9 (neighbor table, router table).
  **No scan and no reading more: no extra radio traffic.** Published when it changes and every 15 minutes,
  kept over a restart (`/data/children.json`), a node not learned again for 7 days dropped.
- `ext` is now read from the `router table` too (internal: `parse_router_rows`).

## [0.1.10] - 2026-11-17

### Fixed

- The MAC counters of `thread_link` were almost all missing (only `tx_total` and `rx_total` came out):
  OpenThread writes `TxRetry`, `TxErrCca`, `TxErrAbort`, `TxErrBusyChannel`, `RxErrNoFrame`,
  `RxErrUnknownNeighbor`, `RxErrSec`, `RxErrFcs` indented under `TxTotal` / `RxTotal`, and the
  lines in an indent were left out. They are read now. The tests use the real, indented format.
- The RSSI of the parent (`rssi_avg`, `rssi_last`) came out empty. The parent is now looked for in
  the neighbor table by its RLOC16 and then by its extended address, and `in_neighbor_table` says
  whether it was found (`null`: the table could not be read). When it is not, the raw table is in
  the log in Debug mode (`link: parent 0x… not in the neighbor table`), to see the real format.

### Added

- `parent_history` in `thread_link`: the last 10 changes of parent of the border router
  (`{"at", "from", "to"}`, oldest first), also kept over a restart of the add-on in
  `/data/parent_history.json`. A change made while the add-on was off, or between a detachment and
  the next attachment, is seen too. Read only, as the rest of `thread_link`.

## [0.1.9] - 2026-11-17

### Added

- The link of the border router with its parent and its neighbors, in the state (`thread_link` in
  `thread_anchor/state`): its RLOC16; for a child, its parent (RLOC16, extended address, link
  quality in / out, average and last RSSI, age); the 3 routers heard with the best average RSSI
  (with the link quality and path cost of the router table, `is_parent`); the number of routers
  heard; and the counters of the MLE layer (detachments, attach attempts, parent changes…) and of
  the MAC layer (retries, CCA and FCS errors…). It answers the question « how good is the link of
  the border router with its parent? ». Local reads of the border router (`rloc16`, `parent`,
  `neighbor table`, `router table`, `counters mle`, `counters mac`): no radio traffic, nothing
  written, one reading a minute at most, through the same single `ot-ctl` entry point as the rest.
  A part that cannot be read is left out, the others are kept.
- A change of parent of the border router is said in the log.
- No new Home Assistant entity: the values are in the state JSON only. Ages, RSSI and counters move
  at every reading and do not make the state "change" by themselves: they go out with the next
  change or the 5-minute heartbeat.

## [0.1.8] - 2026-11-17

### Fixed

- The meshdiag step no longer gives up when `meshdiag topology` times out (`Error 28:
  ResponseTimeout`: it asks every router at once). It used to end with `not found` and no
  per-router step, although the node was on the network. It now carries on: the routers are taken
  from the `router table` read earlier in the same search and from the request's `routers`
  (`routers from the router table: N routers…` in `search`), then asked one by one with
  `meshdiag childtable`, and `meshdiag topology children` / `networkdiagnostic get` for the ones that
  do not answer, all inside the same 90 s budget. A `Busy` answer still stops the step. Without
  a router table and without a hint, nothing is invented: the step says the error.

## [0.1.7] - 2026-11-17

### Fixed

- The second try for the silent children of the router named in the request (`children of 0x…
  (again)`, 0.1.6) now comes right after the routers that answer have been read, BEFORE the
  children of the other routers that did not answer `meshdiag childtable` are read. It came
  last, so those routers could use up the whole 90 s budget and the second try never happened.

## [0.1.6] - 2026-11-17

### Added

- The children that stayed silent are named. A child asked for its extended address
  (`networkdiagnostic get`) that did not answer is listed in `silent_children` of the answer
  (`[{"rloc16": "0x6c06", "parent": "0x6c00"}]`; `[]` when none) and in the log line of the
  step (`children of 0x6c00: 3 children asked, 2 answered, ext not among them; silent: 0x6c06`).
  A node that attached again to its parent under a new RLOC16 and sleeps is typically there.
- One more try for the silent children of a router named in the request's `routers`: at the end
  of the scan, if there is time left, only those are asked again once (`children of 0x… (again)`):
  a child asleep answers when it is awake.
- A scan that stopped before its end (time budget of 90 s, or a hit) is carried on by the next
  one, for 30 minutes: the routers whose children are all known and the children that answered
  are not asked again, the routers not read yet come first, then the ones with silent children;
  a router named in the request is read again anyway. A child that answered in the scan that is
  carried on is found again without any traffic. A scan that went to the end with every router
  known is not carried on (the next one is complete), nor after the border router started again.
  Same limits as before: 90 s, one scan every 5 minutes.

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
- `search` says whether the old RLOC16 given in `routers` (`"0x6C05"`) is still listed
  under its router (`old RLOC16 0x6c05`: `old_listed` / `old_gone`).
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

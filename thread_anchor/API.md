# Thread Anchor: MQTT reference

The MQTT topics of Thread Anchor, for the tools that read or drive it (Mesh Guardian, your own scripts).
To install and use the app, see its documentation (`DOCS.md`).

## State: `thread_anchor/state`

Retained, JSON.

| Field | |
|---|---|
| `wanted`, `preference` | prefix and preference of the options (`wanted` empty: watch only) |
| `mode`, `current`, `current_preference` | what the border router holds (`auto`, `custom`…) |
| `enforced` | the border router holds the prefix of the options |
| `anchored_since` | since when it has held it without a break (ISO 8601 with the time zone). Filled when the prefix is found in place, even set by something else; kept over a restart of the app and while the border router cannot be read; empty once the prefix is read and is no longer in place |
| `favored`, `favored_preference`, `local` | prefix the network favors, and the border router's own |
| `followed` | `enforced`, and the network favors that prefix with that preference. When it is false while `enforced` is true, another border router wins: a warning is in the log |
| `applied`, `applied_at` | times the prefix was set since the app started, and the last time (Unix time) |
| `thread_role`, `thread_routers` | role of the border router in the Thread network (`ot-ctl state`) and number of routers its router table lists (`ot-ctl router list`); two small reads at every check, no radio traffic. `thread_routers` is `null` without a network (`disabled`, `detached`), both are `null` when unreadable |
| `thread_link` | the link of the border router with the Thread network, read from the border router itself: `ot-ctl rloc16`, `parent`, `neighbor table`, `router table`, `counters mle`, `counters mac`. Local reads, no radio traffic, nothing written; one reading a minute at most (at once when the role changes); `null` when the role is unknown or `disabled`. Content: `rloc16` (of the border router), `parent` (a child's only: `rloc16`, `ext`, `lq_in`, `lq_out` — Thread link quality 0 to 3 —, `quality` (`good` 3, `medium` 2, `weak` 1, `unknown` 0, of the worse direction), `age` in s, `rssi_avg` and `rssi_last` in dBm, `in_neighbor_table`: whether the parent was found in the neighbor table, by RLOC16 then by extended address, `null` when the table could not be read; the RSSI are `null` when it was not, and the raw table is then in the log in Debug mode), `routers_heard` (routers in the neighbor table), `best` (the 3 routers heard with the best average RSSI: `rloc16`, `ext`, `rssi_avg`, `rssi_last`, `age`, `lq_in`, `lq_out`, `path_cost` from the router table, `is_parent`), `counters` (`mle`: `role_detached`, `role_child`, `role_router`, `role_leader`, `attach_attempts`, `partition_id_changes`, `better_partition_attach_attempts`, `parent_changes`; `mac`: `tx_total`, `tx_retry`, `tx_err_cca`, `tx_err_abort`, `tx_err_busy_channel`, `rx_total`, `rx_err_no_frame`, `rx_err_unknown_neighbor`, `rx_err_sec`, `rx_err_fcs`; counted since the start of the radio, only the ones the firmware gives; OpenThread writes them indented under `TxTotal` / `RxTotal`, which is read as is), `parent_history` (the last 10 changes of parent, oldest first: `{"at": time of the reading that saw it, "from": "0x…", "to": "0x…"}`; kept in `/data/parent_history.json` over a restart of the app, so a change made while the app was off is seen at its first reading; a back and forth between two readings, a minute apart, is not seen: `counters.mle.parent_changes` counts them all since the radio started), `read_at`. A part that cannot be read is left out (`null` or missing), the others are kept. A change of parent is said in the log (`Parent of the border router changed: 0x3400 -> 0x5800`). Ages, RSSI and counters move at every reading: they go out with the next change of the state or the 5-minute heartbeat |
| `otbr_started_at`, `error` | start of the border router container, last error (a short message; the raw text of a Docker failure is only in the app log) |
| `error_kind` | kind of the last error: `exec_failed` (command impossible in the container), `timeout`, `access_denied` (Docker API refused: turn Protection mode off), `not_found` (container absent or stopped), `other`, `no_answer` (`ot-ctl` busy), `too_old` (no `br omrconfig`); `null` without error |
| `version`, `updated` | version of the app, time of this state |

## The change of the counters, hour by hour (`thread_anchor/link_stats` and 7 sensors)

The counters of `thread_link.counters` only say "since the start of the radio": they hide when things
happened. The app keeps the **change over each hour** (reads nothing more: it uses the counters of the
link reading), to follow the health of the radio link over days.

- `thread_link.stats.last`: the last hour that ended, `{"from", "to", "seconds", "role", ...}` with, per counter,
  the change over the window (`tx_total`, `tx_ack_requested`, `tx_acked`, `tx_retry`, `tx_err_cca`,
  `tx_err_abort`, `tx_err_busy_channel`, `rx_total`, `rx_err_*`, `role_detached`, `role_child`, `role_router`,
  `parent_changes`, `attach_attempts`, `partition_id_changes`), and the derived `tx_no_ack` (frames sent
  expecting an ack that did not come: `tx_ack_requested − tx_acked`), `tx_err_abort_pct`, `tx_no_ack_pct` and
  `tx_err_cca_pct` (share of `tx_total`). `stats.since`: start of the window in progress.
- A window runs from a reading just after the hour starts to the next one (about 60 min, 55 to 90 accepted).
  Not counted: the first (partial) hour after a start, an hour in which the border router restarted or a
  counter went down, a window that is not an hour (app stopped for long).
- `thread_anchor/link_stats` (retained): the last 72 windows (3 days), kept over a restart in
  `/data/link_stats.json`, to correlate over days.
- 7 sensors in Home Assistant (device *Thread Anchor*, `state_class: measurement`, so Home Assistant keeps
  their long statistics): *TX aborted per hour*, *TX CCA errors per hour*, *TX without ack per hour*,
  *TX retries per hour*, *Detachments per hour*, *Parent changes per hour*, *TX abort ratio* (%). *unknown*
  until the first full hour.
- `tx_retry` is 0 on a radio co-processor that retries by itself (the counter of the host only counts the
  retries the host makes): the frames that never got their ack are in `tx_no_ack`, the better figure.

## Round trip to the radio chip, on request: `thread_anchor/latency/request`

To tell a slow USB/IP link from a healthy one. **Never run on its own**, only when asked:
`{"id": "x1", "count": 100, "interval_s": 1}` (`count` 10 to 200, default 100; `interval_s` 0.5 to 3, default 1).
It alternates `ot-ctl state` (answered by the host alone) and `ot-ctl txpower` (reads a setting of the chip over
spinel: no radio emission), times each, and the difference of the two is the round trip to the chip. `txpower`
must be at least 1 ms slower than `state`, else it was answered from a cache and `ccathreshold` is tried (the
answer says `command`, and `cached_suspected: true` when neither is slower). Reads only: `state`, `txpower`,
`ccathreshold`, `counters mac` (frames sent and aborted before and after). One at a time, refused (`busy`)
while a diagnostic runs, and no diagnostic while it runs. About `count × (interval_s + 0.1)` seconds.

Answer on `thread_anchor/latency/result/<id>` (not retained; the last good one also on
`thread_anchor/latency/last`, retained): `state` (`ok`, `error`, `refused`), `command`, `n`, `errors`,
`state_ms`, `chip_ms`, `diff_ms` (`min`, `median`, `p95`, `max`), `spikes_count` and `spikes` (the first 20
differences above 50 ms, with their time), `counters` (`before`, `after`, `delta`, `abort_pct`), `started`,
`seconds`. The log has one line with the median, p95 and max.

## What the app knows about the nodes: `thread_anchor/children`

Published retained, JSON, **no reading of its own and no radio traffic**: it is only what the app already
learns, kept and published as it comes. Nothing new is asked of the network for it.

```json
{"version": 1, "updated": "2026-11-17T22:10:00+01:00", "count": 3, "add_on_version": "0.1.11",
 "nodes": {
   "1a2b3c4d5e6f7081": {"rloc16": "0x6c05", "parent": "0x6c00", "role": "child",
                        "source": "diagnostic", "read_at": "2026-11-17T22:07:11+01:00"},
   "5a6b7c8d9e0f1a2b": {"rloc16": "0x3400", "parent": null, "role": "router", "source": "neighbor table",
                        "read_at": "2026-11-17T22:09:31+01:00",
                        "signal": {"rssi_avg": -62, "rssi_last": -64, "lq_in": 3, "lq_out": 2, "toward": "otbr"}}}}
```

- The key is the extended address (lower case), as Mesh Guardian knows the node (`hw_address`).
- `rloc16`: the RLOC16 when it was learned. A node that attaches again to another parent changes it: use
  `read_at` to judge how fresh it is. `role`: `child` or `router`. `parent`: the RLOC16 of the router of a
  child (its RLOC16 & 0xFC00); `null` for a router.
- `source`, how it was learned: `childtable` (the router listed it in `meshdiag childtable`), `diagnostic`
  (the node answered a network diagnostic at that RLOC16, or a child of a silent router answered), `topology`
  (`meshdiag topology`), `router table`, `neighbor table`, `child table` (the tables of the border router).
- `signal` is only there when it was read, and says `"toward": "otbr"`: it is measured between that node and
  the **border router** (RSSI of its neighbor table, link quality of its router table), **not** toward the
  node's own parent. A child learned by a scan has none: show nothing rather than a guess.
- Published when a node appears or its RLOC16, parent or role changes, and every 15 minutes anyway. Kept over
  a restart in `/data/children.json`; a node not learned again for 7 days is dropped.
- Not in it: the children of a router that does not answer `meshdiag childtable` and did not answer a
  diagnostic; a node never searched for, never seen in a scan and not in the tables. The list grows with the
  searches (those asked by Mesh Guardian, or any scan of the network: at most one every 5 minutes).

## Diagnostic of a node

To find a node that stayed on an old OMR prefix (it does not answer on the
current one), Thread Anchor can look at it from the border router. It only
**reads**: nothing is set on the border router (no `omrconfig`, no route, no
network data). Needs MQTT.

Request, on `thread_anchor/diag/request` (not retained):

```json
{"id": "r1", "rloc16": "0x6C05", "ext": "1a2b3c4d5e6f7081", "ping": true}
```

`id` is a unique string (letters, digits, `-`, `_`; no `/`, `+` or `#`), `rloc16`
the short address of the node, `ext` its extended address (16 hexadecimal
digits; checked against the answer), `ping` `false` to skip the ping; `mleid`,
`routers` and `scan` are for a node whose RLOC16 is not known (below). In the
border router container it runs, one after the other (reads only):

1. `ot-ctl ipaddr rloc` — the mesh-local prefix, hence the RLOC address of the
   node: `<mesh-local prefix>:0:ff:fe00:<rloc16>`;
2. `ot-ctl ping <rloc address> 16 1` (if `ping`);
3. `ot-ctl networkdiagnostic get <rloc address> 0 8` — the extended address
   (TLV 0) and the IPv6 address list (TLV 8) of the node.

### Without `rloc16`

A node that attached again may have a new RLOC16. Leave `rloc16` out (do not
send `null`) and give `ext`, and / or `mleid` (its mesh-local address, `ML-EID`;
it must be in the mesh-local prefix). The RLOC16 is looked for before step 1,
in this order, and the first answer wins:

1. with `mleid`: `ot-ctl networkdiagnostic get <mleid> 0 1 8` — extended
   address (TLV 0), RLOC16 (TLV 1) and addresses (TLV 8) in one request. If `ext`
   was given and differs from the one received, the address is not that node's
   any more: this step is dropped;
2. with `ext`: the tables of the border router, `ot-ctl child table`,
   `neighbor table`, then `router table` (columns *RLOC16* and *Extended MAC*).
   They cost no radio traffic, but hold only the children and neighbors of the
   border router itself and the routers: a node attached to another router is
   not in them;
3. with `ext`, if the tables do not have it: the **meshdiag** step (below);
4. otherwise the answer is `error: "not found"`, with no ping and no diagnostic.

Once found, the rest is unchanged (ping, network diagnostic; with `mleid` the
diagnostic of step 1 is reused). Steps 1 and 2 are limited to 15 s together,
the meshdiag step has its own 90 s, and the ping and the diagnostic that follow
have their own 15 s.

Every step is one line in the log (`Search child table: 4 rows, ext not in it`)
and one entry of `search` in the answer.

### The meshdiag step

The other routers of the network are asked, one by one, for their children
(`ot-ctl meshdiag topology`, then `ot-ctl meshdiag childtable <router RLOC16>`):
this finds a node attached to a router the border router does not see itself.
Reads only, but it is radio traffic: a request for every router.

- `ot-ctl help` first (once for each start of the border router): without
  `meshdiag` the step says `not supported` in `search` and the answer is
  `not found`, no error;
- when `meshdiag topology` itself times out (it asks every router at once; on a
  large network it can), the step does not give up: the routers are taken from
  the `router table` already read in the same search, plus the routers of the
  request (`routers from the router table` in `search`, with their number), and
  asked one by one as below, in the same 90 s. Without a router table and
  without a `routers` hint there is nothing to ask: the step says the error. A
  `Busy` answer still stops it;
- the routers are asked in the order of the topology, the border router itself
  left out (its children are in `child table`), after the ones named in the
  request's `routers` (RLOC16 of routers, or of their children: `"0x6C05"`
  stands for the router `0x6C00`); it stops as soon as the extended address
  is found, or after 90 s (`stopped`), or when a router answers `Busy`;
- a router that does not answer `meshdiag childtable` (`ResponseTimeout`; some
  firmwares do not know the Diagnostic Query it needs) is not skipped: its
  children are read with `ot-ctl meshdiag topology children` (one per scan; the
  routers do answer the Diagnostic Get it uses; the children come as RLOC16
  only), then each child is asked for its extended address with `ot-ctl
  networkdiagnostic get <RLOC address of the child> 0`, one request per child,
  the old RLOC16 of the request first. A router named in the request is dealt
  with at once, the other silent ones after all the routers that answer. A child
  that sleeps answers late (its parent hands it the question when it wakes up),
  many do not answer in time: the step says how many were asked and how many
  answered (`children of 0x6c00: 12 children asked, 7 answered, ext not among
  them; silent: 0x6c03, 0x6c0a`). The children that answered are kept with the
  scan, and those that did not are named in `silent_children` of the answer.
  For a router named in the request, the silent ones are asked once more, if
  there is time left, as soon as the routers that answer have been read and
  before the other silent routers (`children of 0x6c00 (again)`);
- a scan that stopped before its end (the 90 s are used, or a hit) is carried on
  by the next scans for 30 minutes: the routers whose children are all known,
  and the children that answered, are not asked again; the routers not read yet
  come first, then those with silent children; a router named in the request is
  read again anyway. After a scan that went to the end with every router known,
  or when the border router started again, the next scan is complete;
- when a request names an old RLOC16 of a child in `routers` (`"0x6C05"`) and
  the list of children of its router (`0x6C00`) was read, `search` says whether
  that RLOC16 is still listed there (`old RLOC16 0x6c05`: `old_listed` or
  `old_gone`, `detail`: the router);
- at most one scan every 5 minutes; in between, the answer of the last scan is
  read again without any traffic (`too soon` in `search` when the node was not
  in it). `"scan": false` in the request skips this step;
- while a scan runs, every other request gets `busy`.

**A table does not prove that the node is alive.** A parent keeps a child in its
table for a while after the child has gone. Only the answer to the ping or to
the network diagnostic counts: see `alive` below.

Answer, on `thread_anchor/diag/result/<id>` (not retained, JSON):

| Field | |
|---|---|
| `id` | as in the request |
| `rloc16` | as in the request; when it was left out: the RLOC16 found, like `"0x6c05"` (`null`: not found) |
| `rloc16_from` | how it is known: `request`, `mleid`, `child table`, `neighbor table`, `router table` or `meshdiag`; `null` when not found or the request was refused |
| `parent` | with `meshdiag`: RLOC16 of the router whose child table lists the node (`null` when the node is a router itself, or not found by `meshdiag`) |
| `alive` | `true` only if the ping or the network diagnostic answered (and the node that answers has the `ext` asked); `false` when the RLOC16 is known (even from a table) but nobody answered, or another node answers there; `null` when there is no RLOC16 (not found, request refused) |
| `search` | the steps of the search for the RLOC16, in order: `[{"step": "child table", "result": "found", "rows": 4, "detail": "0x6c05"}, …]`; `step` is `mleid`, `child table`, `neighbor table`, `router table`, `meshdiag help`, `meshdiag`, `meshdiag topology`, `meshdiag childtable 0x…`, `meshdiag topology children`, `children of 0x…` (also `children of 0x… (again)`) or `old RLOC16 0x…`; `result` is `found`, `not_found`, `no_answer`, `ext_differs`, `error`, `not_supported`, `too_soon`, `stopped`, `kids`, `no_list`, `asked`, `old_listed` or `old_gone`; `rows`: lines read (tables, topology: routers; `children of`: children asked); `detail`: RLOC16, extended address received, error or reason. Empty when `rloc16` was given |
| `silent_children` | children of routers read by `meshdiag topology children` that did not answer the request for their extended address: `[{"rloc16": "0x6c06", "parent": "0x6c00"}]`, as known at the end of the scan (carried over from the last scans while they are carried on); `[]` when none, or when there was no meshdiag step. A silent child is not proved dead: it may be asleep |
| `rloc_address` | the RLOC address that was asked (`null` if it could not be built) |
| `ext` | extended address the node answered with, lowercase (`null`: no answer) |
| `ping` | `{"ok": bool, "rtt_ms": float or null}`; `null` when no ping was asked |
| `addresses` | every IPv6 address of the node |
| `omr_addresses` | those in the anchored prefix (`wanted`) or in the prefix the network favors (`favored`) |
| `other_prefix_addresses` | global or local (ULA) addresses that are neither mesh-local, nor link-local, nor in the current prefixes: an old OMR prefix the node kept |
| `error` | `null`, or why it failed: `busy`, `too soon`, `not found`, `invalid rloc16: …` / `invalid ext: …` / `invalid mleid: …`, `rloc16, ext or mleid needed`, `mleid is not in the mesh-local prefix`, `timeout (15 s)`, `no answer to the network diagnostic`, `ot-ctl: no answer (another command pending?)`, a different `ext` than asked, an `ot-ctl` or Docker error |
| `at` | time of the answer (ISO 8601 with the time zone) |

**One `ot-ctl` command at a time.** The command interpreter of OpenThread is
unique: a command received while an asynchronous one (`meshdiag`,
`networkdiagnostic get`, `ping`) is waiting is ignored without a word (empty
output). Every `ot-ctl` command of the app, the anchor's and the diagnostic's,
goes through one gate taken for ONE command (never for a whole scan), so the
check of the anchor waits only for the command in progress. An empty output is
asked again (3 tries, 3 s apart), then reported as `ot-ctl: no answer (another
command pending?)`: a ping with no output is not a lost ping (`ping` stays
`null`, `alive` too), and the border router is not declared unreachable.

Limits: one diagnostic at a time (`busy`, also while a meshdiag scan runs), at
most one per node every 10 s (`too soon`; the node is its `rloc16`, else its
`ext`, else its `mleid`), 15 s at most each (a search with the meshdiag step:
up to 15 + 90 + 15 s). A request without a usable `id` gets no answer
(only a line in the log). Each diagnostic is one line in the log. A node that
does not answer the ping may still answer the network diagnostic (it is reached
by its RLOC address, which does not depend on the OMR prefix).

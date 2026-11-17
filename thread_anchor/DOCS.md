# Thread Anchor

Keeps the Thread network of the house on one OMR prefix, so that border routers
that change theirs (Google TV, Nest Hub, HomePod…) stop moving every device to
a new address.

> **Beta.** The add-on reaches the OpenThread border router through the Docker
> API: **Protection mode** must be turned off in its Info tab.

## The problem

Each border router of a Thread network publishes an **OMR prefix** (off-mesh
routable): the address prefix the devices use to be reached from the home
network. A prefix a border router generates itself has a **low** preference.
The network uses the favored one — the highest preference, then the lowest
number — and when a border router replaces its prefix, every device moves to the
new one. Matter controllers then lose the devices until they are found again:
they show as unavailable, sometimes for a long time.

## What the add-on does

With `omr_prefix`, Thread Anchor gives the OpenThread border router of Home
Assistant that prefix with the preference `omr_preference` (`high` by default):

```
ot-ctl br omrconfig custom <omr_prefix> <omr_preference>
```

Every border router favors it over the low-preference prefixes and withdraws
its own. OpenThread keeps this setting **in memory only**: Thread Anchor watches
the border router container, sets it again as soon as it restarts, and reads it
every `check_interval` seconds. It also reads the prefix the whole network
favors (`br omrprefix`): when it is yours with `prf:high`, the other border
routers follow.

## Setup

1. The **OpenThread Border Router** add-on runs, on the Thread network of the
   house (Settings → Thread: it is in the same network as your other border
   routers).
2. Install Thread Anchor, turn **Protection mode** off, start it **without**
   `omr_prefix`: it only watches. The entity *Favored OMR prefix* (and Mesh
   Guardian) shows the prefix the network uses now, e.g. `fdd7:20e4:8187:1::/64`.
3. Put **that** prefix in `omr_prefix` and restart the add-on. The log says
   `OMR prefix … set on the border router (it was: auto)`, then
   `The network favors … (high)`. The devices keep their addresses: nothing was
   renumbered.

| Option | |
|---|---|
| `omr_prefix` | local `/64` prefix to anchor (ULA, in `fc00::/7`: it starts with `fc` or `fd`); empty: watch only. Any other prefix is refused and nothing is set |
| `omr_preference` | `high` (default), `med` or `low` |
| `otbr_addon` | slug of the border router add-on (`core_openthread_border_router`) |
| `check_interval` | seconds between two readings (30) |
| `language` | `en` or `fr` |

## Good to know

- If the Home Assistant border router stops, the other border routers publish
  their own prefixes again, and the network moves until it is back. Thread
  Anchor sets the anchor again as soon as it restarts.
- To stop: empty `omr_prefix` and restart the border router add-on (or run
  `ot-ctl br omrconfig auto` in it). Its own low-preference prefix then competes
  with the others again.
- Only one tool should set the prefix: if you used the `omr_prefix` option of
  USB/IP Link 0.2.x, empty it there.
- The Docker API gives the add-on control over every container: that is why
  Home Assistant asks for Protection mode to be off. Thread Anchor only reads
  the state of the border router container and runs `ot-ctl br omrconfig` /
  `ot-ctl br omrprefix` in it.

## Entities and Mesh Guardian

With MQTT (state on `thread_anchor/state`, retained):

- **binary_sensor** *OMR prefix anchored*: on when the border router holds the
  prefix of the options; attributes: mode, current prefix and preference,
  prefix favored by the network, number of times it was set, last error.
- **sensor** *Favored OMR prefix*: the prefix the whole network uses.

Without a broker at start, the add-on works all the same and looks for it again
every 60 s. `thread_anchor/state/available` says `online` / `offline`: `offline`
is published when the add-on stops; the retained state is then left as it was.

Fields of `thread_anchor/state` (JSON):

| Field | |
|---|---|
| `wanted`, `preference` | prefix and preference of the options (`wanted` empty: watch only) |
| `mode`, `current`, `current_preference` | what the border router holds (`auto`, `custom`…) |
| `enforced` | the border router holds the prefix of the options |
| `anchored_since` | since when it has held it without a break (ISO 8601 with the time zone). Filled when the prefix is found in place, even set by something else; kept over a restart of the add-on and while the border router cannot be read; empty once the prefix is read and is no longer in place |
| `favored`, `favored_preference`, `local` | prefix the network favors, and the border router's own |
| `followed` | `enforced`, and the network favors that prefix with that preference. When it is false while `enforced` is true, another border router wins: a warning is in the log |
| `applied`, `applied_at` | times the prefix was set since the add-on started, and the last time (Unix time) |
| `otbr_started_at`, `error` | start of the border router container, last error |
| `version`, `updated` | version of the add-on, time of this state |

**Mesh Guardian** reads this state: it says in *To do* when the anchor is no
longer in place, and in its log when it is lost and back.

## Diagnostic of a node

To find a node that stayed on an old OMR prefix (it does not answer on the
current one), Thread Anchor can look at it from the border router. It only
**reads**: nothing is set on the border router (no `omrconfig`, no route, no
network data). Needs MQTT.

Request, on `thread_anchor/diag/request` (not retained):

```json
{"id": "r1", "rloc16": "0xB45C", "ext": "ca7a34808b66e461", "ping": true}
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
- the routers are asked in the order of the topology, the border router itself
  left out (its children are in `child table`), after the ones named in the
  request's `routers` (RLOC16 of routers, or of their children: `"0xB45C"`
  stands for the router `0xB400`); it stops as soon as the extended address
  is found, or after 90 s (`stopped`), or when a router answers `Busy`;
- a router that does not answer is skipped;
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
| `rloc16` | as in the request; when it was left out: the RLOC16 found, like `"0xb45c"` (`null`: not found) |
| `rloc16_from` | how it is known: `request`, `mleid`, `child table`, `neighbor table`, `router table` or `meshdiag`; `null` when not found or the request was refused |
| `parent` | with `meshdiag`: RLOC16 of the router whose child table lists the node (`null` when the node is a router itself, or not found by `meshdiag`) |
| `alive` | `true` only if the ping or the network diagnostic answered (and the node that answers has the `ext` asked); `false` when the RLOC16 is known (even from a table) but nobody answered, or another node answers there; `null` when there is no RLOC16 (not found, request refused) |
| `search` | the steps of the search for the RLOC16, in order: `[{"step": "child table", "result": "found", "rows": 4, "detail": "0xb45c"}, …]`; `step` is `mleid`, `child table`, `neighbor table`, `router table`, `meshdiag help`, `meshdiag`, `meshdiag topology` or `meshdiag childtable 0x…`; `result` is `found`, `not_found`, `no_answer`, `ext_differs`, `error`, `not_supported`, `too_soon` or `stopped`; `rows`: lines read (tables, topology: routers); `detail`: RLOC16, extended address received, error or reason. Empty when `rloc16` was given |
| `rloc_address` | the RLOC address that was asked (`null` if it could not be built) |
| `ext` | extended address the node answered with, lowercase (`null`: no answer) |
| `ping` | `{"ok": bool, "rtt_ms": float or null}`; `null` when no ping was asked |
| `addresses` | every IPv6 address of the node |
| `omr_addresses` | those in the anchored prefix (`wanted`) or in the prefix the network favors (`favored`) |
| `other_prefix_addresses` | global or local (ULA) addresses that are neither mesh-local, nor link-local, nor in the current prefixes: an old OMR prefix the node kept |
| `error` | `null`, or why it failed: `busy`, `too soon`, `not found`, `invalid rloc16: …` / `invalid ext: …` / `invalid mleid: …`, `rloc16, ext or mleid needed`, `mleid is not in the mesh-local prefix`, `timeout (15 s)`, `no answer to the network diagnostic`, a different `ext` than asked, an `ot-ctl` or Docker error |
| `at` | time of the answer (ISO 8601 with the time zone) |

Limits: one diagnostic at a time (`busy`, also while a meshdiag scan runs), at
most one per node every 10 s (`too soon`; the node is its `rloc16`, else its
`ext`, else its `mleid`), 15 s at most each (a search with the meshdiag step:
up to 15 + 90 + 15 s). A request without a usable `id` gets no answer
(only a line in the log). Each diagnostic is one line in the log. A node that
does not answer the ping may still answer the network diagnostic (it is reached
by its RLOC address, which does not depend on the OMR prefix).

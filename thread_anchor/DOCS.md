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

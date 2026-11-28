# Thread Anchor

Keeps the Thread network of the house on one OMR prefix, so that devices are
less likely to move to a new address when another border router (Google TV,
Nest Hub, HomePod…) changes its prefix.

> **Beta.** The app reaches the OpenThread border router through the Docker
> API: **Protection mode** must be turned off in its Info tab.

## The problem

Each border router of a Thread network publishes an **OMR prefix** (off-mesh
routable): the address prefix the devices use to be reached from the home
network. A prefix a border router generates itself has a **low** preference.
The network uses the favored one — the highest preference, then the lowest
number — and when a border router replaces its prefix, every device moves to the
new one. Matter controllers then lose the devices until they are found again:
they show as unavailable, sometimes for a long time.

## What the app does

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

1. The **OpenThread Border Router** app runs, on the Thread network of the
   house (Settings → Thread: it is in the same network as your other border
   routers).
2. Install Thread Anchor, turn **Protection mode** off, start it **without**
   `omr_prefix`: it only watches. The entity *Favored OMR prefix* (and Mesh
   Guardian) shows the prefix the network uses now, e.g. `fd00:aaaa:bbbb:1::/64`.
3. Put **that** prefix in `omr_prefix` and restart the app. The log says
   `OMR prefix … set on the border router (it was: auto)`, then
   `The network favors … (high)`. The devices keep their addresses: nothing was
   renumbered.

| Option | |
|---|---|
| `omr_prefix` | local `/64` prefix to anchor (ULA, in `fc00::/7`: it starts with `fc` or `fd`); empty: watch only. Any other prefix is refused and nothing is set |
| `omr_preference` | `high` (default), `med` or `low` |
| `otbr_addon` | slug of the border router app (`core_openthread_border_router`) |
| `check_interval` | seconds between two readings (30) |
| `language` | `en` or `fr` |
| `debug` | more detail in the log (`false`) |

## Good to know

- If the Home Assistant border router stops, the other border routers publish
  their own prefixes again, and the network moves until it is back. Thread
  Anchor sets the anchor again as soon as it restarts.
- To stop: empty `omr_prefix` and restart the border router app (or run
  `ot-ctl br omrconfig auto` in it). Its own low-preference prefix then competes
  with the others again.
- Only one tool should set the prefix: if you used the `omr_prefix` option of
  USB/IP Link 0.2.x, empty it there.
- The Docker API gives the app control over every container: that is why
  Home Assistant asks for Protection mode to be off. Thread Anchor only reads
  the state of the border router container and runs `ot-ctl br omrconfig` /
  `ot-ctl br omrprefix` in it.

## Entities and Mesh Guardian

With MQTT (state on `thread_anchor/state`, retained):

- **binary_sensor** *OMR prefix anchored*: on when the border router holds the
  prefix of the options; attributes: mode, current prefix and preference,
  prefix favored by the network, number of times it was set, last error.
- **sensor** *Favored OMR prefix*: the prefix the whole network uses.
- **sensor** *Thread role*: the role of the border router of Home Assistant in
  the Thread network (`disabled`, `detached`, `child`, `router` or `leader`),
  with the number of routers it sees in the attribute `thread_routers`. Shown
  only: Thread Anchor never tries to change the role of the border router.

Without a broker at start, the app works all the same and looks for it again
every 60 s. `thread_anchor/state/available` says `online` / `offline`: `offline`
is published when the app stops; the retained state is then left as it was.

**Mesh Guardian** reads this state: it says in *To do* when the anchor is no
longer in place, and in its log when it is lost and back.

## MQTT reference

Also over MQTT: link statistics hour by hour (7 sensors of the *Thread Anchor* device), the nodes the app
has learned about, and two tests run only on request (diagnostic of a node, latency of the radio chip).
Topics and fields: [API.md](https://github.com/Pintjes/ha-addons/blob/main/thread_anchor/API.md).

# Changelog

## [0.4.7] - 2026-11-28

### Docs

- License stated the same way everywhere: versions 0.1.0–0.2.0 were published under MIT and versions
  0.2.1–0.4.2 under GPL-3.0-or-later (the presentation page and the 0.4.3 entry below only said GPL);
  license badge in English.
- The four kernel rights the app asks for are listed (`NET_ADMIN`, `SYS_ADMIN`, `SYS_MODULE`, `SYS_RAWIO`),
  with the `manager` role; the AppArmor profile is said to be in complain mode, so not a protection yet.
- `server_port` and `debug` added to the table of options; version numbers taken out of the documentation
  (this changelog keeps them); links to the other apps made absolute; calmer presentation page.
- No change to the behaviour.

## [0.4.6] - 2026-11-27

### Fixed

- Device attached again right after a restart of Windows (virtual machine saved, then restored): the serial port
  was there, but the radio never answered, and the OpenThread border router hung on it for good, in the kernel:
  it could not even be stopped, only a restart of the system of Home Assistant freed it. Its USB transfers waited
  for the server to cancel them, which it never did. Three changes:
  - a server back after a silence or a pause must answer for **30 s** before anything is attached, so that
    usbipd-win and the device have settled;
  - after the restart of an OpenThread border router of `restart_addons`, the app checks that its otbr-agent
    answers on its REST API (port 8081, network only: the serial port is never opened here) within 90 s;
  - if it does not, the device is detached, which closes the USB/IP connection and gives the waiting transfers
    back, so that the border router can end; it is attached again after 30 s, then 60 s, 120 s and 300 s at
    the next tries, the border router restarted each time; after 4 tries it is given up and said in the log.
    The check acts only once the REST API has answered at least once since the start of the app (else a stuck
    radio could not be told from an API out of reach: it is said once and nothing is done), and only on a border
    router in the *started* state.
- A detach that does not end (kernel stuck) no longer blocks the checks: left running after 20 s, and said.

## [0.4.5] - 2026-11-27

### Changed

- Wording: Home Assistant now says "app" instead of "add-on" (**Settings → Apps**): the presentation page,
  the documentation, the option labels (English and French) and the messages of the log follow. No change to
  the behaviour; names of options and technical names are unchanged.

## [0.4.4] - 2026-11-26

### Fixed

- An attachment the server accepts but whose enumeration hangs (device not ready on the server just after its
  restart) was said "attached", though no serial port ever appeared; `usbip port` does not show such a port,
  so the add-on then said "link lost" and attached again on another port, until the server answered
  `Device busy (exported)` for good. An attachment now counts only once the kernel has finished the
  enumeration **and**, for a serial device (CDC ACM), its tty exists, within 15 s; else that port is detached
  and the attachment tried again at the next check.
- A port taken by a device that never appeared (state of `/sys/devices/platform/vhci_hcd.0/status`) is
  detached, at the start of the add-on and before any attachment.
- The restart of the add-ons of `restart_addons` waits for that verification; a refusal with HTTP 400 (the
  Supervisor does not see the serial port yet) is tried again too, every 15 s for 5 min.

## [0.4.3] - 2026-11-22

### Changed

- License changed: proprietary from this version (© 2026 Pintjes, all rights reserved, end user license
  agreement in `LICENSE`, French text and English translation); earlier versions keep their license
  (0.1.0–0.2.0: MIT; 0.2.1–0.4.2: GPL-3.0-or-later). No change to the behaviour of the add-on.

## [0.4.2] - 2026-11-20

### Fixed

- Attached device, server silent for a short while (virtual machine resumed, usbipd restarted):
  the kernel may never see the link die, the port stays "in use" on a dead connection and the add-on,
  which only looked at the port, did nothing, silently. Now, when the server answers again after
  **any** silence, even a single check, the device is detached and attached again, and the add-ons of
  `restart_addons` are restarted (before, a detach only happened after three silent checks, 30 s).
- Machine paused then resumed (Hyper-V "Save" when Windows restarts: the virtual machine is saved, then
  restored a minute later, without a boot): the link is dead and nothing tells the kernel. The clock gives
  it away: the wall clock jumps forward by the length of the pause while the monotonic one stops. A jump
  of more than 20 s, seen within 2 s, detaches the device **at once**, the server answering or not (this
  frees whatever is stuck on the dead device, the border router included), attaches it again as soon as
  the server answers, and restarts the add-ons of `restart_addons`. A clock set back by more than 20 s
  counts too.
- An add-on restart the Supervisor refuses (HTTP 503 while it starts, at the boot of Home Assistant) was
  lost, the border router staying started without its radio: it is tried again every 15 s for 5 min, said
  in the log, then given up said too (with the hint that it may be stuck on the dead device: stop it,
  then start it by hand). A 4xx error is not retried.
- No MQTT broker found at the start (Supervisor not ready): the add-on went on without MQTT until its next
  restart. The broker is now looked for again every 30 s, in the background, until found.

### Added

- Clearer log: `already attached (port, server, bus id), taken as it is` at the start of the add-on,
  `answers again after a silence, the device is detached and attached again`, `cannot detach port`
  (said once, tried again at each check), `bus id changed on the server` (device plugged into another USB
  port), `restarted after N tries`.

## [0.4.1] - 2026-11-17

### Added

- *Link latency max* and *Link latency p95* sensors (diagnostic, `state_class: measurement`):
  the worst value and the 95th percentile (nearest rank) of the last 5 minutes of checks, next
  to the average. The average hides the peaks and the max was only an attribute, which Home
  Assistant does not keep in its long-term statistics: these two stay for months.
  `latency_p95_ms` added to `usbip_link/state` (`latency_max_ms` was already there).

## [0.4.0] - 2026-11-17

### Changed

- `full_access` removed: the add-on opens no device node, it only needs `SYS_ADMIN` (remount
  `/sys` read-write, attach through sysfs) and `SYS_MODULE` (`modprobe vhci-hcd`), which stay.
  **Protection mode can now stay on.** An add-on installed before keeps the Protection mode it
  had (off) until it is turned on in the Info tab.
- A dedicated AppArmor profile, `apparmor.txt`, replaces `apparmor: false`. It starts in
  *complain* mode (a denied access is only logged, nothing is blocked), so that a gap in the
  profile cannot cut the radio; it will be enforced after a run on the real Home Assistant.
  Security rating shown by Home Assistant: 1 → 3 (the Supervisor forces 1 with `full_access`).
- `NET_ADMIN` and `SYS_RAWIO` are kept for now (probably unused: to try without, later; the
  rating does not change).

### Added

- `Cannot remount /sys writable, attaching will fail (AppArmor profile?)` warning in the log
  when the remount of `/sys` is refused (it used to be ignored silently).

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

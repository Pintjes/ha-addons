# USB/IP Link

Uses the USB devices of another computer as if they were plugged into Home Assistant, and
**keeps them attached**: when that computer restarts (a Windows update at night…), the
device is attached again by itself as soon as it is back. Made for Home Assistant in a
virtual machine that has no USB (Hyper-V on Windows 11 Pro), with a radio such as the
Home Assistant Connect ZBT-2 plugged into the host.

> **Beta.** The add-on runs privileged (it loads a kernel module and writes to `/sys`):
> **Protection mode** must be turned off in its Info tab.

## How it works

The computer the device is plugged into shares it with **USB/IP** (TCP port 3240). The
add-on loads the `vhci-hcd` module of Home Assistant OS (a virtual USB controller) and
attaches the device to it: Home Assistant then sees a USB device, `/dev/ttyACM0` and
`/dev/serial/by-id/…` included, and the other add-ons use it as usual.

Every `check_interval` seconds the add-on checks the link:

- not attached → attached as soon as the server answers;
- server silent three checks in a row → the device is detached (a dead link would keep the
  port busy for a long time) and attached again when the server is back;
- attached again after a loss → the add-ons of `restart_addons` are restarted (the
  OpenThread border router opens its radio only when it starts).

A restart of the add-on itself does not detach anything.

## 1. Windows: share the device (usbipd-win)

In a PowerShell **as administrator**, on the computer the device is plugged into:

```powershell
winget install --exact dorssel.usbipd-win
usbipd list
```

Note the `BUSID` (e.g. `2-3`) and the `VID:PID` (e.g. `303a:831a`) of the device, then:

```powershell
usbipd bind --busid 2-3
New-NetFirewallRule -DisplayName "USB/IP (Home Assistant)" -Direction Inbound -Protocol TCP -LocalPort 3240 -RemoteAddress <IP of Home Assistant> -Action Allow
```

`bind` is kept across restarts and the usbipd service starts with Windows: nothing else to
do after a restart. Limit the firewall rule to the address of Home Assistant: USB/IP has no
password.

## 2. Home Assistant: the add-on

| Option | |
|---|---|
| `server` | address of the computer that shares the device |
| `devices` | one entry per device: `name`, and `hardware_id` (`VID:PID`, recommended: the USB port can change) or `bus_id` |
| `check_interval` | seconds between two checks (10) |
| `restart_addons` | add-ons restarted after the device is attached again, e.g. `core_openthread_border_router` |
| `omr_prefix` | optional: `/64` OMR prefix the OpenThread border router is kept on (see below) |
| `omr_preference` | `high` (default) or `med` |
| `otbr_addon` | border router add-on, if not `core_openthread_border_router` |
| `language` | `en` or `fr` |

Turn **Protection mode** off, start the add-on: the log says `ZBT-2: attached (… 2-3)`.

## 3. The radio: OpenThread Border Router

In the OpenThread Border Router add-on, choose the device (`/dev/serial/by-id/…ZBT-2…`),
baud rate **460800**, **hardware flow control** on (ZBT-2 with the OpenThread firmware).
To join an existing Thread network (Google, Apple…) instead of creating a new one, share
its credentials first (Home Assistant companion app → Troubleshooting → Sync Thread
credentials), then **Settings → Thread → join**.

## 4. Optional: a stable OMR prefix

Every Thread device has an address in the OMR (off-mesh routable) prefix of the network. Each
border router generates one with a **low** preference and the network uses the favored one;
some border routers (Google TV…) replace theirs now and then, and the whole network then moves
to another prefix: Matter devices drop out until they are found again.

With `omr_prefix`, the add-on keeps the OpenThread border router on that prefix with the
preference `omr_preference` (`high` by default): it is favored over the low prefixes of the
other border routers, which withdraw theirs. Take the **current** OMR prefix of the network
(Mesh Guardian shows it): nothing changes for the devices when it is set.

OpenThread keeps this setting in memory only: the add-on reads it every 30 s and sets it again
after each start of the border router (`ot-ctl br omrconfig custom <prefix> <preference>`,
through the Docker API: Protection mode off). If the border router stops, the others publish
their own prefixes again until it is back. Entity: **binary_sensor** *OMR prefix* (on = in
place). Leave `omr_prefix` empty to stop: the border router goes back to its own prefix at
its next start (or `ot-ctl br omrconfig auto`).

## Entities and Mesh Guardian

With MQTT, one entity per device: **binary_sensor** *connectivity* (on = attached), with
the server, the bus id, the number of attachments and the last error as attributes. The
state is published on `usbip_link/state`; **Mesh Guardian** reads it and says in *To do*
when the radio of a border router is cut off, and in its log when it comes back.

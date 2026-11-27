# USB/IP Link

Uses the USB devices of another computer as if they were plugged into Home Assistant, and
**keeps them attached**: when that computer restarts (a Windows update at night…), the
device is attached again by itself as soon as it is back. Made for Home Assistant in a
virtual machine that has no USB (Hyper-V on Windows 11 Pro), with a radio such as the
Home Assistant Connect ZBT-2 plugged into the host.

> **Beta.** The app loads a kernel module and writes to `/sys`: it keeps the `SYS_ADMIN` and
> `SYS_MODULE` rights, but no longer asks for full access to the devices, so **Protection mode
> can stay on** (0.4.0). It has its own AppArmor profile, `apparmor.txt`, in *complain* mode for
> now: it only logs what it would refuse, nothing is blocked.

## How it works

The computer the device is plugged into shares it with **USB/IP** (TCP port 3240). The
app loads the `vhci-hcd` module of Home Assistant OS (a virtual USB controller) and
attaches the device to it: Home Assistant then sees a USB device, `/dev/ttyACM0` and
`/dev/serial/by-id/…` included, and the other apps use it as usual.

Every `check_interval` seconds the app checks the link:

- not attached → attached as soon as the server answers;
- an attachment counts only once the device is really there (and its serial port, for a CDC ACM device such
  as the ZBT-2), within 15 s; else its port is detached and it is tried again. A port taken by a device that
  never appeared (`usbip port` does not show it, and the server then answers `Device busy (exported)`) is
  detached too, at the start of the app and before any attachment (0.4.4);
- server silent three checks in a row → the device is detached (a dead link would keep the
  port busy for a long time) and attached again when the server is back;
- server silent for less than that (a single check is enough), then back → the device is detached and
  attached again all the same: after a virtual machine pause or a restart of usbipd the kernel may
  never notice that the link is dead (0.4.2);
- Home Assistant's own clock jumps by more than 20 seconds (the virtual machine was paused, as Hyper-V
  does when Windows restarts with "Save": it is saved, then restored a minute later) → the device is
  detached at once, without waiting for the server, and attached again when it answers, then the apps
  of `restart_addons` are restarted (0.4.2);
- server back after a silence or a pause → nothing is attached before it has answered for 30 s: right after
  Windows starts, a device attached too early may never answer (0.4.6);
- attached again after a loss → the apps of `restart_addons` are restarted (the
  OpenThread border router opens its radio only when it starts);
- an OpenThread border router of `restart_addons` just restarted → its otbr-agent must answer on its REST API
  (port 8081) within 90 s. Else its radio hangs: the device is detached, which frees the border router stuck on
  it, and attached again after 30 s, then 60, 120 and 300 s; after 4 tries the log says to restart the system
  of Home Assistant. Nothing is done as long as that API has never answered since the start of the app (0.4.6);
- attached for the first time (start of Home Assistant) → those of them that already run,
  or are in error, are restarted once: they may have started before the device was there.

A restart of the app itself does not detach anything, and restarts nothing: a device
found attached is taken as it is (the log says so), and its state is published only once checked.

A restart that Home Assistant refuses (503 while it starts, or 400 while it does not see the serial port
yet) is tried again every 15 seconds for 5 minutes, and the log says so. Without a MQTT broker at the start, the app keeps
looking for it every 30 seconds.

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

> **The installer opens the port too.** usbipd-win adds its own inbound rule, `usbipd`, for
> the whole local subnet. Windows firewall rules that allow add up: while it is on, any
> computer of the network can attach the device, whatever the rule above says. Disable it,
> or limit it to the address of Home Assistant:
>
> ```powershell
> Get-NetFirewallRule -DisplayName "usbipd" | Set-NetFirewallRule -RemoteAddress <IP of Home Assistant>
> ```

## 2. Home Assistant: the app

| Option | |
|---|---|
| `server` | address (or name) of the computer that shares the device |
| `devices` | one entry per device: `name`, and `hardware_id` (`VID:PID`, recommended: the USB port can change) or `bus_id` |
| `check_interval` | seconds between two checks (10) |
| `restart_addons` | apps restarted after the device is attached again, e.g. `core_openthread_border_router` |
| `language` | `en` or `fr` |

`omr_prefix`, `omr_preference` and `otbr_addon` of 0.2.x are no longer used: see below.

Start the app: the log says `ZBT-2: attached (… 2-3)`. If it says `Cannot remount /sys
writable`, turn **Protection mode** off in the Info tab and start it again, then tell us.
An app installed before 0.4.0 keeps the Protection mode it had (off): turn it on in the Info
tab when you want to try it.

## 3. The radio: OpenThread Border Router

In the OpenThread Border Router app, choose the device (`/dev/serial/by-id/…ZBT-2…`),
baud rate **460800**, **hardware flow control** on (ZBT-2 with the OpenThread firmware).
To join an existing Thread network (Google, Apple…) instead of creating a new one, share
its credentials first (Home Assistant companion app → Troubleshooting → Sync Thread
credentials), then **Settings → Thread → join**.

## 4. A stable OMR prefix: Thread Anchor

The fixed OMR prefix of 0.2.x (`omr_prefix`) moved to its own app,
[Thread Anchor](../thread_anchor/): it serves any OpenThread border router, with or without
USB/IP. Coming from 0.2.x: set the same prefix in Thread Anchor, check that its *OMR prefix
anchored* entity is on, then empty `omr_prefix` here (a filled one only gives a warning in the
log now). USB/IP Link no longer needs the Docker API.

## Entities and Mesh Guardian

With MQTT:

- one entity per device: **binary_sensor** *connectivity* (on = attached), with the server,
  the bus id, the number of attachments, the last error and the latency as attributes;
- **sensor** *Link latency*: time the server takes to answer (TCP connection to its USB/IP
  port, every check), averaged over the last 5 minutes; the last and the worst values as
  attributes. A slow or irregular link shows there before the radio suffers. Published at
  most every minute; unknown while the server is silent.
- **sensors** *Link latency max* and *Link latency p95* (diagnostic): the worst value and the
  95th percentile of the same 5-minute window. The average hides the peaks, and these two are
  kept in the long-term statistics of Home Assistant (the attribute of the average is not).
  Note that this is the time to open a TCP connection to the server, not the round trip of the
  USB data through usbipd.

The state is published on `usbip_link/state` (`latency_ms`, `latency_avg_ms`,
`latency_max_ms`, `latency_p95_ms`); **Mesh Guardian** reads it and says in *To do* when the radio of a border
router is cut off, and in its log when it comes back.

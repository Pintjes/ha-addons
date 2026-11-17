# USB/IP Link

Uses the USB devices of another computer as if they were plugged into Home Assistant, and
**keeps them attached**: when that computer restarts (a Windows update at night…), the
device is attached again by itself as soon as it is back. Made for Home Assistant in a
virtual machine that has no USB (Hyper-V on Windows 11 Pro), with a radio such as the
Home Assistant Connect ZBT-2 plugged into the host.

> **Beta.** The add-on loads a kernel module and writes to `/sys`: it keeps the `SYS_ADMIN` and
> `SYS_MODULE` rights, but no longer asks for full access to the devices, so **Protection mode
> can stay on** (0.4.0). It has its own AppArmor profile, `apparmor.txt`, in *complain* mode for
> now: it only logs what it would refuse, nothing is blocked.

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
  OpenThread border router opens its radio only when it starts);
- attached for the first time (start of Home Assistant) → those of them that already run,
  or are in error, are restarted once: they may have started before the device was there.

A restart of the add-on itself does not detach anything, and restarts nothing: a device
found attached is taken as it is, and its state is published only once checked.

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

## 2. Home Assistant: the add-on

| Option | |
|---|---|
| `server` | address (or name) of the computer that shares the device |
| `devices` | one entry per device: `name`, and `hardware_id` (`VID:PID`, recommended: the USB port can change) or `bus_id` |
| `check_interval` | seconds between two checks (10) |
| `restart_addons` | add-ons restarted after the device is attached again, e.g. `core_openthread_border_router` |
| `language` | `en` or `fr` |

`omr_prefix`, `omr_preference` and `otbr_addon` of 0.2.x are no longer used: see below.

Start the add-on: the log says `ZBT-2: attached (… 2-3)`. If it says `Cannot remount /sys
writable`, turn **Protection mode** off in the Info tab and start it again, then tell us.
An add-on installed before 0.4.0 keeps the Protection mode it had (off): turn it on in the Info
tab when you want to try it.

## 3. The radio: OpenThread Border Router

In the OpenThread Border Router add-on, choose the device (`/dev/serial/by-id/…ZBT-2…`),
baud rate **460800**, **hardware flow control** on (ZBT-2 with the OpenThread firmware).
To join an existing Thread network (Google, Apple…) instead of creating a new one, share
its credentials first (Home Assistant companion app → Troubleshooting → Sync Thread
credentials), then **Settings → Thread → join**.

## 4. A stable OMR prefix: Thread Anchor

The fixed OMR prefix of 0.2.x (`omr_prefix`) moved to its own add-on,
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

The state is published on `usbip_link/state` (`latency_ms`, `latency_avg_ms`,
`latency_max_ms`); **Mesh Guardian** reads it and says in *To do* when the radio of a border
router is cut off, and in its log when it comes back.

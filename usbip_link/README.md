<p align="center">
  <img src="logo.png" alt="USB/IP Link" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-app-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant app"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fusbip_link%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/usbip_link/LICENSE"><img src="https://img.shields.io/badge/license-proprietary-lightgrey" alt="License: proprietary"></a>
</p>

> **Beta.** The app loads a kernel module and attaches devices through `/sys`. It asks for the
> `NET_ADMIN`, `SYS_ADMIN`, `SYS_MODULE` and `SYS_RAWIO` rights, but not for full access to the
> devices, so Protection mode can stay on. Its AppArmor profile is in complain mode for now: it
> logs what it would refuse and blocks nothing.

**USB/IP Link plugs the USB devices of another computer into Home Assistant,
and keeps them plugged in.** Made for Home Assistant in a virtual machine
without USB (Hyper-V on Windows), with a radio such as the Home Assistant
Connect ZBT-2 plugged into the host and shared with usbipd-win.

## Why this app

**1. Re-attaches the device after the host restarts.**
A USB/IP client that attaches once at start stops working when the computer
that shares the device restarts: the link is dead and stays so until someone
restarts things by hand. USB/IP Link keeps checking the link: the dead link is
freed, the device is attached again once the computer answers, then the
OpenThread border router is restarted so that it opens its radio again.

**2. Found by what it is, not where it is.**
The device is looked up by its `VID:PID`: another USB port on the host, another
bus id, nothing to change.

**3. A link you can watch.**
The time the host takes to answer is measured at every check and published as
a *Link latency* entity: a slow or irregular link shows there before the radio
suffers.

## Also

- For Home Assistant the device is a local one: `/dev/serial/by-id/…`, usable
  by any app or integration.
- One entity per device (attached or not, number of attachments, last error)
  and one for the latency of the link, on MQTT.
- A Thread network that keeps changing its OMR prefix (Matter devices dropping
  out)? That is the job of [Thread Anchor](https://github.com/Pintjes/ha-addons/tree/main/thread_anchor),
  which works with any OpenThread border router, through USB/IP Link or not.
- Read by [Mesh Guardian](https://github.com/Pintjes/ha-addons/tree/main/mesh_guardian), which says
  when the radio of a border router is cut off.
- A restart of the app detaches nothing.

Full documentation: see the Documentation tab of the app, or
[DOCS.md](https://github.com/Pintjes/ha-addons/blob/main/usbip_link/DOCS.md).

## License

Proprietary, © 2026 Pintjes: see the [EULA](https://github.com/Pintjes/ha-addons/blob/main/usbip_link/LICENSE)
(French text prevails, English translation included). Versions 0.1.0–0.2.0 were published under MIT
and versions 0.2.1–0.4.2 under GPL-3.0-or-later; they keep that license. Third-party components keep
their own licenses.

The idea comes from [rogerfar/ha-usbip-client](https://github.com/rogerfar/ha-usbip-client);
USB/IP Link is written anew and uses none of its code.

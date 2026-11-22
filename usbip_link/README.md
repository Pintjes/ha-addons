<p align="center">
  <img src="logo.png" alt="USB/IP Link" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fusbip_link%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/usbip_link/LICENSE"><img src="https://img.shields.io/badge/licence-propri%C3%A9taire-lightgrey" alt="Licence : propriétaire"></a>
</p>

> **Beta.** The add-on loads a kernel module and attaches devices (`SYS_ADMIN`, `SYS_MODULE`),
> with its own AppArmor profile and without full access to the devices: **Protection mode can
> stay on** (0.4.0).

**USB/IP Link plugs the USB devices of another computer into Home Assistant,
and keeps them plugged in.** Made for Home Assistant in a virtual machine
without USB (Hyper-V on Windows), with a radio such as the Home Assistant
Connect ZBT-2 plugged into the host and shared with usbipd-win.

## Why this add-on

**1. You don't wake up without a radio.**
A USB/IP client that attaches once at start works until the computer that
shares the device restarts (a Windows update at night): the link is dead, the
radio is gone, and nothing brings it back until someone restarts things by
hand. USB/IP Link keeps checking: the dead link is freed, the device is
attached again as soon as the computer answers, then the OpenThread border
router is restarted to open its radio again. No click in the morning.

**2. Found by what it is, not where it is.**
The device is looked up by its `VID:PID`: another USB port on the host, another
bus id, nothing to change.

**3. A link you can watch.**
The time the host takes to answer is measured at every check and published as
a *Link latency* entity: a slow or irregular link shows there before the radio
suffers.

## Also

- For Home Assistant the device is a local one: `/dev/serial/by-id/…`, usable
  by any add-on or integration.
- One entity per device (attached or not, number of attachments, last error)
  and one for the latency of the link, on MQTT.
- A Thread network that keeps changing its OMR prefix (Matter devices dropping
  out)? That is the job of [Thread Anchor](../thread_anchor/), which works with
  any OpenThread border router, through USB/IP Link or not.
- Read by [Mesh Guardian](../mesh_guardian/), which says when the radio of a
  border router is cut off.
- A restart of the add-on detaches nothing.

Full documentation: [DOCS.md](DOCS.md).

## License

Proprietary, © 2026 Pintjes. All rights reserved: see the [license agreement](LICENSE)
(French text, English translation below). Versions before 0.4.3 stay under GPL-3.0-or-later.
Third-party components keep their own licenses.

The idea comes from [rogerfar/ha-usbip-client](https://github.com/rogerfar/ha-usbip-client);
USB/IP Link is written anew and uses none of its code.

<p align="center">
  <img src="logo.png" alt="USB/IP Link" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fusbip_link%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/usbip_link/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

> **Beta.** The add-on runs privileged (it loads a kernel module and attaches
> devices): **Protection mode** must be turned off.

**USB/IP Link plugs the USB devices of another computer into Home Assistant,
and keeps them plugged in.** Made for Home Assistant in a virtual machine
without USB (Hyper-V on Windows), with a radio such as the Home Assistant
Connect ZBT-2 plugged into the host and shared with usbipd-win.

## Why this add-on

**1. The radio comes back by itself.**
When the computer that shares the device restarts (a Windows update at night),
the dead link is freed and the device is attached again as soon as the computer
answers, then the OpenThread border router is restarted to open its radio
again. No click in the morning.

**2. Found by what it is, not where it is.**
The device is looked up by its `VID:PID`: another USB port on the host, another
bus id, nothing to change.

**3. A Thread network that stops moving.**
Optional: the OpenThread border router is kept on a fixed OMR prefix, favored
over the ones other border routers (Google TV…) keep replacing. The devices
keep their addresses; Matter stops losing them.

## Also

- For Home Assistant the device is a local one: `/dev/serial/by-id/…`, usable
  by any add-on or integration.
- One entity per device (attached or not, number of attachments, last error)
  and one for the OMR prefix, on MQTT.
- Read by [Mesh Guardian](../mesh_guardian/), which says when the radio of a
  border router is cut off.
- A restart of the add-on detaches nothing.

Full documentation: [DOCS.md](DOCS.md).

## License

[GPL-3.0](LICENSE) © Pintjes

The idea comes from [rogerfar/ha-usbip-client](https://github.com/rogerfar/ha-usbip-client);
USB/IP Link is written anew and uses none of its code.

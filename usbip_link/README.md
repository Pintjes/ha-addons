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

**And it can stop your Thread network from changing its OMR prefix** — the
reason Matter devices drop out every day in homes with Google or Apple border
routers.

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

**3. A Thread network that stops moving.**
See below.

## A stable OMR prefix for Thread

Every Thread device has an address in the OMR prefix of the network, chosen
among the prefixes the border routers publish. Some border routers (Google TV,
Nest Hub…) replace theirs now and then: the whole network moves to another
prefix, and Matter devices become unavailable until they are found again at
their new address. On the network this add-on was made for, that was **7
different OMR prefixes in 3 days**, with devices dropping out each time.

With `omr_prefix`, USB/IP Link keeps the Home Assistant OpenThread border
router on one prefix with a **high** preference. Every border router favors it
over the low-preference prefixes they generate themselves, and withdraws its
own:

- **nothing to renumber:** take the prefix the network uses now (Mesh Guardian
  shows it), the devices keep their addresses when it is set;
- **kept in place:** OpenThread forgets this setting at each restart, so the
  add-on reads it every 30 s and sets it again (`ot-ctl br omrconfig`);
- **visible:** an *OMR prefix* entity says whether it is in place.

It works with any radio of the OpenThread Border Router add-on, attached through
USB/IP or not. The price: the add-on needs the Docker API to reach the border
router, so **Protection mode** must be off. If the Home Assistant border router
stops, the others publish their own prefixes again until it is back.

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

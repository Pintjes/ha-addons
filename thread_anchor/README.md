<p align="center">
  <img src="logo.png" alt="Thread Anchor" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fthread_anchor%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/thread_anchor/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

> **Beta.** Thread Anchor reaches the OpenThread border router through the
> Docker API: **Protection mode** must be turned off.

**Thread Anchor keeps your Thread network on one OMR prefix.** The OpenThread
border router of Home Assistant anchors it, so the Google, Apple or Amazon
border routers of the house stop moving it — and your Matter devices stop
dropping out.

## Why this add-on

**1. Matter devices that drop out every day.**
Every Thread device has an address in the OMR prefix of the network, chosen
among the prefixes the border routers publish. Some border routers (Google TV,
Nest Hub…) replace theirs now and then: the whole network moves to another
prefix, and Matter devices become unavailable until they are found again at
their new address. On the network this add-on was made for, that was **7
different OMR prefixes in 3 days**.

**2. One prefix, favored by every border router.**
Thread Anchor gives the Home Assistant border router a prefix with a **high**
preference. Every border router favors it over the low-preference prefixes
they generate themselves, and withdraws its own.

**3. Nothing to renumber.**
Anchor the prefix the network uses now: the devices keep their addresses the
moment it is set. The *Favored OMR prefix* entity (or Mesh Guardian) shows it.

## Also

- OpenThread forgets the setting at each restart: Thread Anchor sees a restart
  of the border router at once and sets it again, and reads it every 30 s.
- It reads the prefix the whole network favors: you see the other border
  routers follow.
- Entities on MQTT: *OMR prefix anchored* (on / off, with the reason) and
  *Favored OMR prefix*. Read by [Mesh Guardian](../mesh_guardian/).
- Without a prefix set, it only watches: a safe way to look first.
- Works with any radio of the OpenThread Border Router add-on (ZBT-1, ZBT-2,
  Yellow…), plugged in directly or through [USB/IP Link](../usbip_link/).

Full documentation: [DOCS.md](DOCS.md).

## License

[GPL-3.0](LICENSE) © Pintjes

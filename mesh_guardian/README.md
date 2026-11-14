<p align="center">
  <img src="logo.png" alt="Mesh Guardian" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fmesh_guardian%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/mesh_guardian/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

**Mesh Guardian keeps your Thread / Matter devices online**, shows you every
node of your mesh in one table, and tells you what to fix — in plain language.


> **Requirements:** Home Assistant OS or Supervised, the Matter integration,
> an **MQTT broker** (Mosquitto broker add-on) and the **MQTT** integration.

## Why this add-on

**1. Lost nodes come back on their own.**
Thread devices rarely die: they get *lost*. When a border router restarts or
hands over the leader role, the network prefix can change; the device still
works in the mesh, but Home Assistant shows it *unavailable* until you restart
something. Mesh Guardian notices it and pings the node through the Matter
Server, which finds it again — within minutes, without restarting
anything. It holds back during Home Assistant restarts and Thread
storms, when pinging would only add traffic.

**2. Your whole mesh in one table.**
A **Mesh Guardian** page in the sidebar lists every Thread node: role, parent
(or best link for a router) with its signal, neighbors, detaches, outages,
reboots, battery level, last contact and a one-line advice such as *Remove the
battery 10s*. Sort by any column, filter, pick the columns. Values are live,
read from the Matter Server without any radio traffic: unplug a device, plug it
back, and watch it pick its new parent.

**3. Know what your border routers really do.**
Any brand — Google, Apple, Amazon, Home Assistant Connect… Mesh Guardian
follows each border router (online, role, partition, network prefix), the
leader, network splits and Thread storms, and recognizes when Home Assistant
has lost its route to the Thread network (border router on another VLAN,
IPv6 routing blocked).

**4. Two buttons you will not find elsewhere.**
**Ping all nodes** checks every node at once, battery-powered ones included.
**Rename nodes** writes the names you gave your devices in Home Assistant into
the Matter nodes themselves, so tools that read the node show the same names —
only when you press it, never automatically.

## Also

- Everything as Home Assistant entities (MQTT): border routers, leader,
  partitions, unavailable nodes, recoveries, weak links, storms.
- A readable event log (also kept in a file and sent over MQTT).
- Safe: it never controls a device. It listens to mDNS, reads Home Assistant,
  and asks the Matter Server for node data, pings and neighbor tables. The only
  thing it ever writes is the node name, when you press **Rename nodes**.
- Local only: no cloud, no telemetry.
- English and French.

**Requirements:** Home Assistant OS or Supervised, the **Matter** integration
(Matter Server add-on), the **Mosquitto broker** add-on and the **MQTT**
integration. See the **Documentation** tab for installation, options and
entities.

## Contributing

Bug reports and ideas are welcome: [open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).
Please include the add-on version and the relevant lines of the log.

## License

[GPL-3.0](https://github.com/Pintjes/ha-addons/blob/main/mesh_guardian/LICENSE) © Pintjes

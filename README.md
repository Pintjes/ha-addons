# Home Assistant add-ons by Pintjes

[![Add repository to my Home Assistant][repo-badge]][repo-link]
[![CI][ci-badge]][ci-link]
[![Licence : propriétaire, sauf Side Door][license-badge]][license-link]
[![Side Door: GPL-3.0][sd-license-badge]][sd-license-link]

Add-on repository for [Home Assistant](https://www.home-assistant.io/).

## Add-ons

| | Add-on | Version | Description |
|:-:|---|:-:|---|
| <img src="mesh_guardian/icon.png" width="48" alt=""> | **[Mesh Guardian](mesh_guardian/)** *(beta)* | ![version][mg-version] | Keeps your Thread / Matter devices online: automatic recovery of lost nodes, a live table of every node, border router monitoring and radio advice. |
| <img src="thread_anchor/icon.png" width="48" alt=""> | **[Thread Anchor](thread_anchor/)** *(beta)* | ![version][ta-version] | Keeps your Thread network on one OMR prefix: no more Matter devices dropping out when Google, Apple or Amazon border routers change theirs. |
| <img src="voice_agent_bridge/icon.png" width="48" alt=""> | **[Voice Agent Bridge](voice_agent_bridge/)** *(beta)* | ![version][vab-version] | Talk to Claude through Assist and your voice satellites, with your Claude plan (no API key), the full Home Assistant toolset and a conversation panel. |
| <img src="side_door/icon.png" width="48" alt=""> | **[Side Door](side_door/)** | ![version][sd-version] | Opens a web app of your local network in the Home Assistant sidebar: HTTPS and Home Assistant login for free, nothing exposed to the Internet. |
| <img src="usbip_link/icon.png" width="48" alt=""> | **[USB/IP Link](usbip_link/)** *(beta)* | ![version][ul-version] | A radio plugged into another computer (usbipd-win on Windows) for Home Assistant in a virtual machine without USB, attached again by itself after every restart of that computer, the OpenThread border router restarted on it. |

## Installation

1. Click the button below, or add `https://github.com/Pintjes/ha-addons` in
   **Settings → Add-ons → Add-on store → ⋮ → Repositories**.

   [![Add repository to my Home Assistant][repo-badge]][repo-link]

2. Find the add-on in the store and click **Install**.

## Support

Something wrong, or an idea? [Open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).

## License

© 2026 Pintjes. All rights reserved. Each add-on is under its own license: see the `LICENSE` file of its folder. The source is public to read and to report issues; except for Side Door (below), it may not be copied, modified or redistributed without permission. **Side Door** is under [GPL-3.0-or-later](side_door/LICENSE) from version 2.8.1: that restriction does not apply to it, and its license says what you may do (version 2.8.0 was published under a proprietary license). Versions published before an add-on's license change stay under GPL-3.0-or-later.

These add-ons are independent projects, not affiliated with or endorsed by Anthropic, the Connectivity Standards Alliance or the Thread Group.

[repo-badge]: https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg
[repo-link]: https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons
[ci-badge]: https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg
[ci-link]: https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml
[license-badge]: https://img.shields.io/badge/licence-propri%C3%A9taire%20(sauf%20Side%20Door)-lightgrey
[license-link]: https://github.com/Pintjes/ha-addons/blob/main/LICENSE
[sd-license-badge]: https://img.shields.io/badge/Side%20Door-GPL--3.0-blue
[sd-license-link]: https://github.com/Pintjes/ha-addons/blob/main/side_door/LICENSE
[mg-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fmesh_guardian%2Fconfig.yaml&query=%24.version&label=&color=blue
[vab-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fvoice_agent_bridge%2Fconfig.yaml&query=%24.version&label=&color=blue
[sd-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fside_door%2Fconfig.yaml&query=%24.version&label=&color=blue
[ul-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fusbip_link%2Fconfig.yaml&query=%24.version&label=&color=blue
[ta-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fthread_anchor%2Fconfig.yaml&query=%24.version&label=&color=blue

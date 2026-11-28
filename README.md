<p align="center"><img src="images/pintjes-logo.png" alt="Pintjes" width="160"></p>

# Home Assistant apps by Pintjes

[![Add repository to my Home Assistant][repo-badge]][repo-link]
[![CI][ci-badge]][ci-link]
[![License: proprietary, Side Door GPL-3.0+][license-badge]][license-link]

App repository for [Home Assistant](https://www.home-assistant.io/).

## Apps

| | App | Version | Description |
|:-:|---|:-:|---|
| <img src="mesh_guardian/icon.png" width="48" alt=""> | **[Mesh Guardian](mesh_guardian/)** *(beta)* | ![version][mg-version] | Watches your Thread / Matter network: a table of the nodes, border router monitoring, radio advice and optional recovery of lost nodes. |
| <img src="thread_anchor/icon.png" width="48" alt=""> | **[Thread Anchor](thread_anchor/)** *(beta)* | ![version][ta-version] | Keeps your Thread network on one stable OMR prefix, through the OpenThread border router. |
| <img src="voice_agent_bridge/icon.png" width="48" alt=""> | **[Voice Agent Bridge](voice_agent_bridge/)** *(beta)* | ![version][vab-version] | Talk to Claude through Assist, voice satellites or a conversation panel, with your Claude plan (no API key). |
| <img src="side_door/icon.png" width="48" alt=""> | **[Side Door](side_door/)** *(beta)* | ![version][sd-version] | Opens web apps of your local network in the Home Assistant sidebar, behind the Home Assistant login. |
| <img src="usbip_link/icon.png" width="48" alt=""> | **[USB/IP Link](usbip_link/)** *(beta)* | ![version][ul-version] | Lets Home Assistant use a USB radio plugged into another computer, over the network (USB/IP). |

## Installation

1. Click the button below, or add `https://github.com/Pintjes/ha-addons` in
   **Settings → Apps → Install app → ⋮ → Repositories**.

   [![Add repository to my Home Assistant][repo-badge]][repo-link]

2. Find the app in the store and click **Install**.

## Support

Something wrong, or an idea? [Open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).

## License

© 2026 Pintjes. **Side Door** is open source (GPL-3.0-or-later). **The other apps** are proprietary: currently free to use, source public to read, not to copy, modify or redistribute without permission. See the `LICENSE` file of each app.

Not affiliated with or endorsed by Anthropic, the Connectivity Standards Alliance or the Thread Group.

[repo-badge]: https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg
[repo-link]: https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons
[ci-badge]: https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg
[ci-link]: https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml
[license-badge]: https://img.shields.io/badge/license-proprietary%2C%20Side%20Door%20GPL--3.0%2B-lightgrey
[license-link]: https://github.com/Pintjes/ha-addons/blob/main/LICENSE
[mg-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fmesh_guardian%2Fconfig.yaml&query=%24.version&label=&color=blue
[vab-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fvoice_agent_bridge%2Fconfig.yaml&query=%24.version&label=&color=blue
[sd-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fside_door%2Fconfig.yaml&query=%24.version&label=&color=blue
[ul-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fusbip_link%2Fconfig.yaml&query=%24.version&label=&color=blue
[ta-version]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fthread_anchor%2Fconfig.yaml&query=%24.version&label=&color=blue

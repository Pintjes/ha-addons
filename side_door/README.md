<p align="center">
  <img src="logo.png" alt="Side Door" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fside_door%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/side_door/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

**Side Door opens a web app of your local network in the Home Assistant
sidebar.** The app keeps running where it is; Home Assistant becomes its front
door.

## Why this add-on

**1. No more mixed content.**
A dashboard iframe to `http://192.168.x.x` stays blank when Home Assistant is
opened in HTTPS. Through the ingress, the browser only talks to Home Assistant.

**2. Reachable wherever Home Assistant is, nothing exposed.**
No port, no tunnel, no DNS record for the app: it sits behind the Home
Assistant login.

**3. Works with apps that know nothing about ingress.**
Links, redirections and cookies are rewritten for the ingress path, WebSockets
are relayed, and the headers the app checks (`Host`, `Origin`) are the ones it
expects.

## Also

- One option to set: the address of the app.
- A clear page when the app is off or the address is missing.
- Extra rewrite rules for the stubborn cases.

Full documentation: [DOCS.md](DOCS.md).

## License

[GPL-3.0](LICENSE) © Pintjes

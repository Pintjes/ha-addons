<p align="center">
  <img src="logo.png" alt="Side Door" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-app-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant app"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fside_door%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/side_door/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

> **Beta.** Side Door has been tested on one installation only. It rewrites the
> pages of the apps it shows: some web apps may not work through it. Reports are
> welcome: please
> [open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).

**Side Door is a Home Assistant app that opens the web apps of your local
network in the Home Assistant sidebar.** Each app keeps running where it is;
Home Assistant becomes its front door.

## Automatic: no rule to write

In the usual case you only need to know the address of your web app. Give it to
Side Door; the rest is done for you:

- links, redirections and cookies are rewritten for Home Assistant, and
  WebSockets are relayed;
- apps that build their addresses in JavaScript are handled by a small script,
  loaded by default;
- at each start, Side Door looks for the start page of an app whose root
  redirects to it (the very first time, it only says what it found: restart to
  apply it);
- the certificate of an `https://` app given by a name is checked.

The settings that lower a protection (`hide_proxy`, `headers`, `verify_tls`)
are never set for you: Side Door only suggests them. Some apps need one of them,
and some may not work (see the beta notice above).

## Why Side Door

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
- Several apps in the same panel, each on a tab with the name you choose, and
  settings of their own.
- An eye to hide apps, and a link for each app to open it from a dashboard
  button, with or without the row of tabs.
- A clear page when the app is off or the address is missing.
- Optional rewrite rules and per-app settings for the stubborn cases.

Full documentation: [DOCS.md](DOCS.md).

## License

[GPL-3.0-or-later](LICENSE) © 2026 Pintjes. Version 2.8.0 was published under a
proprietary license; 2.8.1 and the following versions are under
GPL-3.0-or-later, like the versions before 2.8.0.

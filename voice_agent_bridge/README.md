<p align="center">
  <img src="logo.png" alt="Voice Agent Bridge" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant add-on"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fvoice_agent_bridge%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/voice_agent_bridge/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0"></a>
</p>

**Voice Agent Bridge lets you talk to Claude from any Assist voice satellite**
(Home Assistant Voice, ESPHome, the companion app): say the wake word, Claude
answers out loud and runs your home.

## Why this add-on

**1. Your Claude plan, no API key.**
Already on Claude Pro or Max? Use it. Requests are counted on your plan's Agent SDK
credit: nothing else to pay, no API key to manage. (An Anthropic API key works too.)

**2. Claude really understands your home.**
Not only "turn on / turn off". Claude runs the official Claude Code agent with the
full [ha-mcp](https://github.com/homeassistant-ai/ha-mcp) toolset: history,
statistics, automation traces, logs, calendars, add-ons… It chains several steps,
loads only the tools it needs (fast and cheap) and keeps the thread of the
conversation. Ask *"why did the office heating stop last night?"* and it finds out.
Simple commands still go to local intents first: instant and free.

**3. Everything in one panel.**
A **Claude** panel in the sidebar shows every conversation, whatever the source
(a satellite and its room, the panel, Assist in the app), Claude on the left, you
on the right. Type or tap the microphone to talk from there, and edit the
**house notes** that tell Claude your rooms, words and rules. The log shows the
time, cost and tokens of each request.

## Also

- Streamed answers: the satellite starts speaking right away.
- Safety: no shell or file tools for Claude, read-only option, budget per request,
  and no unlocking, opening or disarming without your explicit "yes".
- English and French.

See the **Documentation** tab for installation and setup.


## Contributing

Bug reports and ideas are welcome: [open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).
Please include the add-on version and the relevant lines of the log.

## License

[GPL-3.0](https://github.com/Pintjes/ha-addons/blob/main/voice_agent_bridge/LICENSE) © Pintjes

> Voice Agent Bridge is an independent project, not affiliated with or endorsed by
> Anthropic. Claude is a trademark of Anthropic, PBC.

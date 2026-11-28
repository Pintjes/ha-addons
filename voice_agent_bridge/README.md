<p align="center">
  <img src="logo.png" alt="Voice Agent Bridge" width="300">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FPintjes%2Fha-addons"><img src="https://img.shields.io/badge/Home%20Assistant-app-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant app"></a>
  <img src="https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FPintjes%2Fha-addons%2Fmain%2Fvoice_agent_bridge%2Fconfig.yaml&query=%24.version&label=version&color=blue" alt="Version">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20aarch64-informational" alt="Architectures">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta">
  <a href="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml"><img src="https://github.com/Pintjes/ha-addons/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Pintjes/ha-addons/blob/main/voice_agent_bridge/LICENSE"><img src="https://img.shields.io/badge/license-proprietary-lightgrey" alt="License: proprietary"></a>
</p>

> **Beta.** Voice Agent Bridge has been tested on one installation only. It relies
> on the Claude Code agent and on your plan's Agent SDK credit: a change on
> Anthropic's side can break it without notice.

**Voice Agent Bridge lets you talk to Claude from any Assist voice satellite**
(Home Assistant Voice, ESPHome, the companion app): say the wake word, Claude
answers out loud and runs your home.

## Why this app

**1. Your Claude plan or an API key.**
Uses your Claude Pro or Max plan's Agent SDK credit, or an Anthropic API key.

**2. The Home Assistant toolset.**
Claude runs the official Claude Code agent with the
[ha-mcp](https://github.com/homeassistant-ai/ha-mcp) tools: history, statistics,
automation traces, logs, calendars, apps… It can chain several steps, loads only
the tools it needs and keeps the thread of the conversation, for questions such as
*"why did the office heating stop last night?"*. Simple commands go to local
intents first and do not reach Claude.

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
Please include the app version and the relevant lines of the log.

## License

Proprietary, © 2026 Pintjes: see the [EULA](https://github.com/Pintjes/ha-addons/blob/main/voice_agent_bridge/LICENSE)
(French text prevails, English translation included). Versions before 1.1.3 were
published under GPL-3.0-or-later and keep that license.

Claude Code, downloaded when the image is built, is Anthropic software under
Anthropic's terms. The agent's answers and actions come with no guarantee: do not
use it for safety, alarm or access control. Voice Agent Bridge is not affiliated
with or endorsed by Anthropic; Claude is a trademark of Anthropic, PBC.

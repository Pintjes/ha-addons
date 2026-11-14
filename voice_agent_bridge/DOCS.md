# Voice Agent Bridge

Talk to Claude through Assist: say the wake word to your voice satellite
(Home Assistant Voice, ESPHome, the companion app…) and Claude answers and
controls your home, like a smart speaker.

## Contents

- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [Installation](#installation)
- [Connect it to Assist](#connect-it-to-assist)
- [House notes](#house-notes)
- [Configuration](#configuration)
- [Cost and speed](#cost-and-speed)
- [Security](#security)
- [FAQ and troubleshooting](#faq-and-troubleshooting)

## How it works

```text
 Satellite ── wake word ──▶ Assist pipeline ── speech-to-text
                                 │
                                 ├─ local intents first ("turn on the kitchen light": instant)
                                 │
                                 └─ otherwise ──▶ Extended OpenAI Conversation
                                                      │  (OpenAI-compatible request)
                                                      ▼
                                          Voice Agent Bridge (this add-on)
                                                      │  claude -p (Claude Code)
                                                      ▼
                                          ha-mcp ──▶ Home Assistant (states, history,
                                                      services, automations…)
 Satellite ◀── text-to-speech ◀── streamed answer ◀──┘
```

The add-on runs the official Claude Code CLI in non-interactive mode. Claude
reaches your home through [ha-mcp](https://github.com/homeassistant-ai/ha-mcp),
started inside the add-on with the add-on's own Home Assistant access: you do
not create a long-lived access token.

The answer is streamed, so the satellite starts speaking before Claude has
finished. A follow-up question in the same conversation continues the same
Claude session.

## What you need

- Home Assistant OS or Supervised (add-ons).
- [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation)
  3.x (HACS). It is the bridge between Assist and this add-on.
- One of:
  - a **Claude Pro or Max plan** and a token from `claude setup-token`; usage is
    counted on the plan's Agent SDK credit;
  - an **Anthropic API key** (pay per use).

Use of a Claude plan is for your own, personal use (your home). If you build
something for other people, use an API key.

## Installation

1. Add the repository and install **Voice Agent Bridge**.
2. Get a token. On any computer with [Claude Code](https://code.claude.com)
   installed, run:

   ```bash
   claude setup-token
   ```

   Sign in with your Claude account and copy the token (`sk-ant-oat01-…`).
3. Paste it in **Configuration → Claude token**, choose the **Language**, save
   and start the add-on.
4. In the **Log** tab, check for `Voice Agent Bridge listening on port 8791`.

## Connect it to Assist

1. **Settings → Devices & services → Add integration → Extended OpenAI Conversation**:
   - **API key**: anything (for example `claude`), or the **Gateway key** if you set one;
   - **Base URL**: `http://<hostname>:8791/v1`, where `<hostname>` is shown on the
     add-on **Info** tab (for example `abcd1234-voice-agent-bridge`).
2. Add a conversation agent to this entry:
   - **Model**: `claude`;
   - **Prompt**: keep it short; the gateway gives Claude its own instructions. A good
     prompt tells Claude where the satellite is:

     ```jinja
     Satellite room: {{ area_name(current_device_id) }}
     ```

   - **Functions**: empty (`[]`). Claude uses its own tools.
3. **Settings → Voice assistants → Add assistant**:
   - **Conversation agent**: the new agent;
   - **Prefer handling commands locally**: on (simple commands stay instant);
   - speech-to-text and text-to-speech: as you like.
4. On the satellite device page, choose this assistant.

Say the wake word and ask: *"Which lights are on downstairs?"*

## House notes

At first start the add-on creates `CLAUDE.md` in its configuration folder
(`/addon_configs/<hostname>/CLAUDE.md`, reachable with the File editor or Samba).
Describe your home there: who lives there, how you name rooms and devices,
habits, rules. The file is read at every request: changes apply immediately.
Keep it short, every line is sent with every request.

Edit the notes straight from the **Claude** panel with the **✎ House notes**
button (Ctrl+S saves).

Prefer the File editor? Set **House notes file** to a path in your Home
Assistant configuration folder, for example `claude_notes.md`. The add-on maps
the Home Assistant configuration folder only to read and save that one file;
Claude itself has no file access.

## Conversation history

The add-on adds a **Claude** panel to the sidebar (tick **Show in sidebar** on
the add-on Info tab). It shows every conversation, Claude on the left and you on
the right, whatever the source: a voice satellite (with its room), the panel
itself, or Assist in the Home Assistant app.

At the bottom, type a request or tap the microphone. The panel runs the selected
Assist pipeline exactly like the Assist dialog: local intents first, then Claude,
with the pipeline's speech-to-text and text-to-speech. The microphone needs
HTTPS (for example your Nabu Casa address) and your browser's permission. In
the Home Assistant companion app, the button always opens the app's own Assist
microphone with the selected assistant (it works on local `http://` addresses too);
the exchange then appears in the panel, but voice and typed requests are separate
conversations.
Commands answered by Home Assistant itself (local intents) appear with a 🏠
label. Home Assistant does not send them to the add-on: the panel reads them from
the Assist debug data when it opens, then every 10 seconds while it stays open.
Home Assistant keeps only the last runs of each assistant in memory and clears
them when it restarts, so open the panel now and then if you want all of them.
**New conversation** starts a fresh Claude session.

For the room of each satellite, keep the first line of the agent prompt as
`Satellite room: {{ area_name(current_device_id) }}`.

Each question and answer is written to the add-on log and, with **Logbook** on,
to the Home Assistant logbook (name *Claude*), so you find your voice
conversations in **Logbook** and in **Settings → Voice assistants → ⋮ → Debug**.

## Configuration

| Option | Default | Description |
|---|---|---|
| Language | `en` | Language of the answers (`en`, `fr`). |
| Claude token | | Token from `claude setup-token`. |
| Anthropic API key | | Alternative to the token. |
| Model | `haiku` | `haiku`, `sonnet`, `opus` or a full model name. |
| Effort | `low` | Thinking effort. |
| Web search | on | Questions outside the home (weather, news…). |
| Read-only | off | Claude can look but not touch. |
| Use the Home Assistant prompt | on | Pass the agent prompt (room of the satellite…). |
| Maximum steps | 12 | Tool steps per request. |
| Budget per request (USD) | 0.5 | Safety stop per request. |
| Timeout (seconds) | 90 | Maximum time per request. |
| Gateway key | | Optional key required from clients. |
| Load tools on demand | on | Claude loads only the tools it needs: much cheaper. |
| Home Assistant tool modules | `all` | Limit the ha-mcp modules (advanced). |
| House notes file | | Path in the Home Assistant config folder (File editor). |
| Logbook | on | Write each exchange in the Home Assistant logbook. |
| History (days) | 90 | How long conversations stay in the panel. |
| Recent exchanges | 20 | Last exchanges of every channel given to Claude with each request (0 = off). |
| Recent exchanges (hours) | 24 | Only exchanges from the last hours. |

## Cost and speed

- Simple commands handled by local intents cost nothing and never reach Claude.
- Each Claude request starts a Claude Code process: count a few seconds, more
  when Claude needs several tools. `haiku` and effort `low` are the fastest.
- With a Claude plan, requests use the monthly Agent SDK credit of the plan.
  The log shows the duration, the cost and the tokens of every request.
- **Load tools on demand** keeps every request small: Claude receives the list
  of tool names and loads a tool only when it needs it.
- Good house notes save steps: Claude finds the right entity at once.

## Security

- Claude can do what the add-on's Home Assistant access allows, unless
  **Read-only** is on.
- The instructions ask Claude never to unlock, open or disarm locks, garage
  doors, gates, alarms, vehicles or pool covers without your explicit "yes".
  Add your own rules in the house notes.
- The endpoint is only reachable inside Home Assistant unless you map port 8791.
  If you map it, set a **Gateway key**.
- Claude Code runs without shell, file or code tools: only the Home Assistant
  tools and, if enabled, web search.

## FAQ and troubleshooting

**The satellite says Claude is not signed in.** The token is missing, wrong or
revoked. Create a new one with `claude setup-token`.

**The satellite says the usage limit is reached.** The plan's credit or the
budget per request is exhausted. Raise **Budget per request** or wait.

**Extended OpenAI Conversation cannot connect.** Check the hostname and port
`8791` in the base URL, and that the add-on is started.

**Answers are slow.** Use `haiku`, keep effort `low`, keep the house notes short
and leave **Prefer handling commands locally** on.


## Contributing

Bug reports and ideas are welcome: [open an issue](https://github.com/Pintjes/ha-addons/issues/new/choose).
Please include the add-on version and the relevant lines of the log.

## License

[GPL-3.0](https://github.com/Pintjes/ha-addons/blob/main/voice_agent_bridge/LICENSE) © Pintjes

> Voice Agent Bridge is an independent project, not affiliated with or endorsed by
> Anthropic. Claude is a trademark of Anthropic, PBC.

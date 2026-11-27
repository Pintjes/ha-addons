# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.6] - 2026-11-27

### Changed

- Home Assistant now calls add-ons "apps" (**Settings → Apps**): the documentation,
  the option descriptions, the spoken error messages and the log say "app"
  (also in French: « l'app »). No change to how the app works.

## [1.1.5] - 2026-11-26

### Fixed

- **Load tools on demand** now works. The add-on gave Claude Code a list of built-in
  tools without the tool search tool, so Claude Code turned tool search off and sent
  every Home Assistant tool in full with each request: more than 100,000 tokens, which
  also puts Claude Haiku 5.5 on its higher price for long prompts. Now only the tool
  names are sent and Claude loads the few tools it needs: a request is much smaller
  and cheaper. If you raised **Budget per request** because requests stopped
  with "I did not finish", you can lower it again.
- The log shows the cost of each request. In a continued conversation Claude Code
  reports the total of the whole conversation; it is now shown apart, for example
  `$0.0012 (conversation $0.0150)`.
- When a request stops (budget, steps, timeout) while a tool call is still waiting for
  its result, the `Claude error` line says so (`no result for: …`) and gives the cost.

## [1.1.4] - 2026-11-26

### Fixed

- When Claude fails, the log now says why: the kind of error, the error messages
  and the end of the Claude Code error output, the number of turns, the time and
  the tools called. Before, it only said "exit code 1". Secrets (token, key,
  private server path) are removed from these lines.
- A tool call refused or failed (for example wrong arguments) is logged as a
  warning, with the tool name and a short message.
- When a request goes over the turns or budget set for one request, the speaker
  says "I did not finish" instead of the general error message.
- A failed request is tried once more, by itself, only when nothing was said yet
  and only tools that read were called (search, states, history…): a device is
  never commanded twice. It is not tried again after a timeout, a sign-in error or
  a usage limit.

## [1.1.3] - 2026-11-22

### Changed

- License changed: proprietary from this version; earlier versions stay under
  GPL-3.0-or-later. The license agreement (French, with an English translation)
  is in the `LICENSE` file. No change to the code.

## [1.1.2] - 2026-11-15

### Changed

- The panel, logo and icon use the same blue as the other add-ons of the
  repository (#1f6feb). Your messages no longer take the color of the Home
  Assistant theme.
- Marked as beta (README and description).

## [1.1.1] - 2026-11-15

### Fixed

- A follow-up question now takes the edited house notes into account. A
  conversation started before the notes (or the options) changed is no longer
  resumed: Claude Code keeps the system prompt of the first request when it
  resumes a session, so the new notes were ignored until the next conversation.

## [1.1.0] - 2026-11-14

### Added

- Recent exchanges: Claude receives the last exchanges of every channel (panel,
  satellites, Assist, local Home Assistant answers) with each request, so it
  knows what was said before, even when Home Assistant answered. Options
  *Recent exchanges* (20) and *Recent exchanges (hours)* (24).

## [1.0.3] - 2026-11-14

### Changed

- Token option: link to the documentation explaining how to get it.

## [1.0.2] - 2026-11-14

### Changed

- New logo and accent color.

## [1.0.0] - 2026-11-14

### Added

- OpenAI-compatible endpoint that answers Assist requests with the official
  Claude Code CLI, connected to Home Assistant through a local ha-mcp server.
- Claude plan token (`claude setup-token`) or Anthropic API key.
- Streamed answers, tools loaded on demand, local intents first.
- Conversation panel in the sidebar: every conversation, text and voice input,
  house notes editor, log with time, cost and tokens.
- Safety: no shell or file tools, read-only option, budget per request, no
  unlocking, opening or disarming without an explicit confirmation.
- English and French.

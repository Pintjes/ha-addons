# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

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

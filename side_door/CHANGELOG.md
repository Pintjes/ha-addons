# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-15

### Added

- Several apps in the same panel: each app has the name you choose, shown on
  a tab. An app keeps its page when you switch tabs.

## [1.0.1] - 2026-11-15

### Fixed

- A redirection of the app (to its login page, for example) ended in
  "502: Bad Gateway": the rewritten address was made absolute.

## [1.0.0] - 2026-11-15

### Added

- A web app of the local network shown in a sidebar panel, through the Home
  Assistant ingress.
- Paths, redirections and cookies rewritten for the ingress path.
- WebSockets relayed.
- A page that says so when the address is missing or the app does not answer.

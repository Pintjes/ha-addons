# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.3] - 2026-11-15

### Fixed

- Logging in to an app looped when Home Assistant was opened in plain HTTP
  and the app reserved its cookies to HTTPS: in that case the cookies lose
  that mark.

## [1.3.2] - 2026-11-15

### Fixed

- A tab stayed blank after the address of its app had been corrected: the
  browser kept following the permanent redirection the first address had
  answered. Such redirections are no longer kept, and the apps of the tabs
  moved to a new path (you log in to them once more).

## [1.3.1] - 2026-11-15

### Fixed

- `inject_script`: an app that looks at the page around it no longer takes
  the panel for its own shell.
- `inject_script`: the browser no longer keeps the pages and scripts of the
  app, so turning the option on takes effect without emptying its cache.

## [1.3.0] - 2026-11-15

### Added

- Experimental option `inject_script`, for apps that build their addresses
  in JavaScript: a script loaded before the app moves its requests, its
  navigation and its redirections under the ingress path.

## [1.2.0] - 2026-11-15

### Added

- A dashboard button can open a given app: add `?app=<name>` to the address
  of the panel.

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

# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.9.0] - 2026-11-16

### Added

- Next to the eye of each tab, a link icon copies the path a dashboard button
  needs to open that app (`/app/<add-on>?app=<app>`). When the browser does
  not allow copying, the path is shown, selected, ready to be copied.

## [1.8.0] - 2026-11-16

### Added

- An eye at the end of the row of tabs: click it, then click the apps to hide
  or show (struck through, with a crossed eye, when hidden). A hidden app has
  no tab and is not loaded. The choice is kept by the browser; an app opened by
  a dashboard button still opens.

## [1.7.0] - 2026-11-16

### Added

- An app of the list can be `hidden`: it keeps its entry, but has no tab and
  is not relayed. The other apps do not move.

## [1.6.2] - 2026-11-15

### Fixed

- The log no longer shows the parameters of the addresses (what follows `?`):
  the error messages of nginx wrote whole addresses, tokens of the apps
  included.
- An app given by a host name is reached at its IPv4 addresses: without an
  IPv6 route, each request first failed on an IPv6 address.

## [1.6.1] - 2026-11-15

### Fixed

- The translations of version 1.6.0 could not be read.

## [1.6.0] - 2026-11-15

### Added

- An app of the list can have `headers`, sent with every request: for an app
  behind a gate that lets a token in (a service token of an access proxy).
- The rule of a page that says who may show it (`frame-ancestors` of its
  Content-Security-Policy) is removed, like `X-Frame-Options`.
- `inject_script`: the injected script carries the pass (`nonce`) of a
  page that only runs the scripts it knows.

## [1.5.1] - 2026-11-15

### Added

- An app of the list can have a `start` page: the page its tab opens on,
  when it is not the root of the app.

## [1.5.0] - 2026-11-15

### Added

- Option `hide_proxy`, for apps that ask for a login through Side Door but
  not on the local network: the app is no longer told that the request was
  relayed.

### Fixed

- `inject_script`: back from a login on another site, Home Assistant
  answered `401: Unauthorized`. The browser now comes back to the panel,
  which opens the app on the right page.

## [1.4.4] - 2026-11-15

### Added

- `inject_script`: an app that sends the browser to another site to log in
  (an account service) now opens that site in the whole window, since such
  pages refuse to be shown inside the panel, and gives it the right address
  to come back to. Back on the app, a button leads to Home Assistant.

## [1.4.3] - 2026-11-15

### Fixed

- Scripts loaded by other scripts (JavaScript modules: `import … from "/…"`,
  `import("/…")`) are rewritten too.

## [1.4.2] - 2026-11-15

### Fixed

- An app that checks the fingerprint of its scripts (Subresource Integrity)
  refused the rewritten ones and stayed blank: that check is dropped for the
  pages and scripts the add-on rewrites.

## [1.4.1] - 2026-11-15

### Fixed

- After an update or a change of the configuration, the browser could keep
  using pages and scripts rewritten the old way (an app fixed by the update
  stayed broken). What the browser keeps is now tied to the version and the
  configuration.

## [1.4.0] - 2026-11-15

### Changed

- The answers of the apps are rewritten by a script of the add-on instead of
  nginx text filters. Upper and lower case are now told apart.

### Fixed

- An app stayed blank when one of its scripts had a name ending like a
  rewritten text (`resolveUrl("/…")`, `baseHref="/…"`): the name was put in
  lower case.
- An address without scheme (`href="//example.com/x"`) is left as it is.
- Between two pages of an app, the tab no longer flashes white: it keeps the
  background colour of the app.

## [1.3.8] - 2026-11-15

### Fixed

- The full addresses of an app stay full addresses once rewritten: an app
  that expected one no longer stops on a bare path.

## [1.3.7] - 2026-11-15

### Fixed

- Answers of a GraphQL API (`application/graphql-response+json`) are
  rewritten like the other JSON answers.

## [1.3.6] - 2026-11-15

### Fixed

- Pictures missing in an app that writes its own full address in its answers
  (`http://192.168.1.10:9999/picture`): these addresses are rewritten too.

## [1.3.5] - 2026-11-15

### Fixed

- Plain HTTP: a cookie marked `Partitioned` was still refused by the
  browser, and the login kept looping. That mark is removed too.

## [1.3.4] - 2026-11-15

### Added

- The log tells when an app sets a cookie: its name and its marks, never its
  value. It is what explains a login that loops.

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

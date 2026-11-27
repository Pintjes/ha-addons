# Changelog

All notable changes to Side Door are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.8.1] - 2026-11-27

### Changed

- License: GPL-3.0-or-later again. Version 2.8.0 was published under a
  proprietary license; 2.8.1 and the following versions are under
  GPL-3.0-or-later, like the versions before 2.8.0.
- The texts say "app", the word Home Assistant now uses, and show what Side Door
  does on its own. No change to how the apps are relayed.

## [2.8.0] - 2026-11-22

### Changed

- License changed: proprietary from this version (end user license agreement in `LICENSE`, French text with an English translation); earlier versions stay under GPL-3.0-or-later. No change to how the apps are relayed.

## [2.7.0] - 2026-11-19

### Added

- With several apps, an information button at the end of the row of tabs
  opens a report: for each app, every setting as it applies with its origin
  (`set`, `default`, `detected`), what the detection found, and its
  suggestions (`hide_proxy`, `headers`, `verify_tls`) with the reason and the
  warning. The button shows how many suggestions there are. It is what the log
  already said, seen at the last start; nothing more is applied.

## [2.6.1] - 2026-11-19

### Changed

- The log now has one line of verdict for each app the detection looked at:
  nothing needed, found (applied or not), refused with the reason, start page
  written in the configuration and not replaced, or not looked at. When the
  request that looks relayed fails, the log says so instead of staying
  silent. How the apps are relayed does not change.

## [2.6.0] - 2026-11-19

### Added

- Automatic detection (option `auto_settings`: `apply` by default, `report`,
  `off`). At each start the add-on looks at each app with a few plain GET
  requests (no cookie, no login, no `headers`) and finds its start page when
  the root of the app redirects to one. It is applied only when every
  redirection stays on the app and sets no cookie, the page is not a login
  (address, password field) and answers normally; a `start` you write is
  never replaced; an app that does not answer keeps the page found last time
  (`/data/detected.json`). The log says what was found (`(detected)`) and why
  nothing was applied.
- The first time the detection runs (no `/data/detected.json` yet), `apply`
  only says what it found and applies nothing; the next start applies it.
- `hide_proxy`, `headers` and `verify_tls` are never set automatically: the
  log suggests them (different answer to a relayed request, 401/403 to a plain
  request, certificate that does not pass).

### Fixed

- A stop asked while the add-on is starting is no longer ignored.

## [2.5.0] - 2026-11-19

### Added

- The log lists, for each app, every setting as it applies and where it comes
  from: `(set)` when written in the configuration, `(default)` when left out
  (names of headers only, never their values).

### Changed

- The descriptions of the configuration and the documentation say that only
  `name` and `url` are needed: a setting left out takes its default. No change
  to how the apps are relayed.

## [2.4.2] - 2026-11-17

### Fixed

- Stopping the add-on took 10 s and left it in error: the stop signal of the
  nginx image (SIGQUIT) was ignored, and the container was killed. It now
  stops at once, cleanly. The CI checks it.

## [2.4.1] - 2026-11-17

### Fixed

- 2.4.0 could leave an answer unfinished when its last piece came empty.

## [2.4.0] - 2026-11-17

### Fixed

- A rewritten answer was held until its end: a stream of data (live values,
  a long list sent bit by bit) stayed blocked. It is now relayed line by line,
  as it comes.
- An answer the app says is not in UTF-8 (`charset=iso-8859-1`…) is relayed as
  it is from its first byte.

## [2.3.0] - 2026-11-17

### Fixed

- `inject_script` now also covers the forms an app creates (`action`,
  `formAction`), the windows it opens (`window.open`) and the HTML it inserts
  as a block (`innerHTML`, `outerHTML`, `insertAdjacentHTML`).
- What an app sends with `fetch` or `XMLHttpRequest` gets its own addresses
  back: an app that edits and saves a page or its settings no longer stores the
  address of Home Assistant in its data.
- The way back from a login on another site refuses an encoded `..`.

## [2.2.0] - 2026-11-17

### Fixed

- A host name that did not resolve when the add-on started (Internet not
  ready yet) stopped the whole add-on. Names are now looked up at each use: such
  an app only has its own tab unavailable, and a name whose addresses change
  is followed.
- A cookie with `Domain=` was refused by the browser (login that loops): the
  domain is dropped. A cookie an app writes in JavaScript stays under the path
  of the app.
- An app that emptied the storage of the browser at log out logged you out of
  Home Assistant and cleared the eye. Each app now has its own part of that
  storage (when `inject_script` is on, the default). What an app kept there
  before is no longer seen: it may ask for a login or its settings once.

## [2.1.0] - 2026-11-17

### Changed

- `inject_script` is on by default: an app built in JavaScript works without
  any setting. Turn it off for an app that behaves badly with it. The
  certificate stays automatic, and `hide_proxy` stays a choice of yours: it
  lets everyone who opens the panel into the app without its login.

## [2.0.0] - 2026-11-17

### Changed

- **Breaking:** `rewrite_paths`, `inject_script` and `hide_proxy` are now
  settings of each app (`rewrite`, `inject_script`, `hide_proxy` in the
  entries of `apps`), no longer options of the whole add-on. An app that
  needed one of them must have it set again after the update.

### Added

- The certificate of an `https://` app is checked when the app is given by a
  name, not when it is given by an IP address. `verify_tls` (`auto`, `on`,
  `off`) decides for an app.

### Documentation

- Security: every app shown by Side Door can act on Home Assistant as you; only
  open apps you trust.

## [1.10.1] - 2026-11-17

### Fixed

- An answer the app compressed although nobody asked for it was damaged: it
  is relayed as it is.
- A page that is not in UTF-8 (ISO-8859-1, Windows-1252…) lost its accented
  letters: it is relayed as it is.
- A piece of an answer (a download that resumes) is no longer rewritten.
- The log no longer shows the user name and password of a refused address
  written `http://user:password@host/`.

### Changed

- Tests are part of the repository and of the CI: what the add-on writes from
  the options, and the add-on at work in front of a test app.

## [1.10.0] - 2026-11-16

### Added

- `&only=1` after `?app=` opens the app alone, without the row of tabs, on
  every device. The link icon offers both paths, each with a Copy button.

## [1.9.1] - 2026-11-16

### Fixed

- The link icon gives the `/app/<add-on>?app=<app>` path when Home Assistant
  has it: it keeps working when the add-on is not shown in the sidebar, while
  the sidebar address goes away with the sidebar entry.

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

# Side Door

Side Door is a Home Assistant app that opens web apps of your local network in
the Home Assistant sidebar, through the Home Assistant ingress. In the usual case you
write no rewrite rule: a name and an address are enough (see the limits in
*What is rewritten*).

## Contents

- [How it works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Several apps](#several-apps)
- [What is rewritten](#what-is-rewritten)
- [Security](#security)
- [FAQ and troubleshooting](#faq-and-troubleshooting)

## How it works

```text
 Browser ── HTTPS ──▶ Home Assistant (login) ── ingress ──▶ Side Door (nginx)
                                                                │  HTTP or HTTPS, local network
                                                                ▼
                                                        your app (target_url)
```

The app is shown in a sidebar panel. Your browser only talks to Home
Assistant, so:

- an app served in plain HTTP works inside a Home Assistant opened in HTTPS
  (no mixed content);
- the app is reachable wherever Home Assistant is (Nabu Casa, your own
  tunnel), behind the Home Assistant login;
- Side Door publishes no port.

WebSockets are relayed.

## Installation

1. Add the repository `https://github.com/Pintjes/ha-addons` in
   **Settings → Apps → Install app → ⋮ → Repositories**.
2. Install **Side Door**.
3. In the **Configuration** tab, set the address of the app, then start
   Side Door.
4. Turn on **Show in sidebar**.

Home Assistant must be able to reach the address: check the firewall of the
computer that runs the app, and the rules between your networks (VLANs).

## Configuration

| Option | Default | Description |
|---|---|---|
| `target_url` | empty | For a single app: the address Home Assistant uses to reach it, for example `http://192.168.1.10:8000`. A path is accepted (`http://192.168.1.10/app/`). |
| `apps` | empty | A list of apps, each with a `name`, a `url` and its own settings (see below). When filled, `target_url` is ignored. |
| `rewrite_prefixes` | empty | Advanced: more texts after which a path is rewritten. |
| `auto_settings` | `apply` | Automatic detection of the start page (see below): `apply`, `report` (only said in the Log tab) or `off` (no request). |
| `max_body_mb` | `100` | Largest upload, in MB. |
| `timeout` | `120` | Seconds to wait for an answer of the app. A WebSocket with no traffic for that long is closed. |

The panel title and icon are fixed (a Home Assistant limit: they are not
options). The panel is shown to administrators only.

## Several apps

Fill `apps` with one entry per app:

```yaml
apps:
  - name: Accounting
    url: http://192.168.1.10:8000
  - name: Printer
    url: http://192.168.1.20
```

### Settings of an app

Only `name` and `url` are needed. A setting you leave out takes its default
(the table below), which is what most apps need: do not add a setting just
because the form shows it. The **Log** tab says, for each app, every setting as
it applies and where it comes from: `(set)` when it is written in the
configuration, `(default)` when it is left out.

Each entry can also have, only when the app needs it:

| Setting | Default | Description |
|---|---|---|
| `start` | empty | The page the tab opens on, when the interface is not at the root of the app: `web/index.html` for Plex. |
| `rewrite` | on | Rewrites the paths of the app (see below). Turn off for an app that already handles the `X-Ingress-Path` header. |
| `inject_script` | on | Needed by an app that builds its addresses in JavaScript (see below). Turn off for an app that behaves badly with it. |
| `hide_proxy` | off | For an app that asks for a login through Side Door but not on the local network (see below). |
| `verify_tls` | `auto` | The certificate of an `https://` app (see *Security*). |
| `headers` | empty | Headers sent with every request (see below). |
| `hidden` | off | The app is put aside (see below). |

### Automatic detection

At each start (and each restart), Side Door looks at every app with a few
plain `GET` requests: no cookie, no login, none of your `headers`. It sends at
most 4 requests per app, waits 5 seconds at most, and writes what it learnt in
`/data/detected.json` (inside Side Door).

- **`start`** is found, and used, when the root of the app redirects to a page
  of the app. It is only applied when every redirection stays on the app and
  sets no cookie, the page answers normally, its address has nothing of a login
  (`login`, `signin`, `auth`, `sso`, `oauth`, `session`, `account`) and the
  page has no password field. Otherwise nothing is applied and the Log tab says
  why. A `start` you write is never replaced. If the app does not answer at
  start, the page found last time is kept. In the log, `(detected)` marks it.
- **`hide_proxy`**, **`headers`** and **`verify_tls`** are never set
  automatically; the Log tab only suggests them: when the app answers
  differently to a request that looks relayed (`hide_proxy`: it would open the
  app without login to every Home Assistant administrator), when it answers 401
  or 403 to a plain request (`headers`), or when its certificate does not pass
  (`verify_tls`).
- The Log tab has one line for each app that was looked at, whatever the
  result (`no start page needed`, `found`, `no start page applied (reason)`,
  `written in the configuration, not replaced`, `not looked at`).
- With several apps (a row of tabs), the information button at the end of the
  row opens a report with the same content as the log, as of the last start:
  for each app, every setting with its origin (`set`, `default`, `detected`),
  the verdict of the detection and the suggestions with their reason and
  warning. The button shows the number of suggestions. With a single app there
  is no row, so no report: the Log tab is the place.
- With `auto_settings: report` the Log tab says what was found and nothing is
  applied; with `off` no request is sent.
- The very first time the detection runs (no `/data/detected.json` yet, for
  example right after updating to this version), `apply` only says what it
  found and applies nothing: read the Log tab, then restart Side Door to
  apply it.

What detection cannot do:

- An app that shows its login without redirecting, and without a password
  field in the first 256 KB of the page (an app that draws everything in
  JavaScript), is not seen as a login: a `start` could then be wrong. Write
  `start` yourself, or set `auto_settings: off`.
- A redirection made in JavaScript, not by the server, is not followed.
- Why Plex needs `start: web/index.html` is not established: detection finds
  it only if the root of Plex redirects to it. If the Log tab does not say so,
  keep writing it.
- An app that counts every request sees 1 to 4 more at each start.

A target set with `target_url` takes the default settings. Up to version
1.10, `rewrite_paths`, `inject_script` and `hide_proxy` were options of
Side Door as a whole; they are now settings of each app.

An entry can have `headers`, sent to the app with every request. They are
written `Name: value` and separated by ` | `. This is for an app behind a
gate that lets a token in, such as a service token of Cloudflare Access:

```yaml
  - name: Remote app
    url: https://app.example.com
    headers: "CF-Access-Client-Id: <id> | CF-Access-Client-Secret: <secret>"
```

The gate then lets Side Door in on its own: everyone who can open the panel
goes through it without logging in there.

To hide apps in one browser only, click the eye at the end of the row of
tabs, then click the apps to hide or show: a hidden app is struck through,
with a crossed eye. Click the eye again to finish. A hidden app has no tab and
is not loaded, but Side Door still relays it: an app opened by a dashboard
button (`?app=`) still opens. The choice is kept by the browser.

An entry can also be `hidden` in the configuration, for every browser: the
app is put aside without losing its settings.
It has no tab, is not loaded, and its address under the panel answers
"not found". The other apps keep their place.

With two apps or more, the panel shows a row of tabs with the names you
chose. An app is loaded the first time its tab is opened and keeps its page
when you switch tabs. The panel opens on the tab you used last.

With a single entry, the app fills the panel, without tabs.

### Open a given app from a dashboard

The simplest: click the eye at the end of the row of tabs, then the link icon
next to the app. It offers two paths, each with a Copy button: one opens the
panel on that app with the row of tabs, the other (ending with `&only=1`)
opens the app alone, without the row. On the button card, choose the action
*Navigate* and paste the path.

The path is the address of the panel followed by `?app=` and the name of
the app. On a button card:

```yaml
type: button
name: Printer
tap_action:
  action: navigate
  navigation_path: /app/<slug of Side Door>?app=Printer
```

The slug is in the address bar when the panel is open (for example
`4f047962_side_door`). The `/app/…` path works whether or not Side Door is
shown in the sidebar; the sidebar address (`/4f047962_side_door`) only works
while it is. Upper and lower case do not matter.

The sidebar keeps one entry, named Side Door: Home Assistant gives one panel
to each of its apps and takes its title from that app itself. The names you choose
are the ones on the tabs.

Moving from one app to several (or back) changes the path of the apps: you
log in to them once more.

## What is rewritten

Behind the ingress, the app is not at `/` but under a path such as
`/api/hassio_ingress/<token>/`. Most apps write links starting with `/`
(`/static/style.css`, `/login`), which would leave the ingress. With
`rewrite` on (the default), Side Door:

- rewrites redirections (`Location`) and the path of cookies, and drops the
  `Domain` of cookies (it names the app, not Home Assistant: the browser
  would refuse them);
- rewrites, in HTML, CSS, JavaScript and JSON answers, a path starting with
  `/` found right after `href="`, `src="`, `action="`, `poster="`,
  `srcset="`, `url(`, `fetch("`, `;url=`, and the `import` of JavaScript
  modules (single quotes too);
- rewrites the full addresses of the app itself (`http://192.168.1.10:8000/…`)
  found in these answers;
- sends the `Host`, `Origin` and `Referer` headers the app expects, so that
  its cross-site request checks (CSRF) keep working;
- removes `X-Frame-Options` and the `frame-ancestors` rule of the
  Content-Security-Policy, since the app is shown inside the panel;
- drops the fingerprint check of scripts (Subresource Integrity): a rewritten
  script no longer has the fingerprint the app expects.

The original `X-Ingress-Path` header is passed on to the app.

A rewritten answer is relayed line by line, as it comes: a stream of data
reaches the browser without waiting for its end. An answer the app says is in
another encoding than UTF-8 is relayed as it is.

Limits of the rewriting:

- a path built in JavaScript at run time is not seen. If it always follows the
  same text, add that text to `rewrite_prefixes` (for example `data-url="`);
- a single-page app with its own router may need a base path setting on its
  side instead.

### Apps that build their addresses in JavaScript

Some apps send an almost empty page and a program that builds every address
in the browser. Nothing can be rewritten in what Side Door relays, and the
app stays blank or leaves the panel. With `inject_script` on (the default), Side Door:

- loads a small script before the app. It moves under the ingress path the
  requests of the app (`fetch`, `XMLHttpRequest`, WebSocket), its internal
  navigation, the addresses it puts on the elements it creates (forms
  included), the HTML it inserts, the windows it opens and the cookies it writes
  itself;
- puts the addresses back as the app wrote them in what the app sends
  (`fetch`, `XMLHttpRequest`): a page or settings it edits and saves never keep
  the address of Home Assistant;
- gives the app its own part of the storage of the browser (`localStorage`,
  `sessionStorage`): it only sees what it wrote, and an app that empties it at
  log out no longer logs you out of Home Assistant;
- replaces `window.location` and `document.location` in the scripts of the
  app by an object that shows the app an address without the ingress path, and
  keeps its redirections inside the panel.

When the app sends the browser to another site to log in, that site opens in
the whole window (login pages refuse to be shown inside another page). Once
logged in, the browser comes back to the Side Door panel, which opens the app
on the page it expects. This needs the app to be a tab (two apps or more).

It is on by default: an app that does not need it is not disturbed by it. A
form sent by the browser itself, without JavaScript, is not put back. It
cannot work with every app: a script that reads
`location` without `window.` in front is not caught, and neither is an
address built inside a web worker. Turn it off for an app that behaves badly
with it.

### Apps that only trust the local network

Some apps let the local network in without a login, and ask for one as soon
as a request was relayed (they look at the `X-Forwarded-For` header). Plex
does. With `hide_proxy` on, Side Door no longer says the request was
relayed: the app sees a request coming from Home Assistant itself. Set it
only on the apps that need it. The
address of Home Assistant must then be one the app lets in without a login
(in Plex: Settings → Network → *List of IP addresses and networks that are
allowed without auth*).

Everyone who can open the panel then enters the app without a login: only
use it when that is what you want.

An app opened this way works without an account, and may hide what depends
on one (in Plex, the menu of the three dots on a poster does not open). To
get it back, log in to the app once inside Side Door. Since the app has its
own part of the storage of the browser, a login made in a normal tab is not
seen here, and this login stays in Side Door.

## Security

**Only open apps you trust.** An app shown by Side Door runs at the address of
Home Assistant. Its JavaScript, and every script it loads from elsewhere, can
read what Home Assistant keeps in the browser, your login included, and act on
Home Assistant as you. It can read the other apps of the panel too. No setting
can prevent it while the app goes through the ingress: keep Side Door for apps
of your own network that you trust, never for a public website.

- Only the Home Assistant ingress (172.30.32.2) is accepted; no port is
  published.
- Every Home Assistant administrator can open the panel, and so reach the
  app, from wherever Home Assistant is reachable. The login of the app itself
  still applies: keep it.
- When Home Assistant is opened in plain HTTP (`http://` on the local
  network), the cookies an app reserves to HTTPS lose that mark, otherwise
  nobody could log in to it. They then travel unencrypted between the browser
  and Home Assistant, like the rest of that session. Over HTTPS nothing
  changes.
- The certificate of an `https://` app is checked when the app is given by a
  name (`https://app.example.com`) and not when it is given by an IP address
  (`https://192.168.1.1`), since devices of a local network often sign their
  own certificate. Set `verify_tls` to `on` or `off` to decide. Keep it
  checked for an app reached over the Internet, above all when it receives
  `headers`: they would otherwise go to whoever stands in the way.

## FAQ and troubleshooting

**"No target yet"** — no address is set, or none is valid. The reason is in
the **Log** tab.

**"The app does not answer"** — Home Assistant cannot reach the address:
computer off, app stopped, firewall, or a rule between two networks.

**The page shows without style, or links leave the panel** — a path is not
rewritten. Look at the address that fails in the browser developer tools and
add the text that precedes it to `rewrite_prefixes`.

**"The app does not answer" for an `https://` app given by a name** — its
certificate may not be valid (self-signed, expired, another name). The Log tab
says `certificate verify failed`. Set `verify_tls: off` for that app if you
trust the network in between.

**"The app does not answer" for an app given by a name** — the name may not
resolve (Internet not ready, typing error). It is looked up again at each
visit: the other apps are not affected.

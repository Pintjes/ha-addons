# Side Door

Opens web apps of your local network in the Home Assistant sidebar, through
the Home Assistant ingress.

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
- the add-on publishes no port.

WebSockets are relayed.

## Installation

1. Add the repository `https://github.com/Pintjes/ha-addons` in
   **Settings → Add-ons → Add-on store → ⋮ → Repositories**.
2. Install **Side Door**.
3. In the **Configuration** tab, set the address of the app, then start the
   add-on.
4. Turn on **Show in sidebar**.

Home Assistant must be able to reach the address: check the firewall of the
computer that runs the app, and the rules between your networks (VLANs).

## Configuration

| Option | Default | Description |
|---|---|---|
| `target_url` | empty | For a single app: the address Home Assistant uses to reach it, for example `http://192.168.1.10:8000`. A path is accepted (`http://192.168.1.10/app/`). |
| `apps` | empty | For several apps: a list of `name` and `url` (see below). When filled, `target_url` is ignored. |
| `rewrite_paths` | `true` | Rewrites the paths of the app (see below). Turn off for an app that already handles the `X-Ingress-Path` header. |
| `rewrite_prefixes` | empty | Advanced: more texts after which a path is rewritten. |
| `inject_script` | `false` | Experimental: for apps that build their addresses in JavaScript (see below). |
| `hide_proxy` | `false` | For apps that ask for a login through Side Door but not on the local network (see below). |
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

An entry can also have a `start` page, for an app whose interface is not at
its root: `start: web/index.html` for Plex.

An entry can have `headers`, sent to the app with every request. They are
written `Name: value` and separated by ` | `. This is for an app behind a
gate that lets a token in, such as a service token of Cloudflare Access:

```yaml
  - name: Remote app
    url: https://app.example.com
    headers: "CF-Access-Client-Id: <id> | CF-Access-Client-Secret: <secret>"
```

The gate then lets the add-on in on its own: everyone who can open the panel
goes through it without logging in there.

To hide apps in one browser only, click the eye at the end of the row of
tabs, then click the apps to hide or show: a hidden app is struck through,
with a crossed eye. Click the eye again to finish. A hidden app has no tab and
is not loaded, but the add-on still relays it: an app opened by a dashboard
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
next to the app. The path to give the button is copied (or shown, ready to be
copied, when the browser does not allow copying). Then, on the button card,
choose the action *Navigate* and paste it as the path.

The path is the address of the panel followed by `?app=` and the name of
the app. On a button card:

```yaml
type: button
name: Printer
tap_action:
  action: navigate
  navigation_path: /<slug of the add-on>?app=Printer
```

The slug is in the address bar when the panel is open (for example
`/4f047962_side_door`). Upper and lower case do not matter.

The sidebar keeps one entry, named Side Door: Home Assistant gives one panel
to an add-on and takes its title from the add-on itself. The names you choose
are the ones on the tabs.

Moving from one app to several (or back) changes the path of the apps: you
log in to them once more.

## What is rewritten

Behind the ingress, the app is not at `/` but under a path such as
`/api/hassio_ingress/<token>/`. Most apps write links starting with `/`
(`/static/style.css`, `/login`), which would leave the ingress. With
`rewrite_paths` on, the add-on:

- rewrites redirections (`Location`) and the path of cookies;
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

### Apps that build their addresses in JavaScript

Some apps send an almost empty page and a program that builds every address
in the browser. Nothing can be rewritten in what the add-on relays, and the
app stays blank or leaves the panel. With `inject_script` on, the add-on:

- loads a small script before the app. It moves under the ingress path the
  requests of the app (`fetch`, `XMLHttpRequest`, WebSocket), its internal
  navigation and the addresses it puts on the elements it creates;
- replaces `window.location` and `document.location` in the scripts of the
  app by an object that shows the app an address without the ingress path, and
  keeps its redirections inside the panel.

When the app sends the browser to another site to log in, that site opens in
the whole window (login pages refuse to be shown inside another page). Once
logged in, the browser comes back to the Side Door panel, which opens the app
on the page it expects. This needs the app to be a tab (two apps or more).

This is experimental and cannot work with every app: a script that reads
`location` without `window.` in front is not caught, and neither is an
address built inside a web worker. Leave the option off when the app works
without it. It applies to every app of the list.

### Apps that only trust the local network

Some apps let the local network in without a login, and ask for one as soon
as a request was relayed (they look at the `X-Forwarded-For` header). Plex
does. With `hide_proxy` on, the add-on no longer says the request was
relayed: the app sees a request coming from Home Assistant itself. The
address of Home Assistant must then be one the app lets in without a login
(in Plex: Settings → Network → *List of IP addresses and networks that are
allowed without auth*).

Everyone who can open the panel then enters the app without a login: only
use it when that is what you want.

Limits:

- a path built in JavaScript at run time is not seen. If it always follows the
  same text, add that text to `rewrite_prefixes` (for example `data-url="`);
- a single-page app with its own router may need a base path setting on its
  side instead.

## Security

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
- The TLS certificate of an `https://` target is not checked (self-signed
  certificates are common on a local network).

## FAQ and troubleshooting

**"No target yet"** — no address is set, or none is valid. The reason is in
the **Log** tab.

**"The app does not answer"** — Home Assistant cannot reach the address:
computer off, app stopped, firewall, or a rule between two networks.

**The page shows without style, or links leave the panel** — a path is not
rewritten. Look at the address that fails in the browser developer tools and
add the text that precedes it to `rewrite_prefixes`.

**The add-on does not start** — a host name that cannot be resolved stops
nginx. Use an IP address.

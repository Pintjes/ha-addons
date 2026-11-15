# Side Door

Opens a web app of your local network in the Home Assistant sidebar, through
the Home Assistant ingress.

## Contents

- [How it works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
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
| `target_url` | empty | Address Home Assistant uses to reach the app, for example `http://192.168.1.10:8000`. A path is accepted (`http://192.168.1.10/app/`). |
| `rewrite_paths` | `true` | Rewrites the paths of the app (see below). Turn off for an app that already handles the `X-Ingress-Path` header. |
| `rewrite_prefixes` | empty | Advanced: more texts after which a path is rewritten. |
| `max_body_mb` | `100` | Largest upload, in MB. |
| `timeout` | `120` | Seconds to wait for an answer of the app. A WebSocket with no traffic for that long is closed. |

The panel title and icon are fixed (a Home Assistant limit: they are not
options). The panel is shown to administrators only.

## What is rewritten

Behind the ingress, the app is not at `/` but under a path such as
`/api/hassio_ingress/<token>/`. Most apps write links starting with `/`
(`/static/style.css`, `/login`), which would leave the ingress. With
`rewrite_paths` on, the add-on:

- rewrites redirections (`Location`) and the path of cookies;
- rewrites, in HTML, CSS, JavaScript and JSON answers, a path starting with
  `/` found right after `href="`, `src="`, `action="`, `poster="`,
  `srcset="`, `url(`, `fetch("` and `;url=` (single quotes too);
- sends the `Host`, `Origin` and `Referer` headers the app expects, so that
  its cross-site request checks (CSRF) keep working;
- removes `X-Frame-Options`, since the app is shown inside the panel.

The original `X-Ingress-Path` header is passed on to the app.

Limits:

- a path built in JavaScript at run time is not seen. If it always follows the
  same text, add that text to `rewrite_prefixes` (for example `data-url="`);
- a URL without scheme (`href="//example.com/x"`) is wrongly rewritten;
- an app that sends a `Content-Security-Policy: frame-ancestors` header may
  refuse to be shown in the panel;
- a single-page app with its own router may need a base path setting on its
  side instead.

## Security

- Only the Home Assistant ingress (172.30.32.2) is accepted; no port is
  published.
- Every Home Assistant administrator can open the panel, and so reach the
  app, from wherever Home Assistant is reachable. The login of the app itself
  still applies: keep it.
- The TLS certificate of an `https://` target is not checked (self-signed
  certificates are common on a local network).

## FAQ and troubleshooting

**"No target yet"** — `target_url` is empty or not valid. The reason is in
the **Log** tab.

**"The app does not answer"** — Home Assistant cannot reach the address:
computer off, app stopped, firewall, or a rule between two networks.

**The page shows without style, or links leave the panel** — a path is not
rewritten. Look at the address that fails in the browser developer tools and
add the text that precedes it to `rewrite_prefixes`.

**The add-on does not start** — a host name that cannot be resolved stops
nginx. Use an IP address.

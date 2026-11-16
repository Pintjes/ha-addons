#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Side Door: starts nginx in front of web apps of the local network.

Reads the add-on options, writes the nginx configuration and replaces itself
with nginx. Only the Home Assistant ingress can reach the proxy: no port is
published, Home Assistant does the authentication.

One app is shown alone in the panel. Several apps are shown under a row of
tabs, each app under its own path (/app/<id>/).

nginx relays the requests; njs/side_door.js changes the answers (addresses of
the app moved under the ingress path, cookies in plain HTTP).
"""
import hashlib
import html
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
from urllib.parse import urlsplit

OPTIONS = "/data/options.json"
CONF = "/tmp/side_door.conf"
SHELL_DIR = "/tmp/side_door_web"
NJS_SOURCE = "/njs/side_door.js"
NJS = "/tmp/side_door.js"
PORT = 8792
WEB = "/web"

# What comes right before a root-relative path in a page. The path that
# follows is moved under the ingress path.
PREFIXES = [
    'href="', "href='", 'src="', "src='", 'action="', "action='",
    'poster="', "poster='",
    'srcset="', "srcset='", "url(", 'url("', "url('",
    'fetch("', "fetch('", ";url=",
    # Scripts that load other scripts (JavaScript modules)
    'from"', "from'", 'from "', "from '", 'import"', "import'", 'import "', "import '", 'import("', "import('",
]

HEAD = """\
load_module modules/ngx_http_js_module.so;
daemon off;
worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr warn;

events {
    worker_connections 256;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    # The log only tells when an app sets a cookie: its name and its marks,
    # never its value. It is what explains a login that loops.
    map $upstream_http_set_cookie $sd_cookie {
        default '';
        "~*^(?<sd_cookie_name>[^=;]+)=[^;]*(?<sd_cookie_marks>(?:; *(?:path|domain|max-age|samesite|priority)=[^;,]*|; *expires=[a-z]{3}, [0-9a-z :-]*|; *(?:secure|httponly|partitioned))*)" "$sd_cookie_name$sd_cookie_marks";
    }
    log_format side_door '[side_door] $request_method $uri -> $status, cookie set: $sd_cookie (Home Assistant opened in $http_x_forwarded_proto)';
    access_log /dev/stdout side_door if=$sd_cookie;
    server_tokens off;
    client_body_temp_path /tmp/nginx_body;
    proxy_temp_path /tmp/nginx_proxy;
    js_import sd from %(njs)s;

    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }
    # The browser asks "has it changed?" with the ETag it kept. Only an ETag
    # of this version and configuration is passed on to the app (see MARK in
    # njs/side_door.js); otherwise the app answers in full.
    map $http_if_none_match $sd_if_none_match {
        default '';
        "~^(?:W/)?\\"%(mark)s-(?<sd_etag>[^\\"]*)\\"$" "\\"$sd_etag\\"";
    }
    # 1 when the browser reaches Home Assistant in plain HTTP
    map $http_x_forwarded_proto $sd_plain {
        default  0;
        http     1;
    }
    # The address of Home Assistant as the browser uses it (empty if unknown)
    map "$http_x_forwarded_proto:$http_x_forwarded_host" $sd_public {
        default '';
        "~^(?<sd_public_proto>https?):(?<sd_public_host>[^/ ]+)$" "$sd_public_proto://$sd_public_host";
    }
%(maps)s
    server {
        listen %(port)d;
        # Home Assistant ingress only
        allow 172.30.32.2;
        allow 127.0.0.1;
        deny all;
        root %(web)s;
        # A rewritten redirection stays a path: the browser keeps the address
        # it used to reach Home Assistant
        absolute_redirect off;
"""

NOT_SET = """\
        location / {
            default_type text/html;
            try_files /not_configured.html =404;
        }
    }
}
"""

SERVER = """\
        client_max_body_size %(max_body_mb)dm;
        error_page 502 503 504 /side_door_unreachable.html;

        location = /side_door_unreachable.html {
            internal;
            try_files /unreachable.html =502;
        }

        # The script of the option inject_script
        location = /side_door_shim.js {
            add_header Cache-Control no-cache;
            try_files /shim.js =404;
        }
"""

SHELL_LOCATION = """\

        location = / {
            root %(shell_dir)s;
            add_header Cache-Control no-store;
            try_files /index.html =404;
        }
"""

APP_LOCATION = """\

        location %(path)s {
            # Which app of njs/side_door.js this is
            set $sd_app %(n)d;
            proxy_pass %(target)s;
            proxy_http_version 1.1;
            proxy_set_header Host %(host)s;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            # The target sees requests coming from its own address
            proxy_set_header Origin $sd_origin_%(n)d;
            proxy_set_header Referer $sd_referer_%(n)d;
%(forwarded)s            # Answers must come uncompressed to be rewritten
            proxy_set_header Accept-Encoding "";
            proxy_set_header If-None-Match $sd_if_none_match;
            proxy_set_header If-Modified-Since "";
            proxy_ssl_server_name on;
            proxy_connect_timeout 10s;
            proxy_read_timeout %(timeout)ds;
            proxy_send_timeout %(timeout)ds;
            proxy_buffering off;
            # The page is shown inside the Home Assistant panel
            proxy_hide_header X-Frame-Options;
            js_header_filter sd.headers;
            js_body_filter sd.body buffer_type=buffer;
%(rewrite)s        }
"""

# A single app with a start page: the panel opens on that page
START_LOCATION = """\

        location = / {
            return 302 $http_x_ingress_path/%(start)s;
        }
"""

# What the app is told about the browser behind Home Assistant
FORWARDED = """\
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
"""
# Option hide_proxy: nothing. Some apps treat a relayed request as coming from
# outside and ask for a login they do not ask on the local network.
NOT_FORWARDED = """\
            proxy_set_header X-Forwarded-For "";
            proxy_set_header X-Forwarded-Host "";
            proxy_set_header X-Forwarded-Proto "";
            proxy_set_header X-Real-IP "";
            proxy_set_header Forwarded "";
            proxy_set_header Via "";
"""

MAPS = """\
    map $http_origin $sd_origin_%(n)d {
        ''      '';
        default %(origin)s;
    }
    map $http_referer $sd_referer_%(n)d {
        ''      '';
        default %(origin)s/;
    }
"""

SHELL = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Side Door</title>
<style>
  html, body { height: 100%%; margin: 0; }
  body { display: flex; flex-direction: column; font-family: system-ui, sans-serif;
         background: #f4f6f8; color: #1c2733; }
  nav { display: flex; gap: .25rem; padding: 0 .5rem; overflow-x: auto; flex: none;
        background: #fff; border-bottom: 1px solid #d5dbe1; }
  nav button { font: inherit; color: inherit; background: none; border: 0; border-bottom: 3px solid transparent;
               padding: .6rem .9rem .45rem; cursor: pointer; white-space: nowrap; opacity: .7; }
  nav button:hover { opacity: 1; }
  nav button.on { opacity: 1; font-weight: 600; color: #1f6feb; border-bottom-color: #1f6feb; }
  nav button[hidden] { display: none; }
  nav .tabs { display: flex; gap: .25rem; flex: 1; }
  nav svg { width: 18px; height: 18px; fill: currentColor; vertical-align: -3px; }
  nav button.eye { padding: .5rem .6rem; margin-left: auto; }
  nav button.eye.on { border-bottom-color: transparent; color: #1f6feb; }
  nav button .vis { display: none; margin-left: .4rem; }
  body.editing nav .tabs button .vis { display: inline; }
  body.editing nav .tabs button.off { opacity: .45; text-decoration: line-through; }
  main { flex: 1; position: relative; }
  iframe { position: absolute; inset: 0; width: 100%%; height: 100%%; border: 0; background: #fff; }
  iframe[hidden] { display: none; }
  .none { padding: 2rem; text-align: center; opacity: .8; }
  @media (prefers-color-scheme: dark) {
    body { background: #111a22; color: #e3e8ee; }
    nav { background: #1c2733; border-bottom-color: #2b3947; }
    nav button.on { color: #6ea8ff; border-bottom-color: #6ea8ff; }
  }
</style>
</head>
<body>
<nav><div class="tabs">%(tabs)s</div><button type="button" class="eye"
  title="Show or hide apps / Afficher ou masquer des applications"></button></nav>
<main></main>
<script>
  // One frame per app, created the first time its tab is opened: an app keeps
  // its page when you come back to it.
  const tabs = [...document.querySelectorAll("nav .tabs button")];
  const eye = document.querySelector("nav button.eye");
  const main = document.querySelector("main");
  const frames = {};
  tabs.forEach((t) => { t.dataset.name = t.textContent.trim(); });
  function find(key) {
    key = (key || "").trim().toLowerCase();
    return tabs.find((t) => t.dataset.app === key || t.dataset.name.toLowerCase() === key);
  }
  // Apps hidden with the eye: a choice of this browser, kept in it
  const EYE = "M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,17A5,5 0 0,1 7,12A5,5 0 0,1 "
    + "12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17M12,4.5C7,4.5 2.73,7.61 1,12C2.73,16.39 7,19.5 12,19.5C17,19.5 21.27,16.39 "
    + "23,12C21.27,7.61 17,4.5 12,4.5Z";
  const EYE_OFF = "M11.83,9L15,12.16C15,12.11 15,12.05 15,12A3,3 0 0,0 12,9C11.94,9 11.89,9 11.83,9M7.53,9.8L9.08,11.35"
    + "C9.03,11.56 9,11.77 9,12A3,3 0 0,0 12,15C12.22,15 12.44,14.97 12.65,14.92L14.2,16.47C13.53,16.8 12.79,17 12,17"
    + "A5,5 0 0,1 7,12C7,11.21 7.2,10.47 7.53,9.8M2,4.27L4.28,6.55L4.73,7C3.08,8.3 1.78,10 1,12C2.73,16.39 7,19.5 12,19.5"
    + "C13.55,19.5 15.03,19.2 16.38,18.66L16.81,19.08L19.73,22L21,20.73L3.27,3M12,7A5,5 0 0,1 17,12C17,12.64 16.87,13.26 "
    + "16.64,13.82L19.57,16.75C21.07,15.5 22.27,13.86 23,12C21.27,7.61 17,4.5 12,4.5C10.6,4.5 9.26,4.75 8,5.2L10.17,7.35"
    + "C10.74,7.13 11.35,7 12,7Z";
  function icon(path) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + path + '"/></svg>';
  }
  let hiddenApps = [];
  try { hiddenApps = JSON.parse(localStorage.getItem("side_door_hidden") || "[]"); } catch (error) { /* none */ }
  let editing = false;
  let current = null;
  function isHidden(id) { return hiddenApps.includes(id); }
  function saveHidden() {
    try { localStorage.setItem("side_door_hidden", JSON.stringify(hiddenApps)); } catch (error) { /* private window */ }
  }
  // "?app=<name>" in the address of the panel: a dashboard button opens a given app
  function asked() {
    for (const place of [window.parent, window]) {
      try {
        const app = new URLSearchParams(place.location.search).get("app");
        if (app) return app;
      } catch (error) { /* not the same site */ }
    }
    return null;
  }
  // Between two pages of an app the frame shows its own background: it takes
  // the colour of the page, so that a dark app does not flash white.
  function follow(frame) {
    frame.addEventListener("load", () => {
      try {
        const page = frame.contentDocument;
        const colours = [page.body, page.documentElement].map((part) => getComputedStyle(part).backgroundColor);
        const colour = colours.find((c) => c && c !== "transparent" && !/, 0\\)$/.test(c));
        frame.style.background = colour || "#fff";
      } catch (error) { /* not the same site */ }
    });
  }
  // Back from a login on another site (see web/shim.js): the address of the
  // panel ends with "sd_path=" and the page the app must open. It is taken
  // out of the address, so that reloading the panel does not open it again.
  function comeback() {
    try {
      const where = window.parent.location;
      const at = where.search.indexOf("sd_path=");
      if (at < 0) return "";
      const page = (where.search.slice(at + 8) + where.hash).replace(/^[/]+/, "");
      window.parent.history.replaceState(window.parent.history.state, "",
        where.pathname + where.search.slice(0, at).replace(/[?&]$/, ""));
      return /^[a-z][a-z0-9+.-]*:|(^|[/])[.][.]([/]|$)/i.test(page) ? "" : page;
    } catch (error) {
      return "";
    }
  }
  // "force": an app asked by a dashboard button opens even when hidden here
  function show(key, page, force) {
    let tab = find(key);
    if (!tab || (isHidden(tab.dataset.app) && !force)) tab = tabs.find((t) => !isHidden(t.dataset.app));
    const empty = main.querySelector(".none");
    if (empty) empty.remove();
    if (!tab) {
      current = null;
      tabs.forEach((t) => t.classList.remove("on"));
      for (const key in frames) frames[key].hidden = true;
      const note = document.createElement("div");
      note.className = "none";
      note.textContent = "Every app is hidden: click the eye to show one. / Toutes les applications sont masquées : "
        + "cliquez sur l'œil pour en afficher une.";
      main.appendChild(note);
      return;
    }
    const id = tab.dataset.app;
    current = id;
    tabs.forEach((t) => t.classList.toggle("on", t === tab));
    if (!frames[id]) {
      frames[id] = document.createElement("iframe");
      frames[id].title = tab.dataset.name;
      follow(frames[id]);
      frames[id].src = "app/" + id + "/" + (page || tab.dataset.start || "");
      main.appendChild(frames[id]);
    }
    for (const key in frames) frames[key].hidden = key !== id;
    try { localStorage.setItem("side_door_app", id); } catch (error) { /* private window */ }
  }
  // The row as it must look: a hidden app has no tab, except while choosing
  function draw() {
    document.body.classList.toggle("editing", editing);
    eye.classList.toggle("on", editing);
    eye.innerHTML = icon(EYE);
    tabs.forEach((t) => {
      const off = isHidden(t.dataset.app);
      t.hidden = off && !editing && t.dataset.app !== current;
      t.classList.toggle("off", off);
      t.innerHTML = "";
      t.append(t.dataset.name);
      const mark = document.createElement("span");
      mark.className = "vis";
      mark.innerHTML = icon(off ? EYE_OFF : EYE);
      t.append(mark);
    });
  }
  // A hidden app is not loaded: its frame goes away
  function setHidden(id, off) {
    hiddenApps = hiddenApps.filter((x) => x !== id);
    if (off) {
      hiddenApps.push(id);
      if (frames[id]) { frames[id].remove(); delete frames[id]; }
    }
    saveHidden();
    if (off && current === id) show(null);
    else if (!off && current === null) show(id);
    draw();
  }
  eye.addEventListener("click", () => { editing = !editing; draw(); });
  tabs.forEach((t) => t.addEventListener("click", () => {
    if (editing) setHidden(t.dataset.app, !isHidden(t.dataset.app));
    else show(t.dataset.app);
  }));
  // A single app in the list: no row at all, the app fills the panel
  if (tabs.length < 2) document.querySelector("nav").style.display = "none";
  let last = null;
  try { last = localStorage.getItem("side_door_app"); } catch (error) { /* private window */ }
  const first = find(asked()) ? asked() : null;
  show(first || last, first ? comeback() : "", !!first);
  draw();
  try {
    window.parent.addEventListener("location-changed", () => {
      if (find(asked())) { show(asked(), "", true); draw(); }
    });
  } catch (error) { /* not the same site */ }
</script>
</body>
</html>
"""


def log(message):
    print(f"[side_door] {message}", flush=True)


def parse_target(url):
    """Returns (proxy_pass, origin, host header, base path) or raises ValueError."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("the address must look like http://192.168.1.10:8000")
    if parts.username or parts.password:
        raise ValueError("the address must not contain a user name or a password")
    if parts.query or parts.fragment:
        raise ValueError("the address must not contain '?' or '#'")
    if any(c in url for c in " ;{}$'\"\\"):
        raise ValueError("the address contains a character that is not allowed")
    origin = f"{parts.scheme}://{parts.netloc}"
    base = parts.path or "/"
    if not base.endswith("/"):
        base += "/"
    return origin + base, origin, parts.netloc, base


def redirect_rules(origin, base, ingress):
    """nginx directives moving the redirections and the cookies of the target
    under 'ingress', the path of the app as the browser sees it."""
    lines = [
        f"proxy_redirect {origin}{base} {ingress};",
        f"proxy_redirect {base} {ingress};",
        f"proxy_cookie_path {base} {ingress};",
    ]
    return "".join(f"            {line}\n" for line in lines)


def all_prefixes(extra):
    """The texts found right before a path of an app."""
    prefixes = list(PREFIXES)
    for prefix in extra:
        if not prefix or "\n" in prefix:
            log(f"rewrite_prefixes: {prefix!r} ignored (empty, or contains a line break)")
        elif prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def app_id(name, used):
    """Short id for the path of an app, from its name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def read_apps(options):
    """Valid apps of the options: a list of dicts name, id, target, origin,
    host, base. 'apps' wins over the single 'target_url'."""
    entries = []
    for entry in options.get("apps") or []:
        if isinstance(entry, dict):
            entries.append(((entry.get("name") or "").strip(), (entry.get("url") or "").strip(),
                            (entry.get("start") or "").strip(), entry.get("headers") or "",
                            bool(entry.get("hidden"))))
    single = (options.get("target_url") or "").strip()
    if entries and single:
        log("apps is set: target_url is ignored")
    elif single:
        entries = [("", single, "", "", False)]
    apps, used = [], set()
    for name, url, start, headers, hidden in entries:
        label = name or url or "(empty)"
        if not url:
            log(f"app {label!r} ignored: no address")
            continue
        try:
            target, origin, host, base = parse_target(url)
        except ValueError as error:
            log(f"app {label!r} ignored: {error} (got {url!r})")
            continue
        name = name[:40] or host
        start = start.lstrip("/")
        if not re.fullmatch(r"[A-Za-z0-9._~/#?=&%!-]*", start) or ".." in start:
            log(f"app {label!r}: start page {start!r} ignored (only letters, digits and ._~/#?=&%!- are accepted)")
            start = ""
        # A hidden app keeps its place: the paths of the others do not move
        apps.append({"name": name, "id": app_id(name, used), "target": target,
                     "origin": origin, "host": host, "base": base, "start": start,
                     "hidden": hidden, "headers": [] if hidden else read_headers(label, headers)})
    return apps


# Headers the add-on sets itself: an app entry cannot replace them
OWN_HEADERS = {"host", "connection", "upgrade", "content-length", "transfer-encoding", "accept-encoding",
               "if-none-match", "if-modified-since"}


def read_headers(label, text):
    """Headers sent to an app with every request, written "Name: value" and
    separated by " | ". For an app behind a gate that lets a token in.
    Returns [(name, value)]. The values are secrets: never logged."""
    headers = []
    for part in str(text).split("|"):
        part = part.strip()
        if not part:
            continue
        name, colon, value = part.partition(":")
        name, value = name.strip(), value.strip()
        if not colon or not re.fullmatch(r"[A-Za-z0-9-]+", name) or not value:
            log(f"app {label!r}: a header is ignored (expected \"Name: value\")")
        elif name.lower() in OWN_HEADERS:
            log(f"app {label!r}: header {name} ignored (set by the add-on)")
        elif not re.fullmatch(r"[\x20-\x7e]+", value) or any(c in value for c in "\"$\\;{}"):
            log(f"app {label!r}: header {name} ignored (its value has a character that is not accepted)")
        else:
            headers.append((name, value))
    if headers:
        log(f"app {label!r}: sends the headers {', '.join(name for name, _ in headers)}")
    return headers


def shell_page(apps):
    """The page with the row of tabs."""
    tabs = "".join(
        f'<button type="button" data-app="{app["id"]}" data-start="{html.escape(app["start"])}">'
        f'{html.escape(app["name"])}</button>' for app in apps
    )
    return SHELL % {"tabs": tabs}


def ipv4_servers(origin):
    """The IPv4 addresses ("address:port") of an app given by a host name, or
    None for an app given by an address or a name without IPv4. Home Assistant
    often has no IPv6 route: nginx, left alone, tries the IPv6 addresses of
    the name first, fails, and only then uses the others."""
    parts = urlsplit(origin)
    host, port = parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    try:
        found = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None
    return sorted({f"{info[4][0]}:{port}" for info in found}) or None


def build(options, mark="sd0", resolve=ipv4_servers):
    """Returns (nginx configuration, apps for njs/side_door.js, tabs page or
    None, message for the log)."""
    apps = read_apps(options)
    shown = [app for app in apps if not app["hidden"]]
    if not shown:
        head = HEAD % {"port": PORT, "web": WEB, "njs": NJS, "mark": mark, "maps": ""}
        why = "every app is hidden" if apps else "no valid app"
        return head + NOT_SET, {}, None, f"{why}: set one in the add-on configuration"
    # Tabs as soon as the list has two apps, hidden ones included: hiding an
    # app does not move the others (they would ask for a new login)
    several = len(apps) > 1
    rewrite_on = bool(options.get("rewrite_paths", True))
    inject = bool(options.get("inject_script", False))
    forwarded = NOT_FORWARDED if options.get("hide_proxy", False) else FORWARDED
    prefixes = all_prefixes(options.get("rewrite_prefixes") or [])
    timeout = int(options.get("timeout", 120))
    maps, locations, script_apps = "", "", {}
    for n, app in enumerate(apps, 1):
        if app["hidden"]:
            # Not relayed at all: no tab, and its address answers "not found"
            continue
        path = f"/app/{app['id']}/" if several else "/"
        maps += MAPS % {"n": n, "origin": app["origin"]}
        rewrite = redirect_rules(app["origin"], app["base"], "$http_x_ingress_path" + path) if rewrite_on else ""
        extra = "".join(f'            proxy_set_header {name} "{value}";\n' for name, value in app["headers"])
        target = app["target"]
        servers = resolve(app["origin"])
        if servers:
            # A host name: reached at its IPv4 addresses, under its own name
            scheme, name = app["origin"].split("://")[0], urlsplit(app["origin"]).hostname
            maps += "    upstream sd_app_%d {\n%s    }\n" % (n, "".join(f"        server {s};\n" for s in servers))
            target = f"{scheme}://sd_app_{n}{app['base']}"
            extra += f"            proxy_ssl_name {name};\n"
        locations += APP_LOCATION % {
            "path": path, "target": target, "host": app["host"],
            "n": n, "timeout": timeout, "rewrite": rewrite, "forwarded": forwarded + extra,
        }
        if app["start"] and not several:
            locations += START_LOCATION % {"start": app["start"]}
        script_apps[str(n)] = {
            "path": path, "base": app["base"], "own": app["origin"] + app["base"],
            "rewrite": rewrite_on, "inject": inject, "prefixes": prefixes,
        }
    conf = HEAD % {"port": PORT, "web": WEB, "njs": NJS, "mark": mark, "maps": maps}
    conf += SERVER % {"max_body_mb": int(options.get("max_body_mb", 100))}
    if several:
        conf += SHELL_LOCATION % {"shell_dir": SHELL_DIR}
    conf += locations + "    }\n}\n"
    paths = "paths rewritten" if rewrite_on else "paths not rewritten"
    if inject:
        paths += ", script injected"
    listed = ", ".join(f"{app['name']} -> {app['target']}" for app in shown)
    hidden = [app["name"] for app in apps if app["hidden"]]
    if hidden:
        listed += f" (hidden: {', '.join(hidden)})"
    return conf, script_apps, shell_page(shown) if several else None, f"{len(shown)} app(s), {paths}: {listed}"


def script(source, script_apps, mark="sd0"):
    """njs/side_door.js with the apps of the configuration and the mark."""
    for marker in ("var APPS = {};", "var MARK = '';"):
        if marker not in source:
            raise ValueError(f"{NJS_SOURCE}: line '{marker}' not found")
    source = source.replace("var APPS = {};", "var APPS = " + json.dumps(script_apps, ensure_ascii=True) + ";", 1)
    return source.replace("var MARK = '';", f"var MARK = '{mark}';", 1)


def make_mark(options, source):
    """Changes with the configuration and with the code of the add-on."""
    with open(__file__, "rb") as handle:
        own = handle.read()
    seed = json.dumps(options, sort_keys=True).encode() + source.encode() + own
    return "sd" + hashlib.sha1(seed).hexdigest()[:10]


def main():
    try:
        with open(OPTIONS, encoding="utf-8") as handle:
            options = json.load(handle)
    except (OSError, ValueError) as error:
        log(f"options not readable ({error}): default values")
        options = {}
    with open(NJS_SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    mark = make_mark(options, source)
    conf, script_apps, shell, message = build(options, mark)
    with open(CONF, "w", encoding="utf-8") as handle:
        handle.write(conf)
    with open(NJS, "w", encoding="utf-8") as handle:
        handle.write(script(source, script_apps, mark))
    if shell:
        os.makedirs(SHELL_DIR, exist_ok=True)
        with open(os.path.join(SHELL_DIR, "index.html"), "w", encoding="utf-8") as handle:
            handle.write(shell)
        os.chmod(SHELL_DIR, 0o755)
    log(message)
    if "--check" in sys.argv:
        os.execvp("nginx", ["nginx", "-t", "-c", CONF])
    sys.exit(run_nginx())


# What follows "?" in an address: it may hold a token of the app
PARAMETERS = re.compile(r"\?[^\s\"']*")


def run_nginx():
    """Runs nginx and relays what it says, without the parameters of the
    addresses: nginx writes whole addresses in its error messages."""
    child = subprocess.Popen(["nginx", "-c", CONF], stderr=subprocess.PIPE, text=True, errors="replace")

    def stop(signum, frame):
        child.send_signal(signal.SIGTERM)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    for line in child.stderr:
        sys.stderr.write(PARAMETERS.sub("?...", line))
        sys.stderr.flush()
    return child.wait()


if __name__ == "__main__":
    main()

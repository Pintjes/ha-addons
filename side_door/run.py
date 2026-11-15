#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Side Door: starts nginx in front of web apps of the local network.

Reads the add-on options, writes the nginx configuration and replaces itself
with nginx. Only the Home Assistant ingress can reach the proxy: no port is
published, Home Assistant does the authentication.

One app is shown alone in the panel. Several apps are shown under a row of
tabs, each app under its own path (/a/<id>/).
"""
import html
import json
import os
import re
import sys
from urllib.parse import urlsplit

OPTIONS = "/data/options.json"
CONF = "/tmp/side_door.conf"
SHELL_DIR = "/tmp/side_door_web"
PORT = 8792
WEB = "/web"

# What comes right before a root-relative path in a page. The path that
# follows is moved under the ingress path.
PREFIXES = [
    'href="', "href='", 'src="', "src='", 'action="', "action='",
    'poster="', "poster='",
    'srcset="', "srcset='", "url(", 'url("', "url('",
    'fetch("', "fetch('", ";url=",
]
REWRITTEN_TYPES = "text/css application/javascript text/javascript application/json"

HEAD = """\
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
    access_log off;
    server_tokens off;
    client_body_temp_path /tmp/nginx_body;
    proxy_temp_path /tmp/nginx_proxy;

    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
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
            proxy_pass %(target)s;
            proxy_http_version 1.1;
            proxy_set_header Host %(host)s;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            # The target sees requests coming from its own address
            proxy_set_header Origin $sd_origin_%(n)d;
            proxy_set_header Referer $sd_referer_%(n)d;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header Accept-Encoding "";
            proxy_ssl_server_name on;
            proxy_connect_timeout 10s;
            proxy_read_timeout %(timeout)ds;
            proxy_send_timeout %(timeout)ds;
            proxy_buffering off;
            # The page is shown inside the Home Assistant panel
            proxy_hide_header X-Frame-Options;
%(rewrite)s        }
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
  main { flex: 1; position: relative; }
  iframe { position: absolute; inset: 0; width: 100%%; height: 100%%; border: 0; background: #fff; }
  iframe[hidden] { display: none; }
  @media (prefers-color-scheme: dark) {
    body { background: #111a22; color: #e3e8ee; }
    nav { background: #1c2733; border-bottom-color: #2b3947; }
    nav button.on { color: #6ea8ff; border-bottom-color: #6ea8ff; }
  }
</style>
</head>
<body>
<nav>%(tabs)s</nav>
<main></main>
<script>
  // One frame per app, created the first time its tab is opened: an app keeps
  // its page when you come back to it.
  const tabs = [...document.querySelectorAll("nav button")];
  const main = document.querySelector("main");
  const frames = {};
  function find(key) {
    key = (key || "").trim().toLowerCase();
    return tabs.find((t) => t.dataset.app === key || t.textContent.trim().toLowerCase() === key);
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
  function show(key) {
    const tab = find(key) || tabs[0];
    const id = tab.dataset.app;
    tabs.forEach((t) => t.classList.toggle("on", t === tab));
    if (!frames[id]) {
      frames[id] = document.createElement("iframe");
      frames[id].title = tab.textContent;
      frames[id].src = "a/" + id + "/";
      main.appendChild(frames[id]);
    }
    for (const key in frames) frames[key].hidden = key !== id;
    try { localStorage.setItem("side_door_app", id); } catch (error) { /* private window */ }
  }
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.app)));
  let last = null;
  try { last = localStorage.getItem("side_door_app"); } catch (error) { /* private window */ }
  show(find(asked()) ? asked() : last);
  try {
    window.parent.addEventListener("location-changed", () => { if (find(asked())) show(asked()); });
  } catch (error) { /* not the same site */ }
</script>
</body>
</html>
"""


def log(message):
    print(f"[side_door] {message}", flush=True)


def quote(text, variable=""):
    """nginx single-quoted string, optionally ended by an nginx variable.
    A '$' in the text would start a variable: such texts are refused before."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + variable + "'"


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


def rewrite_rules(origin, base, extra, ingress, rewrite_on, inject):
    """nginx directives moving the paths of the target under 'ingress', the
    path of the app as the browser sees it. 'inject' also loads the script
    that moves the addresses the app builds in JavaScript."""
    if not rewrite_on and not inject:
        return ""
    lines = []
    if rewrite_on:
        lines += [
            f"proxy_redirect {origin}{base} {ingress};",
            f"proxy_redirect {base} {ingress};",
            f"proxy_cookie_path {base} {ingress};",
        ]
    lines += ["sub_filter_once off;", f"sub_filter_types {REWRITTEN_TYPES};"]
    if inject:
        # No quote in the tag: it stays harmless inside a text of a script
        tag = f"<head><script src=$http_x_ingress_path/side_door_shim.js data-base={ingress}></script>"
        lines += [
            f"sub_filter '<head>' '{tag}';",
            "sub_filter 'window.location' 'window.__sd_loc';",
            "sub_filter 'document.location' 'document.__sd_loc';",
        ]
    if rewrite_on:
        prefixes = list(PREFIXES)
        for prefix in extra:
            if not prefix or "$" in prefix or "\n" in prefix:
                log(f"rewrite_prefixes: {prefix!r} ignored (empty, or contains '$' or a line break)")
            elif prefix not in prefixes:
                prefixes.append(prefix)
        for prefix in prefixes:
            lines.append(f"sub_filter {quote(prefix + base)} {quote(prefix, ingress)};")
    return "".join(f"            {line}\n" for line in lines)


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
            entries.append(((entry.get("name") or "").strip(), (entry.get("url") or "").strip()))
    single = (options.get("target_url") or "").strip()
    if entries and single:
        log("apps is set: target_url is ignored")
    elif single:
        entries = [("", single)]
    apps, used = [], set()
    for name, url in entries:
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
        apps.append({"name": name, "id": app_id(name, used), "target": target,
                     "origin": origin, "host": host, "base": base})
    return apps


def shell_page(apps):
    """The page with the row of tabs."""
    tabs = "".join(
        f'<button type="button" data-app="{app["id"]}">{html.escape(app["name"])}</button>' for app in apps
    )
    return SHELL % {"tabs": tabs}


def build(options):
    """Returns (nginx configuration, tabs page or None, message for the log)."""
    apps = read_apps(options)
    if not apps:
        head = HEAD % {"port": PORT, "web": WEB, "maps": ""}
        return head + NOT_SET, None, "no valid app: set one in the add-on configuration"
    several = len(apps) > 1
    rewrite_on = options.get("rewrite_paths", True)
    inject = bool(options.get("inject_script", False))
    extra = options.get("rewrite_prefixes") or []
    timeout = int(options.get("timeout", 120))
    maps, locations = "", ""
    for n, app in enumerate(apps, 1):
        path = f"/a/{app['id']}/" if several else "/"
        maps += MAPS % {"n": n, "origin": app["origin"]}
        rewrite = rewrite_rules(app["origin"], app["base"], extra, "$http_x_ingress_path" + path, rewrite_on, inject)
        locations += APP_LOCATION % {
            "path": path, "target": app["target"], "host": app["host"],
            "n": n, "timeout": timeout, "rewrite": rewrite,
        }
    conf = HEAD % {"port": PORT, "web": WEB, "maps": maps}
    conf += SERVER % {"max_body_mb": int(options.get("max_body_mb", 100))}
    if several:
        conf += SHELL_LOCATION % {"shell_dir": SHELL_DIR}
    conf += locations + "    }\n}\n"
    paths = "paths rewritten" if rewrite_on else "paths not rewritten"
    if inject:
        paths += ", script injected"
    listed = ", ".join(f"{app['name']} -> {app['target']}" for app in apps)
    return conf, shell_page(apps) if several else None, f"{len(apps)} app(s), {paths}: {listed}"


def main():
    try:
        with open(OPTIONS, encoding="utf-8") as handle:
            options = json.load(handle)
    except (OSError, ValueError) as error:
        log(f"options not readable ({error}): default values")
        options = {}
    conf, shell, message = build(options)
    with open(CONF, "w", encoding="utf-8") as handle:
        handle.write(conf)
    if shell:
        os.makedirs(SHELL_DIR, exist_ok=True)
        with open(os.path.join(SHELL_DIR, "index.html"), "w", encoding="utf-8") as handle:
            handle.write(shell)
        os.chmod(SHELL_DIR, 0o755)
    log(message)
    if "--check" in sys.argv:
        os.execvp("nginx", ["nginx", "-t", "-c", CONF])
    os.execvp("nginx", ["nginx", "-c", CONF])


if __name__ == "__main__":
    main()

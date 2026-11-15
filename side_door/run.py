#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Side Door: starts nginx in front of a web app of the local network.

Reads the add-on options, writes the nginx configuration and replaces itself
with nginx. Only the Home Assistant ingress can reach the proxy: no port is
published, Home Assistant does the authentication.
"""
import json
import os
import sys
from urllib.parse import urlsplit

OPTIONS = "/data/options.json"
CONF = "/tmp/side_door.conf"
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

PROXY = """\
        client_max_body_size %(max_body_mb)dm;
        error_page 502 503 504 /side_door_unreachable.html;

        location = /side_door_unreachable.html {
            internal;
            try_files /unreachable.html =502;
        }

        location / {
            proxy_pass %(target)s;
            proxy_http_version 1.1;
            proxy_set_header Host %(host)s;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            # The target sees requests coming from its own address
            proxy_set_header Origin $target_origin;
            proxy_set_header Referer $target_referer;
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
    }
}
"""

MAPS = """\
    map $http_origin $target_origin {
        ''      '';
        default %(origin)s;
    }
    map $http_referer $target_referer {
        ''      '';
        default %(origin)s/;
    }
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
        raise ValueError("target_url must look like http://192.168.1.10:8000")
    if parts.username or parts.password:
        raise ValueError("target_url must not contain a user name or a password")
    if parts.query or parts.fragment:
        raise ValueError("target_url must not contain '?' or '#'")
    if any(c in url for c in " ;{}$'\"\\"):
        raise ValueError("target_url contains a character that is not allowed")
    origin = f"{parts.scheme}://{parts.netloc}"
    base = parts.path or "/"
    if not base.endswith("/"):
        base += "/"
    return origin + base, origin, parts.netloc, base


def rewrite_rules(origin, base, extra):
    """nginx directives moving the paths of the target under the ingress path."""
    ingress = "$http_x_ingress_path/"
    lines = [
        f"proxy_redirect {origin}{base} {ingress};",
        f"proxy_redirect {base} {ingress};",
        f"proxy_cookie_path {base} {ingress};",
        "sub_filter_once off;",
        f"sub_filter_types {REWRITTEN_TYPES};",
    ]
    prefixes = list(PREFIXES)
    for prefix in extra:
        if not prefix or "$" in prefix or "\n" in prefix:
            log(f"rewrite_prefixes: {prefix!r} ignored (empty, or contains '$' or a line break)")
        elif prefix not in prefixes:
            prefixes.append(prefix)
    for prefix in prefixes:
        lines.append(f"sub_filter {quote(prefix + base)} {quote(prefix, ingress)};")
    return "".join(f"            {line}\n" for line in lines)


def build(options):
    """Returns (nginx configuration, message for the log)."""
    url = (options.get("target_url") or "").strip()
    if not url:
        head = HEAD % {"port": PORT, "web": WEB, "maps": ""}
        return head + NOT_SET, "target_url is empty: set it in the add-on configuration"
    try:
        target, origin, host, base = parse_target(url)
    except ValueError as error:
        head = HEAD % {"port": PORT, "web": WEB, "maps": ""}
        return head + NOT_SET, f"{error} (got {url!r})"
    head = HEAD % {"port": PORT, "web": WEB, "maps": MAPS % {"origin": origin}}
    rewrite = ""
    if options.get("rewrite_paths", True):
        rewrite = rewrite_rules(origin, base, options.get("rewrite_prefixes") or [])
    proxy = PROXY % {
        "target": target,
        "host": host,
        "max_body_mb": int(options.get("max_body_mb", 100)),
        "timeout": int(options.get("timeout", 120)),
        "rewrite": rewrite,
    }
    paths = "paths rewritten" if rewrite else "paths not rewritten"
    return head + proxy, f"proxying to {target} ({paths})"


def main():
    try:
        with open(OPTIONS, encoding="utf-8") as handle:
            options = json.load(handle)
    except (OSError, ValueError) as error:
        log(f"options not readable ({error}): default values")
        options = {}
    conf, message = build(options)
    with open(CONF, "w", encoding="utf-8") as handle:
        handle.write(conf)
    log(message)
    if "--check" in sys.argv:
        os.execvp("nginx", ["nginx", "-t", "-c", CONF])
    os.execvp("nginx", ["nginx", "-c", CONF])


if __name__ == "__main__":
    main()

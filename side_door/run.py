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
import concurrent.futures
import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import signal
import ssl
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

OPTIONS = "/data/options.json"
DETECTED = "/data/detected.json"
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
  nav button.info { padding: .5rem .6rem; }
  nav button.info.on { border-bottom-color: transparent; color: #1f6feb; }
  nav .badge { margin-left: .25rem; padding: 0 .4rem; border-radius: 9px; font-size: .75rem; background: #d29922;
               color: #fff; vertical-align: 2px; }
  main[hidden], #report[hidden] { display: none; }
  #report { flex: 1; overflow: auto; padding: .5rem 1rem 1.5rem; }
  #report h2 { margin: .6rem 0 .4rem; font-size: 1.15rem; }
  #report h3 { margin: 0 0 .5rem; font-size: 1rem; }
  #report p { margin: .4rem 0; max-width: 60rem; }
  #report .muted { opacity: .75; font-size: .85rem; }
  #report .app { max-width: 60rem; margin: .8rem 0; padding: .7rem 1rem; border-radius: 8px;
                 background: #fff; border: 1px solid #d5dbe1; }
  #report table { border-collapse: collapse; font-size: .9rem; }
  #report td { padding: .1rem 1.2rem .1rem 0; vertical-align: top; }
  #report td:first-child { min-width: 8rem; }
  #report .tip { margin: .6rem 0 .2rem; padding: .5rem .7rem; border-left: 3px solid #d29922;
                 background: rgba(210, 153, 34, .12); }
  nav button .vis, nav button .link { display: none; margin-left: .4rem; }
  body.editing nav .tabs button .vis, body.editing nav .tabs button .link { display: inline; }
  nav button .link:hover { color: #1f6feb; }
  .toast { position: fixed; left: 50%%; bottom: 1rem; transform: translateX(-50%%); max-width: 90vw; z-index: 9;
           padding: .6rem .9rem; border-radius: 8px; background: #1c2733; color: #e3e8ee;
           box-shadow: 0 2px 10px rgba(0, 0, 0, .35); font-size: .9rem; }
  .toast { padding-right: 2.2rem; }
  .toast input { font: inherit; width: 28rem; max-width: 55vw; margin-left: .4rem; padding: .2rem .4rem;
                 border: 1px solid #2b3947; border-radius: 4px; background: #111a22; color: inherit; }
  .toast button { font: inherit; margin-left: .4rem; padding: .2rem .6rem; border: 1px solid #2b3947;
                  border-radius: 4px; background: #2b3947; color: inherit; cursor: pointer; }
  body.editing nav .tabs button.off { opacity: .45; text-decoration: line-through; }
  main { flex: 1; position: relative; }
  iframe { position: absolute; inset: 0; width: 100%%; height: 100%%; border: 0; background: #fff; }
  iframe[hidden] { display: none; }
  .none { padding: 2rem; text-align: center; opacity: .8; }
  @media (prefers-color-scheme: dark) {
    body { background: #111a22; color: #e3e8ee; }
    nav { background: #1c2733; border-bottom-color: #2b3947; }
    nav button.on { color: #6ea8ff; border-bottom-color: #6ea8ff; }
    #report .app { background: #1c2733; border-color: #2b3947; }
  }
</style>
</head>
<body>
<nav><div class="tabs">%(tabs)s</div><button type="button" class="eye"
  title="Show or hide apps / Afficher ou masquer des applications"></button><button type="button" class="info"
  title="Detected settings / Réglages détectés">%(badge)s</button></nav>
<main></main>
<section id="report" hidden>
%(report)s
</section>
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
  const LINK = "M10.59,13.41C11,13.8 11,14.44 10.59,14.83C10.2,15.22 9.56,15.22 9.17,14.83C7.22,12.88 7.22,9.71 "
    + "9.17,7.76L12.71,4.22C14.66,2.27 17.83,2.27 19.78,4.22C21.73,6.17 21.73,9.34 19.78,11.29L18.29,12.78C18.3,11.96 "
    + "18.17,11.14 17.89,10.36L18.36,9.88C19.54,8.71 19.54,6.81 18.36,5.64C17.19,4.46 15.29,4.46 14.12,5.64L10.59,9.17"
    + "C9.41,10.34 9.41,12.24 10.59,13.41M13.41,9.17C13.8,8.78 14.44,8.78 14.83,9.17C16.78,11.12 16.78,14.29 14.83,16.24"
    + "L11.29,19.78C9.34,21.73 6.17,21.73 4.22,19.78C2.27,17.83 2.27,14.66 4.22,12.71L5.71,11.22C5.7,12.04 5.83,12.86 "
    + "6.11,13.65L5.64,14.12C4.46,15.29 4.46,17.19 5.64,18.36C6.81,19.54 8.71,19.54 9.88,18.36L13.41,14.83C14.59,13.66 "
    + "14.59,11.76 13.41,10.59C13,10.2 13,9.56 13.41,9.17Z";
  // The path a dashboard button needs to open an app ("Navigate" action):
  // the address of this panel in Home Assistant, then "?app=" and the app.
  // When Home Assistant has the "/app/<add-on>" page, that address is given:
  // it works whether or not the add-on is shown in the sidebar, while the
  // sidebar address ("/<add-on>") disappears with the sidebar entry.
  function linkOf(id) {
    let panel = "/";
    try {
      panel = window.parent.location.pathname.replace(/[/]+$/, "");
      const ha = window.parent.document.querySelector("home-assistant");
      const addon = panel.split("/").pop();
      if (ha && ha.hass && ha.hass.panels && ha.hass.panels.app && addon) panel = "/app/" + addon;
    } catch (error) { /* not the same site */ }
    return panel + "?app=" + id;
  }
  // Copied when the browser lets it (on plain HTTP it may not): the field
  // stays selected, ready to be copied by hand
  function copyField(field, button) {
    field.focus();
    field.select();
    let copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { /* not allowed */ }
    button.textContent = copied ? "Copied / Copié" : "Ctrl+C";
  }
  // The two links of an app: with the row of tabs, or the app alone
  function copyLink(tab) {
    document.querySelectorAll(".toast").forEach((old) => old.remove());
    const box = document.createElement("div");
    box.className = "toast";
    const title = document.createElement("div");
    title.textContent = tab.dataset.name + " : path for a dashboard button / chemin pour un bouton (Naviguer)";
    box.append(title);
    const base = linkOf(tab.dataset.app);
    [["With the tabs / Avec les onglets", base], ["Alone / Seule", base + "&only=1"]].forEach(([label, link]) => {
      const row = document.createElement("div");
      row.style.marginTop = ".4rem";
      const name = document.createElement("span");
      name.textContent = label;
      name.style.cssText = "display:inline-block;min-width:11rem";
      const field = document.createElement("input");
      field.readOnly = true;
      field.value = link;
      field.addEventListener("focus", () => field.select());
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Copy / Copier";
      button.addEventListener("click", () => copyField(field, button));
      row.append(name, field, button);
      box.append(row);
    });
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "✕";
    close.title = "Close / Fermer";
    close.style.cssText = "position:absolute;top:.3rem;right:.4rem";
    close.addEventListener("click", () => box.remove());
    box.append(close);
    document.body.appendChild(box);
  }
  function icon(path) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + path + '"/></svg>';
  }
  // The settings report: it takes the place of the apps, which stay loaded
  const INFO = "M11,9H13V7H11M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20"
    + "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M11,17H13V11H11V17Z";
  const info = document.querySelector("nav button.info");
  const report = document.querySelector("#report");
  info.insertAdjacentHTML("afterbegin", icon(INFO));
  function showReport(on) {
    report.hidden = !on;
    main.hidden = on;
    info.classList.toggle("on", on);
  }
  info.addEventListener("click", () => showReport(report.hidden));
  let hiddenApps = [];
  try { hiddenApps = JSON.parse(localStorage.getItem("side_door_hidden") || "[]"); } catch (error) { /* none */ }
  let editing = false;
  let current = null;
  function isHidden(id) { return hiddenApps.includes(id); }
  function saveHidden() {
    try { localStorage.setItem("side_door_hidden", JSON.stringify(hiddenApps)); } catch (error) { /* private window */ }
  }
  // "?app=<name>" in the address of the panel: a dashboard button opens a given app
  function param(name) {
    for (const place of [window.parent, window]) {
      try {
        const value = new URLSearchParams(place.location.search).get(name);
        if (value) return value;
      } catch (error) { /* not the same site */ }
    }
    return null;
  }
  function asked() { return param("app"); }
  // "&only=1" with "?app=": the app alone, without the row of tabs
  function alone() { return !!find(asked()) && /^(1|true|yes)$/i.test(param("only") || ""); }
  function placeRow() {
    document.querySelector("nav").style.display = tabs.length < 2 || alone() ? "none" : "";
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
      // Never another site, nor a way out of the app ("..", also encoded)
      let plain = "";
      try { plain = decodeURIComponent(page); } catch (error) { return ""; }
      return /^[a-z][a-z0-9+.-]*:|(^|[/\\\\])[.][.]([/\\\\]|$)|^[/\\\\]/i.test(plain) ? "" : page;
    } catch (error) {
      return "";
    }
  }
  // "force": an app asked by a dashboard button opens even when hidden here
  function show(key, page, force) {
    showReport(false);
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
      const link = document.createElement("span");
      link.className = "link";
      link.title = "Copy the link for a dashboard button / Copier le lien pour un bouton de tableau de bord";
      link.innerHTML = icon(LINK);
      link.addEventListener("click", (event) => { event.stopPropagation(); copyLink(t); });
      t.append(link);
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
  // A single app in the list, or an app asked alone: no row, the app fills the panel
  placeRow();
  let last = null;
  try { last = localStorage.getItem("side_door_app"); } catch (error) { /* private window */ }
  const first = find(asked()) ? asked() : null;
  show(first || last, first ? comeback() : "", !!first);
  draw();
  try {
    window.parent.addEventListener("location-changed", () => {
      if (find(asked())) { show(asked(), "", true); draw(); }
      placeRow();
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


def discreet(url):
    """An address as the log may show it: without the user name and password
    someone may have written in it ("http://user:password@host/")."""
    return re.sub(r"//[^/@]*@", "//***@", url)


def flag(entry, key, default):
    """A yes/no setting of an app entry; the default when it is not set."""
    value = entry.get(key)
    return default if value is None else bool(value)


def valid_start(start):
    """A start page the add-on accepts: only letters, digits and ._~/#?=&%!-,
    and no way out of the app."""
    return bool(re.fullmatch(r"[A-Za-z0-9._~/#?=&%!-]*", start)) and ".." not in start


def read_apps(options):
    """Valid apps of the options: a list of dicts name, id, target, origin,
    host, base, and the settings of the app. 'apps' wins over the single
    'target_url', which takes the default settings."""
    entries = []
    for entry in options.get("apps") or []:
        if isinstance(entry, dict):
            entries.append(entry)
    single = (options.get("target_url") or "").strip()
    if entries and single:
        log("apps is set: target_url is ignored")
    elif single:
        entries = [{"url": single}]
    apps, used = [], set()
    for entry in entries:
        name, url = (entry.get("name") or "").strip(), (entry.get("url") or "").strip()
        start, headers = (entry.get("start") or "").strip(), entry.get("headers") or ""
        hidden = flag(entry, "hidden", False)
        label = name or discreet(url) or "(empty)"
        if not url:
            log(f"app {label!r} ignored: no address")
            continue
        try:
            target, origin, host, base = parse_target(url)
        except ValueError as error:
            log(f"app {label!r} ignored: {error} (got {discreet(url)!r})")
            continue
        name = name[:40] or host
        start = start.lstrip("/")
        if not valid_start(start):
            log(f"app {label!r}: start page {start!r} ignored (only letters, digits and ._~/#?=&%!- are accepted)")
            start = ""
        verify_tls = str(entry.get("verify_tls") or "auto").lower()
        if verify_tls not in ("auto", "on", "off"):
            log(f"app {label!r}: verify_tls {verify_tls!r} ignored (auto, on or off)")
            verify_tls = "auto"
        # A hidden app keeps its place: the paths of the others do not move
        apps.append({"name": name, "id": app_id(name, used), "target": target,
                     "origin": origin, "host": host, "base": base, "start": start,
                     "hidden": hidden, "headers": [] if hidden else read_headers(label, headers),
                     # On unless turned off: harmless for an app that does
                     # not need it, needed by an app built in JavaScript
                     "rewrite": flag(entry, "rewrite", True), "inject": flag(entry, "inject_script", True),
                     "hide_proxy": flag(entry, "hide_proxy", False), "verify_tls": verify_tls,
                     # What the user wrote: the others are the add-on's own choice
                     # (or, for the ones in "detected", what it found out: see detect)
                     "detected": [],
                     "set":[key for key in ("start", "headers", "rewrite", "inject_script", "hide_proxy",
                                             "verify_tls") if entry.get(key) not in (None, "")]})
    return apps


# The certificates of the public authorities (package ca-certificates)
AUTHORITIES = "/etc/ssl/certs/ca-certificates.crt"


def tls_verified(app):
    """True when the certificate of an https app is checked ("auto": when the
    app is given by a name, not by an IP address)."""
    mode = app["verify_tls"]
    if mode == "auto":
        try:
            ipaddress.ip_address(urlsplit(app["origin"]).hostname)
            mode = "off"
        except ValueError:
            mode = "on"
    return mode == "on"


def tls_rules(app):
    """nginx directives on the certificate of an app reached over HTTPS.
    "auto": checked when the app is given by a name (a public site, or a name
    with a real certificate), not when it is given by an address (a device of
    the local network, most often with a certificate it signed itself)."""
    if not app["origin"].startswith("https://"):
        return ""
    if not tls_verified(app):
        return "            proxy_ssl_verify off;\n"
    return ("            proxy_ssl_verify on;\n"
            f"            proxy_ssl_trusted_certificate {AUTHORITIES};\n"
            "            proxy_ssl_verify_depth 5;\n"
            f"            proxy_ssl_name {urlsplit(app['origin']).hostname};\n")


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


REPORT_STATES = {
    "apply": "auto_settings: apply. A start page that is found is applied; nothing else is.",
    "report": "auto_settings: report. Nothing is applied, it is only said here.",
    "first": "First start of the detection: nothing was applied, it is only said here. "
             "The next start applies the start page found.",
    "off": "auto_settings: off. The apps were not looked at.",
    "none": "The detection did not run.",
}


def sentence(text):
    """A sentence from a fragment of the log: capital letter, full stop."""
    if "_" not in text.split(" ")[0]:  # not the name of a setting
        text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def suggestions(report):
    """How many suggestions (a setting the user may change) the report holds."""
    return sum(1 for app in report["apps"] for each in app["hints"] if each["advice"])


def report_page(report):
    """The part of the tabs page that says what is in effect for each app, what
    the detection found and what it suggests. Made from what the add-on knows
    at its start; everything is escaped (an answer of an app is not trusted)."""
    esc = html.escape
    out = ["<h2>Detected settings / Réglages détectés</h2>",
           f'<p>{esc(REPORT_STATES.get(report["state"], REPORT_STATES["none"]))}</p>',
           '<p class="muted">Seen at the last start of the add-on. '
           "<b>set</b>: written in the configuration. <b>default</b>: the choice of the add-on. "
           "<b>detected</b>: found by the detection. hide_proxy, headers and verify_tls are never set automatically.</p>"]
    for app in report["apps"]:
        out.append(f'<div class="app"><h3>{esc(app["name"])}</h3><table>')
        for name, value, where in app["settings"]:
            out.append(f"<tr><td>{esc(name)}</td><td>{esc(value)}</td><td class=\"muted\">{esc(where)}</td></tr>")
        out.append(f'</table><p>Detection: {esc(app["verdict"])}.</p>')
        for each in app["hints"]:
            if not each["advice"]:
                out.append(f'<p class="muted">{esc(sentence(each["seen"]))}</p>')
                continue
            out.append(f'<div class="tip"><b>{esc(each["setting"])}</b>: suggestion, not applied.<br>'
                       f'{esc(sentence(each["seen"]))} {esc(sentence(each["advice"]))}<br>'
                       f'{esc(sentence(each["warning"]))}</div>')
        out.append("</div>")
    return "\n".join(out)


def shell_page(apps, report=None):
    """The page with the row of tabs (and the settings report, behind the
    button at the end of the row)."""
    tabs = "".join(
        f'<button type="button" data-app="{app["id"]}" data-start="{html.escape(app["start"])}">'
        f'{html.escape(app["name"])}</button>' for app in apps
    )
    report = report or {"state": "none", "apps": []}
    count = suggestions(report)
    badge = f'<span class="badge">{count}</span>' if count else ""
    return SHELL % {"tabs": tabs, "report": report_page(report), "badge": badge}


def name_servers(path="/etc/resolv.conf"):
    """The DNS servers of the add-on, as nginx writes them."""
    found = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    try:
                        address = ipaddress.ip_address(parts[1].split("%")[0])
                    except ValueError:
                        continue
                    found.append(f"[{address}]" if address.version == 6 else str(address))
    except OSError:
        pass
    return found


def by_name(origin):
    """True when the app is given by a host name, not by an IP address."""
    try:
        ipaddress.ip_address(urlsplit(origin).hostname)
        return False
    except ValueError:
        return True


def build(options, mark="sd0", dns=None, probe=None):
    """Returns (nginx configuration, apps for njs/side_door.js, tabs page or
    None, message for the log). 'dns': the DNS servers (read from the system
    when not given). 'probe': what looks at the apps to find out their start
    page (see detect); it gets the apps and returns ({address: start page},
    lines for the log, what the report of the tabs page says)."""
    if dns is None:
        dns = name_servers()
    apps = read_apps(options)
    shown = [app for app in apps if not app["hidden"]]
    if not shown:
        head = HEAD % {"port": PORT, "web": WEB, "njs": NJS, "mark": mark, "maps": ""}
        why = "every app is hidden" if apps else "no valid app"
        return head + NOT_SET, {}, None, f"{why}: set one in the add-on configuration"
    found, notes, facts = probe(shown) if probe else ({}, [], {"state": "none", "apps": {}})
    for app in shown:
        if found.get(app["target"]) and not app["start"]:
            app["start"] = found[app["target"]]
            app["detected"].append("start")
    # Tabs as soon as the list has two apps, hidden ones included: hiding an
    # app does not move the others (they would ask for a new login)
    several = len(apps) > 1
    prefixes = all_prefixes(options.get("rewrite_prefixes") or [])
    timeout = int(options.get("timeout", 120))
    maps, locations, script_apps = "", "", {}
    uses_dns = False
    for n, app in enumerate(apps, 1):
        if app["hidden"]:
            # Not relayed at all: no tab, and its address answers "not found"
            continue
        path = f"/app/{app['id']}/" if several else "/"
        maps += MAPS % {"n": n, "origin": app["origin"]}
        rewrite = ""
        if app["rewrite"]:
            rewrite = redirect_rules(app["origin"], app["base"], "$http_x_ingress_path" + path)
        forwarded = NOT_FORWARDED if app["hide_proxy"] else FORWARDED
        extra = "".join(f'            proxy_set_header {name} "{value}";\n' for name, value in app["headers"])
        extra += tls_rules(app)
        target = app["target"]
        if dns and by_name(app["origin"]):
            # A host name is looked up at each use, not once at the start: a
            # name that does not resolve yet (Internet not ready when Home
            # Assistant starts) only makes its own tab unavailable, and a name
            # whose addresses change (a CDN) is followed. IPv4 only: Home
            # Assistant often has no IPv6 route.
            target = f"$sd_target_{n}"
            extra += (f"            set $sd_target_{n} {app['origin']};\n"
                      f"            rewrite ^{path}(.*)$ {app['base']}$1 break;\n")
            uses_dns = True
        locations += APP_LOCATION % {
            "path": path, "target": target, "host": app["host"],
            "n": n, "timeout": timeout, "rewrite": rewrite, "forwarded": forwarded + extra,
        }
        if app["start"] and not several:
            locations += START_LOCATION % {"start": app["start"]}
        script_apps[str(n)] = {
            "path": path, "base": app["base"], "own": app["origin"] + app["base"],
            "rewrite": app["rewrite"], "inject": app["inject"], "prefixes": prefixes,
        }
    if uses_dns:
        maps += f"    resolver {' '.join(dns)} ipv6=off valid=30s;\n    resolver_timeout 5s;\n"
    elif any(by_name(app["origin"]) for app in shown):
        log("no DNS server found: the names of the apps are looked up once, at the start")
    conf = HEAD % {"port": PORT, "web": WEB, "njs": NJS, "mark": mark, "maps": maps}
    conf += SERVER % {"max_body_mb": int(options.get("max_body_mb", 100))}
    if several:
        conf += SHELL_LOCATION % {"shell_dir": SHELL_DIR}
    conf += locations + "    }\n}\n"
    listed = ", ".join(f"{app['name']} -> {app['target']}{settings(app)}" for app in shown)
    hidden = [app["name"] for app in apps if app["hidden"]]
    if hidden:
        listed += f" (hidden: {', '.join(hidden)})"
    message = f"{len(shown)} app(s): {listed}"
    for app in shown:
        message += f"\n[side_door] {app['name']}: {in_effect(app)}"
    for note in notes:
        message += f"\n[side_door] {note}"
    report = {"state": facts["state"], "apps": []}
    for app in shown:
        fact = facts["apps"].get(app["target"]) or {
            "verdict": "not looked at (auto_settings: off)" if facts["state"] == "off" else "not looked at", "hints": []}
        report["apps"].append({"name": app["name"], "settings": effective(app), **fact})
    return conf, script_apps, shell_page(shown, report) if several else None, message


def settings(app):
    """The settings of an app that are not the default ones, for the log."""
    said = []
    if not app["rewrite"]:
        said.append("paths not rewritten")
    if not app["inject"]:
        said.append("script not injected")
    if app["hide_proxy"]:
        said.append("relay hidden")
    if app["origin"].startswith("https://"):
        said.append("certificate " + ("checked" if "proxy_ssl_verify on;" in tls_rules(app) else "not checked"))
    return f" [{', '.join(said)}]" if said else ""


def effective(app):
    """Every setting of an app as it applies, and where it comes from: [(name,
    value, origin)], origin "set" (written in the configuration), "detected"
    or "default" (the add-on's own choice). The values of 'headers' are
    secrets: only their names are given."""
    def origin(key):
        if key in app["set"]:
            return "set"
        return "detected" if key in app["detected"] else "default"

    def onoff(value):
        return "on" if value else "off"

    rows = [("start", app["start"] or "-", origin("start")),
            ("rewrite", onoff(app["rewrite"]), origin("rewrite")),
            ("inject_script", onoff(app["inject"]), origin("inject_script")),
            ("hide_proxy", onoff(app["hide_proxy"]), origin("hide_proxy"))]
    if app["origin"].startswith("https://"):
        rows.append(("verify_tls", f"{app['verify_tls']} -> certificate {'checked' if tls_verified(app) else 'not checked'}",
                     origin("verify_tls")))
    names = ", ".join(name for name, _ in app["headers"])
    rows.append(("headers", names or "-", origin("headers")))
    return rows


def in_effect(app):
    """The settings of an app, for the log."""
    return "; ".join(f"{name} {value} ({where})" for name, value, where in effective(app))


# Detection of the settings of an app (DOCS.md, "Automatic detection"). Each
# app is looked at once, at the start, with a few plain GET requests: no cookie,
# no identification, no header of the configuration.
MODES = ("off", "report", "apply")
PROBE_SECONDS = 5
PROBE_BYTES = 256 * 1024
REDIRECTIONS = 3
REDIRECTION_CODES = (301, 302, 303, 307, 308)
# What a login looks like: in the address of the page, or as a password field
LOGIN_ADDRESS = re.compile(r"log-?in|log-?on|sign-?in|auth|sso|oauth|session|account", re.I)
PASSWORD_FIELD = re.compile(rb"""type\s*=\s*["']?password""", re.I)
# The address of Home Assistant for the app, as when it relays a request
RELAYED = {"X-Forwarded-For": "172.30.32.2"}


class Failed(Exception):
    """An app could not be looked at (off, too slow, error): nothing is learnt."""


def auto_mode(options):
    """off, report or apply (the default)."""
    mode = str(options.get("auto_settings") or "apply").lower()
    if mode not in MODES:
        log(f"auto_settings {mode!r} ignored (off, report or apply)")
        return "apply"
    return mode


def fetch(app, path, deadline, headers=None):
    """One GET of an app. Returns (status, Location, sets a cookie, start of
    the body) or raises Failed."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise Failed("no answer in time")
    parts = urlsplit(app["origin"])
    sent = {"Host": parts.netloc, "Accept": "text/html,*/*;q=0.8", "Accept-Encoding": "identity",
            "User-Agent": "Side-Door"}
    sent.update(headers or {})
    try:
        if parts.scheme == "https":
            cafile = AUTHORITIES if os.path.exists(AUTHORITIES) else None
            context = ssl.create_default_context(cafile=cafile)
            if not tls_verified(app):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(parts.hostname, parts.port, timeout=left, context=context)
        else:
            conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=left)
        try:
            conn.request("GET", path, headers=sent)
            reply = conn.getresponse()
            body = reply.read(PROBE_BYTES)
            return reply.status, reply.getheader("Location") or "", bool(reply.getheader("Set-Cookie")), body
        finally:
            conn.close()
    except ssl.SSLCertVerificationError as error:
        raise Failed("certificate verify failed") from error
    except (OSError, http.client.HTTPException) as error:
        raise Failed(type(error).__name__) from error


def probe_app(app, get=fetch):
    """What one app tells about its start page. Returns {"start": page or "",
    "why": why none was kept, "hints": [what the user may set]}; raises Failed.
    A start page is kept only when the root of the app leads to it by
    redirections that stay on the app and set no cookie, and when it is not a
    login (unknown to the add-on when the app shows it without redirecting)."""
    deadline = time.monotonic() + PROBE_SECONDS
    base, origin = app["base"], app["origin"]
    path, hops, first = base, 0, None
    result = {"start": "", "why": "", "hints": []}
    while True:
        status, location, cookie, body = get(app, path, deadline)
        first = first or (status, location)
        if status >= 500:
            raise Failed(f"answers {status}")
        if status not in REDIRECTION_CODES or not location:
            break
        if cookie:
            result["why"] = "a redirection sets a cookie"
            break
        if hops == REDIRECTIONS:
            result["why"] = f"more than {REDIRECTIONS} redirections"
            break
        target = urlsplit(urljoin(origin + path, location))
        if f"{target.scheme}://{target.netloc}".lower() != origin.lower():
            result["why"] = "the address leads to another site"
            break
        path = (target.path or "/") + (f"?{target.query}" if target.query else "")
        hops += 1
    if first[0] in (401, 403) and "headers" not in app["set"]:
        result["hints"].append(hint("headers", f"answers {first[0]} to a plain request",
                                    "if a gateway guards it, 'headers' can carry the token it lets in",
                                    "never set automatically"))
    if not result["why"]:
        result["why"] = leads_to(result, base, path, status, body)
    if "hide_proxy" not in app["set"] and not app["hide_proxy"]:
        try:
            again = get(app, base, deadline, RELAYED)
            if again[:2] != first:
                result["hints"].append(hint(
                    "hide_proxy", f"answers differently (status {first[0]}, then {again[0]}) when the request looks relayed",
                    "if it asks for a login only through Side Door, set hide_proxy",
                    "never set automatically: it opens the app without login to every Home Assistant administrator"))
        except Failed as error:
            result["hints"].append(hint("hide_proxy", f"hide_proxy not checked: the request that looks relayed failed ({error})"))
    return result


def hint(setting, seen, advice="", warning=""):
    """What the detection saw, and what the user may set because of it. A
    suggestion is never applied. Said in the log as one line."""
    line = f"{seen}: {advice} ({warning})" if advice else seen
    return {"setting": setting, "seen": seen, "advice": advice, "warning": warning, "line": line}


def leads_to(result, base, path, status, body):
    """Sets result["start"] when the page reached from the root is a start
    page; returns what stopped it ("" when nothing has to be said)."""
    if status in (401, 403):
        return f"answers {status}"
    if not 200 <= status < 300:
        return f"answers {status}"
    plain = path.split("?")[0]
    if plain == base:
        return ""
    if not plain.startswith(base):
        return "the page is outside the app address"
    start = path[len(base):]
    if LOGIN_ADDRESS.search(plain):
        return "the page looks like a login (its address)"
    if PASSWORD_FIELD.search(body):
        return "the page has a password field"
    if not valid_start(start):
        return "the address has a character that is not accepted"
    result["start"] = start
    return ""


def load_detected(path):
    """What the last start found, {address of the app: start page}."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}


def save_detected(path, data):
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
        os.replace(path + ".tmp", path)
    except OSError as error:
        log(f"detection: {path} not written ({error})")


def detect(apps, mode, get=fetch, path=DETECTED):
    """Looks at the apps whose start page is not written in the configuration.
    Returns ({address of the app: start page to apply}, lines for the log).
    Only the start page is ever applied, and only in mode "apply". An app that
    cannot be looked at keeps the page found last time; a value written in the
    configuration is never replaced."""
    if mode == "off" or not apps:
        return {}, [], {"state": "off", "apps": {}}
    # The very first time (no file of what was found yet), nothing is applied:
    # the user sees in the log what would be, and the next start applies it
    first = mode == "apply" and not os.path.exists(path)
    applying = mode == "apply" and not first
    not_applied = "first start of the detection: restart to apply it" if first else "auto_settings: report"
    saved = load_detected(path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(apps)) as pool:
        jobs = [(app, pool.submit(probe_app, app, get)) for app in apps]
    keep, notes, facts = {}, [], {}
    for app, job in jobs:
        key, name, written = app["target"], app["name"], "start" in app["set"]
        hints = []
        try:
            result = job.result()
        except Exception as error:  # an app that cannot be looked at must not stop the add-on
            old = saved.get(key, "")
            if str(error) == "certificate verify failed" and "verify_tls" not in app["set"]:
                hints.append(hint("verify_tls", "certificate verify failed",
                                  "verify_tls off lets it in if you trust the network", "never set automatically"))
            if written:
                verdict = f"start page written in the configuration, not replaced; not looked at ({error})"
            else:
                keep[key] = old
                verdict = f"not looked at ({error})" + (f", start page kept as last time: {old}" if old else "")
        else:
            hints = result["hints"]
            # One line for each app that was looked at
            if written:
                verdict = "start page written in the configuration, not replaced"
            else:
                keep[key] = result["start"]
                if result["start"] and applying:
                    verdict = f"start page {result['start']} found (the address redirects there) and applied"
                elif result["start"]:
                    verdict = f"start page {result['start']} found, not applied ({not_applied})"
                elif result["why"]:
                    verdict = f"no start page applied ({result['why']})"
                else:
                    verdict = "no start page needed (the root of the app answers)"
        notes.append(f"{name}: {verdict}")
        notes += [f"{name}: {each['line']}" for each in hints]
        facts[key] = {"verdict": verdict, "hints": hints}
    save_detected(path, keep)
    if first:
        notes.insert(0, "detection: first start, nothing is applied, only said below; the next start applies it")
    found = {key: start for key, start in keep.items() if start and valid_start(start)} if applying else {}
    state = "first" if first else mode
    return found, notes, {"state": state, "apps": facts}


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


def leave(signum, frame):
    os._exit(0)


def main():
    # Looking at the apps may take a few seconds: a stop asked meanwhile must
    # not be ignored (run_nginx takes over once nginx runs)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(signum, leave)
    try:
        with open(OPTIONS, encoding="utf-8") as handle:
            options = json.load(handle)
    except (OSError, ValueError) as error:
        log(f"options not readable ({error}): default values")
        options = {}
    with open(NJS_SOURCE, encoding="utf-8") as handle:
        source = handle.read()
    mark = make_mark(options, source)
    mode = auto_mode(options)
    conf, script_apps, shell, message = build(options, mark, probe=lambda apps: detect(apps, mode))
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

    # Run as process 1, this script dies of no signal it does not catch. The
    # nginx image stops its containers with SIGQUIT: left alone, it was
    # ignored and the container was killed after 10 s, in error.
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(signum, stop)
    for line in child.stderr:
        sys.stderr.write(PARAMETERS.sub("?...", line))
        sys.stderr.flush()
    return child.wait()


if __name__ == "__main__":
    main()

# © 2026 Pintjes. All rights reserved. See LICENSE.
"""What run.py writes from the options: nginx configuration, tabs page, log.

Run from the repository: python -m unittest discover -s side_door/tests -p "test_build.py"
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import threading
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("run", HERE.parent / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

A = {"name": "Immo", "url": "http://192.168.1.10:8000"}
B = {"name": "Plex", "url": "http://192.168.1.20:32400", "start": "web/index.html"}


def build(options, dns=()):
    """(configuration, apps of the script, tabs page, message, log)."""
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        conf, apps, shell, message = run.build(options, "sdtest", list(dns))
    return conf, apps, shell, message, said.getvalue()


class Build(unittest.TestCase):
    def test_nothing_set(self):
        conf, apps, shell, message, _ = build({})
        self.assertIn("not_configured", conf)
        self.assertNotIn("proxy_pass", conf)
        self.assertEqual(apps, {})
        self.assertIsNone(shell)

    def test_refused_addresses(self):
        for bad in ["192.168.1.10:8000", "ftp://x", "http://u:p@h/", "http://h/?a=1", "http://h/a;b",
                    "http://h/$x", "http://"]:
            self.assertNotIn("proxy_pass", build({"target_url": bad})[0], bad)
            self.assertNotIn("proxy_pass", build({"apps": [{"name": "X", "url": bad}]})[0], bad)

    def test_password_of_a_refused_address_is_not_logged(self):
        for options in ({"target_url": "http://user:s3cret@host/"}, {"apps": [{"name": "", "url": "http://user:s3cret@host/"}]}):
            said = build(options)[4]
            self.assertNotIn("s3cret", said)
            self.assertIn("//***@host", said)

    def test_single_app(self):
        conf, apps, shell, _, _ = build({"target_url": A["url"], "rewrite_prefixes": ['data-url="', "pri$x", ""]})
        self.assertIsNone(shell)
        for line in ["location / {", "proxy_pass http://192.168.1.10:8000/;", "set $sd_app 1;",
                     "proxy_redirect / $http_x_ingress_path/;", "proxy_cookie_path / $http_x_ingress_path/;",
                     "js_header_filter sd.headers;", "js_body_filter sd.body buffer_type=buffer;"]:
            self.assertIn(line, conf)
        self.assertNotIn("%(", conf)
        self.assertEqual(apps["1"]["prefixes"], run.PREFIXES + ['data-url="', "pri$x"])
        self.assertEqual(conf, build({"apps": [A]})[0])

    def test_several_apps(self):
        conf, apps, shell, _, _ = build({"target_url": "http://ignored:1", "apps": [
            A, {"name": "<b>NAS & co</b>", "url": "https://nas.lan/app", "inject_script": True},
            dict(A, url="http://10.0.0.5"), {"name": "x", "url": "nope"}]})
        for line in ["location = / {", "location /app/immo/ {", "location /app/b-nas-co-b/ {",
                     "location /app/immo-2/ {", "proxy_pass https://nas.lan/app/;",
                     "proxy_redirect /app/ $http_x_ingress_path/app/b-nas-co-b/;", "set $sd_app 3;"]:
            self.assertIn(line, conf)
        self.assertNotIn("ignored", conf)
        self.assertNotIn("nope", conf)
        self.assertEqual(apps["2"], {"path": "/app/b-nas-co-b/", "base": "/app/", "own": "https://nas.lan/app/",
                                     "rewrite": True, "inject": True, "prefixes": run.PREFIXES})
        self.assertIn('data-app="b-nas-co-b" data-start="">&lt;b&gt;NAS &amp; co&lt;/b&gt;</button>', shell)
        self.assertEqual(shell.count("data-app="), 3)
        self.assertNotIn("%%", shell)

    def test_hidden_app_is_not_relayed_and_moves_nothing(self):
        reference = build({"apps": [A, B, dict(A, url="http://10.0.0.5")]})[0]
        conf, apps, shell, message, _ = build({"apps": [A, dict(B, hidden=True, headers="X-T: secret"),
                                                        dict(A, url="http://10.0.0.5")]})
        self.assertIn("location /app/immo-2/ {", conf)
        self.assertNotIn("/app/plex/", conf)
        self.assertNotIn("32400", conf)
        self.assertNotIn("X-T", conf)
        self.assertEqual(set(apps), {"1", "3"})
        self.assertNotIn('data-app="plex"', shell)
        self.assertIn("(hidden: Plex)", message)
        self.assertEqual(build({"apps": [A, dict(B, hidden=False), dict(A, url="http://10.0.0.5")]})[0], reference)
        self.assertIn("every app is hidden", build({"apps": [dict(A, hidden=True)]})[3])

    def test_start_page(self):
        conf, _, shell, _, said = build({"apps": [A, dict(B, start="/web/index.html"),
                                                  {"name": "Bad", "url": "http://b", "start": 'x"><script>'}]})
        self.assertIn('data-app="plex" data-start="web/index.html">Plex</button>', shell)
        self.assertIn('data-app="bad" data-start="">', shell)
        self.assertIn("start page", said)
        conf = build({"apps": [B]})[0]
        self.assertIn("return 302 $http_x_ingress_path/web/index.html;", conf)

    def test_headers_reach_nginx_but_not_the_log(self):
        conf, _, _, _, said = build({"apps": [A, {"name": "Gate", "url": "https://g.example", "headers":
                                                  "CF-Access-Client-Id: abc.access | CF-Access-Client-Secret: s3cr3t"
                                                  ' | Host: evil | Bad Name: x | X-Q: a"b | X-V: $var | nocolon'}]})
        self.assertIn('proxy_set_header CF-Access-Client-Id "abc.access";', conf)
        self.assertIn('proxy_set_header CF-Access-Client-Secret "s3cr3t";', conf)
        for refused in ["evil", "$var", 'a"b', "Bad Name"]:
            self.assertNotIn(refused, conf)
        self.assertNotIn("s3cr3t", said)
        self.assertIn("sends the headers CF-Access-Client-Id, CF-Access-Client-Secret", said)

    def test_hide_proxy(self):
        self.assertIn("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;", build({"apps": [A]})[0])
        conf = build({"apps": [dict(A, hide_proxy=True)]})[0]
        self.assertIn('proxy_set_header X-Forwarded-For "";', conf)
        self.assertNotIn("$proxy_add_x_forwarded_for", conf)

    def location(self, conf, app_id):
        """The block of an app in the configuration."""
        start = conf.index(f"location /app/{app_id}/ {{")
        return conf[start:conf.index("\n        }\n", start)]

    def test_settings_are_per_app(self):
        conf, apps, _, message, _ = build({"apps": [
            A, dict(B, hide_proxy=True), {"name": "Raw", "url": "http://h", "rewrite": False, "inject_script": False}]})
        immo, plex, raw = self.location(conf, "immo"), self.location(conf, "plex"), self.location(conf, "raw")
        self.assertIn("$proxy_add_x_forwarded_for", immo)
        self.assertIn('proxy_set_header X-Forwarded-For "";', plex)
        self.assertIn("proxy_redirect", immo)
        self.assertNotIn("proxy_redirect", raw)
        # The script is injected unless it is turned off
        self.assertEqual([apps[n]["inject"] for n in "123"], [True, True, False])
        self.assertEqual([apps[n]["rewrite"] for n in "123"], [True, True, False])
        self.assertIn("Plex -> http://192.168.1.20:32400/ [relay hidden]", message)
        self.assertIn("Raw -> http://h/ [paths not rewritten, script not injected]", message)
        self.assertIn("Immo -> http://192.168.1.10:8000/,", message)

    def test_log_says_every_setting_and_where_it_comes_from(self):
        _, _, _, message, _ = build({"apps": [
            A,
            dict(B, hide_proxy=False, headers="X-Token: secret-value"),
            {"name": "Lan", "url": "https://192.168.1.1", "verify_tls": "auto"},
            {"name": "Named", "url": "https://app.example.com"}]})
        lines = {line.split("] ", 1)[1].split(": ", 1)[0]: line for line in message.split("\n")[1:]}
        self.assertEqual(lines["Immo"].split(": ", 1)[1],
                         "start - (default); rewrite on (default); inject_script on (default); "
                         "hide_proxy off (default); headers - (default)")
        # An explicit "off" is a value written by the user, not the default
        self.assertIn("start web/index.html (set)", lines["Plex"])
        self.assertIn("hide_proxy off (set)", lines["Plex"])
        self.assertIn("headers X-Token (set)", lines["Plex"])
        self.assertIn("verify_tls auto -> certificate not checked (set)", lines["Lan"])
        self.assertIn("verify_tls auto -> certificate checked (default)", lines["Named"])
        # Never the value of a header
        self.assertNotIn("secret-value", message)

    def test_configuration_does_not_depend_on_where_a_setting_comes_from(self):
        # Written as the default or left out: the same nginx configuration
        plain = build({"apps": [A]})[0]
        written = build({"apps": [dict(A, rewrite=True, inject_script=True, hide_proxy=False, verify_tls="auto")]})[0]
        self.assertEqual(plain, written)

    def test_old_options_of_the_whole_add_on_are_ignored(self):
        conf, apps, _, _, _ = build({"apps": [A], "inject_script": False, "hide_proxy": True, "rewrite_paths": False})
        self.assertTrue(apps["1"]["inject"])
        self.assertTrue(apps["1"]["rewrite"])
        self.assertIn("$proxy_add_x_forwarded_for", conf)

    def test_certificate(self):
        conf = build({"apps": [
            {"name": "Lan", "url": "https://192.168.1.1"},
            {"name": "Named", "url": "https://plex.example.com"},
            {"name": "Self", "url": "https://nas.local", "verify_tls": "off"},
            {"name": "Forced", "url": "https://10.0.0.9", "verify_tls": "on"},
            {"name": "Plain", "url": "http://10.0.0.8"},
            {"name": "Odd", "url": "https://odd.example", "verify_tls": "maybe"}]})[0]
        checked = "proxy_ssl_verify on;\n            proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;"
        self.assertIn("proxy_ssl_verify off;", self.location(conf, "lan"))
        self.assertIn(checked, self.location(conf, "named"))
        self.assertIn("proxy_ssl_name plex.example.com;", self.location(conf, "named"))
        self.assertIn("proxy_ssl_verify off;", self.location(conf, "self"))
        self.assertIn(checked, self.location(conf, "forced"))
        self.assertNotIn("proxy_ssl_verify", self.location(conf, "plain"))
        self.assertIn(checked, self.location(conf, "odd"))

    def test_certificate_of_a_name_looked_up_at_each_use(self):
        conf = build({"apps": [A, {"name": "R", "url": "https://remote.example"}]}, ["172.30.32.3"])[0]
        block = self.location(conf, "r")
        self.assertIn("proxy_ssl_verify on;", block)
        self.assertEqual(block.count("proxy_ssl_name remote.example;"), 1)

    def test_host_name_is_looked_up_at_each_use(self):
        conf = build({"apps": [A, {"name": "R", "url": "https://remote.example/x"}]}, ["172.30.32.3", "[fd00::1]"])[0]
        self.assertIn("    resolver 172.30.32.3 [fd00::1] ipv6=off valid=30s;", conf)
        block = self.location(conf, "r")
        self.assertIn("set $sd_target_2 https://remote.example;", block)
        self.assertIn("rewrite ^/app/r/(.*)$ /x/$1 break;", block)
        self.assertIn("proxy_pass $sd_target_2;", block)
        self.assertIn("proxy_pass http://192.168.1.10:8000/;", self.location(conf, "immo"))

    def test_without_dns_server_a_name_is_looked_up_at_the_start(self):
        conf, _, _, _, said = build({"apps": [A, {"name": "R", "url": "https://remote.example/x"}]})
        self.assertNotIn("resolver", conf)
        self.assertIn("proxy_pass https://remote.example/x/;", conf)
        self.assertIn("no DNS server found", said)

    def test_no_resolver_when_every_app_is_given_by_address(self):
        self.assertNotIn("resolver", build({"apps": [A, B]}, ["172.30.32.3"])[0])

    def test_name_servers_of_the_system(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as handle:
            handle.write("# comment\nnameserver 172.30.32.3\nnameserver fe80::1%eth0\nnameserver bad\noptions ndots:0\n")
        try:
            self.assertEqual(run.name_servers(handle.name), ["172.30.32.3", "[fe80::1]"])
        finally:
            pathlib.Path(handle.name).unlink()
        self.assertEqual(run.name_servers("/does/not/exist"), [])

    def test_log_of_nginx_loses_the_parameters_of_addresses(self):
        line = '[error] connect() failed, request: "GET /app/p/hubs?type=2&X-Plex-Token=SECRET HTTP/1.1", ' \
               'upstream: "https://[2606::1]:443/hubs?X-Plex-Token=SECRET", referrer: "http://ha/x?app=Plex"'
        clean = run.PARAMETERS.sub("?...", line)
        self.assertNotIn("SECRET", clean)
        self.assertEqual(clean.count("?..."), 3)

    def test_way_back_from_a_login_never_leaves_the_app(self):
        shell = build({"apps": [A, B]})[2]
        self.assertIn("plain = decodeURIComponent(page)", shell)

    def test_script_receives_the_apps_and_the_mark(self):
        source = (HERE.parent / "njs" / "side_door.js").read_text(encoding="utf-8")
        _, apps, _, _, _ = build({"apps": [A, B]})
        out = run.script(source, apps, "sdtest")
        self.assertIn('var APPS = {"1"', out)
        self.assertIn("var MARK = 'sdtest';", out)
        self.assertNotEqual(run.make_mark({"a": 1}, source), run.make_mark({"a": 2}, source))


class Site:
    """A small web server of the tests. 'routes': path -> (status, headers, body), or a function of
    the request returning that. 'seen': (path, X-Forwarded-For) of each request."""

    def __init__(self, routes):
        site = self
        self.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?")[0]
                site.seen.append((path, self.headers.get("X-Forwarded-For")))
                route = routes.get(path, (404, [], b""))
                status, headers, body = route(self) if callable(route) else route
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def to(place):
    return (302, [("Location", place)], b"")


PAGE = (200, [("Content-Type", "text/html")], b"<html><body>hello</body></html>")


class Detect(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = os.path.join(folder.name, "detected.json")
        # Not the first start of the detection (see test_the_first_start_only_tells)
        with open(self.file, "w", encoding="utf-8") as handle:
            handle.write("{}")

    def site(self, routes):
        site = Site(routes)
        self.addCleanup(site.close)
        return site

    def build(self, options, mode="apply"):
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            conf, apps, shell, message = run.build(
                options, "sdtest", [], probe=lambda found: run.detect(found, mode, path=self.file))
        return conf, shell, message

    def test_a_root_that_leads_to_a_page_gives_the_start_page(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        conf, _, message = self.build({"apps": [{"name": "P", "url": site.url}]})
        self.assertIn("return 302 $http_x_ingress_path/web/index.html;", conf)
        self.assertIn("start web/index.html (detected)", message)
        self.assertIn("P: start page web/index.html found (the address redirects there) and applied", message)

    def test_with_several_apps_the_tab_opens_on_the_start_page(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        other = self.site({"/": PAGE})
        _, shell, _ = self.build({"apps": [{"name": "P", "url": site.url}, {"name": "Q", "url": other.url}]})
        self.assertIn('data-start="web/index.html"', shell)

    def test_a_start_page_is_kept_only_when_it_is_not_a_login_or_a_leak(self):
        cases = {
            "login address": ({"/": to("/accounts/login/"), "/accounts/login/": PAGE}, "looks like a login"),
            "another site": ({"/": to("http://other.example/x")}, "another site"),
            "cookie": ({"/": (302, [("Location", "/home"), ("Set-Cookie", "s=1")], b""), "/home": PAGE}, "cookie"),
            "password field": ({"/": to("/home"), "/home": (200, [], b'<input type="password">')}, "password field"),
            "refused": ({"/": (401, [], b"")}, "answers 401"),
            "loop": ({"/": to("/a"), "/a": to("/b"), "/b": to("/c"), "/c": to("/d"), "/d": PAGE}, "redirections"),
            "no redirection": ({"/": PAGE}, ""),
        }
        for label, (routes, why) in cases.items():
            with self.subTest(label):
                site = self.site(routes)
                conf, _, message = self.build({"apps": [{"name": "P", "url": site.url}]})
                self.assertNotIn("return 302 $http_x_ingress_path/", conf)
                self.assertIn("start - (default)", message)
                self.assertIn(why, message)

    def test_an_app_that_does_not_answer_keeps_what_was_found(self):
        routes = {"/": to("/web/index.html"), "/web/index.html": PAGE}
        site = self.site(routes)
        entry = {"name": "P", "url": site.url}
        self.build({"apps": [entry]})
        site.close()
        conf, _, message = self.build({"apps": [entry]})
        self.assertIn("return 302 $http_x_ingress_path/web/index.html;", conf)
        self.assertIn("not looked at", message)
        self.assertIn("kept as last time: web/index.html", message)

    def test_an_app_that_never_answered_gets_nothing(self):
        conf, _, message = self.build({"apps": [{"name": "P", "url": "http://127.0.0.1:9"}]})
        self.assertNotIn("return 302 $http_x_ingress_path/", conf)
        self.assertIn("P: not looked at", message)

    def test_a_server_error_learns_nothing(self):
        site = self.site({"/": (503, [], b"")})
        self.build({"apps": [{"name": "P", "url": site.url}]})
        with open(self.file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {site.url + "/": ""})
        self.assertIn("answers 503", self.build({"apps": [{"name": "P", "url": site.url}]})[2])

    def test_a_start_page_written_by_hand_is_never_replaced(self):
        site = self.site({"/": to("/other"), "/other": PAGE})
        conf, _, message = self.build({"apps": [{"name": "P", "url": site.url, "start": "mine.html"}]})
        self.assertIn("return 302 $http_x_ingress_path/mine.html;", conf)
        self.assertNotIn("/other", conf)
        self.assertIn("start mine.html (set)", message)

    def test_apps_with_every_setting_written_keep_the_same_configuration(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        # An app behind a login: its root leads to the login page
        gate = self.site({"/": to("/login/"), "/login/": PAGE})
        options = {"apps": [
            {"name": "Plex", "url": site.url, "start": "web/index.html", "hide_proxy": True,
             "rewrite": True, "inject_script": True, "verify_tls": "auto"},
            {"name": "Immo", "url": gate.url}]}
        off = build(dict(options, auto_settings="off"))[0]
        self.assertEqual(self.build(options)[0], off)

    def test_the_first_start_only_tells(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        options = {"apps": [{"name": "P", "url": site.url}]}
        os.remove(self.file)
        conf, _, message = self.build(options)
        self.assertNotIn("return 302 $http_x_ingress_path/", conf)
        self.assertIn("detection: first start, nothing is applied", message)
        self.assertIn("start page web/index.html found, not applied (first start of the detection", message)
        self.assertIn("start - (default)", message)
        # What was found is kept: the next start applies it
        conf, _, message = self.build(options)
        self.assertIn("return 302 $http_x_ingress_path/web/index.html;", conf)
        self.assertNotIn("first start", message)

    def test_a_start_in_report_mode_is_not_a_first_start_for_the_next_apply(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        os.remove(self.file)
        self.build({"apps": [{"name": "P", "url": site.url}]}, "report")
        conf, _, _ = self.build({"apps": [{"name": "P", "url": site.url}]})
        self.assertIn("return 302 $http_x_ingress_path/web/index.html;", conf)

    def test_report_mode_only_tells(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        conf, _, message = self.build({"apps": [{"name": "P", "url": site.url}]}, "report")
        self.assertNotIn("return 302 $http_x_ingress_path/", conf)
        self.assertIn("found, not applied (auto_settings: report)", message)

    def test_off_mode_sends_no_request(self):
        site = self.site({"/": to("/web/index.html")})
        os.remove(self.file)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            found, notes, facts = run.detect(run.read_apps({"apps": [{"name": "P", "url": site.url}]}), "off",
                                             path=self.file)
        self.assertEqual((found, notes, facts["apps"], site.seen), ({}, [], {}, []))
        self.assertFalse(os.path.exists(self.file))

    def test_requests_are_plain_gets_without_the_headers_of_the_configuration(self):
        site = self.site({"/": PAGE})
        self.build({"apps": [{"name": "P", "url": site.url, "headers": "X-Token: abc", "hide_proxy": True}]})
        self.assertEqual(site.seen, [("/", None)])

    def test_a_different_answer_to_a_relayed_request_is_suggested_not_applied(self):
        def root(request):
            return (401, [], b"") if request.headers.get("X-Forwarded-For") else PAGE
        site = self.site({"/": root})
        conf, _, message = self.build({"apps": [{"name": "P", "url": site.url}]})
        self.assertIn("answers differently (status 200, then 401)", message)
        self.assertIn("hide_proxy", message)
        self.assertNotIn('proxy_set_header X-Forwarded-For "";', conf)
        self.assertIn("hide_proxy off (default)", message)
        # Said once it is set
        _, _, message = self.build({"apps": [{"name": "P", "url": site.url, "hide_proxy": False}]})
        self.assertNotIn("answers differently", message)

    def test_a_gateway_answer_suggests_headers_and_changes_nothing(self):
        site = self.site({"/": (403, [], b"")})
        conf, _, message = self.build({"apps": [{"name": "P", "url": site.url}]})
        self.assertIn("answers 403 to a plain request", message)
        self.assertIn("headers - (default)", message)
        self.assertEqual(conf, build({"apps": [{"name": "P", "url": site.url}]})[0])

    def test_each_app_that_was_looked_at_gets_one_line(self):
        plain = self.site({"/": PAGE})
        found = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        gate = self.site({"/": to("/login/"), "/login/": PAGE})
        written = self.site({"/": PAGE})
        _, _, message = self.build({"apps": [
            {"name": "Plain", "url": plain.url}, {"name": "Found", "url": found.url},
            {"name": "Gate", "url": gate.url}, {"name": "Written", "url": written.url, "start": "mine.html"},
            {"name": "Off", "url": "http://127.0.0.1:9"}, {"name": "OffWritten", "url": "http://127.0.0.1:9", "start": "a"}]})
        lines = message.split("\n")
        for name, expected in [
                ("Plain", "no start page needed (the root of the app answers)"),
                ("Found", "start page web/index.html found (the address redirects there) and applied"),
                ("Gate", "no start page applied (the page looks like a login (its address))"),
                ("Written", "start page written in the configuration, not replaced"),
                ("Off", "not looked at ("),
                ("OffWritten", "start page written in the configuration, not replaced; not looked at (")]:
            with self.subTest(name):
                said = [line for line in lines if line.startswith(f"[side_door] {name}: ") and expected in line]
                self.assertEqual(len(said), 1, lines)

    def test_a_failed_check_of_the_relayed_request_is_said(self):
        app = run.read_apps({"apps": [{"name": "P", "url": "http://h"}]})[0]

        def get(app_, path, deadline, headers=None):
            if headers:
                raise run.Failed("TimeoutError")
            return 200, "", False, b""
        result = run.probe_app(app, get)
        self.assertEqual([each["line"] for each in result["hints"]],
                         ["hide_proxy not checked: the request that looks relayed failed (TimeoutError)"])

    def report(self, options, mode="apply"):
        shell = self.build(options, mode)[1]
        return shell[shell.index('<section id="report"'):shell.index("</section>")]

    def test_the_report_says_the_settings_with_their_origin(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        other = self.site({"/": PAGE})
        page = self.report({"apps": [{"name": "P", "url": site.url, "inject_script": False},
                                     {"name": "Q", "url": other.url, "headers": "X-Token: secret"}]})
        self.assertIn("<h3>P</h3>", page)
        self.assertIn("<tr><td>start</td><td>web/index.html</td><td class=\"muted\">detected</td></tr>", page)
        self.assertIn("<tr><td>inject_script</td><td>off</td><td class=\"muted\">set</td></tr>", page)
        self.assertIn("<tr><td>rewrite</td><td>on</td><td class=\"muted\">default</td></tr>", page)
        self.assertIn("<tr><td>headers</td><td>X-Token</td><td class=\"muted\">set</td></tr>", page)
        self.assertIn("Detection: start page web/index.html found (the address redirects there) and applied.", page)
        self.assertIn("Detection: no start page needed (the root of the app answers).", page)
        self.assertIn("auto_settings: apply.", page)
        # Neither a value of 'headers' nor the address of an app
        self.assertNotIn("secret", page)
        self.assertNotIn("127.0.0.1", page)

    def test_the_report_gives_the_suggestions_and_their_warning(self):
        def root(request):
            return (401, [], b"") if request.headers.get("X-Forwarded-For") else PAGE
        relayed = self.site({"/": root})
        guarded = self.site({"/": (403, [], b"")})
        quiet = self.site({"/": PAGE})
        options = {"apps": [{"name": "A", "url": relayed.url}, {"name": "B", "url": guarded.url},
                            {"name": "C", "url": quiet.url}]}
        shell = self.build(options)[1]
        page = self.report(options)
        self.assertIn("<b>hide_proxy</b>: suggestion, not applied.", page)
        self.assertIn("Answers differently (status 200, then 401) when the request looks relayed. "
                      "If it asks for a login only through Side Door, set hide_proxy.", page)
        self.assertIn("Never set automatically: it opens the app without login to every Home Assistant administrator.", page)
        self.assertIn("<b>headers</b>: suggestion, not applied.", page)
        self.assertIn("Answers 403 to a plain request.", page)
        self.assertEqual(page.count("suggestion, not applied"), 2)
        # The button of the row counts them
        self.assertIn('<span class="badge">2</span></button>', shell)
        # Nothing to suggest: no count
        self.assertNotIn('class="badge"', self.build({"apps": [{"name": "A", "url": quiet.url},
                                                              {"name": "B", "url": quiet.url}]})[1])

    def test_the_report_says_why_an_app_was_not_looked_at(self):
        page = self.report({"apps": [{"name": "Off", "url": "http://127.0.0.1:9"},
                                     {"name": "Two", "url": "http://127.0.0.1:9/x"}]})
        self.assertIn("Detection: not looked at (", page)
        page = self.report({"apps": [{"name": "Off", "url": "http://127.0.0.1:9"}, {"name": "Two", "url": "http://h"}]},
                           "off")
        self.assertIn("auto_settings: off.", page)
        self.assertEqual(page.count("Detection: not looked at (auto_settings: off)."), 2)

    def test_the_report_of_the_first_start_and_of_the_report_mode(self):
        site = self.site({"/": to("/web/index.html"), "/web/index.html": PAGE})
        options = {"apps": [{"name": "P", "url": site.url}, {"name": "Q", "url": site.url + "/q/"}]}
        self.assertIn("auto_settings: report. Nothing is applied", self.report(options, "report"))
        os.remove(self.file)
        page = self.report(options)
        self.assertIn("First start of the detection: nothing was applied", page)
        self.assertIn("found, not applied (first start of the detection: restart to apply it).", page)

    def test_what_an_app_answers_is_escaped_in_the_report(self):
        site = self.site({"/": to("/web/<b>x</b>"), "/web/<b>x</b>": PAGE})
        shell = self.build({"apps": [{"name": "<i>P</i>", "url": site.url}, {"name": "Q", "url": site.url}]})[1]
        self.assertNotIn("<i>P</i>", shell)
        self.assertNotIn("<b>x</b>", shell)
        self.assertIn("&lt;i&gt;P&lt;/i&gt;", shell)

    def test_the_tabs_page_is_valid_with_the_report(self):
        shell = self.build({"apps": [{"name": "P", "url": "http://127.0.0.1:9"}, {"name": "Q", "url": "http://h"}]})[1]
        self.assertNotIn("%(", shell)
        self.assertEqual(shell.count('class="info"'), 1)
        self.assertIn('title="Detected settings / Réglages détectés"', shell)

    def test_the_mode_of_auto_settings(self):
        self.assertEqual(run.auto_mode({}), "apply")
        self.assertEqual(run.auto_mode({"auto_settings": "report"}), "report")
        self.assertEqual(run.auto_mode({"auto_settings": "off"}), "off")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.auto_mode({"auto_settings": "x"}), "apply")


if __name__ == "__main__":
    unittest.main()

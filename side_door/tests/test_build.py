# SPDX-License-Identifier: GPL-3.0-or-later
"""What run.py writes from the options: nginx configuration, tabs page, log.

Run from the repository: python -m unittest discover -s side_door/tests -p "test_build.py"
"""
import contextlib
import importlib.util
import io
import pathlib
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


if __name__ == "__main__":
    unittest.main()

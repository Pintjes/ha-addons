# SPDX-License-Identifier: GPL-3.0-or-later
"""The add-on at work, in front of tests/upstream.py: real nginx, real script.

Needs the add-on running on port 8792 with tests/options_live.json, and
upstream.py on port 8000 (see the "Live test" step of .github/workflows/ci.yml).
"""
import gzip
import importlib.util
import json
import pathlib
import unittest
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("upstream", HERE / "upstream.py")
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)

DOOR = "http://127.0.0.1:8792"
INGRESS = "/api/hassio_ingress/TOKEN"
APP = INGRESS + "/app/one/"
PUBLIC = "http://ha.test:8123"
# What Home Assistant adds to a request it relays
FROM_HA = {"X-Ingress-Path": INGRESS, "X-Forwarded-Proto": "http", "X-Forwarded-Host": "ha.test:8123",
           "X-Forwarded-For": "192.168.1.50"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)


def get(path, headers=None):
    """(status, headers, body) of an address of the add-on."""
    request = urllib.request.Request(DOOR + path, headers=dict(FROM_HA, **(headers or {})))
    try:
        with opener.open(request, timeout=10) as answer:
            return answer.status, answer.headers, answer.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


class Live(unittest.TestCase):
    def test_tabs_page_lists_the_apps_that_are_not_hidden(self):
        status, _, body = get("/")
        self.assertEqual(status, 200)
        self.assertIn(b'data-app="one"', body)
        self.assertNotIn(b'data-app="two"', body)

    def test_hidden_app_is_not_relayed(self):
        self.assertEqual(get("/app/two/page")[0], 404)

    def test_page_is_rewritten(self):
        status, headers, body = get("/app/one/page")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("<title>café</title>", text)
        self.assertIn(f'<a href="{APP}x">', text)
        self.assertIn('<a href="//other.example/y">', text)
        self.assertIn(f'<img src="{PUBLIC}{APP}i.png">', text)
        self.assertIn(f'<script src="{APP}s.js">', text)
        self.assertNotIn("integrity=", text)
        # Upper and lower case are told apart: these are not paths after 'url(' or 'href='
        self.assertIn('r.resolveUrl("/web");e.baseHref="/";', text)
        self.assertIn("var h=window.__sd_loc.href;", text)
        self.assertIn(f'<head><script src="{INGRESS}/side_door_shim.js" data-base="{APP}"></script>', text)
        self.assertIsNone(headers.get("X-Frame-Options"))
        self.assertEqual(headers.get("Content-Security-Policy"), "default-src 'self' 'unsafe-inline'")
        self.assertTrue(headers.get("ETag").startswith('W/"sd'))

    def test_unchanged_page_is_not_sent_again(self):
        etag = get("/app/one/page")[1].get("ETag")
        self.assertEqual(get("/app/one/page", {"If-None-Match": etag})[0], 304)
        # An ETag of another version or configuration is not passed on
        self.assertEqual(get("/app/one/page", {"If-None-Match": '"abc"'})[0], 200)

    def test_compressed_answer_is_left_alone(self):
        status, headers, body = get("/app/one/gzip")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertEqual(gzip.decompress(body).decode("utf-8"), upstream.PAGE)

    def test_page_not_in_utf8_is_left_alone(self):
        for path in ("/app/one/latin1", "/app/one/latin1-unsaid"):
            status, _, body = get(path)
            self.assertEqual(status, 200)
            self.assertEqual(body, upstream.LATIN1, path)

    def test_binary_answer_is_left_alone(self):
        self.assertEqual(get("/app/one/bin")[2], b'\x00\xff href="/x" \xe9')

    def test_redirection_stays_in_the_panel(self):
        status, headers, _ = get("/app/one/redirect")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), APP + "login")

    def test_permanent_redirection_is_not_kept(self):
        status, headers, _ = get("/app/one/moved")
        self.assertEqual(status, 301)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_cookie_in_plain_http(self):
        cookie = get("/app/one/cookie")[1].get("Set-Cookie")
        self.assertIn(f"Path={APP}", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertNotIn("secure", cookie.lower())
        self.assertNotIn("partitioned", cookie.lower())
        self.assertNotIn("domain", cookie.lower())

    def test_cookie_over_https_is_left_alone(self):
        cookie = get("/app/one/cookie", {"X-Forwarded-Proto": "https"})[1].get("Set-Cookie")
        self.assertIn("Secure", cookie)
        self.assertIn("Partitioned", cookie)
        self.assertIn("SameSite=None", cookie)
        self.assertNotIn("domain", cookie.lower())

    def test_own_addresses_in_an_api_answer(self):
        answer = json.loads(get("/app/one/graphql")[2])
        self.assertEqual(answer, {"u": f"{PUBLIC}{APP}a", "v": f"{PUBLIC}{APP}b"})

    def test_what_the_app_is_told(self):
        seen = json.loads(get("/app/one/echo", {"Origin": "http://ha.test:8123", "If-Modified-Since": "x"})[2])
        self.assertEqual(seen["host"], "127.0.0.1:8000")
        self.assertEqual(seen["origin"], "http://127.0.0.1:8000")
        self.assertTrue(seen["x-forwarded-for"].startswith("192.168.1.50"))
        self.assertEqual(seen["x-test"], "yes")
        self.assertNotIn("if-modified-since", seen)
        self.assertNotIn("accept-encoding", seen)

    def test_name_that_does_not_resolve_only_takes_down_its_own_tab(self):
        # The add-on started although this name does not exist: the other
        # tests reached it. Its tab says the app does not answer.
        status, _, body = get("/app/ghost/")
        self.assertEqual(status, 502)
        self.assertIn(b"does not answer", body)
        self.assertIn(b'data-app="ghost"', get("/")[2])

    def test_script_of_the_option_inject_script(self):
        status, _, body = get("/side_door_shim.js")
        self.assertEqual(status, 200)
        self.assertIn(b"__sd_loc", body)


if __name__ == "__main__":
    unittest.main()

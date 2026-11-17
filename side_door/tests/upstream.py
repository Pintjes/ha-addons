# SPDX-License-Identifier: GPL-3.0-or-later
"""A small app for test_live.py: each address answers the way some real app
does (compressed anyway, not in UTF-8, with a cookie reserved to HTTPS...).

python side_door/tests/upstream.py   (listens on 127.0.0.1:8000)
"""
import gzip
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fixed: test_live.py imports this file to compare what it receives
PORT = 8000
OWN = f"http://127.0.0.1:{PORT}/"

PAGE = (
    '<html><head><title>café</title></head><body><a href="/x">l</a><a href="//other.example/y">o</a>'
    f'<img src="{OWN}i.png"><script integrity="sha256-abc" src="/s.js"></script>'
    '<script>r.resolveUrl("/web");e.baseHref="/";var h=window.location.href;</script></body></html>'
)
LATIN1 = '<html><head></head><body>café crème <a href="/x">l</a></body></html>'.encode("latin-1")


class App(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def answer(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        html = [("Content-Type", "text/html; charset=utf-8")]
        if path == "/page":
            if self.headers.get("If-None-Match") == '"abc"':
                self.answer(304, headers=[("ETag", '"abc"')])
            else:
                self.answer(200, PAGE.encode(), html + [("ETag", '"abc"'), ("X-Frame-Options", "DENY"), (
                    "Content-Security-Policy", "default-src 'self' 'unsafe-inline'; frame-ancestors 'none'")])
        elif path == "/gzip":
            # Compressed although nobody asked for it
            self.answer(200, gzip.compress(PAGE.encode()), html + [("Content-Encoding", "gzip")])
        elif path == "/latin1":
            self.answer(200, LATIN1, [("Content-Type", "text/html; charset=iso-8859-1")])
        elif path == "/latin1-unsaid":
            self.answer(200, LATIN1, [("Content-Type", "text/html")])
        elif path == "/redirect":
            self.answer(302, headers=[("Location", "/login")])
        elif path == "/moved":
            self.answer(301, headers=[("Location", "/x"), ("Cache-Control", "max-age=31536000")])
        elif path == "/cookie":
            self.answer(200, b"ok", [("Content-Type", "text/plain"),
                                     ("Set-Cookie", "S=1; Path=/; Domain=127.0.0.1; Secure; HttpOnly; SameSite=None; Partitioned")])
        elif path == "/graphql":
            # Its own address, plain and with the slashes escaped as JSON allows
            body = '{"u": "' + OWN + 'a", "v": "' + OWN.replace("/", "\\/") + 'b"}'
            self.answer(200, body.encode(), [("Content-Type", "application/graphql-response+json")])
        elif path == "/stream":
            # A stream of data: a first line, then the next one 3 s later
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for line, pause in ((f'{{"link": "{OWN}a"}}\n', 3), (f'{{"link": "{OWN}b"}}\n', 0)):
                data = line.encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()
                time.sleep(pause)
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/pieces":
            # A page in two pieces, the second one holding another "<head>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for piece in (b'<html><head></head><body>\n', b"<script>var s = '<head>';</script></body></html>\n"):
                self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                self.wfile.flush()
                time.sleep(0.3)
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/bin":
            self.answer(200, b'\x00\xff href="/x" \xe9', [("Content-Type", "application/octet-stream")])
        elif path == "/echo":
            self.answer(200, json.dumps({name.lower(): value for name, value in self.headers.items()}).encode(),
                        [("Content-Type", "text/plain")])
        else:
            self.answer(404, b"not found", [("Content-Type", "text/plain")])

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), App).serve_forever()

# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Node table shown in the Home Assistant sidebar (ingress).

The server only listens on the internal Supervisor network and only accepts
requests relayed by the Home Assistant ingress (Home Assistant authentication).
"""

import json
import time
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from i18n import t

LOG = logging.getLogger("mg.web")
PORT = 8790
ALLOWED = {"172.30.32.2", "127.0.0.1", "::1"}
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
BETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "beta.html")


class WebUI:
    def __init__(self, watch, table):
        self.w = watch
        self.table = table

    def _handler(self):
        ui = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep the log quiet
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                data = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _allowed(self):
                if self.client_address[0] not in ALLOWED:
                    self._send(403, '{"error": "access restricted to the Home Assistant ingress"}')
                    return False
                return True

            def do_GET(self):
                if not self._allowed():
                    return
                path, _, query = self.path.partition("?")
                path = path.rstrip("/")
                if path in ("", "/index.html", "/beta.html"):
                    try:
                        with open(BETA if path == "/beta.html" else PAGE, "rb") as f:
                            self._send(200, f.read(), "text/html; charset=utf-8")
                    except OSError:
                        self._send(500, '{"error": "page not found"}')
                elif path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                elif path == "/api/table":
                    try:
                        data = ui.table.get(force="force=1" in query)
                        self._send(200, json.dumps(data, ensure_ascii=False))
                    except Exception as err:  # noqa: BLE001
                        self._send(503, json.dumps({"error": str(err)}, ensure_ascii=False))
                elif path == "/api/node":
                    try:
                        nid = f"{int(query.split('id=')[1].split('&')[0], 16):016X}"
                        self._send(200, json.dumps(ui.w.history.node(nid), ensure_ascii=False))
                    except Exception as err:  # noqa: BLE001
                        self._send(400, json.dumps({"error": str(err)}, ensure_ascii=False))
                elif path == "/api/report":
                    try:
                        import report
                        version = getattr(sys.modules.get("__main__"), "VERSION", "?")
                        text = report.build(ui.table.get(), version).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/markdown; charset=utf-8")
                        self.send_header("Content-Disposition",
                                         f'attachment; filename="mesh-guardian-report-{time.strftime("%Y%m%d-%H%M")}.md"')
                        self.send_header("Content-Length", str(len(text)))
                        self.end_headers()
                        self.wfile.write(text)
                    except Exception as err:  # noqa: BLE001
                        self._send(503, json.dumps({"error": str(err)}, ensure_ascii=False))
                else:
                    self._send(404, '{"error": "not found"}')

            def do_POST(self):
                if not self._allowed():
                    return
                path = self.path.partition("?")[0].rstrip("/")
                if path != "/api/ap_name":
                    return self._send(404, '{"error": "not found"}')
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                    ui.table.set_ap_name(str(body.get("bssid") or ""), str(body.get("name") or ""))
                    self._send(200, '{"ok": true}')
                except Exception as err:  # noqa: BLE001
                    self._send(400, json.dumps({"error": str(err)}, ensure_ascii=False))

        return H

    def run(self):
        server = None
        for host in ("172.30.32.1", "0.0.0.0"):
            try:
                server = ThreadingHTTPServer((host, PORT), self._handler())
                LOG.info(t("Node table ready", host=host, port=PORT))
                break
            except OSError as err:
                LOG.debug("Cannot listen on %s:%d: %s", host, PORT, err)
        if server is None:
            LOG.warning(t("Node table unavailable: port {port} in use", port=PORT))
            return
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True, name="webui").start()
        self.w.stop.wait()
        server.shutdown()

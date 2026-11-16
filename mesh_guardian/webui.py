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
from pairing import Pairing, identity

LOG = logging.getLogger("mg.web")
PORT = 8790
ALLOWED = {"172.30.32.2", "127.0.0.1", "::1"}
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PAGE = os.path.join(WEB, "index.html")
SCRIPTS = ("jsqr.js", "qrcode.js")   # QR code reader and writer, loaded by the page when a pairing code needs them


class WebUI:
    def __init__(self, watch, table):
        self.w = watch
        self.table = table
        self.pairing = Pairing()

    def _node(self, nid):
        """(ids of the nodes there now, attributes of this node, its name, area and model)."""
        nodes = self.table._nodes()
        present = {f"{int(n.get('node_id', 0)):016X}" for n in nodes}
        attrs = next(((n.get("attributes") or {}) for n in nodes if f"{int(n.get('node_id', 0)):016X}" == nid), {})
        rid = f"0x{nid.lstrip('0') or '0'}"
        row = next((r for r in self.table.get().get("rows") or [] if r.get("id") == rid), {})
        return present, attrs, row.get("name") or "", row.get("area") or "", row.get("model") or ""

    def pairing_get(self, nid):
        """Pairing code of a node and the kept codes it could take; without node, every code
        whose node is gone (the ones needed to pair a device again)."""
        if nid is None:
            present = {f"{int(n.get('node_id', 0)):016X}" for n in self.table._nodes()}
            return {"free": self.pairing.free(present), "count": self.pairing.count()}
        present, attrs, name, area, model = self._node(nid)
        ident = identity(attrs)
        code = self.pairing.of(nid, attrs, present)
        if code:
            self.pairing.refresh(nid, attrs, name, area, model)
        return {"code": code, "free": [] if code else self.pairing.free(present, ident["vid"], ident["pid"])}

    def pairing_post(self, body):
        if body.get("delete"):
            return {"ok": self.pairing.delete(str(body["delete"]))}
        nid = f"{int(str(body.get('id')), 16):016X}"
        present, attrs, name, area, model = self._node(nid)
        if nid not in present:
            raise ValueError("node")
        if body.get("attach"):
            return {"ok": True, "code": self.pairing.attach(str(body["attach"]), nid, attrs, name, area, model)}
        return {"ok": True, "code": self.pairing.set(nid, attrs, present, str(body.get("code") or ""), name, area, model)}

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
                        with open(PAGE, "rb") as f:
                            self._send(200, f.read(), "text/html; charset=utf-8")
                    except OSError:
                        self._send(500, '{"error": "page not found"}')
                elif path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                elif path.lstrip("/") in SCRIPTS:
                    try:
                        with open(os.path.join(WEB, path.lstrip("/")), "rb") as f:
                            self._send(200, f.read(), "text/javascript; charset=utf-8")
                    except OSError:
                        self._send(404, '{"error": "not found"}')
                elif path == "/api/pairing":   # pairing code of a node (never in the log nor in the report)
                    try:
                        nid = f"{int(query.split('id=')[1].split('&')[0], 16):016X}" if "id=" in query else None
                        self._send(200, json.dumps(ui.pairing_get(nid), ensure_ascii=False))
                    except Exception as err:  # noqa: BLE001
                        LOG.debug("pairing code: %s", type(err).__name__)
                        self._send(400, '{"error": "pairing"}')
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
                elif path == "/api/raw":   # diagnostics: the Thread tables of one node, as received
                    try:
                        nid = int(query.split("id=")[1].split("&")[0], 16)
                        node = next((n for n in ui.table._nodes() if int(n.get("node_id", -1)) == nid), None)
                        attrs = (node or {}).get("attributes") or {}
                        keep = ("0/53/1", "0/53/7", "0/53/8", "0/53/13", "0/51/0")
                        self._send(200, json.dumps({k: attrs.get(k) for k in keep}, ensure_ascii=False))
                    except Exception as err:  # noqa: BLE001
                        self._send(400, json.dumps({"error": str(err)}, ensure_ascii=False))
                elif path == "/api/supervisor":   # diagnostics: restarts read in the Supervisor log
                    sup = getattr(ui.w, "suplog", None)
                    ml = getattr(ui.w, "matterlog", None)
                    self._send(200, json.dumps({**(sup.summary() if sup else {}),
                                                "matter_log": ml.summary() if ml else {}}, ensure_ascii=False))
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

            def _action(self):
                """Action on one node from the table: ping, parent search, recovery attempt, interview."""
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                    nid = f"{int(str(body.get('id')), 16):016X}"
                    act = body.get("action")
                    h = ui.w.healer
                    t0 = time.time()
                    if act == "ping":
                        res = h.matter_command("ping_node", {"node_id": int(nid, 16)}, timeout=60)
                        ok = isinstance(res, dict) and any(res.values())
                        if ok and getattr(ui.w, "live", None):
                            ui.w.live.note_contact(nid, src="ping")
                        out = {"ok": True, "answered": ok}
                    elif act == "parent":
                        if not getattr(ui.w, "reattach", None):
                            raise RuntimeError("parent search unavailable")
                        out = {"ok": True, **ui.w.reattach.run_node(nid)}
                    elif act == "recover":
                        if not getattr(ui.w, "reattach", None):
                            raise RuntimeError("recovery attempt unavailable")
                        out = {"ok": True, **ui.w.reattach.recover_node(nid)}
                    elif act in ("reset_info", "reset"):
                        # factory reset from a distance: only for a node whose pairing code is kept,
                        # or its label would be the only way back
                        if not getattr(ui.w, "reattach", None):
                            raise RuntimeError("reset unavailable")
                        present, attrs = ui._node(nid)[:2]
                        code = ui.pairing.of(nid, attrs, present)
                        if act == "reset_info":
                            fabs = ui.w.reattach.fabrics(nid)[1]
                            out = {"ok": True, "fabrics": [f["name"] for f in fabs], "manual": code["manual"] if code else None}
                        elif not code:
                            out = {"ok": True, "result": "nocode"}
                        else:
                            out = {"ok": True, **ui.w.reattach.reset_node(nid)}
                    elif act == "remove":
                        h.matter_command("remove_node", {"node_id": int(nid, 16)}, timeout=120)
                        out = {"ok": True}
                    elif act == "interview":
                        h.matter_command("interview_node", {"node_id": int(nid, 16)}, timeout=300)
                        out = {"ok": True, "s": round(time.time() - t0)}
                    else:
                        raise ValueError("unknown action")
                    ui.table.cache_t = 0
                    self._send(200, json.dumps(out, ensure_ascii=False))
                except Exception as err:  # noqa: BLE001
                    LOG.warning("action %s: %s", body.get("action") if isinstance(locals().get("body"), dict) else "?", err)
                    self._send(200, json.dumps({"ok": False}, ensure_ascii=False))

            def do_POST(self):
                if not self._allowed():
                    return
                path = self.path.partition("?")[0].rstrip("/")
                if path == "/api/action":
                    return self._action()
                if path == "/api/reread":   # page opened or Refresh: read every node again
                    q = getattr(ui.w, "quality", None)
                    started = bool(q and q.reread_all())
                    return self._send(200, json.dumps({"started": started}))
                if path == "/api/pairing":   # keep, attach or delete a pairing code
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                        return self._send(200, json.dumps(ui.pairing_post(body), ensure_ascii=False))
                    except ValueError as err:   # format, check, device or node: said to the user, the code is not logged
                        why = str(err) if str(err) in ("format", "check", "device", "node") else "format"
                        return self._send(200, json.dumps({"ok": False, "error": why}))
                    except Exception as err:  # noqa: BLE001
                        LOG.warning("pairing code: %s", type(err).__name__)
                        return self._send(200, '{"ok": false, "error": "error"}')
                if path == "/api/br_forget":   # remove an offline border router from the list
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
                        ok = ui.w.forget_br(str(body.get("id") or ""))
                        ui.table.cache_t = 0
                        return self._send(200, json.dumps({"ok": bool(ok)}))
                    except Exception as err:  # noqa: BLE001
                        LOG.warning("br_forget: %s", err)
                        return self._send(200, '{"ok": false}')
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

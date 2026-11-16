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
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from i18n import t
from pairing import Pairing, identity

LOG = logging.getLogger("mg.web")
PORT = 8790
# Only the ingress of Home Assistant (it has checked the user): not the loopback, which any
# process of the host can use when the server listens on every address (fallback below)
ALLOWED = {"172.30.32.2"}
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PAGE = os.path.join(WEB, "index.html")
NEW_NODE_S = 86400   # s: a node paired less than this ago is asked for its pairing code
SCRIPTS = ("jsqr.js", "qrcode.js")   # QR code reader and writer, loaded by the page when a pairing code needs them
MAX_BODY = 4096      # bytes: the largest request of the page is far below
MAX_TEXT = 512       # characters: a pairing code, a name, a key of a kept code
NODE_RE = re.compile(r"^(0x)?[0-9a-fA-F]{1,16}$")


def node_hex(value):
    """Node id sent by the page (hex, as the table shows it) -> 16 hex digits; ValueError("node") otherwise."""
    s = str(value).strip()
    if not NODE_RE.match(s):
        raise ValueError("node")
    return f"{int(s, 16):016X}"


def text_of(body, key):
    """A text field of a request, refused when it is not a short text."""
    v = body.get(key)
    if v is None:
        return ""
    if not isinstance(v, (str, int)) or len(str(v)) > MAX_TEXT:
        raise ValueError("format")
    return str(v)


def _recent(added):
    """True for a commissioning date (ISO text of the Matter Server) less than NEW_NODE_S old.
    A date without time zone is read as local time and as UTC: either may be meant."""
    try:
        when = datetime.fromisoformat(str(added).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if when.tzinfo:
        return abs((datetime.now(timezone.utc) - when).total_seconds()) < NEW_NODE_S
    return min(abs((now - when).total_seconds()) for now in (datetime.now(), datetime.now(timezone.utc).replace(tzinfo=None))) < NEW_NODE_S


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

    def pairing_new(self, rows):
        """Nodes paired in the last day whose pairing code is not kept: [{"id", "name", "area"}].
        The moment to give it is now, while the user still stands in front of the device.
        (Looking a code up also attaches the one that waits for a node since its reset.)"""
        out, nodes = [], None
        for r in rows or []:
            if not _recent(r.get("added")):
                continue
            try:
                if nodes is None:
                    nodes = {f"{int(n.get('node_id', 0)):016X}": n.get("attributes") or {} for n in self.table._nodes()}
                nid = f"{int(str(r.get('id')), 16):016X}"
                if nid in nodes and not self.pairing.of(nid, nodes[nid], set(nodes)):
                    out.append({"id": r.get("id"), "name": r.get("name") or "", "area": r.get("area") or ""})
            except Exception as err:  # noqa: BLE001
                LOG.debug("new node without pairing code: %s", type(err).__name__)
        return out

    def pairing_post(self, body):
        if body.get("delete"):
            return {"ok": self.pairing.delete(text_of(body, "delete"))}
        if body.get("scan"):   # scanned before the pairing: waits for the node it brings
            present = {f"{int(n.get('node_id', 0)):016X}" for n in self.table._nodes()}
            return {"ok": True, "code": self.pairing.scan(text_of(body, "scan"), present)}
        nid = node_hex(body.get("id"))
        present, attrs, name, area, model = self._node(nid)
        if nid not in present:
            raise ValueError("node")
        if body.get("attach"):
            return {"ok": True, "code": self.pairing.attach(text_of(body, "attach"), nid, attrs, name, area, model)}
        return {"ok": True, "code": self.pairing.set(nid, attrs, present, text_of(body, "code"), name, area, model)}

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

            def _same_site(self):
                """A change asked by the page itself, not by another site the user has open: the
                page always sends JSON (another site cannot, without the browser asking this
                server first, which it never accepts), and its origin, when the browser gives
                one, is the address of Home Assistant."""
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._send(415, '{"error": "JSON expected"}')
                    return False
                origin, fwd = self.headers.get("Origin"), self.headers.get("X-Forwarded-Host")
                if origin and fwd:
                    hosts = {h.strip().lower() for h in fwd.split(",")}
                    if urlsplit(origin).netloc.lower() not in hosts:
                        LOG.warning("request refused: origin %s, Home Assistant %s", origin, fwd)
                        self._send(403, '{"error": "other site"}')
                        return False
                return True

            def _body(self):
                """The JSON object sent by the page; ValueError when too large or not an object."""
                n = int(self.headers.get("Content-Length") or 0)
                if n < 0 or n > MAX_BODY:
                    raise ValueError("size")
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("format")
                return body

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
                        # a copy: the table keeps its own. pair_free: codes waiting for their device
                        # (the page shows its "Pairing codes" button only when there is one)
                        data = dict(data, pair_new=ui.pairing_new(data.get("rows")),
                                    pair_free=len(ui.pairing_get(None)["free"]) if ui.pairing.count() else 0)
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
                    body = self._body()
                    nid = node_hex(body.get("id"))
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
                            if out.get("result") in ("reset", "unsure"):
                                ui.pairing.mark_reset(nid)   # its code follows it when it comes back
                    elif act == "remove":
                        # on many devices, leaving their last fabric is a factory reset: same lock as
                        # the other actions on a node, and a trace in the events like the reset
                        rt = getattr(ui.w, "reattach", None)
                        if rt and not rt.busy.acquire(timeout=1):
                            out = {"ok": True, "result": "busy"}
                        else:
                            try:
                                name = ui._node(nid)[2] or f"0x{nid.lstrip('0')}"
                                h.matter_command("remove_node", {"node_id": int(nid, 16)}, timeout=180)
                            finally:
                                if rt:
                                    rt.busy.release()
                            ui.w.emit("node_removed", t("{node}: removed from Home Assistant", node=name), node=name)
                            out = {"ok": True, "result": "removed"}
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
                if not self._allowed() or not self._same_site():
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
                        body = self._body()
                        return self._send(200, json.dumps(ui.pairing_post(body), ensure_ascii=False))
                    except ValueError as err:   # format, check, device or node: said to the user, the code is not logged
                        why = str(err) if str(err) in ("format", "check", "passcode", "device", "node", "typed") else "format"
                        return self._send(200, json.dumps({"ok": False, "error": why}))
                    except Exception as err:  # noqa: BLE001
                        LOG.warning("pairing code: %s", type(err).__name__)
                        return self._send(200, '{"ok": false, "error": "error"}')
                if path == "/api/br_forget":   # remove an offline border router from the list
                    try:
                        body = self._body()
                        ok = ui.w.forget_br(text_of(body, "id"))
                        ui.table.cache_t = 0
                        return self._send(200, json.dumps({"ok": bool(ok)}))
                    except Exception as err:  # noqa: BLE001
                        LOG.warning("br_forget: %s", err)
                        return self._send(200, '{"ok": false}')
                if path != "/api/ap_name":
                    return self._send(404, '{"error": "not found"}')
                try:
                    body = self._body()
                    ui.table.set_ap_name(text_of(body, "bssid"), text_of(body, "name"))
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

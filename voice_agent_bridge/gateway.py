"""Voice Agent Bridge.

OpenAI-compatible endpoint (/v1/models, /v1/chat/completions) that answers
Home Assistant Assist requests with Claude Code (`claude -p`), connected to
Home Assistant through a local ha-mcp server.
"""

import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import prompts

OPTIONS_FILE = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("ADDON_CONFIG_DIR", "/config"))
HA_CONFIG_DIR = Path(os.environ.get("HA_CONFIG_DIR", "/homeassistant"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
HTTP_PORT = int(os.environ.get("GATEWAY_PORT", "8791"))
MCP_PORT = int(os.environ.get("HA_MCP_PORT", "9583"))
SESSION_TTL = 30 * 60
WEB_DIR = Path(os.environ.get("WEB_DIR", Path(__file__).parent / "web"))
INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}

log = logging.getLogger("voice_agent_bridge")


def load_options() -> dict:
    defaults = {
        "language": "en",
        "claude_token": "",
        "anthropic_api_key": "",
        "model": "haiku",
        "effort": "low",
        "web_search": True,
        "read_only": False,
        "forward_ha_prompt": True,
        "max_turns": 12,
        "max_budget_usd": 0.5,
        "timeout": 90,
        "gateway_api_key": "",
        "tool_search": True,
        "ha_tool_modules": "all",
        "notes_file": "",
        "logbook": True,
        "history_days": 90,
        "log_level": "info",
    }
    try:
        defaults.update(json.loads(OPTIONS_FILE.read_text()))
    except FileNotFoundError:
        pass
    return defaults


OPTIONS = load_options()
LANG = OPTIONS["language"] if OPTIONS["language"] in prompts.TEXT else "en"
T = prompts.TEXT[LANG]


# --------------------------------------------------------------------------
# ha-mcp (Home Assistant MCP server), started once and kept warm
# --------------------------------------------------------------------------

def start_ha_mcp() -> str | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.warning("No SUPERVISOR_TOKEN: Home Assistant tools disabled")
        return None
    secret_path = "/mcp-" + secrets.token_urlsafe(16)
    env = dict(os.environ)
    env.update({
        "HOMEASSISTANT_URL": "http://supervisor/core",
        "HOMEASSISTANT_TOKEN": token,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(MCP_PORT),
        "MCP_SECRET_PATH": secret_path,
        "READ_ONLY_MODE": "true" if OPTIONS["read_only"] else "false",
        "ENABLED_TOOL_MODULES": OPTIONS.get("ha_tool_modules") or "all",
        "LOG_LEVEL": "WARNING",
    })
    proc = subprocess.Popen(["ha-mcp-web"], env=env)

    def watch():
        code = proc.wait()
        log.error("ha-mcp stopped (exit code %s), restarting the add-on", code)
        os._exit(1)

    threading.Thread(target=watch, daemon=True).start()
    return f"http://127.0.0.1:{MCP_PORT}{secret_path}"


def write_mcp_config(url: str | None) -> Path:
    servers = {}
    if url:
        servers["homeassistant"] = {"type": "http", "url": url}
    path = DATA_DIR / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def notes_path() -> Path:
    name = (OPTIONS.get("notes_file") or "").strip().lstrip("/")
    if name and ".." not in Path(name).parts:
        return HA_CONFIG_DIR / name
    return CONFIG_DIR / "CLAUDE.md"


def ensure_house_notes() -> Path:
    notes = notes_path()
    if notes.parent == HA_CONFIG_DIR or HA_CONFIG_DIR in notes.parents:
        if not notes.exists():
            log.warning("Notes file %s not found (create it with the File editor)", notes)
        return notes
    notes = CONFIG_DIR / "CLAUDE.md"
    if not notes.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        notes.write_text(T["notes_template"])
        log.info("Created %s: describe your home there", notes)
    return notes


# --------------------------------------------------------------------------
# Conversations: OpenAI clients resend the whole history at every turn.
# We map a hash of that history to the Claude session that produced it.
# --------------------------------------------------------------------------

class Sessions:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, float]] = {}

    @staticmethod
    def key(turns: list[tuple[str, str]]) -> str:
        return hashlib.sha256(json.dumps(turns, ensure_ascii=False).encode()).hexdigest()

    def get(self, turns):
        now = time.time()
        with self._lock:
            for k in [k for k, (_, ts) in self._items.items() if now - ts > SESSION_TTL]:
                del self._items[k]
            item = self._items.get(self.key(turns))
            return item[0] if item else None

    def put(self, turns, session_id):
        with self._lock:
            self._items[self.key(turns)] = (session_id, time.time())


SESSIONS = Sessions()


class History:
    """Conversation history shown in the sidebar panel (one line per exchange)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.items: list[dict] = []
        self.next_id = 1

    def load(self):
        keep_after = time.time() - int(OPTIONS.get("history_days") or 90) * 86400
        try:
            lines = self.path.read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("ts", 0) >= keep_after:
                self.items.append(item)
        self.items = self.items[-5000:]
        self.next_id = max((i.get("id", 0) for i in self.items), default=0) + 1
        if len(self.items) != len(lines):
            self._rewrite()

    def _rewrite(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in self.items))
        tmp.replace(self.path)

    def add(self, conv: str, source: str, place: str, user: str, assistant: str,
            run: str | None = None, ts: float | None = None) -> dict | None:
        with self._lock:
            if run and any(i.get("run") == run for i in self.items):
                return None
            item = {"id": self.next_id, "ts": ts or time.time(), "conv": conv, "source": source,
                    "place": place, "user": user.strip(), "assistant": assistant.strip()}
            if run:
                item["run"] = run
            self.next_id += 1
            self.items.append(item)
            with self.path.open("a") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            if len(self.items) > 6000:
                self.items = self.items[-5000:]
                self._rewrite()
            return item

    def since(self, after: int, limit: int = 500) -> list[dict]:
        with self._lock:
            return [i for i in self.items if i["id"] > after][-limit:]


HISTORY = History(DATA_DIR / "history.jsonl")


def place_from_context(ha_context: str) -> str:
    """First line of the agent prompt, e.g. 'Satellite room: Office' -> 'Office'."""
    first = (ha_context or "").strip().splitlines()[0] if ha_context.strip() else ""
    if ":" not in first or len(first) > 120:
        return ""
    value = first.split(":", 1)[1].strip()
    return "" if value.lower() in ("", "none", "unknown", "inconnue", "inconnu") else value


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def split_messages(messages: list[dict]):
    """Return (ha_context, turns) where turns are (role, text) pairs."""
    ha_context = []
    turns = []
    for m in messages:
        role = m.get("role")
        text = text_of(m.get("content")).strip()
        if role in ("system", "developer"):
            if text:
                ha_context.append(text)
        elif role in ("user", "assistant") and text:
            turns.append((role, text))
    return "\n\n".join(ha_context), turns


# --------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------

def system_prompt() -> str:
    notes = ""
    try:
        notes = notes_path().read_text().strip()
    except OSError:
        pass
    parts = [T["system"]]
    if OPTIONS["read_only"]:
        parts.append(T["read_only"])
    if notes:
        parts.append(T["notes_header"] + "\n\n" + notes)
    return "\n\n".join(parts)


def build_prompt(text: str, ha_context: str, history: list[tuple[str, str]]) -> str:
    now = datetime.now().astimezone()
    lines = [f"[{now:%Y-%m-%d %H:%M} {now.tzname() or ''}]".replace(" ]", "]")]
    if ha_context and OPTIONS["forward_ha_prompt"]:
        lines.append(T["ha_context"] + "\n" + ha_context)
    if history:
        lines.append(T["history"])
        lines += [f"{'User' if r == 'user' else 'Assistant'}: {t}" for r, t in history]
    lines.append(text)
    return "\n\n".join(lines)


def claude_command(prompt: str, resume: str | None, mcp_config: Path) -> list[str]:
    builtin = ["WebSearch", "WebFetch"] if OPTIONS["web_search"] else []
    allowed = ["mcp__homeassistant"] + builtin
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--model", OPTIONS["model"],
        "--system-prompt", system_prompt(),
        "--tools", ",".join(builtin),
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--allowedTools", *allowed,
        "--permission-mode", "dontAsk",
        "--max-turns", str(OPTIONS["max_turns"]),
    ]
    if OPTIONS.get("effort"):
        cmd += ["--effort", OPTIONS["effort"]]
    if OPTIONS.get("max_budget_usd"):
        cmd += ["--max-budget-usd", str(OPTIONS["max_budget_usd"])]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def friendly_error(raw: str) -> str:
    low = (raw or "").lower()
    if any(w in low for w in ("auth", "login", "token", "401", "403", "credential")):
        return T["err_auth"]
    if any(w in low for w in ("limit", "quota", "credit", "429", "usage", "budget")):
        return T["err_limit"]
    if "timeout" in low or "timed out" in low:
        return T["err_timeout"]
    return T["err_generic"]


def run_claude(prompt: str, resume: str | None, mcp_config: Path, on_text):
    """Run Claude, call on_text(delta) for streamed text. Return (text, session_id)."""
    cmd = claude_command(prompt, resume, mcp_config)
    log.debug("Running: %s", " ".join(cmd[:3]) + " ...")
    workdir = DATA_DIR / "workspace"
    workdir.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=claude_env(),
    )
    timer = threading.Timer(OPTIONS["timeout"], proc.kill)
    timer.start()
    streamed: list[str] = []
    session_id = None
    result = None
    need_gap = False
    try:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = ev.get("session_id") or session_id
            etype = ev.get("type")
            if etype == "stream_event":
                inner = ev.get("event", {})
                if inner.get("type") == "content_block_start":
                    if streamed and inner.get("content_block", {}).get("type") == "text":
                        need_gap = True
                elif inner.get("type") == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        piece = delta["text"]
                        if need_gap:
                            piece = " " + piece.lstrip()
                            need_gap = False
                        streamed.append(piece)
                        on_text(piece)
            elif etype == "result":
                result = ev
        proc.wait()
    finally:
        timer.cancel()
    err = proc.stderr.read() if proc.stderr else ""

    if result is None or result.get("is_error"):
        raw = (result or {}).get("result") or err or f"exit code {proc.returncode}"
        if proc.returncode in (-9, 137) and result is None:
            raw = "timeout"
        log.error("Claude error: %s", raw.strip()[:500])
        message = friendly_error(raw)
        if streamed:
            message = " " + message
        on_text(message)
        return "".join(streamed) + message, session_id

    if not streamed and result.get("result"):
        streamed.append(result["result"])
        on_text(result["result"])
    cost = result.get("total_cost_usd")
    usage = result.get("usage") or {}
    log.info("Answered in %.1f s, %s turn(s)%s; tokens in %s, cache write %s, cache read %s, out %s",
             (result.get("duration_ms") or 0) / 1000, result.get("num_turns"),
             f", ${cost:.4f}" if cost else "", usage.get("input_tokens", "?"),
             usage.get("cache_creation_input_tokens", "?"), usage.get("cache_read_input_tokens", "?"),
             usage.get("output_tokens", "?"))
    return "".join(streamed), session_id


def claude_env() -> dict:
    env = dict(os.environ)
    env.pop("SUPERVISOR_TOKEN", None)  # Claude reaches HA only through ha-mcp
    token = OPTIONS.get("claude_token", "").strip()
    key = OPTIONS.get("anthropic_api_key", "").strip()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_API_KEY", None)
    elif key:
        env["ANTHROPIC_API_KEY"] = key
    env.setdefault("CLAUDE_CONFIG_DIR", str(DATA_DIR / "claude"))
    env["DISABLE_AUTOUPDATER"] = "1"
    env["ENABLE_TOOL_SEARCH"] = "true" if OPTIONS.get("tool_search", True) else "false"
    return env


def write_logbook(question: str, answer: str):
    """Record the exchange in the Home Assistant logbook (best effort)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token or not OPTIONS.get("logbook", True):
        return
    body = json.dumps({
        "name": "Claude",
        "message": f"« {question.strip()} » → « {answer.strip()} »",
        "domain": "conversation",
    }).encode()
    req = urllib.request.Request(
        "http://supervisor/core/api/services/logbook/log", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except OSError as exc:
        log.debug("Logbook entry failed: %s", exc)


# --------------------------------------------------------------------------
# HTTP (OpenAI-compatible)
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ClaudeAssistGateway/1"
    mcp_config: Path = DATA_DIR / "mcp.json"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _authorized(self) -> bool:
        expected = OPTIONS.get("gateway_api_key", "").strip()
        if not expected or self.client_address[0] in INGRESS_IPS:
            return True
        got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if secrets.compare_digest(got, expected):
            return True
        self._json(401, {"error": {"message": "Invalid API key", "type": "invalid_request_error"}})
        return False

    def _json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ingress_only(self) -> bool:
        if self.client_address[0] in INGRESS_IPS:
            return True
        self._json(403, {"error": "access restricted to the Home Assistant ingress"})
        return False

    def _file(self, name: str, ctype: str):
        try:
            data = (WEB_DIR / name).read_bytes()
        except OSError:
            self._json(404, {"error": {"message": "Not found"}})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        path = path.rstrip("/")
        if path in ("", "/index.html"):
            if self._ingress_only():
                self._file("index.html", "text/html; charset=utf-8")
            return
        if path == "/icon.png":
            self._file("icon.png", "image/png")
            return
        if path == "/api/history":
            if self._ingress_only():
                params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                after = int(params.get("after", "0") or 0)
                self._json(200, {"items": HISTORY.since(after), "lang": LANG,
                                 "model": OPTIONS["model"]})
            return
        if path == "/api/notes":
            if self._ingress_only():
                notes = notes_path()
                try:
                    text = notes.read_text()
                except OSError:
                    text = ""
                shown = ("/config/" + str(notes.relative_to(HA_CONFIG_DIR))
                         if HA_CONFIG_DIR in notes.parents else
                         "/addon_configs/<add-on>/" + notes.name)
                self._json(200, {"path": shown, "text": text})
            return
        if path == "/health":
            self._json(200, {"status": "ok"})
        elif path in ("/v1/models", "/models"):
            if self._authorized():
                self._json(200, {"object": "list", "data": [
                    {"id": m, "object": "model", "created": 0, "owned_by": "anthropic"}
                    for m in ("claude", OPTIONS["model"])
                ]})
        else:
            self._json(404, {"error": {"message": "Not found"}})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/notes":
            if not self._ingress_only():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("too large")
                body = json.loads(self.rfile.read(length) or b"{}")
                text = str(body["text"])
            except (ValueError, KeyError, json.JSONDecodeError):
                self._json(400, {"error": "Invalid notes"})
                return
            notes = notes_path()
            try:
                notes.parent.mkdir(parents=True, exist_ok=True)
                tmp = notes.with_name(notes.name + ".tmp")
                tmp.write_text(text)
                tmp.replace(notes)
            except OSError as exc:
                log.error("Could not save the house notes: %s", exc)
                self._json(500, {"error": str(exc)})
                return
            log.info("House notes saved from the panel (%d characters)", len(text))
            self._json(200, {"ok": True})
            return
        if path == "/api/log":
            # Exchanges answered by Home Assistant itself (local intents) in the panel
            if not self._ingress_only():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "Invalid JSON"})
                return
            added = None
            if body.get("user") and body.get("assistant"):
                ts = body.get("ts")
                ts = float(ts) if isinstance(ts, (int, float)) and 0 < ts <= time.time() + 60 else None
                added = HISTORY.add(str(body.get("conv") or "local"), "local", str(body.get("place") or "")[:100],
                                    str(body["user"])[:2000], str(body["assistant"])[:4000],
                                    run=str(body.get("run") or "")[:64] or None, ts=ts)
            self._json(200, {"ok": True, "added": bool(added)})
            return
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": {"message": "Not found"}})
            return
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": {"message": "Invalid JSON"}})
            return

        ha_context, turns = split_messages(body.get("messages", []))
        if not turns or turns[-1][0] != "user":
            self._json(400, {"error": {"message": "The last message must come from the user"}})
            return
        history = turns[:-1]
        resume = SESSIONS.get(history) if history else None
        prompt = build_prompt(turns[-1][1], ha_context, [] if resume else history)
        log.info("Request: %s%s", turns[-1][1][:120], " (continued)" if resume else "")

        stream = bool(body.get("stream"))
        model = body.get("model") or "claude"
        cid = "chatcmpl-" + secrets.token_hex(12)
        created = int(time.time())

        def chunk(delta: dict, finish=None) -> bytes:
            payload = {"id": cid, "object": "chat.completion.chunk", "created": created,
                       "model": model,
                       "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(chunk({"role": "assistant", "content": ""}))
            self.wfile.flush()

            def on_text(piece):
                try:
                    self.wfile.write(chunk({"content": piece}))
                    self.wfile.flush()
                except OSError:
                    pass
        else:
            def on_text(piece):
                pass

        try:
            text, session_id = run_claude(prompt, resume, self.mcp_config, on_text)
        except Exception as exc:  # noqa: BLE001 - always answer the speaker
            log.exception("Gateway failure")
            text, session_id = T["err_generic"], None
            on_text(text)
            log.debug("%s", exc)

        if session_id:
            SESSIONS.put(turns + [("assistant", text)], session_id)
        log.info("Answer: %s", text.strip()[:500])
        HISTORY.add(session_id or cid, "assist", place_from_context(ha_context), turns[-1][1], text)
        threading.Thread(target=write_logbook, args=(turns[-1][1], text), daemon=True).start()

        if stream:
            try:
                self.wfile.write(chunk({}, "stop"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True
        else:
            self._json(200, {
                "id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
            })


def main():
    logging.basicConfig(
        level=getattr(logging, str(OPTIONS.get("log_level", "info")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout,
    )
    if not (OPTIONS.get("claude_token") or OPTIONS.get("anthropic_api_key")):
        log.warning("No Claude token or API key configured: see the Documentation tab")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY.load()
    ensure_house_notes()
    Handler.mcp_config = write_mcp_config(start_ha_mcp())
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    log.info("Voice Agent Bridge listening on port %s (model %s)", HTTP_PORT, OPTIONS["model"])
    server.serve_forever()


if __name__ == "__main__":
    main()

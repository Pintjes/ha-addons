#!/usr/bin/env python3
# Thread Anchor — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Thread Anchor: keeps the OpenThread border router of Home Assistant on a fixed OMR prefix.

Every Thread device has an address in the OMR (off-mesh routable) prefix of the network, chosen
among the prefixes the border routers publish. A prefix a border router generates itself has a
low preference; some border routers (Google TV, Nest Hub…) replace theirs now and then, and the
whole network moves to another prefix: Matter devices drop out until they are found again.

With `omr_prefix`, the border router is given a custom OMR prefix with a higher preference
(`ot-ctl br omrconfig custom <prefix> <preference>`): every border router favors it over the low
ones and withdraws its own. OpenThread keeps this setting in memory only, so it is read again every
`check_interval` and set again at once when the border router container restarts. The prefix the
whole network favors (`br omrprefix`) is read too: it shows that the other border routers follow.

The border router is reached through the Docker API (`docker exec` in its container): Protection
mode off. Every `ot-ctl` command goes through `Anchor.otctl`, one at a time (OpenThread ignores a
command received while an asynchronous one is pending). The state is published on MQTT
(`thread_anchor/state`, retained), with entities; Mesh Guardian reads it. The Thread role of the
border router is shown too, never changed.
"""
import http.client
import ipaddress
import json
import logging
import os
import re
import signal
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone

VERSION = "0.1.7"
LOG = logging.getLogger("thread_anchor")
STATE_TOPIC = "thread_anchor/state"
DISCOVERY = "homeassistant"
OTBR_ADDON = "core_openthread_border_router"
PREFERENCES = ("high", "med", "low")
ULA = ipaddress.IPv6Network("fc00::/7")   # local prefixes: the only ones accepted as omr_prefix
DOCKER_SOCK = "/run/docker.sock"
MEMORY_FILE = "/data/anchor.json"         # since when the prefix is anchored: kept over a restart
TICK_S = 5               # s between two looks at the border router container (restart detection)
HEARTBEAT_S = 300        # the state is published again this often, even unchanged
MQTT_RETRY_S = 60        # s before the MQTT broker is looked for again when it was not found
DIAG_REQUEST_TOPIC = "thread_anchor/diag/request"
DIAG_RESULT_TOPIC = "thread_anchor/diag/result"
DIAG_TIMEOUT_S = 15      # at most this long for one diagnostic
DIAG_GAP_S = 10          # at most one diagnostic of the same node this often
DIAG_SCAN_TIMEOUT_S = 90   # budget of the meshdiag step (routers asked one by one)
DIAG_SCAN_GAP_S = 300      # at most one meshdiag scan of the network this often
DIAG_RESUME_S = 1800       # a scan that stopped before the end is carried on by the next ones for this long
OTCTL_TRIES = 3            # an empty answer of ot-ctl is a command ignored (another one is pending): asked again
OTCTL_RETRY_S = 3          # s between two tries
OTCTL_LOCK_S = 60          # s a command waits for the one in progress
ROLES = ("disabled", "detached", "child", "router", "leader")
SEARCH_TEXTS = {           # one line of the log per step of the search for an RLOC16
    "found": "ext found, RLOC16 {d}",
    "not_found": "{n} rows, ext not in it",
    "no_answer": "no answer",
    "ext_differs": "answered with another ext ({d})",
    "error": "error: {d}",
    "not_supported": "not supported by this border router",
    "too_soon": "scan done {d} s ago, ext not in it",
    "stopped": "stopped: {d}",
    "kids": "children of {n} routers read{d}",
    "no_list": "this router gave no list of its children",
    "asked": "{n} children asked, {d} answered, ext not among them{s}",
    "old_listed": "still listed under {d}",
    "old_gone": "not listed any more under {d}",
}

TEXTS = {
    "fr": {
        "Thread Anchor {v} starting": "Démarrage de Thread Anchor {v}",
        "No omr_prefix: the border router is only watched, nothing is set":
            "Pas d'omr_prefix : le border router est seulement observé, rien n'est imposé",
        "Invalid omr_prefix {p}: {err}": "omr_prefix {p} invalide : {err}",
        "Invalid omr_preference {p}: high, med or low": "omr_preference {p} invalide : high, med ou low",
        "an OMR prefix is a /64": "un préfixe OMR est un /64",
        "not a local prefix (ULA, fc00::/7): nothing is set":
            "ce n'est pas un préfixe local (ULA, fc00::/7) : rien n'est imposé",
        "The network does not follow: it favors {p} ({prf}) instead of {w} ({wprf})":
            "Le réseau ne suit pas : il retient {p} ({prf}) au lieu de {w} ({wprf})",
        "The network follows again: it favors {p} ({prf})": "Le réseau suit de nouveau : il retient {p} ({prf})",
        "No MQTT broker yet ({err}): the state is only in the log, tried again every {s} s":
            "Pas encore de broker MQTT ({err}) : l'état n'est que dans le journal, nouvel essai toutes les {s} s",
        "OMR prefix {p} (preference {prf}) set on the border router (it was: {was})":
            "Préfixe OMR {p} (préférence {prf}) imposé au border router (il était : {was})",
        "OMR prefix {p} (preference {prf}) in place on the border router":
            "Préfixe OMR {p} (préférence {prf}) en place sur le border router",
        "The network favors {p} ({prf})": "Le réseau retient {p} ({prf})",
        "Border router restarted: OMR prefix checked again": "Border router redémarré : préfixe OMR revérifié",
        "Border router unreachable: {err}": "Border router injoignable : {err}",
        "This border router does not know `br omrconfig` (OpenThread too old): {err}":
            "Ce border router ne connaît pas `br omrconfig` (OpenThread trop ancien) : {err}",
        "No access to the Docker API ({err}); turn Protection mode off":
            "Pas d'accès à l'API Docker ({err}) ; désactiver le mode protection",
        "Connected to MQTT": "Connecté à MQTT",
        "Diagnostic request ignored (no usable id): {err}": "Demande de diagnostic ignorée (pas d'id utilisable) : {err}",
        "invalid rloc16: {v}": "rloc16 invalide : {v}",
        "invalid ext: {v}": "ext invalide : {v}",
        "invalid mleid: {v}": "mleid invalide : {v}",
        "rloc16, ext or mleid needed": "rloc16, ext ou mleid nécessaire",
        "mleid is not in the mesh-local prefix": "mleid n'est pas dans le préfixe mesh-local",
        "RLOC16 found by {m}": "RLOC16 trouvé par {m}",
        "Search {step}: {text}": "Recherche {step} : {text}",
        "ext found, RLOC16 {d}": "ext trouvée, RLOC16 {d}",
        "{n} rows, ext not in it": "{n} lignes, ext absente",
        "no answer": "pas de réponse",
        "answered with another ext ({d})": "a répondu avec une autre ext ({d})",
        "error: {d}": "erreur : {d}",
        "not supported by this border router": "non pris en charge par ce border router",
        "scan done {d} s ago, ext not in it": "balayage fait il y a {d} s, ext absente",
        "stopped: {d}": "arrêtée : {d}",
        "children of {n} routers read{d}": "enfants de {n} routeurs lus{d}",
        "this router gave no list of its children": "ce routeur n'a pas donné la liste de ses enfants",
        "{n} children asked, {d} answered, ext not among them{s}":
            "{n} enfants interrogés, {d} ont répondu, ext absente{s}",
        "; silent: {l}": " ; muets : {l}",
        "still listed under {d}": "toujours listé sous {d}",
        "not listed any more under {d}": "n'est plus listé sous {d}",
        "ot-ctl: no answer (another command pending?)": "ot-ctl : pas de réponse (autre commande en attente ?)",
        "time budget used": "budget de temps épuisé",
        "no answer to the network diagnostic": "pas de réponse au diagnostic réseau",
        "another node answers at this RLOC16: ext {got} instead of {want}":
            "une autre node répond à ce RLOC16 : ext {got} au lieu de {want}",
        "ping ok {ms} ms": "ping ok {ms} ms",
        "no ping answer": "pas de réponse au ping",
        "Diagnostic {r} ({rloc}): {ping}, {n} addresses, {o} OMR, {x} on another prefix{err}":
            "Diagnostic {r} ({rloc}) : {ping}, {n} adresses, {o} OMR, {x} sur un autre préfixe{err}",
    },
}
LANG = "en"


def t(key, **kw):
    return TEXTS.get(LANG, {}).get(key, key).format(**kw)


# ---------------------------------------------------------------- Docker API (unix socket)
class DockerError(RuntimeError):
    """The Docker API refused or could not be reached."""


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._sock_path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._sock_path)
        self.sock = s


def _docker(method, path, body=None, timeout=30):
    conn = _UnixHTTPConnection(DOCKER_SOCK, timeout)
    try:
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
        resp = conn.getresponse()
        raw = resp.read()
    except OSError as err:
        raise DockerError(str(err)) from err
    finally:
        conn.close()
    if resp.status >= 300:
        try:
            msg = json.loads(raw).get("message", "")
        except ValueError:
            msg = raw.decode(errors="replace").strip()
        raise DockerError(f"{resp.status} {msg}".strip())
    return raw


def demux(raw):
    """Output of a Docker exec without a tty: frames of [stream, 0, 0, 0, size (4 bytes)] + data."""
    if len(raw) < 8 or raw[0] not in (0, 1, 2) or raw[1:4] != b"\0\0\0":
        return raw.decode(errors="replace")
    out, i = [], 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    return b"".join(out).decode(errors="replace")


class Docker:
    """The two calls the add-on needs: start time of a container, and a command run in it."""

    def started_at(self, container):
        info = json.loads(_docker("GET", f"/containers/{container}/json"))
        state = info.get("State") or {}
        return state.get("StartedAt") if state.get("Running") else None

    def exec(self, container, cmd, timeout=30):
        ex = json.loads(_docker("POST", f"/containers/{container}/exec",
                                {"AttachStdout": True, "AttachStderr": True, "Cmd": cmd}, timeout))
        raw = _docker("POST", f"/exec/{ex['Id']}/start", {"Detach": False, "Tty": False}, timeout)
        info = json.loads(_docker("GET", f"/exec/{ex['Id']}/json", None, timeout))
        return info.get("ExitCode"), demux(raw)


class OtctlNoAnswer(RuntimeError):
    """ot-ctl printed nothing, every time: the command was ignored (another one is pending)."""


class Gate:
    """One `ot-ctl` command at a time, first come first served. The interpreter of OpenThread is
    unique: a command received while an asynchronous one (meshdiag, networkdiagnostic, ping) is
    pending is ignored without a word. The gate is taken for ONE command, never for a whole scan."""

    def __init__(self):
        self.cv, self.busy, self.queue = threading.Condition(), False, []

    def acquire(self, timeout):
        """True when the gate is ours; False after `timeout` s of waiting (real time)."""
        ticket, end = object(), time.monotonic() + timeout
        with self.cv:
            self.queue.append(ticket)
            while self.busy or self.queue[0] is not ticket:
                left = end - time.monotonic()
                if left <= 0:
                    self.queue.remove(ticket)
                    self.cv.notify_all()
                    return False
                self.cv.wait(left)
            self.queue.pop(0)
            self.busy = True
            return True

    def release(self):
        with self.cv:
            self.busy = False
            self.cv.notify_all()


# ---------------------------------------------------------------- ot-ctl answers
CUSTOM_RE = re.compile(r"custom\s*\(\s*([0-9a-fA-F:.]+/\d+)\s*,\s*prf:\s*(\w+)\s*\)")
PREFIX_RE = re.compile(r"([0-9a-fA-F:.]+/\d+)(?:\s+prf:\s*(\w+))?")


def _lines(text):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("Error"):
            raise RuntimeError(ln)
    return lines


def _net(p):
    return str(ipaddress.IPv6Network(p, strict=False))


def parse_omrconfig(text):
    """`br omrconfig` -> (mode, prefix, preference): ("custom", "fd00:1::/64", "high"), ("auto", None, None)…"""
    lines = _lines(text)
    for ln in lines:
        m = CUSTOM_RE.search(ln)
        if m:
            return "custom", _net(m.group(1)), m.group(2).lower()
        if ln in ("auto", "disabled"):
            return ln, None, None
    raise RuntimeError(f"unexpected answer: {lines[-1] if lines else '(empty)'}")


def parse_state(text):
    """`state` -> disabled, detached, child, router or leader."""
    for ln in _lines(text):
        if ln.lower() in ROLES:
            return ln.lower()
    raise RuntimeError(f"unexpected answer: {(_lines(text) or ['(empty)'])[0]}")


def parse_router_list(text):
    """`router list` -> router ids (`8 24 50` then `Done`). Read from the router table of the border
    router: no radio traffic."""
    ids = []
    for ln in _lines(text):
        if ln != "Done":
            ids += [int(n) for n in re.findall(r"\b\d+\b", ln)]
    return ids


def parse_omrprefix(text):
    """`br omrprefix` -> {"local": prefix|None, "favored": prefix|None, "favored_preference": prf|None}."""
    out = {"local": None, "favored": None, "favored_preference": None}
    for ln in _lines(text):
        key, _, rest = ln.partition(":")
        key = key.strip().lower()
        if key not in ("local", "favored") or not rest.strip():
            continue
        m = PREFIX_RE.search(rest)
        if not m:
            continue
        try:
            out[key] = _net(m.group(1))
        except ValueError:
            continue
        if key == "favored" and m.group(2):
            out["favored_preference"] = m.group(2).lower()
    return out


# ---------------------------------------------------------------- the anchor
class Anchor:
    def __init__(self, options, docker=None, clock=time.time, memory=None):
        self.prefix, self.config_error = None, None
        raw = str(options.get("omr_prefix") or "").strip()
        self.preference = str(options.get("omr_preference") or "high").strip().lower()
        if self.preference not in PREFERENCES:
            self.config_error = t("Invalid omr_preference {p}: high, med or low", p=self.preference)
            self.preference = "high"
            raw = ""
        if raw:
            try:
                net = ipaddress.IPv6Network(raw, strict=True)
                if net.prefixlen != 64:
                    raise ValueError(t("an OMR prefix is a /64"))
                if not net.subnet_of(ULA):
                    # a global prefix published by mistake would be worse than none
                    raise ValueError(t("not a local prefix (ULA, fc00::/7): nothing is set"))
                self.prefix = str(net)
            except ValueError as err:
                self.config_error = t("Invalid omr_prefix {p}: {err}", p=raw, err=err)
        self.slug = str(options.get("otbr_addon") or "").strip() or OTBR_ADDON
        # container of an add-on: app_<slug> since add-ons became apps (2026), addon_<slug> before
        self.containers = [f"app_{self.slug}", f"addon_{self.slug}"]
        self.container = self.containers[0]
        self.interval = max(10, int(options.get("check_interval") or 30))
        self.docker, self.clock = docker or Docker(), clock
        self.gate, self.sleep = Gate(), time.sleep   # every ot-ctl of the add-on goes through `otctl`
        self.role = self.routers = None              # Thread role of the border router, routers it sees
        self.mode = self.current = self.current_prf = self.error = self.applied_at = None
        self.favored = self.favored_prf = self.local = None
        self.started_at = None
        self.applied = 0
        self.last_check = None
        self.events = []
        self.unfollowed = False      # the "network does not follow" warning was given for this episode
        self.memory = memory         # file that keeps anchored_since over a restart of the add-on
        self.anchored_since = self._remember()

    @property
    def enabled(self):
        return self.prefix is not None

    def enforced(self):
        return self.enabled and self.mode == "custom" and self.current == self.prefix \
            and self.current_prf == self.preference

    def followed(self):
        """The whole network favors the anchored prefix, with its preference."""
        return self.enforced() and self.favored == self.prefix and self.favored_prf == self.preference

    def _remember(self):
        """anchored_since of the last run, when it was for the same prefix and preference."""
        if not (self.memory and self.enabled):
            return None
        try:
            with open(self.memory, encoding="utf-8") as f:
                kept = json.load(f)
            if kept.get("prefix") == self.prefix and kept.get("preference") == self.preference:
                since = kept.get("anchored_since")
                datetime.fromisoformat(since)
                return since
        except (OSError, ValueError, TypeError, AttributeError) as err:
            LOG.debug("memory: %s", err)
        return None

    def _since(self, since):
        """Start of the unbroken period the prefix is in place (None: seen lost), kept in the memory file."""
        if since == self.anchored_since:
            return
        self.anchored_since = since
        if not self.memory:
            return
        try:
            tmp = self.memory + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"prefix": self.prefix, "preference": self.preference, "anchored_since": since}, f)
            os.replace(tmp, self.memory)
        except OSError as err:
            LOG.debug("memory: %s", err)

    def _now_iso(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).astimezone().isoformat(timespec="seconds")

    def emit(self, kind, text, level=logging.INFO):
        LOG.log(level, text)
        self.events.append((kind, text))

    def _call(self, fn, *args):
        """fn(container, *args) on the border router container, trying the other naming on a 404."""
        try:
            return fn(self.container, *args)
        except DockerError as err:
            if not str(err).startswith("404"):
                raise
            other = next(c for c in self.containers if c != self.container)
            res = fn(other, *args)
            self.container = other
            return res

    def otctl(self, *args, deadline=None, limit=None):
        """One `ot-ctl` command: the only way the add-on runs one (anchor and diagnostic alike).
        The gate is taken for this command only, so that nothing is sent while another is pending.
        An empty answer with exit code 0 (no `Done`) is a command OpenThread ignored because another
        one was pending (another client of ot-ctl, for instance): asked again OTCTL_TRIES times,
        OTCTL_RETRY_S apart, then OtctlNoAnswer. With `deadline` (clock time), `limit` is the budget
        named in the message of the timeout."""
        for attempt in range(1, OTCTL_TRIES + 1):
            if deadline is not None and deadline - self.clock() < 1:
                raise RuntimeError(f"timeout ({limit} s)")
            if not self.gate.acquire(OTCTL_LOCK_S):
                raise OtctlNoAnswer(t("ot-ctl: no answer (another command pending?)"))
            try:
                extra = []
                if deadline is not None:
                    extra = [deadline - self.clock()]   # the wait for the gate counts
                    if extra[0] < 1:
                        raise RuntimeError(f"timeout ({limit} s)")
                code, out = self._call(self.docker.exec, ["ot-ctl", *args], *extra)
            finally:
                self.gate.release()
            if code not in (0, None) and "Done" not in out:
                raise RuntimeError((out.strip().splitlines() or [f"exit {code}"])[-1])
            if out.strip():
                return out
            LOG.debug("ot-ctl %s: empty answer (try %d/%d)", " ".join(args), attempt, OTCTL_TRIES)
            if attempt < OTCTL_TRIES:
                self.sleep(OTCTL_RETRY_S)
        raise OtctlNoAnswer(t("ot-ctl: no answer (another command pending?)"))

    _otctl = otctl

    def restarted(self):
        """True when the border router container started again since the last look."""
        try:
            started = self._call(self.docker.started_at)
        except Exception as err:  # noqa: BLE001 - reported by the next check
            LOG.debug("started_at: %s", err)
            return False
        if started and self.started_at and started != self.started_at:
            self.started_at = started
            return True
        if started:
            self.started_at = started
        return False

    def due(self):
        # after a failure (border router starting…), look again sooner
        wait = min(self.interval, 10) if self.error else self.interval
        return self.last_check is None or self.clock() - self.last_check >= wait

    def check(self, reason=None):
        """One reading (and the custom prefix set again when needed); True when the state changed."""
        before = json.dumps(self.public(), sort_keys=True)
        self.last_check = self.clock()
        was_ok, was_favored = self.enforced(), (self.favored, self.favored_prf)
        if reason == "restart":
            self.emit("otbr_restart", t("Border router restarted: OMR prefix checked again"))
        try:
            self.mode, self.current, self.current_prf = parse_omrconfig(self._otctl("br", "omrconfig"))
            applied_now = False
            if self.enabled and not self.enforced():
                self._since(None)   # read, and not in place: the anchoring is seen lost
                was = f"{self.mode} {self.current or ''} {self.current_prf or ''}".strip()
                out = self._otctl("br", "omrconfig", "custom", self.prefix, self.preference)
                if "Done" not in out:
                    raise RuntimeError((out.strip().splitlines() or ["(empty)"])[-1])
                self.applied += 1
                self.applied_at = self.clock()
                applied_now, self.unfollowed = True, False
                self.mode, self.current, self.current_prf = parse_omrconfig(self._otctl("br", "omrconfig"))
                self.emit("anchor_set", t("OMR prefix {p} (preference {prf}) set on the border router (it was: {was})",
                                          p=self.prefix, prf=self.preference, was=was))
            elif self.enforced() and not was_ok:
                self.emit("anchor_ok", t("OMR prefix {p} (preference {prf}) in place on the border router",
                                         p=self.prefix, prf=self.preference))
            if self.enforced() and not self.anchored_since:
                self._since(self._now_iso())
            favored_read = False
            try:
                pr = parse_omrprefix(self._otctl("br", "omrprefix"))
                self.favored, self.favored_prf, self.local = pr["favored"], pr["favored_preference"], pr["local"]
                favored_read = True
            except Exception as err:  # noqa: BLE001 - the anchor itself still works
                LOG.debug("omrprefix: %s", err)
                self.favored = self.favored_prf = self.local = None
            self._read_role()
            if self.favored and (self.favored, self.favored_prf) != was_favored:
                self.emit("favored", t("The network favors {p} ({prf})", p=self.favored, prf=self.favored_prf or "?"))
            if self.followed():
                if self.unfollowed:
                    self.unfollowed = False
                    self.emit("follow_back", t("The network follows again: it favors {p} ({prf})",
                                               p=self.favored, prf=self.favored_prf))
            elif self.enforced() and favored_read and not applied_now and not self.unfollowed:
                # once per episode, and not in the pass that set the prefix: the network needs a moment
                self.unfollowed = True
                self.emit("follow_lost", t("The network does not follow: it favors {p} ({prf}) instead of {w} ({wprf})",
                                           p=self.favored or "-", prf=self.favored_prf or "?", w=self.prefix,
                                           wprf=self.preference), logging.WARNING)
            self.error = None
        except DockerError as err:
            if str(err).startswith(("403", "[Errno 2]", "[Errno 13]")):
                self._fail(t("No access to the Docker API ({err}); turn Protection mode off", err=err))
            else:
                self._fail(t("Border router unreachable: {err}", err=err))
        except OtctlNoAnswer as err:
            # the border router is there, another command kept it busy: what was read stays as it was
            self._fail(str(err), keep=True)
        except Exception as err:  # noqa: BLE001
            if "InvalidCommand" in str(err):
                self._fail(t("This border router does not know `br omrconfig` (OpenThread too old): {err}", err=err))
            else:
                self._fail(t("Border router unreachable: {err}", err=err))
        return json.dumps(self.public(), sort_keys=True) != before

    def _read_role(self):
        """Thread role of the border router and number of routers it sees: two reads, no radio
        traffic. Read only, shown and nothing more: the role is never changed by this add-on."""
        try:
            self.role = parse_state(self.otctl("state"))
            self.routers = None
            if self.role in ("child", "router", "leader"):
                self.routers = len(parse_router_list(self.otctl("router", "list")))
        except OtctlNoAnswer:
            LOG.debug("role: no answer, the last one is kept")
        except Exception as err:  # noqa: BLE001 - the anchor itself still works
            LOG.debug("role: %s", err)
            self.role = self.routers = None

    def _fail(self, txt, keep=False):
        if not keep:
            self.mode = self.current = self.current_prf = None
            self.favored = self.favored_prf = self.local = None
            self.role = self.routers = None
        if txt != self.error:
            self.emit("error", txt, logging.WARNING)
        self.error = txt

    def public(self):
        return {"otbr_addon": self.slug, "wanted": self.prefix, "preference": self.preference, "mode": self.mode,
                "current": self.current, "current_preference": self.current_prf, "enforced": self.enforced(),
                "favored": self.favored, "favored_preference": self.favored_prf, "local": self.local,
                "applied": self.applied, "applied_at": self.applied_at, "otbr_started_at": self.started_at,
                "error": self.error, "anchored_since": self.anchored_since, "followed": self.followed(),
                "thread_role": self.role, "thread_routers": self.routers}


# ---------------------------------------------------------------- diagnostic of one node (read only)
_STOP = object()    # the time budget of the meshdiag step is used
LINK_LOCAL = ipaddress.IPv6Network("fe80::/10")
GLOBAL = ipaddress.IPv6Network("2000::/3")
EXT_RE = re.compile(r"Ext Address:\s*'?([0-9a-fA-F]{16})'?")
RLOC_RE = re.compile(r"Rloc16:\s*(0x[0-9a-fA-F]{1,4})")
EXT_ADDR_RE = re.compile(r"(?:0x)?([0-9a-fA-F]{16})")
SENT_RE = re.compile(r"(\d+) packets transmitted, (\d+) packets received")
RTT_RE = re.compile(r"Round-trip min/avg/max = [\d.]+/([\d.]+)/[\d.]+ ms")
REPLY_RE = re.compile(r"bytes from \S+: icmp_seq=\d+ hlim=\d+ time=(\d+)ms")


def parse_rloc16(value):
    """"0xB45C", "b45c" or 46172 -> 0xb45c; ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError(value)
    n = value if isinstance(value, int) else int(str(value).strip(), 16)
    if not 0 <= n <= 0xFFFE:
        raise ValueError(value)
    return n


def parse_ext(value):
    """"CA7A34808B66E461" or "0xca7a…" -> "ca7a34808b66e461"; ValueError otherwise."""
    m = EXT_ADDR_RE.fullmatch(str(value).strip())
    if not m:
        raise ValueError(value)
    return m.group(1).lower()


def parse_table(text):
    """`child table`, `neighbor table` or `router table` -> {extended address: rloc16}.
    The tables are drawn with `|` columns; the two columns are found from the header line."""
    out, cols = {}, None
    for ln in _lines(text):
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if "RLOC16" in cells and "Extended MAC" in cells:
            cols = (cells.index("RLOC16"), cells.index("Extended MAC"))
            continue
        if cols is None or len(cells) <= max(cols):
            continue
        try:
            out[parse_ext(cells[cols[1]])] = parse_rloc16(cells[cols[0]])
        except ValueError:
            continue
    return out


MESHDIAG_RE = re.compile(r"rloc16:(0x[0-9a-fA-F]{1,4})\s+ext-addr:([0-9a-fA-F]{16})")
ME_RE = re.compile(r"\s-\s+me\b")


def parse_help(text):
    """`help` -> set of the commands (one per line)."""
    return set(_lines(text))


def parse_topology(text):
    """`meshdiag topology` -> routers [{"rloc16", "ext", "me"}] ("me": the border router itself).
    Lines look like `id:02 rloc16:0x0800 ext-addr:8aa57d2c603fe16c ver:4 - me - leader`."""
    out = []
    for ln in _lines(text):
        m = MESHDIAG_RE.search(ln) if ln.startswith("id:") else None
        if m:
            out.append({"rloc16": int(m.group(1), 16), "ext": m.group(2).lower(), "me": bool(ME_RE.search(ln))})
    return out


def parse_childtable(text):
    """`meshdiag childtable <router>` -> {extended address: rloc16} of its children.
    Each child starts with `rloc16:0x6402 ext-addr:8e6f4d323bbed1fe ver:4`; the lines under it are details."""
    out = {}
    for ln in _lines(text):
        m = MESHDIAG_RE.match(ln)
        if m:
            out[m.group(2).lower()] = int(m.group(1), 16)
    return out


KID_RE = re.compile(r"rloc16:(0x[0-9a-fA-F]{1,4})\s+lq:")


def parse_topology_children(text):
    """`meshdiag topology children` -> ({router rloc16: [rloc16 of its children]}, error line or None).
    Under each router line (`id:02 rloc16:0x0800 ext-addr:… `) come `children:` and one line per child,
    `rloc16:0x0803 lq:0, mode:rn`: the children have no extended address here. Tolerant: what was
    read before an `Error …` line is kept (the error comes back beside it)."""
    out, router, error = {}, None, None
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln.startswith("Error"):
            error = ln
            continue
        m = MESHDIAG_RE.search(ln) if ln.startswith("id:") else None
        if m:
            router = int(m.group(1), 16)
            out.setdefault(router, [])
            continue
        m = KID_RE.match(ln)
        if m and router is not None:
            out[router].append(int(m.group(1), 16))
    return out, error


def rloc_address(mesh_local, rloc16):
    """RLOC address of a node: <mesh-local prefix>:0:ff:fe00:<rloc16>."""
    net = ipaddress.IPv6Network(mesh_local, strict=False)
    return str(ipaddress.IPv6Address(int(net.network_address) | 0xFFFE000000 | rloc16))


def parse_ping(text):
    """`ping` output -> {"ok": bool, "rtt_ms": float|None}; RuntimeError on `Error …`."""
    _lines(text)
    m = SENT_RE.search(text or "")
    if not m:
        raise RuntimeError(f"unexpected ping answer: {(text or '').strip()[-80:] or '(empty)'}")
    ok = int(m.group(2)) > 0
    rtt = RTT_RE.search(text) or REPLY_RE.search(text)
    return {"ok": ok, "rtt_ms": float(rtt.group(1)) if ok and rtt else None}


def parse_diag(text):
    """`networkdiagnostic get <addr> 0 [1] 8` -> {"answered", "ext", "rloc16", "addresses"}.
    The answer comes as `DIAG_GET.rsp/ans from …`; without it the node did not answer in time."""
    lines = _lines(text)
    out = {"answered": any(ln.startswith("DIAG_GET.rsp/ans") for ln in lines), "ext": None, "rloc16": None,
           "addresses": []}
    in_list = False
    for ln in lines:
        m = EXT_RE.search(ln)
        if m:
            out["ext"] = m.group(1).lower()
        m = RLOC_RE.search(ln)
        if m:
            out["rloc16"] = int(m.group(1), 16)
        if ln.startswith("IP6 Address List"):
            in_list = True
            continue
        if in_list:
            try:
                addr = str(ipaddress.IPv6Address(ln.lstrip("- ").strip()))
            except ValueError:
                in_list = False
                continue
            if addr not in out["addresses"]:
                out["addresses"].append(addr)
    return out


def classify(addresses, mesh_local, prefixes):
    """omr_addresses: in the wanted or favored prefix; other_prefix_addresses: other GUA / ULA,
    neither mesh-local nor link-local: an old OMR prefix the node kept."""
    mlp = ipaddress.IPv6Network(mesh_local, strict=False) if mesh_local else None
    nets = [ipaddress.IPv6Network(p) for p in prefixes if p]
    omr, other = [], []
    for a in addresses:
        ip = ipaddress.IPv6Address(a)
        if any(ip in n for n in nets):
            omr.append(a)
        elif (ip in ULA or ip in GLOBAL) and ip not in LINK_LOCAL and not (mlp and ip in mlp):
            other.append(a)
    return omr, other


class Diag:
    """Diagnostic of one node asked on MQTT (`thread_anchor/diag/request`): ping of its RLOC address
    and its IPv6 addresses read with a network diagnostic. Reads only: nothing is set on the
    border router. One at a time, at most one per node every DIAG_GAP_S, DIAG_TIMEOUT_S each.
    Without `rloc16`, it is found from the extended address (`ext`): in the tables of the border
    router (child, neighbor, router), or from the mesh-local address of the node (`mleid`), and
    last by asking the routers one by one (`meshdiag`), at most one scan every DIAG_SCAN_GAP_S."""

    def __init__(self, anchor, reply, clock=time.time, spawn=None):
        self.anchor, self.reply, self.clock = anchor, reply, clock
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.lock = threading.Lock()
        self.running = False
        self.last = {}   # rloc16 -> time of the last accepted request
        self.limit = DIAG_TIMEOUT_S              # budget in force, for the message of a timeout
        self.meshdiag, self.meshdiag_for = None, None   # `help` knows meshdiag (for this start of the OTBR)
        self.scan_at, self.scan_map = None, {}   # last scan: when, and {ext: (rloc16, parent rloc16)}
        self.scan_kids, self.scan_topo = {}, None   # last scan: children known per router, `topology children`
        # a scan that stopped before its end (time budget, a hit) is carried on by the next one:
        # routers whose children are all known are not asked again, nor are the children that answered
        self.partial, self.done, self.tried = False, set(), set()
        self.silent = {}          # router rloc16 -> children asked that did not answer

    def submit(self, raw):
        """A request from MQTT: answered at once when refused, else run in the background."""
        try:
            req = json.loads(raw)
            rid = str(req["id"]).strip()
            if not rid or "/" in rid or "+" in rid or "#" in rid:
                raise ValueError("id")
        except (ValueError, TypeError, KeyError) as err:
            LOG.warning(t("Diagnostic request ignored (no usable id): {err}", err=err))
            return
        base = {"id": rid, "rloc16": req.get("rloc16"), "rloc16_from": None, "parent": None, "alive": None,
                "rloc_address": None, "ext": None, "ping": None, "addresses": [], "omr_addresses": [],
                "other_prefix_addresses": [], "search": [], "silent_children": []}
        raw16, raw_ext, raw_ml = req.get("rloc16"), req.get("ext"), req.get("mleid", req.get("ml_eid"))
        try:
            rloc16 = None if raw16 is None or raw16 == "" else parse_rloc16(raw16)
        except (ValueError, TypeError):
            return self._done(base, t("invalid rloc16: {v}", v=raw16))
        try:
            ext = parse_ext(raw_ext) if str(raw_ext or "").strip() else None
        except ValueError:
            return self._done(base, t("invalid ext: {v}", v=raw_ext))
        try:
            ml = str(ipaddress.IPv6Address(str(raw_ml).strip())) if str(raw_ml or "").strip() else None
        except ValueError:
            return self._done(base, t("invalid mleid: {v}", v=raw_ml))
        if rloc16 is None and not ext and not ml:
            return self._done(base, t("rloc16, ext or mleid needed"))
        # the node asked for: its RLOC16 when given, else its extended address, else its ML-EID
        key = ("rloc16", rloc16) if rloc16 is not None else ("ext", ext) if ext else ("mleid", ml)
        with self.lock:
            if self.running:
                return self._done(base, "busy")
            last = self.last.get(key)
            if last is not None and self.clock() - last < DIAG_GAP_S:
                return self._done(base, "too soon")
            self.running, self.last[key] = True, self.clock()
        # RLOC16s of the request's `routers`: a router or a child (its old RLOC16). The routers they
        # belong to are asked first in the meshdiag step; a child RLOC16 is looked for in their lists.
        hints = []
        for v in req.get("routers") if isinstance(req.get("routers"), list) else []:
            try:
                hints.append(parse_rloc16(v))
            except (ValueError, TypeError):
                LOG.debug("routers: ignored %r", v)
        self.spawn(lambda: self.run(base, rloc16, ext, ml, req.get("ping", True) is not False, hints,
                                    req.get("scan", True) is not False))

    def run(self, res, rloc16, ext, ml, ping, hints=(), scan=True):
        try:
            self._run(res, rloc16, ext, ml, ping, hints, scan)
        except Exception as err:  # noqa: BLE001 - always an answer
            res["error"] = str(err) or type(err).__name__
        finally:
            with self.lock:
                self.running = False
        self._done(res, res.get("error"))

    def _otctl(self, deadline, *args):
        """Through the single entry point of the anchor (one command at a time, empty answers asked again)."""
        return self.anchor.otctl(*args, deadline=deadline, limit=self.limit)

    def _step(self, res, step, result, detail=None, rows=None, extra=""):
        """One step of the search for an RLOC16: kept in the answer (`search`) and said in the log
        (`extra`: more words for the log only)."""
        res["search"].append({"step": step, "result": result, "rows": rows, "detail": detail})
        LOG.info(t("Search {step}: {text}", step=step, text=t(SEARCH_TEXTS[result], d=detail, n=rows, s=extra)))

    def _resolve(self, res, deadline, mlp, ext, ml, hints, scan):
        """RLOC16 of a node known by its extended address and / or its ML-EID:
        (rloc16, how, diag, parent rloc16) or (None, None, None, None). The ML-EID answers by itself
        (one request: ext, RLOC16, addresses); the tables of the border router cost no radio traffic
        but hold only its own children and neighbors, and the routers; the meshdiag step asks the
        other routers for their children."""
        if ml:
            if ipaddress.IPv6Address(ml) not in ipaddress.IPv6Network(mlp):
                raise RuntimeError(t("mleid is not in the mesh-local prefix"))
            try:
                diag = parse_diag(self._otctl(deadline, "networkdiagnostic", "get", ml, "0", "1", "8"))
            except RuntimeError as err:
                if "timeout" in str(err):
                    raise
                self._step(res, "mleid", "error", str(err))
            else:
                if not (diag["answered"] and diag["rloc16"] is not None):
                    self._step(res, "mleid", "no_answer")
                elif ext and diag["ext"] != ext:
                    # another extended address than asked: the address is not that node's any more
                    self._step(res, "mleid", "ext_differs", diag["ext"])
                else:
                    self._step(res, "mleid", "found", f"0x{diag['rloc16']:04x}")
                    return diag["rloc16"], "mleid", diag, None
        if ext:
            for name, cmd in (("child table", ("child", "table")), ("neighbor table", ("neighbor", "table")),
                              ("router table", ("router", "table"))):
                try:
                    rows = parse_table(self._otctl(deadline, *cmd))
                except RuntimeError as err:
                    if "timeout" in str(err):
                        raise
                    self._step(res, name, "error", str(err))
                    continue
                found = rows.get(ext)
                if found is not None:
                    self._step(res, name, "found", f"0x{found:04x}", rows=len(rows))
                    return found, name, None, None
                self._step(res, name, "not_found", rows=len(rows))
            if scan:
                hit = self._scan(res, ext, hints, mlp)
                if hit:
                    return hit[0], "meshdiag", None, hit[1]
        return None, None, None, None

    def _scan(self, res, ext, hints, mlp):
        """The meshdiag step: (rloc16, parent rloc16 or None) or None. The routers are asked one by
        one for their children, in DIAG_SCAN_TIMEOUT_S at most, at most one scan every DIAG_SCAN_GAP_S
        (in between, the last scan is read again, no traffic). A router that does not answer
        `meshdiag childtable` is asked for its children by `meshdiag topology children` (RLOC16 only),
        and each child is then asked for its extended address. A scan that stopped before its end
        (time budget, a hit) is carried on by the next ones for DIAG_RESUME_S: routers whose children
        are all known, and the children that answered, are not asked again. Listing a child proves
        nothing about its being alive: only a ping or a diagnostic answer does."""
        self.limit = DIAG_SCAN_TIMEOUT_S
        try:
            hit = self._scan_run(res, ext, hints, mlp)
            self._old_rloc16(res, hints)
            res["silent_children"] = [{"rloc16": f"0x{rl:04x}", "parent": f"0x{r:04x}"}
                                      for r in sorted(self.silent) for rl in sorted(self.silent[r])]
            return hit
        finally:
            self.limit = DIAG_TIMEOUT_S

    def _forget(self):
        """Nothing is kept of the earlier scans (the border router started again, or a scan is new)."""
        self.scan_map, self.scan_kids, self.scan_topo = {}, {}, None
        self.partial, self.done, self.tried, self.silent = False, set(), set(), {}

    def _mark(self, router, silent):
        """The children of a router that did not answer (none: the entry goes)."""
        if silent:
            self.silent[router] = silent
        else:
            self.silent.pop(router, None)

    def _old_rloc16(self, res, hints):
        """Says whether a child RLOC16 of the request (the old one of the node) is still listed under
        its router, when that router gave the list of its children in the last scan."""
        for h in dict.fromkeys(hints):
            router = h & 0xFC00
            if h != router and router in self.scan_kids:
                self._step(res, f"old RLOC16 0x{h:04x}", "old_listed" if h in self.scan_kids[router] else "old_gone",
                           f"0x{router:04x}")

    def _children(self, res, deadline, ext, router, hints, mlp, again=False):
        """Children of a router that did not answer `meshdiag childtable`: their RLOC16 come from
        `meshdiag topology children` (one per scan, same Diagnostic Get as `topology`, which these
        routers do answer), then each child is asked for its extended address (`networkdiagnostic
        get <RLOC address> 0`), the old RLOC16 of the request first. The children that answered
        earlier are not asked again. A child asleep answers late, when its parent gets to hand it the
        question: many do not answer; they are kept in `silent`, and with `again` only those are
        asked once more. (rloc16, router), None, or _STOP when the time budget is used."""
        if self.scan_topo is None:
            self.scan_topo = {}
            name = "meshdiag topology children"
            try:
                kids, err = parse_topology_children(self._otctl(deadline, "meshdiag", "topology", "children"))
            except RuntimeError as err:
                self._step(res, name, "error", str(err))
            else:
                self.scan_topo = kids
                if err and not kids:
                    self._step(res, name, "error", err)
                else:
                    self._step(res, name, "kids", f" ({err})" if err else "", rows=len(kids))
        name = f"children of 0x{router:04x}" + (" (again)" if again else "")
        rlocs = self.scan_topo.get(router)
        if rlocs is None:
            self._step(res, name, "no_list")
            return None
        self.scan_kids[router] = set(rlocs)
        known = {rl for rl, parent in self.scan_map.values() if parent == router}    # answered already
        todo = [rl for rl in rlocs if rl not in known]
        if again:
            todo = [rl for rl in todo if rl in self.silent.get(router, ())]
        asked, answered, silent = 0, 0, []
        for rl in sorted(todo, key=lambda r: (r not in hints, r)):
            if deadline - self.clock() < 1:
                self._mark(router, silent)
                self._step(res, name, "stopped", t("time budget used"))
                return _STOP
            asked += 1
            try:
                diag = parse_diag(self._otctl(deadline, "networkdiagnostic", "get", rloc_address(mlp, rl), "0"))
            except RuntimeError as err:
                LOG.debug("child 0x%04x: %s", rl, err)
                silent.append(rl)
                continue
            if not diag["answered"] or not diag["ext"]:
                silent.append(rl)
                continue
            answered += 1
            self.scan_map[diag["ext"]] = (rl, router)
            if diag["ext"] == ext:
                self._mark(router, silent)
                self._step(res, name, "found", f"0x{rl:04x}", rows=len(rlocs))
                return rl, router
        if silent:
            self.silent[router] = silent
        else:
            self.silent.pop(router, None)
            self.done.add(router)      # every child of the router answered: nothing left to ask
        self._step(res, name, "asked", answered, rows=asked,
                   extra=t("; silent: {l}", l=", ".join(f"0x{r:04x}" for r in silent)) if silent else "")
        return None

    def _scan_run(self, res, ext, hints, mlp):
        now = self.clock()
        deadline = now + DIAG_SCAN_TIMEOUT_S
        started = self.anchor.started_at
        if self.meshdiag is None or self.meshdiag_for != started:
            try:     # asked once per start of the border router, when a search needs it
                self.meshdiag = "meshdiag" in parse_help(self._otctl(deadline, "help"))
            except RuntimeError as err:
                self._step(res, "meshdiag help", "error", str(err))
                return None
            self.meshdiag_for = started
            self._forget()
        if not self.meshdiag:
            self._step(res, "meshdiag", "not_supported")
            return None
        if self.scan_at is not None and now - self.scan_at < DIAG_SCAN_GAP_S:
            hit = self.scan_map.get(ext)
            if hit:
                self._step(res, "meshdiag", "found", f"0x{hit[0]:04x}")
                return hit
            self._step(res, "meshdiag", "too_soon", int(now - self.scan_at))
            return None
        resume = self.partial and self.scan_at is not None and now - self.scan_at < DIAG_RESUME_S
        self.scan_at, self.scan_topo = now, None     # a scan counts as done even when it fails
        if not resume:
            self._forget()
        self.partial = True      # until the scan reaches its end with every router known
        try:
            routers = parse_topology(self._otctl(deadline, "meshdiag", "topology"))
        except RuntimeError as err:
            self._step(res, "meshdiag topology", "error", str(err))
            return None
        rhit = next((r for r in routers if r["ext"] == ext), None)
        for r in routers:
            self.scan_map[r["ext"]] = (r["rloc16"], None)
        self._step(res, "meshdiag topology", "found" if rhit else "not_found",
                   f"0x{rhit['rloc16']:04x}" if rhit else None, rows=len(routers))
        if rhit:
            return rhit["rloc16"], None
        old = self.scan_map.get(ext)     # a child that answered in the scan this one carries on
        if old:
            self._step(res, "meshdiag", "found", f"0x{old[0]:04x}")
            return old
        # the border router's own children are in `child table` already
        others = [r["rloc16"] for r in routers if not r["me"]]
        first = list(dict.fromkeys(h & 0xFC00 for h in hints))    # routers of the request: read again
        todo = [o for o in others if o not in self.done or o in first]
        order = [h for h in first if h in todo] + [o for o in todo if o not in first and o not in self.tried] \
            + [o for o in todo if o not in first and o in self.tried]
        failed = []     # routers that did not answer `meshdiag childtable`, in the order they were asked
        for router in order:
            name = f"meshdiag childtable 0x{router:04x}"
            if deadline - self.clock() < 1:
                self._step(res, name, "stopped", t("time budget used"))
                return None
            self.tried.add(router)
            try:
                kids = parse_childtable(self._otctl(deadline, "meshdiag", "childtable", f"0x{router:04x}"))
            except RuntimeError as err:
                self._step(res, name, "error", str(err))
                if "Busy" in str(err):     # another meshdiag is running: not worth insisting
                    return None
                failed.append(router)
                if router in first:        # a router the request names: its children at once
                    hit = self._children(res, deadline, ext, router, hints, mlp)
                    failed.remove(router)
                    if hit is _STOP:
                        return None
                    if hit:
                        return hit
                continue
            self.scan_kids[router] = set(kids.values())
            self.silent.pop(router, None)
            self.done.add(router)
            for e, rl in kids.items():
                self.scan_map[e] = (rl, router)
            if ext in kids:
                self._step(res, name, "found", f"0x{kids[ext]:04x}", rows=len(kids))
                return kids[ext], router
            self._step(res, name, "not_found", rows=len(kids))
        # a child asleep answers once awake: the silent children of the routers named in the request
        # get one more try, BEFORE the other silent routers are read (those can use up the whole budget)
        for router in first:
            if self.silent.get(router) and router in others and deadline - self.clock() >= 1:
                hit = self._children(res, deadline, ext, router, hints, mlp, again=True)
                if hit is _STOP:
                    return None
                if hit:
                    return hit
        for router in failed:      # the other routers that kept silent
            hit = self._children(res, deadline, ext, router, hints, mlp)
            if hit is _STOP:
                return None
            if hit:
                return hit
        self.partial = not all(o in self.done for o in others)
        return None
    def _run(self, res, rloc16, ext, ml, ping, hints=(), scan=True):
        deadline = self.clock() + DIAG_TIMEOUT_S
        self.limit = DIAG_TIMEOUT_S
        # mesh-local prefix from the RLOC address of the border router itself (no secret in it,
        # unlike `dataset active`)
        own = _lines(self._otctl(deadline, "ipaddr", "rloc"))
        mlp = str(ipaddress.IPv6Network(f"{ipaddress.IPv6Address(own[0])}/64", strict=False))
        diag = None
        if rloc16 is None:
            rloc16, how, diag, parent = self._resolve(res, deadline, mlp, ext, ml, hints, scan)
            if rloc16 is None:
                res["error"] = "not found"
                return
            res["rloc16"], res["rloc16_from"] = f"0x{rloc16:04x}", how
            res["parent"] = f"0x{parent:04x}" if parent is not None else None
            deadline = self.clock() + DIAG_TIMEOUT_S   # the search had its own time
        else:
            res["rloc16_from"] = "request"
        res["rloc_address"] = addr = rloc_address(mlp, rloc16)
        res["alive"] = False   # a table lists the node, which proves nothing: only an answer does
        if ping:
            try:
                res["ping"] = parse_ping(self._otctl(deadline, "ping", addr, "16", "1"))
            except OtctlNoAnswer:
                res["alive"] = None    # the ping was never sent: it says nothing, and is not "lost"
                raise
            except RuntimeError as err:
                if "timeout" in str(err):
                    raise
                res["ping"] = {"ok": False, "rtt_ms": None}
                LOG.debug("ping: %s", err)
            res["alive"] = res["ping"]["ok"]
        if diag is None:
            diag = parse_diag(self._otctl(deadline, "networkdiagnostic", "get", addr, "0", "8"))
        if not diag["answered"]:
            res["error"] = t("no answer to the network diagnostic")
            return
        res["alive"] = True
        res["ext"], res["addresses"] = diag["ext"], diag["addresses"]
        a = self.anchor
        res["omr_addresses"], res["other_prefix_addresses"] = classify(diag["addresses"], mlp, (a.prefix, a.favored))
        if ext and diag["ext"] and diag["ext"] != ext:
            res["alive"] = False   # somebody else is alive at this RLOC16
            res["error"] = t("another node answers at this RLOC16: ext {got} instead of {want}", got=diag["ext"], want=ext)

    def _done(self, res, error):
        res["error"] = error
        res["at"] = datetime.fromtimestamp(self.clock(), timezone.utc).astimezone().isoformat(timespec="seconds")
        p = res.get("ping")
        short = (t("ping ok {ms} ms", ms=p["rtt_ms"]) if p and p["ok"] else t("no ping answer") if p else "-")
        how = res.get("rloc16_from")
        via = f" [{t('RLOC16 found by {m}', m=how)}]" if how not in (None, "request") else ""
        LOG.info(t("Diagnostic {r} ({rloc}): {ping}, {n} addresses, {o} OMR, {x} on another prefix{err}",
                   r=res.get("rloc16") or res["id"], rloc=res.get("rloc_address") or "-", ping=short,
                   n=len(res["addresses"]), o=len(res["omr_addresses"]), x=len(res["other_prefix_addresses"]),
                   err=via + (f" — {error}" if error else "")))
        self.reply(f"{DIAG_RESULT_TOPIC}/{res['id']}", res)
        return res


# ---------------------------------------------------------------- Home Assistant side
def supervisor(path, method="GET", timeout=30):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("no Supervisor token")
    req = urllib.request.Request(f"http://supervisor{path}", method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body).get("data", {}) if body else {}


def _paho_client():
    import paho.mqtt.client as mqtt   # noqa: PLC0415
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="thread_anchor")


class Mqtt:
    """The state on MQTT. The broker is looked for again every MQTT_RETRY_S until it is found
    (`start`, called at every tick); once the client exists, paho reconnects by itself."""

    def __init__(self, anchor, service=None, factory=_paho_client, clock=time.time):
        self.anchor, self.client, self.clock = anchor, None, clock
        self.service = service or (lambda: supervisor("/services/mqtt"))
        self.factory = factory
        self.next_try, self.last_error = 0.0, None
        self.diag = Diag(anchor, self._reply, clock=clock)

    def _reply(self, topic, payload):
        c = self.client
        if c is not None:
            c.publish(topic, json.dumps(payload))   # not retained: one answer for one request

    def on_message(self, client, userdata, message):
        if message.topic == DIAG_REQUEST_TOPIC:
            self.diag.submit(message.payload)

    def start(self):
        """True when the MQTT client exists (made now or before)."""
        if self.client is not None:
            return True
        if self.clock() < self.next_try:
            return False
        c = None
        try:
            conf = self.service()
            c = self.factory()
            if conf.get("username"):
                c.username_pw_set(conf["username"], conf.get("password"))
            c.will_set(STATE_TOPIC + "/available", "offline", retain=True)
            c.on_connect = self.on_connect
            c.on_message = self.on_message
            c.reconnect_delay_set(1, 60)
            c.connect_async(conf.get("host", "core-mosquitto"), int(conf.get("port", 1883)), keepalive=60)
            c.loop_start()
        except Exception as err:  # noqa: BLE001 - no broker yet, add-on stopped, bad answer…
            self.next_try = self.clock() + MQTT_RETRY_S
            if str(err) != self.last_error:   # said once, not every minute
                LOG.warning(t("No MQTT broker yet ({err}): the state is only in the log, tried again every {s} s",
                              err=err, s=MQTT_RETRY_S))
            self.last_error = str(err)
            return False
        self.client, self.last_error = c, None
        return True

    def stop(self):
        """Clean stop: `offline` said at once (the will is only sent when the connection is lost)."""
        c, self.client = self.client, None
        if c is None:
            return
        try:
            info = c.publish(STATE_TOPIC + "/available", "offline", retain=True)
            info.wait_for_publish(2)
        except Exception as err:  # noqa: BLE001 - not connected: the retained value stays as it is
            LOG.debug("offline: %s", err)
        for end in (c.disconnect, c.loop_stop):
            try:
                end()
            except Exception as err:  # noqa: BLE001
                LOG.debug("mqtt stop: %s", err)

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            return
        LOG.info(t("Connected to MQTT"))
        client.publish(STATE_TOPIC + "/available", "online", retain=True)
        client.subscribe(DIAG_REQUEST_TOPIC)
        dev = {"identifiers": ["thread_anchor"], "name": "Thread Anchor", "manufacturer": "Pintjes", "sw_version": VERSION}
        common = {"state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
                  "json_attributes_topic": STATE_TOPIC, "device": dev}
        client.publish(f"{DISCOVERY}/binary_sensor/thread_anchor/anchored/config", json.dumps(dict(
            common, name="OMR prefix anchored", unique_id="thread_anchor_anchored", icon="mdi:anchor",
            value_template="{{ 'ON' if value_json.enforced else 'OFF' }}")), retain=True)
        client.publish(f"{DISCOVERY}/sensor/thread_anchor/favored/config", json.dumps(dict(
            common, name="Favored OMR prefix", unique_id="thread_anchor_favored", icon="mdi:ip-network",
            value_template="{{ value_json.favored or 'unknown' }}")), retain=True)
        # read only: the role of the border router in the Thread network (the number of routers is
        # in the attributes, `thread_routers`); Thread Anchor never tries to change it
        client.publish(f"{DISCOVERY}/sensor/thread_anchor/thread_role/config", json.dumps(dict(
            common, name="Thread role", unique_id="thread_anchor_thread_role", icon="mdi:router-network",
            value_template="{{ value_json.thread_role or 'unknown' }}")), retain=True)
        self.publish()

    def publish(self):
        if self.client is not None:
            state = dict(self.anchor.public(), version=VERSION,
                         updated=datetime.now().astimezone().isoformat(timespec="seconds"))
            self.client.publish(STATE_TOPIC, json.dumps(state), retain=True)


def main():
    global LANG
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    try:
        with open("/data/options.json", encoding="utf-8") as f:
            options = json.load(f)
    except OSError:
        options = {}
    LANG = options.get("language", "en")
    if options.get("debug"):
        logging.getLogger().setLevel(logging.DEBUG)
    LOG.info(t("Thread Anchor {v} starting", v=VERSION))
    anchor = Anchor(options, memory=MEMORY_FILE)
    if anchor.config_error:
        LOG.error(anchor.config_error)
    elif not anchor.enabled:
        LOG.info(t("No omr_prefix: the border router is only watched, nothing is set"))
    mq = Mqtt(anchor)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    last_pub = 0.0
    while not stop.is_set():
        changed = False
        mq.start()
        try:
            if anchor.restarted():
                changed = anchor.check("restart")
            elif anchor.due():
                changed = anchor.check()
        except Exception as err:  # noqa: BLE001 - one bad pass must not end the add-on
            LOG.warning("check: %s", err)
        if changed or anchor.events or time.time() - last_pub > HEARTBEAT_S:
            anchor.events = []
            mq.publish()
            last_pub = time.time()
        stop.wait(TICK_S)
    mq.stop()


if __name__ == "__main__":
    main()

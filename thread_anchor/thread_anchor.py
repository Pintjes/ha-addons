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
mode off. The state is published on MQTT (`thread_anchor/state`, retained), with entities; Mesh
Guardian reads it.
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

VERSION = "0.1.1"
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

    def _otctl(self, *args):
        code, out = self._call(self.docker.exec, ["ot-ctl", *args])
        if code not in (0, None) and "Done" not in out:
            raise RuntimeError((out.strip().splitlines() or [f"exit {code}"])[-1])
        return out

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
        except Exception as err:  # noqa: BLE001
            if "InvalidCommand" in str(err):
                self._fail(t("This border router does not know `br omrconfig` (OpenThread too old): {err}", err=err))
            else:
                self._fail(t("Border router unreachable: {err}", err=err))
        return json.dumps(self.public(), sort_keys=True) != before

    def _fail(self, txt):
        self.mode = self.current = self.current_prf = None
        self.favored = self.favored_prf = self.local = None
        if txt != self.error:
            self.emit("error", txt, logging.WARNING)
        self.error = txt

    def public(self):
        return {"otbr_addon": self.slug, "wanted": self.prefix, "preference": self.preference, "mode": self.mode,
                "current": self.current, "current_preference": self.current_prf, "enforced": self.enforced(),
                "favored": self.favored, "favored_preference": self.favored_prf, "local": self.local,
                "applied": self.applied, "applied_at": self.applied_at, "otbr_started_at": self.started_at,
                "error": self.error, "anchored_since": self.anchored_since, "followed": self.followed()}


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
        dev = {"identifiers": ["thread_anchor"], "name": "Thread Anchor", "manufacturer": "Pintjes", "sw_version": VERSION}
        common = {"state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
                  "json_attributes_topic": STATE_TOPIC, "device": dev}
        client.publish(f"{DISCOVERY}/binary_sensor/thread_anchor/anchored/config", json.dumps(dict(
            common, name="OMR prefix anchored", unique_id="thread_anchor_anchored", icon="mdi:anchor",
            value_template="{{ 'ON' if value_json.enforced else 'OFF' }}")), retain=True)
        client.publish(f"{DISCOVERY}/sensor/thread_anchor/favored/config", json.dumps(dict(
            common, name="Favored OMR prefix", unique_id="thread_anchor_favored", icon="mdi:ip-network",
            value_template="{{ value_json.favored or 'unknown' }}")), retain=True)
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

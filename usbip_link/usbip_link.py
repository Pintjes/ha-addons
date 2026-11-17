# USB/IP Link — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: MIT (see LICENSE). Based on the idea of rogerfar/ha-usbip-client (MIT, (c) 2024 crypted),
# rewritten: attachment kept up for good instead of once at start.
"""USB devices of another computer (USB/IP server: usbipd-win on Windows, usbipd on Linux) attached
to Home Assistant, and kept attached.

Typical use: Home Assistant in a Hyper-V virtual machine, which has no USB, and a radio (ZBT-2,
SkyConnect…) plugged into the Windows host, shared with usbipd-win.

Every `check_interval` seconds:
- a device not attached is attached as soon as the server answers (bus id found from its
  hardware id "vvvv:pppp", so a change of USB port on the server does not matter);
- an attached device whose server no longer answers for DEAD_CHECKS checks in a row (the server
  restarts: Windows update…) is detached, so that its port is free and the device is attached
  again when the server is back, instead of a dead link the kernel keeps for a long time;
- after an attachment that follows a loss, the add-ons listed in `restart_addons` are restarted
  (the OpenThread border router opens its radio at start only).
The state is published on MQTT (`usbip_link/state`, retained) with a Home Assistant entity per
device; Mesh Guardian reads it and says when the radio of a border router is cut off.

Optional (`omr_prefix`): the OpenThread border router is kept on a fixed OMR prefix. A prefix it
generates itself has a low preference, like those of the other border routers (Google TV…), which
replace theirs now and then: the whole Thread network then changes its OMR prefix. A custom prefix
with a higher preference is favored by every border router, the others withdraw theirs. OpenThread
keeps this setting in memory only: it is read back every OMR_CHECK_S and set again after each start
of the border router (`ot-ctl br omrconfig`, through the Docker API).
"""
import http.client
import ipaddress
import json
import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime

VERSION = "0.2.0"
LOG = logging.getLogger("usbip_link")
STATE_TOPIC = "usbip_link/state"
DISCOVERY = "homeassistant"
DEAD_CHECKS = 3          # checks in a row without the server before an attached device is detached
HEARTBEAT_S = 300        # the state is published again this often, even unchanged
RESTART_SETTLE_S = 5     # s: time left to the system to create the serial port before the restarts
USBIP_PORT = 3240
OTBR_ADDON = "core_openthread_border_router"
OMR_CHECK_S = 30         # s between two readings of the OMR configuration of the border router
OMR_PREFERENCES = ("high", "med", "low")
DOCKER_SOCK = "/run/docker.sock"

TEXTS = {
    "fr": {
        "USB/IP Link {v} starting": "Démarrage de USB/IP Link {v}",
        "vhci-hcd module loaded": "Module vhci-hcd chargé",
        "Cannot load the vhci-hcd module: {err}": "Impossible de charger le module vhci-hcd : {err}",
        "{name}: attached ({server} {busid})": "{name} : attaché ({server} {busid})",
        "{name}: attached again after {d} ({server} {busid})": "{name} : rattaché après {d} ({server} {busid})",
        "{name}: server {server} silent, device detached (it will be attached again when the server is back)":
            "{name} : serveur {server} muet, périphérique détaché (rattaché dès le retour du serveur)",
        "{name}: link lost": "{name} : lien perdu",
        "{name}: not found on {server} (hardware id {hw})": "{name} : introuvable sur {server} (identifiant {hw})",
        "{name}: attachment refused: {err}": "{name} : attachement refusé : {err}",
        "Server {server} does not answer (port {port})": "Le serveur {server} ne répond pas (port {port})",
        "Server {server} answers again": "Le serveur {server} répond à nouveau",
        "Add-on {slug} restarted": "Add-on {slug} redémarré",
        "Cannot restart the add-on {slug}: {err}": "Impossible de redémarrer l'add-on {slug} : {err}",
        "Connected to MQTT": "Connecté à MQTT",
        "No MQTT broker: the state is only in the log": "Pas de broker MQTT : l'état n'est que dans le journal",
        "Invalid omr_prefix {p}: {err}": "omr_prefix {p} invalide : {err}",
        "Invalid omr_preference {p}: high, med or low": "omr_preference {p} invalide : high, med ou low",
        "OMR prefix {p} (preference {prf}) set on the border router (it was: {was})":
            "Préfixe OMR {p} (préférence {prf}) imposé au border router (il était : {was})",
        "OMR prefix {p} (preference {prf}) in place on the border router":
            "Préfixe OMR {p} (préférence {prf}) en place sur le border router",
        "OMR prefix: border router unreachable: {err}": "Préfixe OMR : border router injoignable : {err}",
        "OMR prefix: this border router does not know `br omrconfig` (OpenThread too old): {err}":
            "Préfixe OMR : ce border router ne connaît pas `br omrconfig` (OpenThread trop ancien) : {err}",
        "OMR prefix: no access to the Docker API ({err}); turn Protection mode off":
            "Préfixe OMR : pas d'accès à l'API Docker ({err}) ; désactiver le mode protection",
    },
}
LANG = "en"


def t(key, **kw):
    return TEXTS.get(LANG, {}).get(key, key).format(**kw)


def fmt_duration(s):
    s = int(max(0, s))
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{round(s / 60)} min"
    return f"{s // 3600} h {(s % 3600) // 60:02d}"


# ---------------------------------------------------------------- parsing of the usbip tool
PORT_RE = re.compile(r"^Port\s+(\d+):\s+<(.+?)>")
HWID_RE = re.compile(r"\(([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\)\s*$")
REMOTE_RE = re.compile(r"->\s*usbip://\[?([^\]\s/]+?)\]?:(\d+)/(\S+)")
LIST_RE = re.compile(r"^\s*([0-9A-Za-z.-]+):\s+(.*?)\s*\(([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\)\s*$")


def parse_port(text):
    """`usbip port` -> [{"port", "hwid", "server", "busid"}] of the ports in use."""
    out, cur = [], None
    for line in (text or "").splitlines():
        m = PORT_RE.match(line.strip())
        if m:
            cur = {"port": m.group(1), "in_use": "in use" in m.group(2).lower(), "hwid": None, "server": None, "busid": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = HWID_RE.search(line)
        if m and cur["hwid"] is None:
            cur["hwid"] = f"{m.group(1)}:{m.group(2)}".lower()
        m = REMOTE_RE.search(line)
        if m:
            cur["server"], cur["busid"] = m.group(1), m.group(3)
    return [p for p in out if p["in_use"]]


def parse_list(text):
    """`usbip list -r <server>` -> [{"busid", "hwid", "desc"}] of the devices it exports."""
    out = []
    for line in (text or "").splitlines():
        m = LIST_RE.match(line)
        if m:
            out.append({"busid": m.group(1), "desc": m.group(2), "hwid": f"{m.group(3)}:{m.group(4)}".lower()})
    return out


def find_port(ports, dev, server):
    for p in ports:
        if p["server"] not in (None, server):
            continue
        if dev.get("bus_id") and p["busid"] == dev["bus_id"]:
            return p
        if dev.get("hardware_id") and p["hwid"] == dev["hardware_id"].lower():
            return p
    return None


def server_up(host, port=USBIP_PORT, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(args, timeout=20):
    """Output of a command; raises RuntimeError with its error text when it fails."""
    res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or f"exit {res.returncode}").strip().splitlines()[-1])
    return res.stdout


# ---------------------------------------------------------------- the link
class Link:
    def __init__(self, options, runner=run, probe=server_up, clock=time.time):
        self.server = str(options.get("server") or "").strip()
        self.port = int(options.get("server_port") or USBIP_PORT)
        self.devices = []
        for i, d in enumerate(options.get("devices") or []):
            hw = str(d.get("hardware_id") or "").strip().lower()
            bus = str(d.get("bus_id") or "").strip()
            name = str(d.get("name") or "").strip() or hw or bus or f"device {i + 1}"
            if hw or bus:
                self.devices.append({"name": name, "hardware_id": hw, "bus_id": bus})
        self.restart_addons = [s for s in (options.get("restart_addons") or []) if s]
        self.run, self.probe, self.clock = runner, probe, clock
        self.state = {d["name"]: {"attached": False, "since": None, "busid": None, "error": None,
                                  "attached_once": False, "lost_at": None, "attaches": 0} for d in self.devices}
        self.server_ok = None
        self.dead = 0
        self.events = []       # (kind, text) since the last publish, for the log and MQTT
        self.restart = []      # add-ons to restart after this check

    def emit(self, kind, text, level=logging.INFO):
        LOG.log(level, text)
        self.events.append((kind, text))

    def check(self):
        """One pass; returns True when the state changed."""
        before = json.dumps(self.public(), sort_keys=True)
        up = self.probe(self.server, self.port)
        if up != self.server_ok:
            if up is False:
                self.emit("server_down", t("Server {server} does not answer (port {port})", server=self.server, port=self.port),
                          logging.WARNING)
            elif self.server_ok is False:
                self.emit("server_up", t("Server {server} answers again", server=self.server))
            self.server_ok = up
        self.dead = 0 if up else self.dead + 1
        try:
            ports = parse_port(self.run(["usbip", "port"]))
        except Exception as err:  # noqa: BLE001 - no port in use, or the module is missing
            LOG.debug("usbip port: %s", err)
            ports = []
        exported = None
        reattached = False
        for d in self.devices:
            st = self.state[d["name"]]
            p = find_port(ports, d, self.server)
            if p and not up and self.dead >= DEAD_CHECKS:
                # the server restarts: the kernel would keep a dead link for long; free the port
                try:
                    self.run(["usbip", "detach", "-p", str(int(p["port"]))])
                except Exception as err:  # noqa: BLE001
                    LOG.debug("detach %s: %s", d["name"], err)
                self.emit("detached", t("{name}: server {server} silent, device detached (it will be attached again when "
                                        "the server is back)", name=d["name"], server=self.server), logging.WARNING)
                self._lost(st)
                continue
            if p:
                if not st["attached"]:
                    # attached already when the add-on started, or by someone else: taken as it is
                    st.update(attached=True, since=self.clock(), busid=p["busid"], error=None, attached_once=True)
                continue
            if st["attached"]:
                self.emit("lost", t("{name}: link lost", name=d["name"]), logging.WARNING)
                self._lost(st)
            if not up:
                continue
            busid = d["bus_id"]
            if not busid:
                if exported is None:
                    try:
                        exported = parse_list(self.run(["usbip", "list", "-r", self.server]))
                    except Exception as err:  # noqa: BLE001
                        LOG.debug("usbip list: %s", err)
                        exported = []
                busid = next((x["busid"] for x in exported if x["hwid"] == d["hardware_id"]), None)
                if not busid:
                    err = t("{name}: not found on {server} (hardware id {hw})", name=d["name"], server=self.server,
                            hw=d["hardware_id"])
                    if st["error"] != err:
                        self.emit("not_found", err, logging.WARNING)
                    st["error"] = err
                    continue
            try:
                self.run(["usbip", "attach", "-r", self.server, "-b", busid], timeout=30)
            except Exception as err:  # noqa: BLE001
                txt = t("{name}: attachment refused: {err}", name=d["name"], err=err)
                if st["error"] != txt:
                    self.emit("refused", txt, logging.WARNING)
                st["error"] = txt
                continue
            again = st["lost_at"] is not None
            st.update(attached=True, since=self.clock(), busid=busid, error=None, attaches=st["attaches"] + 1)
            if again:
                self.emit("attached", t("{name}: attached again after {d} ({server} {busid})", name=d["name"],
                                        d=fmt_duration(self.clock() - st["lost_at"]), server=self.server, busid=busid))
                reattached = True
            else:
                self.emit("attached", t("{name}: attached ({server} {busid})", name=d["name"], server=self.server, busid=busid))
            st["attached_once"], st["lost_at"] = True, None
        if reattached:
            self.restart = list(self.restart_addons)
        return json.dumps(self.public(), sort_keys=True) != before

    def _lost(self, st):
        st.update(attached=False, since=self.clock(), busid=None)
        if st["lost_at"] is None:
            st["lost_at"] = self.clock()

    def public(self):
        """State published on MQTT (and read by Mesh Guardian)."""
        return {"server": self.server, "server_ok": self.server_ok,
                "devices": [{"name": d["name"], "hardware_id": d["hardware_id"], "attached": self.state[d["name"]]["attached"],
                             "since": self.state[d["name"]]["since"], "busid": self.state[d["name"]]["busid"],
                             "error": self.state[d["name"]]["error"], "attaches": self.state[d["name"]]["attaches"]}
                            for d in self.devices]}


# ---------------------------------------------------------------- OMR prefix of the border router
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


def docker_exec(container, cmd, timeout=30):
    """(exit code, stdout + stderr) of a command run in a container."""
    ex = json.loads(_docker("POST", f"/containers/{container}/exec",
                            {"AttachStdout": True, "AttachStderr": True, "Cmd": cmd}, timeout))
    raw = _docker("POST", f"/exec/{ex['Id']}/start", {"Detach": False, "Tty": False}, timeout)
    info = json.loads(_docker("GET", f"/exec/{ex['Id']}/json", None, timeout))
    return info.get("ExitCode"), demux(raw)


OMR_CUSTOM_RE = re.compile(r"custom\s*\(\s*([0-9a-fA-F:.]+/\d+)\s*,\s*prf:\s*(\w+)\s*\)")


def parse_omrconfig(text):
    """`ot-ctl br omrconfig` -> (mode, prefix, preference): ("custom", "fd00:1::/64", "high"), ("auto", None, None)…"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("Error"):
            raise RuntimeError(ln)
    for ln in lines:
        m = OMR_CUSTOM_RE.search(ln)
        if m:
            return "custom", str(ipaddress.IPv6Network(m.group(1), strict=False)), m.group(2).lower()
        if ln in ("auto", "disabled"):
            return ln, None, None
    raise RuntimeError(f"unexpected answer: {lines[-1] if lines else '(empty)'}")


class OmrKeeper:
    """Keeps the OpenThread border router on the OMR prefix of the options (off without `omr_prefix`)."""

    def __init__(self, options, executor=docker_exec, clock=time.time):
        self.prefix, self.config_error = None, None
        raw = str(options.get("omr_prefix") or "").strip()
        self.preference = str(options.get("omr_preference") or "high").strip().lower()
        if raw:
            try:
                net = ipaddress.IPv6Network(raw, strict=True)
                if net.prefixlen != 64:
                    raise ValueError("an OMR prefix is a /64")
                self.prefix = str(net)
            except ValueError as err:
                self.config_error = t("Invalid omr_prefix {p}: {err}", p=raw, err=err)
            if self.preference not in OMR_PREFERENCES:
                self.config_error = t("Invalid omr_preference {p}: high, med or low", p=self.preference)
                self.prefix = None
        self.container = "addon_" + (str(options.get("otbr_addon") or "").strip() or OTBR_ADDON)
        self.exec, self.clock = executor, clock
        self.mode = self.current = self.current_prf = self.error = self.applied_at = None
        self.applied = 0
        self.last_check = None
        self.events = []

    @property
    def enabled(self):
        return self.prefix is not None

    def enforced(self):
        return self.mode == "custom" and self.current == self.prefix and self.current_prf == self.preference

    def emit(self, kind, text, level=logging.INFO):
        LOG.log(level, text)
        self.events.append((kind, text))

    def _otctl(self, *args):
        code, out = self.exec(self.container, ["ot-ctl", *args])
        if code not in (0, None) and "Done" not in out:
            raise RuntimeError((out.strip().splitlines() or [f"exit {code}"])[-1])
        return out

    def _read(self):
        self.mode, self.current, self.current_prf = parse_omrconfig(self._otctl("br", "omrconfig"))

    def due(self):
        return self.enabled and (self.last_check is None or self.clock() - self.last_check >= OMR_CHECK_S)

    def check(self):
        """One reading, and the custom prefix set again when needed; returns True when the state changed."""
        if not self.enabled:
            return False
        before = json.dumps(self.public(), sort_keys=True)
        self.last_check = self.clock()
        was_ok = self.enforced()
        try:
            self._read()
            if self.enforced():
                if not was_ok:
                    self.emit("omr_ok", t("OMR prefix {p} (preference {prf}) in place on the border router",
                                          p=self.prefix, prf=self.preference))
            else:
                was = f"{self.mode} {self.current or ''} {self.current_prf or ''}".strip()
                out = self._otctl("br", "omrconfig", "custom", self.prefix, self.preference)
                if "Done" not in out:
                    raise RuntimeError((out.strip().splitlines() or ["(empty)"])[-1])
                self.applied += 1
                self.applied_at = self.clock()
                self._read()
                self.emit("omr_set", t("OMR prefix {p} (preference {prf}) set on the border router (it was: {was})",
                                       p=self.prefix, prf=self.preference, was=was))
            self.error = None
        except DockerError as err:
            # 404/409: border router stopped or starting, 403 or no socket: no access to Docker at all
            if str(err).startswith(("403", "[Errno 2]", "[Errno 13]")):
                txt = t("OMR prefix: no access to the Docker API ({err}); turn Protection mode off", err=err)
            else:
                txt = t("OMR prefix: border router unreachable: {err}", err=err)
            self._fail(txt)
        except Exception as err:  # noqa: BLE001
            if "InvalidCommand" in str(err):
                txt = t("OMR prefix: this border router does not know `br omrconfig` (OpenThread too old): {err}", err=err)
            else:
                txt = t("OMR prefix: border router unreachable: {err}", err=err)
            self._fail(txt)
        return json.dumps(self.public(), sort_keys=True) != before

    def _fail(self, txt):
        self.mode = self.current = self.current_prf = None
        if txt != self.error:
            self.emit("omr_error", txt, logging.WARNING)
        self.error = txt

    def public(self):
        return {"wanted": self.prefix, "preference": self.preference, "mode": self.mode, "current": self.current,
                "current_preference": self.current_prf, "enforced": self.enforced(), "applied": self.applied,
                "applied_at": self.applied_at, "error": self.error}


# ---------------------------------------------------------------- Home Assistant side
def supervisor(path, method="GET", timeout=30):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("no Supervisor token")
    req = urllib.request.Request(f"http://supervisor{path}", method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body).get("data", {}) if body else {}


def load_module():
    """vhci-hcd: the virtual USB controller the devices are attached to."""
    if os.path.isdir("/sys/devices/platform/vhci_hcd.0"):
        return True
    try:
        run(["modprobe", "vhci-hcd"])
        LOG.info(t("vhci-hcd module loaded"))
        return True
    except Exception as err:  # noqa: BLE001
        LOG.error(t("Cannot load the vhci-hcd module: {err}", err=err))
        return False


def slug_of(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "device"


class Mqtt:
    def __init__(self, link, omr=None):
        self.link, self.omr, self.client = link, omr, None
        try:
            import paho.mqtt.client as mqtt   # noqa: PLC0415
            conf = supervisor("/services/mqtt")
        except Exception as err:  # noqa: BLE001
            LOG.warning("%s (%s)", t("No MQTT broker: the state is only in the log"), err)
            return
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="usbip_link")
        if conf.get("username"):
            c.username_pw_set(conf["username"], conf.get("password"))
        c.will_set(STATE_TOPIC + "/available", "offline", retain=True)
        c.on_connect = self.on_connect
        c.reconnect_delay_set(1, 60)
        c.connect_async(conf.get("host", "core-mosquitto"), int(conf.get("port", 1883)), keepalive=60)
        c.loop_start()
        self.client = c

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            return
        LOG.info(t("Connected to MQTT"))
        client.publish(STATE_TOPIC + "/available", "online", retain=True)
        dev = {"identifiers": ["usbip_link"], "name": "USB/IP Link", "manufacturer": "Pintjes", "sw_version": VERSION}
        for d in self.link.devices:
            s = slug_of(d["name"])
            cfg = {"name": d["name"], "unique_id": f"usbip_link_{s}", "device_class": "connectivity",
                   "state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
                   "value_template": "{{ 'ON' if (value_json.devices | selectattr('name', 'eq', '%s') | map(attribute='attached') "
                                     "| first) else 'OFF' }}" % d["name"].replace("'", ""),
                   "json_attributes_topic": STATE_TOPIC,
                   "json_attributes_template": "{{ (value_json.devices | selectattr('name', 'eq', '%s') | first) | tojson }}"
                                               % d["name"].replace("'", ""),
                   "device": dev}
            client.publish(f"{DISCOVERY}/binary_sensor/usbip_link/{s}/config", json.dumps(cfg), retain=True)
        omr_topic = f"{DISCOVERY}/binary_sensor/usbip_link/omr_prefix/config"
        if self.omr is not None and self.omr.enabled:
            cfg = {"name": "OMR prefix", "unique_id": "usbip_link_omr_prefix", "icon": "mdi:ip-network",
                   "state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
                   "value_template": "{{ 'ON' if value_json.omr and value_json.omr.enforced else 'OFF' }}",
                   "json_attributes_topic": STATE_TOPIC,
                   "json_attributes_template": "{{ (value_json.omr or {}) | tojson }}",
                   "device": dev}
            client.publish(omr_topic, json.dumps(cfg), retain=True)
        else:
            client.publish(omr_topic, "", retain=True)   # option turned off: the entity goes away
        self.publish()

    def publish(self):
        if self.client is not None:
            state = dict(self.link.public(), version=VERSION,
                         updated=datetime.now().astimezone().isoformat(timespec="seconds"))
            if self.omr is not None and self.omr.enabled:
                state["omr"] = self.omr.public()
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
    LOG.info(t("USB/IP Link {v} starting", v=VERSION))
    try:   # attaching writes to sysfs, read-only in a container until mounted again
        subprocess.run(["mount", "-o", "remount,rw", "/sys"], capture_output=True, timeout=10, check=False)
    except Exception as err:  # noqa: BLE001
        LOG.debug("remount /sys: %s", err)
    load_module()
    link = Link(options)
    omr = OmrKeeper(options)
    if omr.config_error:
        LOG.error(omr.config_error)
    mq = Mqtt(link, omr)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    interval = max(3, int(options.get("check_interval") or 10))
    last_pub = 0.0
    while not stop.is_set():
        try:
            changed = link.check()
        except Exception as err:  # noqa: BLE001 - one bad pass must not end the add-on
            LOG.warning("check: %s", err)
            changed = False
        if link.restart:
            todo, link.restart = link.restart, []
            stop.wait(RESTART_SETTLE_S)
            for slug in todo:
                try:
                    supervisor(f"/addons/{slug}/restart", method="POST", timeout=120)
                    LOG.info(t("Add-on {slug} restarted", slug=slug))
                except Exception as err:  # noqa: BLE001
                    LOG.warning(t("Cannot restart the add-on {slug}: {err}", slug=slug, err=err))
            omr.last_check = None   # the border router just restarted without the custom prefix: check at once
        if omr.due():
            try:
                changed = omr.check() or changed
            except Exception as err:  # noqa: BLE001
                LOG.warning("omr: %s", err)
        if changed or link.events or omr.events or time.time() - last_pub > HEARTBEAT_S:
            link.events, omr.events = [], []
            mq.publish()
            last_pub = time.time()
        stop.wait(interval)
    # the devices stay attached: a restart of the add-on must not cut the radio of the border router


if __name__ == "__main__":
    main()

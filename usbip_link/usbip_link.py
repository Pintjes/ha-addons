# USB/IP Link — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# © 2026 Pintjes. All rights reserved. See LICENSE.
# Idea from rogerfar/ha-usbip-client (shell scripts, MIT); no code taken from it: written anew in
# Python, attachment kept up for good instead of once at start.
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
- when the server answers again after ANY silence, even a single check, the attached device is
  detached and attached again: the kernel does not always see a link die (a virtual machine
  resumed, a restarted usbipd), and the port would stay "in use" on a dead connection;
- an attachment counts only once the device is there (tty included for a serial one); else its port
  is detached and it is tried again. A port taken by a device that never appeared (`usbip port` does
  not show it) is detached before anything else, at the start of the add-on too;
- after an attachment that follows a loss, the add-ons listed in `restart_addons` are restarted
  (the OpenThread border router opens its radio at start only); after the first attachment, only
  those already running (or in error): at the start of Home Assistant they may have started before
  the device was there. A device found attached already (restart of this add-on) restarts nothing.
The state is published on MQTT (`usbip_link/state`, retained) with a Home Assistant entity per
device; Mesh Guardian reads it and says when the radio of a border router is cut off. The time the
server takes to answer (TCP connection to its USB/IP port) is published too, as the latency of the
link: a slow or irregular link shows there before the radio suffers.

The fixed OMR prefix of 0.2.x (`omr_prefix`) moved to its own add-on, Thread Anchor: it serves any
OpenThread border router, with or without USB/IP.
"""
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

VERSION = "0.4.4"
LOG = logging.getLogger("usbip_link")
STATE_TOPIC = "usbip_link/state"
DISCOVERY = "homeassistant"
DEAD_CHECKS = 3          # checks in a row without the server before an attached device is detached
HEARTBEAT_S = 300        # the state is published again this often, even unchanged
RESTART_SETTLE_S = 5     # s: time left to the system to create the serial port before the restarts
USBIP_PORT = 3240
LATENCY_SAMPLES = 30     # latency average over this many checks (5 min at 10 s)
LATENCY_PUBLISH_S = 60   # a change of the latency alone is published at most this often
RUNNING = ("started", "error")   # states of an add-on restarted after the first attachment
RETRY_S = 15             # s between two tries of a restart the Supervisor refused (503 while it starts)
RETRY_MAX_S = 300        # s: a restart is tried again for this long, then given up
MQTT_RETRY_S = 30        # s between two tries to find the MQTT broker, until found
CLOCK_JUMP_S = 20        # s: a jump of the clock (wall vs monotonic) beyond this = machine paused and resumed
WATCH_STEP_S = 2         # s: the wait between two checks is cut in steps of this length to see a jump at once
ENUM_TIMEOUT_S = 15      # s given to the kernel to finish the enumeration of a device just attached
STUCK_CONFIRM_S = 3      # s a port must stay stuck before it is detached
VHCI_DIR = "/sys/devices/platform/vhci_hcd.0"
USB_DIR = "/sys/bus/usb/devices"
VDEV_NULL, VDEV_NOTASSIGNED, VDEV_USED, VDEV_ERROR = 4, 5, 6, 7   # port states of the vhci `status` file
# taken, but not shown (NOTASSIGNED) or not usable (ERROR): `usbip port` leaves them out
STUCK = (VDEV_NOTASSIGNED, VDEV_ERROR)

TEXTS = {
    "fr": {
        "USB/IP Link {v} starting": "Démarrage de USB/IP Link {v}",
        "vhci-hcd module loaded": "Module vhci-hcd chargé",
        "Cannot load the vhci-hcd module: {err}": "Impossible de charger le module vhci-hcd : {err}",
        "Cannot remount /sys writable, attaching will fail (AppArmor profile?): {err}": "Impossible de remonter /sys en écriture, l'attache échouera (profil AppArmor ?) : {err}",
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
        "Add-on {slug} restarted: it started before the device was attached":
            "Add-on {slug} redémarré : il avait démarré avant l'attachement du périphérique",
        "Cannot restart the add-on {slug}: {err}": "Impossible de redémarrer l'add-on {slug} : {err}",
        "Cannot restart the add-on {slug}: {err} (trying again for up to {m} min)":
            "Impossible de redémarrer l'add-on {slug} : {err} (nouvel essai pendant {m} min au plus)",
        "Add-on {slug} restarted after {n} tries": "Add-on {slug} redémarré au bout de {n} essais",
        "Add-on {slug} not restarted after {m} min: {err}. It may be stuck on the dead device: stop it, then start it "
        "again by hand":
            "Add-on {slug} non redémarré après {m} min : {err}. Il est peut-être bloqué sur le périphérique mort : "
            "l'arrêter puis le redémarrer à la main",
        "{name}: already attached (port {port}, {server} {busid}), taken as it is":
            "{name} : déjà attaché (port {port}, {server} {busid}), repris tel quel",
        "{name}: server {server} answers again after a silence, the device is detached and attached again (the link may "
        "have died without the kernel noticing)":
            "{name} : le serveur {server} répond à nouveau après un silence, périphérique détaché puis rattaché (la "
            "liaison a pu mourir sans que le noyau le voie)",
        "The clock jumped by {gap} s (machine paused and resumed?): the links are checked at once":
            "L'horloge a sauté de {gap} s (machine mise en pause puis reprise ?) : les liaisons sont vérifiées tout de suite",
        "{name}: the machine was paused, the device is detached at once (its link may be dead) and attached again when "
        "the server answers":
            "{name} : la machine a été mise en pause, périphérique détaché tout de suite (sa liaison a pu mourir) et "
            "rattaché dès que le serveur répond",
        "{name}: cannot detach port {port}: {err}": "{name} : impossible de détacher le port {port} : {err}",
        "Port {port} taken but the device never appeared (invisible to `usbip port`): detached":
            "Port {port} occupé alors que le périphérique n'est jamais apparu (invisible pour `usbip port`) : détaché",
        "Cannot detach the stuck port {port}: {err}": "Impossible de détacher le port bloqué {port} : {err}",
        "{name}: attached, but the device did not appear within {s} s: port detached, tried again":
            "{name} : attaché, mais le périphérique n'est pas apparu en {s} s : port détaché, nouvel essai",
        "The state of the vhci ports cannot be read: attachments are not checked":
            "L'état des ports vhci est illisible : les attachements ne sont pas vérifiés",
        "{name}: bus id changed on the server ({old} -> {new})": "{name} : identifiant de bus modifié sur le serveur ({old} -> {new})",
        "Connected to MQTT": "Connecté à MQTT",
        "No MQTT broker yet: the state is only in the log until it answers (trying again every {s} s)":
            "Pas encore de broker MQTT : l'état n'est que dans le journal tant qu'il ne répond pas (nouvel essai toutes les {s} s)",
        "omr_prefix is set but no longer used here: the fixed OMR prefix moved to the Thread Anchor add-on":
            "omr_prefix est rempli mais ne sert plus ici : le préfixe OMR fixe est passé dans l'add-on Thread Anchor",
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


def find_port(ports, dev, servers):
    """Port of `dev` among `ports`; `servers`: the names the server is shown under by `usbip port`
    (the address of the option and the addresses it resolves to)."""
    if isinstance(servers, str):
        servers = {servers}
    for p in ports:
        if p["server"] is not None and p["server"] not in servers:
            continue
        if dev.get("bus_id") and p["busid"] == dev["bus_id"]:
            return p
        if dev.get("hardware_id") and p["hwid"] == dev["hardware_id"].lower():
            return p
    return None


def parse_vhci(text):
    """The vhci `status` file -> [{"port", "status", "local_busid"}] of every port (header skipped)."""
    out = []
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) >= 7 and f[0] in ("hs", "ss") and f[1].isdigit() and f[2].isdigit():
            out.append({"port": int(f[1]), "status": int(f[2]), "local_busid": f[6]})
    return out


def read_vhci(root=VHCI_DIR):
    """Ports of every vhci controller (files status, status.1…); None when they cannot be read."""
    try:
        names = sorted(n for n in os.listdir(root) if n == "status" or n.startswith("status."))
        ports = []
        for name in names:
            with open(os.path.join(root, name), encoding="ascii") as f:
                ports += parse_vhci(f.read())
    except (OSError, UnicodeError):
        return None
    return ports or None


def usb_ready(busid, root=USB_DIR):
    """True once the local USB device `busid` is fully there: identified, with its interfaces, and, for a
    serial one of the CDC ACM class (ZBT-2, SkyConnect…), its tty created."""
    if not os.path.isfile(os.path.join(root, busid, "idVendor")):
        return False
    try:
        ifaces = [os.path.join(root, n) for n in os.listdir(root) if n.startswith(busid + ":")]
        if not ifaces:
            return False
        acm, tty = False, False
        for path in ifaces:
            entries = os.listdir(path)
            tty = tty or any(e.startswith("tty") and (e != "tty" or os.listdir(os.path.join(path, e))) for e in entries)
            cls = [_read(os.path.join(path, n)) for n in ("bInterfaceClass", "bInterfaceSubClass")]
            acm = acm or cls == ["02", "02"]
    except OSError:
        return False
    return tty or not acm


def _read(path):
    try:
        with open(path, encoding="ascii") as f:
            return f.read().strip().lower()
    except (OSError, UnicodeError):
        return ""


def server_up(host, port=USBIP_PORT, timeout=2.0):
    """Time to open a TCP connection to the server, in ms (the latency of the link); None when it does
    not answer."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return max(0.01, (time.monotonic() - start) * 1000)
    except OSError:
        return None


def resolve(host):
    """Addresses of `host` (a name or an address); empty when it cannot be resolved now."""
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        return set()


class ClockWatch:
    """Spots a pause of the machine (a virtual machine saved by Hyper-V, then resumed) or a step of its
    clock. The monotonic clock of Linux does not count the time the machine was stopped, and the wall clock
    is set right again after the resume: read together, they drift apart by the length of the pause. If
    the monotonic clock counted it instead, a wait that lasted much longer than asked shows it."""

    def __init__(self, wall=time.time, mono=time.monotonic):
        self.wallf, self.monof = wall, mono
        self.wall, self.mono = wall(), mono()

    def poll(self, expected=None):
        """Seconds of the jump since the last call (+ forward, - backward), or 0.0 when under CLOCK_JUMP_S.
        `expected`: the time the caller just waited, to spot a wait that lasted far longer."""
        w, m = self.wallf(), self.monof()
        dw, dm = w - self.wall, m - self.mono
        self.wall, self.mono = w, m
        drift = dw - dm
        late = max(dw, dm) - expected if expected is not None else 0.0
        for gap in (drift, late):
            if gap > CLOCK_JUMP_S:
                return gap
        if drift < -CLOCK_JUMP_S:
            return drift
        return 0.0


def percentile(values, pct):
    """Nearest-rank percentile of a list (None when empty): the smallest value that at least pct % of
    the values do not exceed."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * pct // 100) - 1)]


def run(args, timeout=20):
    """Output of a command; raises RuntimeError with its error text when it fails."""
    res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout or f"exit {res.returncode}").strip().splitlines()[-1])
    return res.stdout


# ---------------------------------------------------------------- the link
class Link:
    def __init__(self, options, runner=run, probe=server_up, clock=time.time, resolver=resolve, vhci=read_vhci,
                 ready=usb_ready, sleep=time.sleep):
        self.vhci, self.ready, self.sleep = vhci, ready, sleep
        self.unverified_said = False
        self.stuck_failed = set()   # stuck ports whose detach was refused, said once
        self.server = str(options.get("server") or "").strip()
        self.resolver = resolver
        self.servers = {self.server}   # + its addresses, once resolved: `usbip port` shows an address
        self.resolved = False
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
        self.silent = False      # the server did not answer at a check since the last time it did
        self.silent_at = None    # time of the first silent check of that silence
        self.resume_pending = False   # the clock jumped: the attached devices are detached at the next check
        self.last_busid = {}     # device name -> bus id of the last attachment, to say a change
        self.latency_ms = None   # last answer time of the server
        self.latencies = []      # last LATENCY_SAMPLES answer times, for the average and the worst
        self.events = []       # (kind, text) since the last publish, for the log and MQTT
        self.restart = []      # add-ons to restart after this check
        self.restart_if_running = False   # True: only those running or in error (first attachment)
        self.checks = 0        # checks done: nothing is published before the first (attached unknown till then)

    def emit(self, kind, text, level=logging.INFO):
        LOG.log(level, text)
        self.events.append((kind, text))

    def _stuck_ports(self):
        return {p["port"] for p in self.vhci() or [] if p["status"] in STUCK}

    def free_stuck(self):
        """Detaches the ports taken by a device that never appeared (attach accepted, enumeration hung):
        `usbip port` does not show them, yet the server keeps the device "busy" as long as they last."""
        stuck = self._stuck_ports()
        if not stuck:
            self.stuck_failed.clear()
            return
        self.sleep(STUCK_CONFIRM_S)   # not a port in the middle of an enumeration
        for port in sorted(stuck & self._stuck_ports()):
            try:
                self.run(["usbip", "detach", "-p", str(port)])
            except Exception as err:  # noqa: BLE001
                if port not in self.stuck_failed:
                    self.stuck_failed.add(port)
                    self.emit("stuck_failed", t("Cannot detach the stuck port {port}: {err}", port=port, err=err),
                              logging.WARNING)
                continue
            self.stuck_failed.discard(port)
            self.emit("stuck_freed", t("Port {port} taken but the device never appeared (invisible to `usbip port`): "
                                       "detached", port=port), logging.WARNING)

    def _taken_ports(self):
        """Ports in use before an attachment; None when they cannot be read (nothing to check then)."""
        ports = self.vhci()
        if ports is None:
            if not self.unverified_said:
                self.unverified_said = True
                LOG.warning(t("The state of the vhci ports cannot be read: attachments are not checked"))
            return None
        return {p["port"] for p in ports if p["status"] != VDEV_NULL}

    def wait_enumerated(self, before):
        """Waits for the port taken since `before` to hold a complete device (tty included). On failure,
        detaches that port only and returns False."""
        new = []
        for i in range(ENUM_TIMEOUT_S + 1):
            new = [p for p in self.vhci() or [] if p["port"] not in before and p["status"] != VDEV_NULL]
            if any(p["status"] == VDEV_USED and self.ready(p["local_busid"]) for p in new):
                return True
            if i < ENUM_TIMEOUT_S:
                self.sleep(1)
        for p in new:
            try:
                self.run(["usbip", "detach", "-p", str(p["port"])])
            except Exception as err:  # noqa: BLE001 - freed later by free_stuck if it stays stuck
                LOG.debug("detach port %s: %s", p["port"], err)
        return False

    def check(self):
        """One pass; returns True when the state changed."""
        before = json.dumps(self.public(latency=False), sort_keys=True)
        res = self.probe(self.server, self.port)
        # the probe gives the answer time in ms (None: silent); a plain True/False is accepted too
        up = bool(res) if isinstance(res, bool) or res is None else True
        self.latency_ms = round(float(res), 1) if up and not isinstance(res, bool) else None
        if self.latency_ms is not None:
            self.latencies = (self.latencies + [self.latency_ms])[-LATENCY_SAMPLES:]
        elif not up:
            self.latencies = []   # server silent: no latency, rather than an average of before
        if up and not self.resolved:
            # a name: `usbip port` shows the address; tried again at each check until it resolves
            addrs = self.resolver(self.server)
            self.servers |= addrs
            self.resolved = bool(addrs)
        if up != self.server_ok:
            if up is False:
                self.emit("server_down", t("Server {server} does not answer (port {port})", server=self.server, port=self.port),
                          logging.WARNING)
            elif self.server_ok is False:
                self.emit("server_up", t("Server {server} answers again", server=self.server))
            self.server_ok = up
        self.dead = 0 if up else self.dead + 1
        # back after a silence, even one check: a link that died without the kernel noticing (virtual
        # machine resumed, usbipd restarted) would keep the port "in use": detach and attach again
        # (or the clock jumped: virtual machine resumed after a pause: detach at once, server answering or not,
        # which also frees what is stuck on the dead device)
        force = self.resume_pending
        suspect = force or (up and self.silent)
        if not up and not self.silent:
            self.silent, self.silent_at = True, self.clock()
        detach_failed = False
        self.free_stuck()   # at the start of the add-on too, and before any new attachment
        try:
            ports = parse_port(self.run(["usbip", "port"]))
        except Exception as err:  # noqa: BLE001 - no port in use, or the module is missing
            LOG.debug("usbip port: %s", err)
            ports = []
        exported = None
        reattached = first = False
        for d in self.devices:
            st = self.state[d["name"]]
            p = find_port(ports, d, self.servers)
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
            if p and suspect:
                try:
                    self.run(["usbip", "detach", "-p", str(int(p["port"]))])
                except Exception as err:  # noqa: BLE001
                    txt = t("{name}: cannot detach port {port}: {err}", name=d["name"], port=p["port"], err=err)
                    if st["error"] != txt:
                        self.emit("detach_failed", txt, logging.WARNING)
                    st["error"] = txt
                    detach_failed = True   # tried again at the next check
                    continue
                if force:
                    self.emit("resumed", t("{name}: the machine was paused, the device is detached at once (its link may "
                                           "be dead) and attached again when the server answers", name=d["name"]),
                              logging.WARNING)
                else:
                    self.emit("resumed", t("{name}: server {server} answers again after a silence, the device is detached "
                                           "and attached again (the link may have died without the kernel noticing)",
                                           name=d["name"], server=self.server), logging.WARNING)
                self._lost(st)
                if self.silent_at is not None:
                    st["lost_at"] = min(st["lost_at"], self.silent_at)   # the loss dates from the silence
                p = None
            if p:
                if not st["attached"]:
                    # attached already when the add-on started, or by someone else: taken as it is
                    st.update(attached=True, since=self.clock(), busid=p["busid"], error=None, attached_once=True)
                    self.last_busid[d["name"]] = p["busid"]
                    self.emit("adopted", t("{name}: already attached (port {port}, {server} {busid}), taken as it is",
                                           name=d["name"], port=p["port"], server=p["server"] or self.server,
                                           busid=p["busid"]))
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
            before = self._taken_ports()
            try:
                self.run(["usbip", "attach", "-r", self.server, "-b", busid], timeout=30)
            except Exception as err:  # noqa: BLE001
                txt = t("{name}: attachment refused: {err}", name=d["name"], err=err)
                if st["error"] != txt:
                    self.emit("refused", txt, logging.WARNING)
                st["error"] = txt
                continue
            # accepted is not attached: said so (and the add-ons restarted) only once the device is there
            if before is not None and not self.wait_enumerated(before):
                txt = t("{name}: attached, but the device did not appear within {s} s: port detached, tried again",
                        name=d["name"], s=ENUM_TIMEOUT_S)
                if st["error"] != txt:
                    self.emit("enum_failed", txt, logging.WARNING)
                st["error"] = txt
                continue
            again = st["lost_at"] is not None
            old = self.last_busid.get(d["name"])
            if old and old != busid:
                self.emit("busid_changed", t("{name}: bus id changed on the server ({old} -> {new})", name=d["name"],
                                             old=old, new=busid), logging.WARNING)
            self.last_busid[d["name"]] = busid
            st.update(attached=True, since=self.clock(), busid=busid, error=None, attaches=st["attaches"] + 1)
            if again:
                self.emit("attached", t("{name}: attached again after {d} ({server} {busid})", name=d["name"],
                                        d=fmt_duration(self.clock() - st["lost_at"]), server=self.server, busid=busid))
                reattached = True
            else:
                self.emit("attached", t("{name}: attached ({server} {busid})", name=d["name"], server=self.server, busid=busid))
                first = first or not st["attached_once"]
            st["attached_once"], st["lost_at"] = True, None
        if suspect and not detach_failed:
            self.silent, self.silent_at, self.resume_pending = False, None, False
        if reattached:
            self.restart, self.restart_if_running = list(self.restart_addons), False
        elif first:
            # start of Home Assistant: the border router may have opened no radio; restarted if it runs
            self.restart, self.restart_if_running = list(self.restart_addons), True
        self.checks += 1
        # the latency moves at each check: published with the rest, not a reason to publish by itself
        return json.dumps(self.public(latency=False), sort_keys=True) != before

    def resumed(self, gap):
        """The clock jumped by `gap` s (ClockWatch): the machine was paused (a virtual machine saved and
        resumed) and the links with it. The next check detaches the devices at once."""
        self.resume_pending = True
        if not self.silent:
            self.silent, self.silent_at = True, self.clock() - max(0.0, gap)
        self.emit("clock_jump", t("The clock jumped by {gap} s (machine paused and resumed?): the links are checked at once",
                                  gap=f"{gap:+.0f}"), logging.WARNING)

    def _lost(self, st):
        st.update(attached=False, since=self.clock(), busid=None)
        if st["lost_at"] is None:
            st["lost_at"] = self.clock()

    def latency(self):
        """{"latency_ms", "latency_avg_ms", "latency_max_ms", "latency_p95_ms"} of the link to the server
        (None when unknown, the server silent included). Average, worst and 95th percentile are those of the
        last LATENCY_SAMPLES checks."""
        avg = round(sum(self.latencies) / len(self.latencies), 1) if self.latencies else None
        return {"latency_ms": self.latency_ms, "latency_avg_ms": avg,
                "latency_max_ms": max(self.latencies) if self.latencies else None,
                "latency_p95_ms": percentile(self.latencies, 95)}

    def public(self, latency=True):
        """State published on MQTT (and read by Mesh Guardian)."""
        lat = self.latency() if latency else {}
        return dict({"server": self.server, "server_ok": self.server_ok,
                     "devices": [dict({"name": d["name"], "hardware_id": d["hardware_id"],
                                       "attached": self.state[d["name"]]["attached"],
                                       "since": self.state[d["name"]]["since"], "busid": self.state[d["name"]]["busid"],
                                       "error": self.state[d["name"]]["error"],
                                       "attaches": self.state[d["name"]]["attaches"]},
                                      **({"latency_ms": lat["latency_ms"]} if latency else {}))
                                 for d in self.devices]}, **lat)


# ---------------------------------------------------------------- Home Assistant side
def supervisor(path, method="GET", timeout=30):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("no Supervisor token")
    req = urllib.request.Request(f"http://supervisor{path}", method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body).get("data", {}) if body else {}


def remount_sys(runner=run):
    """Attaching writes to sysfs, read-only in a container until mounted again.
    A refusal (AppArmor profile, missing SYS_ADMIN) is said in the log: the attach would fail."""
    try:
        runner(["mount", "-o", "remount,rw", "/sys"], timeout=10)
        return True
    except Exception as err:  # noqa: BLE001
        LOG.warning(t("Cannot remount /sys writable, attaching will fail (AppArmor profile?): {err}", err=err))
        return False


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
    def __init__(self, link):
        self.link, self.client, self.last_try, self.warned = link, None, time.time(), False
        self.connect()

    def retry(self, now):
        """Looks for the broker again every MQTT_RETRY_S until found (the Supervisor may refuse at boot)."""
        if self.client is None and now - self.last_try >= MQTT_RETRY_S:
            self.last_try = now
            self.connect()

    def connect(self):
        try:
            import paho.mqtt.client as mqtt   # noqa: PLC0415
            conf = supervisor("/services/mqtt")
        except Exception as err:  # noqa: BLE001
            if not self.warned:   # said once; the next tries only in the debug log
                LOG.warning("%s (%s)", t("No MQTT broker yet: the state is only in the log until it answers (trying again "
                                         "every {s} s)", s=MQTT_RETRY_S), err)
                self.warned = True
            else:
                LOG.debug("MQTT: %s", err)
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
        for topic, payload in discovery(self.link.devices):
            client.publish(topic, payload, retain=True)
        self.publish()

    def publish(self):
        # before the first check every device reads "not attached": published, that is a false "link cut"
        # for Mesh Guardian at each start of the add-on; the retained state of before stays until then
        if self.client is not None and self.link.checks:
            state = dict(self.link.public(), version=VERSION,
                         updated=datetime.now().astimezone().isoformat(timespec="seconds"))
            self.client.publish(STATE_TOPIC, json.dumps(state), retain=True)


def discovery(devices):
    """[(topic, payload)] of the Home Assistant MQTT discovery: one connectivity entity per device and
    the Link latency entities (average, max, p95); an empty payload removes the OMR prefix entity of 0.2.x."""
    dev = {"identifiers": ["usbip_link"], "name": "USB/IP Link", "manufacturer": "Pintjes", "sw_version": VERSION}
    out = []
    for d in devices:
        s = slug_of(d["name"])
        name = d["name"].replace("'", "")
        cfg = {"name": d["name"], "unique_id": f"usbip_link_{s}", "device_class": "connectivity",
               "state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
               "value_template": "{{ 'ON' if (value_json.devices | selectattr('name', 'eq', '%s') | map(attribute='attached') "
                                 "| first) else 'OFF' }}" % name,
               "json_attributes_topic": STATE_TOPIC,
               "json_attributes_template": "{{ (value_json.devices | selectattr('name', 'eq', '%s') | first) | tojson }}" % name,
               "device": dev}
        out.append((f"{DISCOVERY}/binary_sensor/usbip_link/{s}/config", json.dumps(cfg)))
    out.append((f"{DISCOVERY}/sensor/usbip_link/latency/config", json.dumps({
        "name": "Link latency", "unique_id": "usbip_link_latency", "icon": "mdi:timer-outline",
        "device_class": "duration", "unit_of_measurement": "ms", "state_class": "measurement",
        "state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
        # "None" is the payload Home Assistant takes as unknown; any other text is "not numeric" for it
        "value_template": "{{ value_json.latency_avg_ms if value_json.latency_avg_ms is not none else 'None' }}",
        "json_attributes_topic": STATE_TOPIC,
        "json_attributes_template": "{{ {'last_ms': value_json.latency_ms, 'max_ms': value_json.latency_max_ms,"
                                    " 'server': value_json.server} | tojson }}",
        "device": dev})))
    # worst value and 95th percentile of the same window, as sensors of their own: the average hides
    # the peaks, and an attribute is not kept in the long-term statistics
    for key, label, icon in (("max", "Link latency max", "mdi:timer-alert-outline"),
                             ("p95", "Link latency p95", "mdi:timer-sand")):
        field = f"latency_{key}_ms"
        out.append((f"{DISCOVERY}/sensor/usbip_link/latency_{key}/config", json.dumps({
            "name": label, "unique_id": f"usbip_link_latency_{key}", "icon": icon, "entity_category": "diagnostic",
            "device_class": "duration", "unit_of_measurement": "ms", "state_class": "measurement",
            "state_topic": STATE_TOPIC, "availability_topic": STATE_TOPIC + "/available",
            "value_template": "{{ value_json.%s if value_json.%s is not none else 'None' }}" % (field, field),
            "device": dev})))
    # the OMR prefix entity of 0.2.x: the prefix moved to Thread Anchor, the entity goes away
    out.append((f"{DISCOVERY}/binary_sensor/usbip_link/omr_prefix/config", ""))
    return out


def publish_due(changed, events, now, last_pub, latency, last_latency):
    """True when the state is to be published: a change, an event, the heartbeat, or a latency that
    moved (at most every LATENCY_PUBLISH_S)."""
    if changed or events or now - last_pub > HEARTBEAT_S:
        return True
    return latency != last_latency and now - last_pub >= LATENCY_PUBLISH_S


def restart_one(slug, if_running, sup):
    """Restarts one add-on (with `if_running`, only if it is started or in error: a stopped one finds the
    device when it starts). Returns "done", "skipped" or ("failed", error)."""
    try:
        if if_running:
            state = (sup(f"/addons/{slug}/info") or {}).get("state")
            if state not in RUNNING:
                LOG.debug("%s: %s, not restarted", slug, state)
                return "skipped"
        sup(f"/addons/{slug}/restart", method="POST", timeout=120)
    except Exception as err:  # noqa: BLE001
        return "failed", err
    return "done"


def do_restarts(slugs, if_running, sup=None):
    """Restarts the add-ons `slugs` once; returns the slugs restarted."""
    sup = sup or supervisor
    done = []
    for slug in slugs:
        res = restart_one(slug, if_running, sup)
        if res == "done":
            LOG.info(t("Add-on {slug} restarted: it started before the device was attached" if if_running
                       else "Add-on {slug} restarted", slug=slug))
            done.append(slug)
        elif res != "skipped":
            LOG.warning(t("Cannot restart the add-on {slug}: {err}", slug=slug, err=res[1]))
    return done


def retryable(err):
    """A refusal worth trying again: the Supervisor not ready (5xx) or not reachable, or a 400 (it refuses to
    start an add-on whose serial port it does not see yet); another 4xx will not change."""
    code = getattr(err, "code", None)
    return code is None or code == 400 or code >= 500


class RestartQueue:
    """The add-on restarts to do. One the Supervisor refuses (503 while it starts, as at the boot of Home
    Assistant) is tried again every RETRY_S for RETRY_MAX_S, and said in the log, instead of being lost."""

    def __init__(self, sup=None):
        self.sup = sup or supervisor
        self.items = {}    # slug -> {"if_running", "until", "tries"}
        self.next_try = 0.0

    def add(self, slugs, if_running, now):
        for slug in slugs:
            old = self.items.get(slug)
            self.items[slug] = {"if_running": if_running and (old["if_running"] if old else True),
                                "until": now + RETRY_MAX_S, "tries": old["tries"] if old else 0}
        self.next_try = now

    def due(self, now):
        return bool(self.items) and now >= self.next_try

    def run(self, now):
        """One pass over the pending restarts; returns the slugs restarted."""
        done = []
        for slug, it in list(self.items.items()):
            it["tries"] += 1
            res = restart_one(slug, it["if_running"], self.sup)
            if res == "skipped":
                del self.items[slug]
            elif res == "done":
                LOG.info(t("Add-on {slug} restarted: it started before the device was attached" if it["if_running"]
                           else "Add-on {slug} restarted", slug=slug))
                if it["tries"] > 1:
                    LOG.info(t("Add-on {slug} restarted after {n} tries", slug=slug, n=it["tries"]))
                del self.items[slug]
                done.append(slug)
            else:
                err = res[1]
                if not retryable(err):
                    LOG.warning(t("Cannot restart the add-on {slug}: {err}", slug=slug, err=err))
                    del self.items[slug]
                elif now >= it["until"]:
                    LOG.warning(t("Add-on {slug} not restarted after {m} min: {err}. It may be stuck on the dead device: "
                                  "stop it, then start it again by hand", slug=slug, m=RETRY_MAX_S // 60, err=err))
                    del self.items[slug]
                elif it["tries"] == 1:   # said at the first refusal only
                    LOG.warning(t("Cannot restart the add-on {slug}: {err} (trying again for up to {m} min)", slug=slug,
                                  err=err, m=RETRY_MAX_S // 60))
        self.next_try = now + RETRY_S
        return done


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
    remount_sys()
    load_module()
    link = Link(options)
    if str(options.get("omr_prefix") or "").strip():
        LOG.warning(t("omr_prefix is set but no longer used here: the fixed OMR prefix moved to the Thread Anchor add-on"))
    mq = Mqtt(link)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    interval = max(3, int(options.get("check_interval") or 10))
    last_pub, last_latency = 0.0, None
    queue = RestartQueue()
    watch = ClockWatch()
    while not stop.is_set():
        mq.retry(time.time())
        gap = watch.poll()            # a pause during the work of the last pass
        if gap:
            link.resumed(gap)
        try:
            changed = link.check()
        except Exception as err:  # noqa: BLE001 - one bad pass must not end the add-on
            LOG.warning("check: %s", err)
            changed = False
        if link.restart:
            todo, link.restart = link.restart, []
            stop.wait(RESTART_SETTLE_S)
            queue.add(todo, link.restart_if_running, time.time())
        if queue.due(time.time()):
            queue.run(time.time())
        latency = link.latency()
        if publish_due(changed, link.events, time.time(), last_pub, latency, last_latency):
            link.events = []
            mq.publish()
            last_pub, last_latency = time.time(), latency
        waited = 0
        while waited < interval and not stop.is_set():   # in steps: a pause of the machine is seen within seconds
            step = min(WATCH_STEP_S, interval - waited)
            if stop.wait(step):
                break
            waited += step
            gap = watch.poll(step)
            if gap:
                link.resumed(gap)
                break
    # the devices stay attached: a restart of the add-on must not cut the radio of the border router


if __name__ == "__main__":
    main()

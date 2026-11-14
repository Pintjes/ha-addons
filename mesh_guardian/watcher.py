#!/usr/bin/env python3
# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Mesh Guardian.

Listens to mDNS on the local network and continuously follows:
- the Thread border routers (_meshcop._udp): presence, Thread role (leader,
  router, ...), partition, OMR prefix — any vendor;
- the Matter nodes announced (_matter._tcp) for the Home Assistant fabric;
- smart speakers / hubs that are often border routers (Google Cast
  _googlecast._tcp, Apple AirPlay _airplay._tcp): friendly name and restarts.

Publishes the state to MQTT (Home Assistant discovery) and logs every change
(MQTT, add-on log, /share/mesh_guardian).
"""

import ipaddress
import json
import logging
import os
import queue
import signal
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import paho.mqtt.client as mqtt
from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf

import i18n


# --------------------------------------------------------------------------
# Configuration: add-on options (/data/options.json) and MQTT credentials
# provided by the Supervisor ("mqtt" service).
# --------------------------------------------------------------------------
def _load_options():
    try:
        with open("/data/options.json") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _load_mqtt():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        try:
            req = urllib.request.Request("http://supervisor/services/mqtt",
                                         headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp).get("data", {}) or {}
        except Exception as err:  # noqa: BLE001
            print(f"Cannot read the MQTT service from the Supervisor: {err}", flush=True)
    return {}


OPTIONS = _load_options()
i18n.set_language(OPTIONS.get("language", "en"))
from i18n import t, tn  # noqa: E402

from advice import Advisor  # noqa: E402
from healer import Healer  # noqa: E402
from labels import LabelSync  # noqa: E402
from matterlive import MatterLive  # noqa: E402
from nodetable import NodeTable  # noqa: E402
from quality import Quality  # noqa: E402
from reattach import Reattach  # noqa: E402
from history import History  # noqa: E402
from radio import Radio  # noqa: E402
from storm import Storm  # noqa: E402
from webui import WebUI  # noqa: E402

VERSION = "2.3.1"

_MQ = _load_mqtt()
MQTT_HOST = _MQ.get("host") or os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(_MQ.get("port") or os.environ.get("MQTT_PORT", 1883))
MQTT_USER = _MQ.get("username") or os.environ.get("MQTT_USER") or None
MQTT_PASS = _MQ.get("password") or os.environ.get("MQTT_PASS") or None
FABRIC = str(OPTIONS.get("matter_fabric", os.environ.get("MATTER_FABRIC", ""))).upper().strip()
PROBE_INTERVAL = 60
OFFLINE_AFTER = 2
LOG_TO_FILE = bool(OPTIONS.get("log_events_to_file", True))
ALL_NETWORKS = bool(OPTIONS.get("all_thread_networks", False))

BASE = "mesh_guardian"
DISCOVERY = "homeassistant"
EVENT_DIR = "/share/mesh_guardian"
EVENT_FILE = os.path.join(EVENT_DIR, "events.jsonl")
EVENT_FILE_MAX = 5 * 1024 * 1024
KNOWN_FILE = "/data/known_nodes.json"
BR_NAMES_FILE = "/data/br_names.json"
RENAME_CONFIRM = 5   # announcements in a row giving the same new name before a border router is renamed
MESHCOP_REBROWSE = 5 * 60
BR_FIELDS = ("instance", "network", "ext_pan", "vendor", "model", "role", "interface", "bbr_primary",
             "bbr_active", "partition", "omr", "xa", "addrs", "port")
BR_HEARD_S = 180   # a border router heard by a Matter node within this time is online
ROLE_SETTLE_S = 60       # a border router role change is reported after this time
BR_SILENT_S = 15 * 60   # a border router is offline after this time without any answer
STARTUP_QUIET = 150  # seconds without "appeared" events after start

T_MESHCOP = "_meshcop._udp.local."
T_MATTER = "_matter._tcp.local."
T_CAST = "_googlecast._tcp.local."
T_AIRPLAY = "_airplay._tcp.local."
COMPANIONS = (T_CAST, T_AIRPLAY)

ROLES = {0: "detached", 1: "child", 2: "router", 3: "leader"}
IF_STATUS = {0: "not_initialized", 1: "inactive", 2: "active", 3: "unknown"}

# --------------------------------------------------------------------------
# Readable log in the UI (ANSI colors + icons)
# --------------------------------------------------------------------------
RESET = "\033[0m"
COLORS = {"red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m", "blue": "\033[94m",
          "magenta": "\033[95m", "cyan": "\033[96m", "grey": "\033[90m", "bold": "\033[1m"}
STYLE = {  # event kind -> (icon, color)
    "gave_up": ("⛔", "red"), "ping_error": ("⚠️ ", "red"), "name_failed": ("⚠️ ", "yellow"),
    "offline": ("🔴", "red"), "unavailable": ("🔴", "red"), "unreachable": ("🔴", "red"),
    "global_outage": ("🔴", "red"),
    "back": ("🟢", "green"), "recovered": ("🟢", "green"), "online": ("🟢", "green"), "appeared": ("🟢", "green"),
    "global_return": ("🟢", "green"),
    "ping": ("🟠", "yellow"), "sweep": ("🟠", "yellow"),
    "burst": ("⚡", "magenta"),
    "leader": ("👑", "cyan"), "partition": ("🧩", "cyan"), "omr": ("🧭", "cyan"), "prefix": ("🧭", "cyan"),
    "br_change": ("🔁", "cyan"), "renamed": ("🏷️ ", "cyan"),
    "radio_survey": ("📡", "blue"), "statistics": ("📊", "blue"), "startup": ("🚀", "blue"),
    "auto_recovery": ("🔧", "blue"), "name": ("🏷️ ", "blue"),
    "parent_change": ("🔀", "cyan"), "advice": ("💡", "yellow"),
    "ping_all": ("📣", "yellow"), "reattach": ("🧲", "cyan"),
    "storm_start": ("⛈️ ", "magenta"), "storm_end": ("🌤️ ", "green"),
    "routing_problem": ("🚧", "red"), "routing_ok": ("🟢", "green"), "addon_stop": ("⏹️ ", "blue"),
}


def style_for(kind):
    for key, val in STYLE.items():
        if key in kind:
            return val
    return ("🔵", "blue")


class _Fmt(logging.Formatter):
    def format(self, record):
        msg = record.getMessage()
        if record.levelno >= logging.WARNING:
            msg = f"⚠️  {COLORS['yellow']}{msg}{RESET}"
        return f"{COLORS['grey']}{self.formatTime(record, '%H:%M:%S')}{RESET} {msg}"


_h = logging.StreamHandler()
_h.setFormatter(_Fmt())
logging.basicConfig(level=logging.INFO, handlers=[_h])
logging.getLogger("zeroconf").setLevel(logging.ERROR)  # harmless network noise (e.g. ::1 unreachable)
LOG = logging.getLogger("mg")

DEVICE = {
    "identifiers": [BASE],
    "name": "Mesh Guardian",
    "manufacturer": "Pintjes",
    "model": "Mesh Guardian (add-on)",
    "configuration_url": "https://github.com/Pintjes/ha-addons",
    "sw_version": VERSION,
}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def txt_str(props, key):
    v = props.get(key.encode()) if props else None
    if v is None:
        return ""
    try:
        return v.decode("utf-8")
    except Exception:
        return v.hex()


def txt_bytes(props, key):
    v = props.get(key.encode()) if props else None
    return v if isinstance(v, (bytes, bytearray)) else b""


def parse_omr(raw):
    """TXT "omr": 1 byte = prefix length in bits, then the prefix."""
    if not raw or len(raw) < 2:
        return ""
    plen = raw[0]
    prefix = bytes(raw[1:]) + bytes(16)
    try:
        return str(ipaddress.IPv6Network((prefix[:16], plen), strict=False))
    except Exception:
        return raw.hex()


def prefix64(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return None
    if ip.version != 6 or ip.is_link_local:
        return None
    return str(ipaddress.IPv6Network(f"{addr}/64", strict=False))


def short(name, type_):
    return name[: -len(type_) - 1] if name.endswith("." + type_) else name


def _int16(text):
    try:
        return int(text, 16)
    except ValueError:
        return None


def fmt_duration(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}min"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}"


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
class Watch:
    def __init__(self):
        self.lock = threading.RLock()
        self.start = time.time()
        self.br = {}      # border agent key -> dict
        self.matter = {}  # node id hex -> dict
        self.cast = {}    # companion device (Cast / AirPlay) instance name -> dict
        self.br_by_name = {}  # meshcop instance name -> key
        self.ha_networks = set()  # extended PAN ids used by the Home Assistant nodes
        self.last_event = t("Starting")
        self.events_count = 0
        self.prev_leaders = None
        self.prev_partitions = None
        self.prev_omr = None
        self.prev_node_prefixes = None
        self.dirty = True
        self.discovered_br = set()
        self.mqtt = None
        self.zc = None
        self.q = queue.Queue()
        self.stop = threading.Event()
        # mDNS removals waiting for confirmation: (type, name) -> time of removal.
        # Border routers often withdraw then re-announce the same services
        # (bursts): a disappearance is only reported after a check.
        self.pending = {}
        self.burst = None
        self.bursts_count = 0
        self.healer = None
        self.radio = None
        self.published = set()   # discovery topics published by this run
        self.retained = set()    # retained discovery topics of this add-on found on the broker
        self.storm = None
        self.br_names = {}       # border agent key -> {"name": confirmed name, "detached": [times]}
        self._load_known()
        self._load_br_names()
        self.restore_brs()

    # ---------------------------------------------------------------- known
    def _load_known(self):
        try:
            with open(KNOWN_FILE) as f:
                for node in json.load(f):
                    self.matter.setdefault(node, {
                        "online": False, "since": None, "fails": 0,
                        "addrs": [], "prefix": None, "seen": False,
                    })
            LOG.info(t("{n} known Matter nodes loaded", n=len(self.matter)))
        except FileNotFoundError:
            pass
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot read {file}: {err}", file=KNOWN_FILE, err=err))

    def _save_known(self):
        try:
            with open(KNOWN_FILE, "w") as f:
                json.dump(sorted(self.matter), f)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot write {file}: {err}", file=KNOWN_FILE, err=err))

    def _load_br_names(self):
        try:
            with open(BR_NAMES_FILE) as f:
                self.br_names = json.load(f)
        except FileNotFoundError:
            pass
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot read {file}: {err}", file=BR_NAMES_FILE, err=err))

    def _save_br_names(self):
        cutoff = time.time() - 7 * 86400
        for v in self.br_names.values():
            v["detached"] = [x for x in v.get("detached", []) if x >= cutoff]
        try:
            with open(BR_NAMES_FILE, "w") as f:
                json.dump(self.br_names, f, ensure_ascii=False)
        except Exception as err:  # noqa: BLE001
            LOG.warning(t("Cannot write {file}: {err}", file=BR_NAMES_FILE, err=err))

    def br_stats(self, key):
        times = self.br_names.get(key, {}).get("detached", [])
        last = max(times or [0])
        return {"detached_24h": sum(1 for x in times if x >= time.time() - 86400),
                "last_detached": datetime.fromtimestamp(last).astimezone().isoformat(timespec="seconds") if last else None}

    @property
    def quiet(self):
        return time.time() - self.start < STARTUP_QUIET

    # ---------------------------------------------------------------- events
    def emit(self, kind, text, quiet=False, **data):
        """quiet: minor event, only kept in the event file and on MQTT (not in the log
        nor in Last event)."""
        evt = {"t": now_iso(), "type": kind, "msg": text, **data}
        if not quiet:
            self.last_event = f"{datetime.now().strftime('%H:%M:%S')} {text}"[:250]
            self.events_count += 1
            self.dirty = True
            icon, color = style_for(kind)
            LOG.info("%s %s%s%s", icon, COLORS[color], text, RESET)
        if self.storm:
            try:
                self.storm.observe(kind, data)
            except Exception:  # noqa: BLE001
                pass
        if self.mqtt:
            self.mqtt.publish(f"{BASE}/event", json.dumps(evt, ensure_ascii=False))
        if LOG_TO_FILE:
            try:
                os.makedirs(EVENT_DIR, exist_ok=True)
                if os.path.exists(EVENT_FILE) and os.path.getsize(EVENT_FILE) > EVENT_FILE_MAX:
                    os.replace(EVENT_FILE, EVENT_FILE + ".1")
                with open(EVENT_FILE, "a") as f:
                    f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot write the event log: {err}", err=err))

    # ---------------------------------------------------------------- helpers
    def br_candidate(self, b):
        """Friendly name of the smart speaker / hub at the same IPv4 address as the border
        router (Google Cast "fn", or AirPlay name), so that it follows a rename in the
        vendor app. Returns (name, exact): exact = same set of IPv4 addresses."""
        ip4 = {a for a in b.get("addrs", []) if "." in a}
        if not ip4:
            return None, False
        # companions at the same IPv4, ignoring speaker groups (they share a speaker's IP)
        cands = [c for c in self.cast.values()
                 if c.get("fn") and c.get("online", True) and "group" not in (c.get("model") or "").lower()
                 and ip4 & {a for a in c.get("addrs", []) if "." in a}]
        if not cands:
            return None, False
        exact = sorted(c["fn"] for c in cands if {a for a in c.get("addrs", []) if "." in a} == ip4)
        if b.get("label") in [c["fn"] for c in cands]:
            return b["label"], b["label"] in exact
        return (exact[0], True) if exact else (sorted(c["fn"] for c in cands)[0], False)

    def confirm_label(self, key, b):
        """Called once per announcement of the border router. The name is tied to its
        stable key (border agent id) and kept in /data; it only changes after the same
        new name was found RENAME_CONFIRM times in a row with an exact address match."""
        saved = self.br_names.setdefault(key, {"name": None, "detached": []})
        if not b.get("label") and saved.get("name"):
            b["label"] = saved["name"]
        cand, exact = self.br_candidate(b)
        if not cand or cand == b.get("label"):
            b.pop("_cand", None)
            if cand and saved.get("name") != cand:
                saved["name"] = cand
                self._save_br_names()
            return
        if not b.get("label"):   # first name ever: taken at once, no event
            b["label"] = saved["name"] = cand
            self._save_br_names()
            return
        if not exact:
            return   # an approximate match never renames a known border router
        if b.get("_cand") == cand:
            b["_cand_n"] += 1
        else:
            b["_cand"], b["_cand_n"] = cand, 1
        if b["_cand_n"] < RENAME_CONFIRM:
            return
        before = b["label"]
        b["label"] = saved["name"] = cand
        b.pop("_cand", None)
        self._save_br_names()
        if not self.quiet:
            self.emit("br_renamed", t("Border router renamed: \"{before}\" → \"{after}\"", before=before, after=cand),
                      before=before, after=cand, key=key[:16])

    def br_label(self, b):
        """Confirmed name of a border router, otherwise its mDNS instance name."""
        return b.get("label") or b.get("instance", "?")

    def br_display(self, b):
        """Name used in radio tables and on the map (unique, never empty)."""
        return self.br_label(b) or b.get("instance") or "border router"

    def br_relevant(self, b):
        """True if the border router belongs to the Thread network used by the
        Home Assistant nodes (or if every network is followed)."""
        if ALL_NETWORKS or not self.ha_networks or not b.get("ext_pan"):
            return True
        try:
            xp = int(b["ext_pan"], 16)
        except ValueError:
            return True
        return any(abs(xp - n) <= 4096 for n in self.ha_networks)  # JSON may round 64-bit ints

    def set_ha_networks(self, nets):
        with self.lock:
            if nets == self.ha_networks:
                return
            first = not self.ha_networks
            self.ha_networks = set(nets)
            others = [b for b in self.br.values() if not self.br_relevant(b)]
        if first:
            LOG.info(t("Thread network: {nets}{others}",
                       nets=", ".join(f"{n:016x}" for n in sorted(nets)),
                       others=t(" ({n} other networks ignored)", n=len(others)) if others else ""))
        self.dirty = True

    # ---------------------------------------------------------------- bursts
    def note_flap(self, type_, name):
        """Service withdrawn then re-announced: counted in the current burst."""
        now = time.time()
        if self.burst is None:
            self.burst = {"start": now, "last": now, "matter": set(), "br": set(), "cast": set()}
        self.burst["last"] = now
        if type_ == T_MATTER:
            inst = short(name, T_MATTER)
            self.burst["matter"].add(inst.split("-", 1)[-1].upper())
        elif type_ == T_MESHCOP:
            self.burst["br"].add(name)
        else:
            self.burst["cast"].add(name)

    def flush_burst(self, force=False):
        b = self.burst
        if not b or (not force and time.time() - b["last"] < 30):
            return
        self.burst = None
        self.bursts_count += 1
        t0 = datetime.fromtimestamp(b["start"]).strftime("%H:%M:%S")
        t1 = datetime.fromtimestamp(b["last"]).strftime("%H:%M:%S")
        parts = []
        if b["matter"]:
            parts.append(tn("{n} Matter node", "{n} Matter nodes", len(b["matter"])))
        if b["br"]:
            parts.append(tn("{n} border router", "{n} border routers", len(b["br"])))
        if b["cast"]:
            parts.append(tn("{n} smart speaker", "{n} smart speakers", len(b["cast"])))
        self.emit("mdns_burst",
                  t("mDNS burst: {parts} re-announced",
                    t0=t0, t1=t1, parts=", ".join(parts)),
                  start=t0, end=t1, duration_s=int(b["last"] - b["start"]),
                  matter=sorted(f"0x{n.lstrip('0') or '0'}" for n in b["matter"]),
                  border_routers=len(b["br"]), cast=len(b["cast"]), quiet=True)

    def confirm_pending(self):
        """Check removals older than 20s: really gone -> disappearance,
        otherwise a plain re-announcement (burst)."""
        now = time.time()
        with self.lock:
            due = [k for k, t in self.pending.items() if now - t >= 20]
        for type_, name in due:
            try:
                info = self.zc.get_service_info(type_, name, timeout=3000)
            except Exception:  # noqa: BLE001
                info = None
            with self.lock:
                if (type_, name) not in self.pending:
                    continue
                del self.pending[(type_, name)]
                if info:
                    self.note_flap(type_, name)
            if info:
                self.handle_info(type_, name, info)
            else:
                self.handle_removed(type_, name, t("announcement withdrawn, no answer"))

    # ---------------------------------------------------------------- meshcop
    def update_br(self, name, info):
        props = info.properties or {}
        key = txt_bytes(props, "id").hex() or short(name, T_MESHCOP)
        sb_raw = txt_bytes(props, "sb")
        sb = int.from_bytes(sb_raw, "big") if sb_raw else None
        role = ROLES.get((sb >> 9) & 0b11) if sb is not None else "?"
        ifst = IF_STATUS.get((sb >> 3) & 0b11) if sb is not None else "?"
        pt_raw = txt_bytes(props, "pt")
        new = {
            "instance": short(name, T_MESHCOP),
            "network": txt_str(props, "nn"),
            "ext_pan": txt_bytes(props, "xp").hex(),
            "vendor": txt_str(props, "vn"),
            "model": txt_str(props, "mn"),
            "role": role,
            "interface": ifst,
            "bbr_primary": bool(sb is not None and (sb >> 8) & 1),
            "bbr_active": bool(sb is not None and (sb >> 7) & 1),
            "partition": pt_raw.hex() if pt_raw else "",
            "omr": parse_omr(txt_bytes(props, "omr")),
            "xa": int.from_bytes(txt_bytes(props, "xa"), "big") if len(txt_bytes(props, "xa")) == 8 else None,
            "addrs": sorted(info.parsed_addresses(IPVersion.All)),
            "port": info.port,
        }
        with self.lock:
            prev = self.br_by_name.get(name)
            self.br_by_name[name] = key
            if prev and prev != key and prev in self.br:
                # same mDNS instance, new border agent id: it is the same border router
                if key not in self.br:
                    self.br[key] = self.br.pop(prev)
                    saved = self.br_names.pop(prev, None)
                    if saved:
                        self.br_names[key] = saved
                    self._save_br_names()
                    self._clear_br_entity(prev)
                else:
                    self._drop_br(prev)
            old = self.br.get(key)
            now = time.time()
            if old is None:
                b = {**new, "online": True, "since": now, "fails": 0, "last_seen": now, "mdns_seen": now}
                self.br[key] = b
                self.confirm_label(key, b)
                if role == "detached":
                    self.br_names[key].setdefault("detached", []).append(now)
                    self._save_br_names()
                label = self.br_label(b)
                if not self.quiet and self.br_relevant(b):
                    self.emit("br_appeared", t("Border router {name} appeared ({role})", name=label, role=t(role)),
                              br=label, role=role, partition=new["partition"], omr=new["omr"])
            else:
                b = old
                was_online = b["online"]
                # during a re-announcement, some border routers publish an empty OMR prefix
                # or partition for a few seconds: keep the last known value
                for field in ("omr", "partition"):
                    if not new[field] and old.get(field):
                        new[field] = old[field]
                changes = []
                if old.get("role") != new["role"]:
                    # role event only once the new role held ROLE_SETTLE_S (no event for a round trip)
                    if b.get("_role_from") == new["role"]:
                        b.pop("_role_from", None)
                        b.pop("_role_t", None)
                    elif "_role_from" not in b:
                        b["_role_from"], b["_role_t"] = old.get("role"), now
                for field, txt in (("partition", t("partition")),
                                   ("omr", t("OMR prefix")), ("interface", t("Thread interface")),
                                   ("bbr_primary", t("primary BBR"))):
                    if old.get(field) != new[field]:
                        before, after = old.get(field), new[field]
                        if field in ("role", "interface"):
                            before, after = t(str(before)), t(str(after))
                        changes.append(f"{txt} {before or '-'} → {after or '-'}")
                if role == "detached" and old.get("role") != "detached":
                    self.br_names.setdefault(key, {"name": None, "detached": []}).setdefault("detached", []).append(now)
                    self._save_br_names()
                b.update(new)
                b["fails"] = 0
                b["last_seen"] = now
                b["mdns_seen"] = now
                self.confirm_label(key, b)
                label = self.br_label(b)
                relevant = self.br_relevant(b)
                if not was_online:
                    down = now - (b.get("since") or now)
                    b["online"] = True
                    b["since"] = now
                    if relevant:
                        self.emit("br_back", t("Border router {name} back ({d})", name=label, d=fmt_duration(down)),
                                  br=label, offline_s=int(down), role=role)
                if changes and relevant:
                    self.emit("br_change", t("Border router {name}: ", name=label) + "; ".join(changes),
                              br=label, changes=changes)
            self._remember_br(key, name, b)
            self.dirty = True
        self.check_global()

    def _remember_br(self, key, name, b):
        """Keep the last announcement of a border router, restored at the next start."""
        saved = self.br_names.setdefault(key, {"name": None, "detached": []})
        name = name or (saved.get("last") or {}).get("mdns")
        last = {k: b.get(k) for k in BR_FIELDS} | {"mdns": name}
        contact = {"mdns": b.get("mdns_seen"), "thread": b.get("thread_seen")}
        due = time.time() - saved.get("_saved_t", 0) >= 300
        if saved.get("last") != last or (due and saved.get("contact") != contact):
            saved["last"] = last
            saved["contact"] = contact
            saved["_saved_t"] = time.time()
            self._save_br_names()

    def flush_br_roles(self):
        """Role change of a border router reported once the new role held ROLE_SETTLE_S."""
        now = time.time()
        with self.lock:
            for b in self.br.values():
                if "_role_from" not in b or now - b["_role_t"] < ROLE_SETTLE_S:
                    continue
                before = b.pop("_role_from")
                b.pop("_role_t", None)
                after = b.get("role")
                if after == before or not b["online"] or not self.br_relevant(b):
                    continue
                label = self.br_label(b)
                change = f"{t('role')} {t(str(before)) if before else '-'} → {t(str(after)) if after else '-'}"
                self.emit("br_change", t("Border router {name}: ", name=label) + change, br=label, changes=[change])

    def _clear_br_entity(self, key):
        """Remove the MQTT entity of a border router key that is no longer used."""
        topic = f"{DISCOVERY}/sensor/{BASE}/br_{key[:16]}/config"
        self.published.discard(topic)
        self.discovered_br = {x for x in self.discovered_br if x[0] != key}
        if self.mqtt:
            self.mqtt.publish(topic, b"", retain=True)
            self.mqtt.publish(f"{BASE}/br/{key}", b"", retain=True)
        self.dirty = True

    def _drop_br(self, key):
        """Forget a border router key replaced by a newer one (lock held)."""
        self.br.pop(key, None)
        self.br_names.pop(key, None)
        self._save_br_names()
        self._clear_br_entity(key)

    @staticmethod
    def _saved_contact(saved):
        c = (saved or {}).get("contact") or {}
        return max([x for x in (c.get("mdns"), c.get("thread")) if x] or [0])

    def restore_brs(self):
        """At start, border routers already known keep their last state until they
        answer again, or are reported offline after BR_SILENT_S without any answer."""
        now = time.time()
        with self.lock:
            # one entry per mDNS instance: keep the key with the latest contact
            by_name = {}
            for key, saved in list(self.br_names.items()):
                name = (saved.get("last") or {}).get("mdns")
                if not name:
                    continue
                other = by_name.get(name)
                if other is None:
                    by_name[name] = key
                    continue
                if self._saved_contact(saved) > self._saved_contact(self.br_names[other]):
                    by_name[name], key = key, other
                self.br_names.pop(key, None)
                self._save_br_names()
            for key, saved in self.br_names.items():
                last = saved.get("last")
                if not last or key in self.br:
                    continue
                name = last.get("mdns")
                b = {k: v for k, v in last.items() if k != "mdns"}
                b.update({"online": True, "since": now, "fails": 0, "last_seen": now})
                if saved.get("name"):
                    b["label"] = saved["name"]
                c = saved.get("contact") or {}
                b["mdns_seen"], b["thread_seen"] = c.get("mdns"), c.get("thread")
                self.br[key] = b
                if name:
                    self.br_by_name[name] = key
            self.dirty = True

    @staticmethod
    def br_contact(b):
        """(time, source) of the last sign of life of a border router: mDNS answer or Thread."""
        m, th = b.get("mdns_seen"), b.get("thread_seen")
        if m is None and th is None:
            return None, None
        if th is not None and (m is None or th > m):
            return th, "thread"
        return m, "mdns"

    def _br_heard(self, key, b, heard):
        """A Matter node heard this border router `heard` seconds ago over Thread."""
        ts = time.time() - heard
        if ts > (b.get("thread_seen") or 0):
            b["thread_seen"] = ts
        if ts > (b.get("last_seen") or 0):
            b["last_seen"] = ts
        self._remember_br(key, None, b)

    def br_thread_refresh(self):
        """After each radio survey: the neighbor tables of the nodes also tell when each
        border router was last heard over Thread (keeps the offline timer fresh)."""
        live = getattr(self, "live", None)
        if not live or not live.connected:
            return
        with self.lock:
            items = [(k, b) for k, b in self.br.items() if b.get("xa") is not None]
        for key, b in items:
            heard = live.last_heard(b["xa"])
            if heard is not None:
                with self.lock:
                    self._br_heard(key, b, heard)
        self.dirty = True

    def reset_stats(self, origin):
        """Reset button: every statistic back to zero. Names, settings and the switch are kept."""
        self.healer.reset_stats()
        if getattr(self, "live", None):
            self.live.reset_contacts()
        if getattr(self, "radio", None):
            self.radio.reset()
        if getattr(self, "advisor", None):
            self.advisor.reset()
        if self.storm:
            self.storm.reset()
        if getattr(self, "quality", None):
            self.quality.reset()
        if getattr(self, "history", None):
            with self.history.lock:
                self.history.data = {}
            self.history._save()
        with self.lock:
            for v in self.br_names.values():
                v["detached"] = []
                v["contact"] = {"mdns": None, "thread": None}
            for b in self.br.values():
                b["mdns_seen"] = b["thread_seen"] = None
            self._save_br_names()
            self.bursts_count = 0
            self.dirty = True
        self.emit("stats_reset", t("Statistics reset"), origin=origin)

    def prune_gone(self):
        """Forget, in every file, the nodes that no longer exist in the Matter Server."""
        live = getattr(self, "live", None)
        if not live or not live.connected:
            return
        ids = live.node_ids()
        if not ids:
            return
        n = self.healer.prune(ids) + live.prune(ids)
        with self.lock:
            gone = [k for k in self.matter if _int16(k) not in ids and not self.matter[k].get("online")]
            for k in gone:
                del self.matter[k]
            # still announced on the fabric but unknown to the Matter Server: a device removed
            # from Home Assistant without a factory reset keeps announcing itself
            ghosts = sorted(k for k in self.matter if _int16(k) not in ids and self.matter[k].get("online"))
        if gone:
            self._save_known()
        if ghosts != getattr(self, "ghosts", []):
            self.ghosts = ghosts
            if ghosts:
                LOG.warning(t("Announced on the Matter fabric but unknown to the Matter Server (removed without a "
                              "factory reset?): {ids}", ids=", ".join("0x" + (k.lstrip("0") or "0") for k in ghosts)))
        if getattr(self, "advisor", None) and getattr(self, "radio", None) and self.radio.last:
            names = {v for v in (self.radio.last.get("names") or [])}
            if names:
                n += self.advisor.prune(names)
        if n or gone:
            LOG.info(t("Forgotten nodes: {n}", n=max(n, len(gone))))

    def br_heard_in_thread(self, b):
        """Seconds since a Matter node last heard this border router over the radio, or None."""
        live = getattr(self, "live", None)
        if not live or not live.connected or b.get("xa") is None:
            return None
        return live.last_heard(b["xa"])

    def br_gone(self, key, reason):
        """A border router is only reported offline when nothing came from it for
        BR_SILENT_S: no mDNS answer (probe or browse) and, for a router, no radio
        contact seen by a Matter node."""
        with self.lock:
            b = self.br.get(key)
            if not b or not b["online"]:
                return
            xa = b.get("xa")
            silent = time.time() - (b.get("last_seen") or 0)
        if silent < BR_SILENT_S:
            return
        heard = self.br_heard_in_thread(b)
        if (heard is None or heard > BR_HEARD_S) and xa is not None and getattr(self, "live", None) \
                and self.live.connected:
            # mDNS is silent: ask the mesh (neighbor table of a router next to it)
            heard = self.live.check_heard(xa)
        with self.lock:
            if not b["online"]:
                return
            if heard is not None and heard <= BR_HEARD_S:
                # mDNS did not answer, but the mesh still hears it: it is there
                LOG.debug("%s silent in mDNS but heard in Thread %ds ago", self.br_label(b), heard)
                self._br_heard(key, b, heard)
                return
            reason = t("not seen for {m}min", m=int(silent // 60))
            b["online"] = False
            b["since"] = time.time()
            label = self.br_label(b)
            if self.br_relevant(b):
                self.emit("br_offline", t("Border router {name} offline", name=label,
                                          reason=reason, role=t(b.get("role") or "?")),
                          br=label, role=b.get("role"), reason=reason)
            self.dirty = True
        self.check_global()

    # ---------------------------------------------------------------- matter
    def update_matter(self, name, info):
        inst = short(name, T_MATTER)
        if "-" not in inst:
            return
        fabric, node = inst.split("-", 1)
        if FABRIC and fabric.upper() != FABRIC:
            return
        node = node.upper()
        addrs = sorted(info.parsed_addresses(IPVersion.All)) if info else []
        prefixes = sorted({p for p in (prefix64(a) for a in addrs) if p})
        with self.lock:
            now = time.time()
            n = self.matter.get(node)
            is_new = n is None
            if is_new:
                n = {"online": False, "since": None, "fails": 0, "addrs": [], "prefix": None, "seen": False}
                self.matter[node] = n
                self._save_known()
            if not n["online"]:
                silent = n.pop("silent_off", False)
                if n.get("seen") and n.get("since") and not silent:
                    down = now - n["since"]
                    self.emit("matter_back", t("{node} back in mDNS ({d})", node=self.node_disp(node), d=fmt_duration(down)),
                              node=node, name=self.node_name(node), offline_s=int(down))
                elif not self.quiet and is_new and not self.node_name(node):
                    # a node known by Home Assistant seen for the first time since start is not news
                    self.emit("matter_appeared", t("Node 0x{id} unknown to Home Assistant",
                                                   id=node.lstrip("0") or "0"), node=node)
                n["online"] = True
                n["since"] = now
            n["seen"] = True
            n["fails"] = 0
            n["addrs"] = addrs
            n["prefix"] = prefixes[0] if prefixes else n.get("prefix")
            self.dirty = True

    def node_name(self, node):
        """"Name (area)" of the node according to Home Assistant, or None."""
        try:
            return self.healer.label(node) if self.healer else None
        except Exception:  # noqa: BLE001
            return None

    def node_disp(self, node):
        short_hex = "0x" + (node.lstrip("0") or "0")
        name = self.node_name(node)
        return f"{name} [{short_hex}]" if name else t("Matter node {id}", id=short_hex)

    def matter_gone(self, node, reason):
        with self.lock:
            n = self.matter.get(node)
            if not n or not n["online"]:
                return
            n["online"] = False
            n["since"] = time.time()
            self.dirty = True
            h = self.healer.nodes.get(str(node).upper().zfill(16)) if self.healer else None
            if h and h.get("battery") and h.get("available"):
                # a sleepy battery node often drops out of mDNS while Home Assistant still reaches it
                n["silent_off"] = True
                LOG.debug("%s missing from mDNS (battery, available in Home Assistant)", self.node_disp(node))
                return
            self.emit("matter_offline", t("{node} missing from mDNS", node=self.node_disp(node), reason=reason),
                      node=node, name=self.node_name(node), reason=reason)

    # ---------------------------------------------------------------- companions
    def update_cast(self, type_, name, info):
        """Smart speaker / hub announced via Google Cast or Apple AirPlay."""
        props = info.properties or {}
        if type_ == T_CAST:
            fn, model = txt_str(props, "fn"), txt_str(props, "md")
        else:
            fn, model = short(name, T_AIRPLAY), txt_str(props, "model")
        new = {"fn": fn, "model": model, "kind": "cast" if type_ == T_CAST else "airplay",
               "addrs": sorted(info.parsed_addresses(IPVersion.All))}
        with self.lock:
            now = time.time()
            c = self.cast.get(name)
            if c is None:
                self.cast[name] = {**new, "online": True, "since": now, "fails": 0}
                if not self.quiet:
                    self.emit("speaker_appeared", t('"{name}" appeared', name=fn), cast=fn)
            else:
                c.update(new)
                c["fails"] = 0
                if not c["online"]:
                    down = now - (c.get("since") or now)
                    hint = t(" (restart likely)") if down < 900 else ""
                    self.emit("speaker_back", t('"{name}" back ({d})', name=c["fn"],
                                                d=fmt_duration(down)) + hint,
                              cast=c["fn"], offline_s=int(down))
                    c["online"] = True
                    c["since"] = now
            self.dirty = True

    def cast_gone(self, name, reason):
        with self.lock:
            c = self.cast.get(name)
            if not c or not c["online"]:
                return
            c["online"] = False
            c["since"] = time.time()
            self.emit("speaker_offline", t('"{name}" offline', name=c.get("fn"), reason=reason),
                      cast=c.get("fn"), reason=reason)
            self.dirty = True

    # ---------------------------------------------------------------- global
    def summary(self):
        with self.lock:
            mine = {k: b for k, b in self.br.items() if self.br_relevant(b)}
            online = [b for b in mine.values() if b["online"]]
            leader_keys = sorted(k for k, b in mine.items() if b["online"] and b["role"] == "leader")
            leaders = sorted(self.br_label(self.br[k]) for k in leader_keys)
            partitions = sorted({b["partition"] for b in online if b["partition"] and b["interface"] == "active"})
            leader_txt = ", ".join(leaders) if leaders else t("none")
            if not leaders and partitions:
                # the leader can be any router of the mesh, e.g. a bulb: not announced in mDNS
                mesh = self.radio.mesh_leader() if self.radio else []
                leader_txt = ", ".join(mesh) if mesh else t("unknown")
                leader_keys = [f"node:{m}" for m in mesh]
            omr = sorted({b["omr"] for b in online if b["omr"]})
            nodes_on = sorted(k for k, n in self.matter.items() if n["online"])
            nodes_off = sorted(k for k, n in self.matter.items() if not n["online"])
            node_prefixes = {}
            for k in nodes_on:
                p = self.matter[k].get("prefix")
                if p:
                    node_prefixes[p] = node_prefixes.get(p, 0) + 1
            casts_on = sorted(c["fn"] for c in self.cast.values() if c["online"])
            casts_off = sorted(c["fn"] for c in self.cast.values() if not c["online"])
            return {
                "br_online": len(online),
                "br_total": len(mine),
                "br_other_networks": len(self.br) - len(mine),
                "br_list": {self.br_label(b): (b["role"] if b["online"] else "offline") for b in mine.values()},
                "leader": leader_txt,
                "leader_keys": leader_keys,
                "bursts_count": self.bursts_count,
                "pending": len(self.pending),
                "leaders_count": len(leaders),
                "partitions": len(partitions),
                "partition_ids": partitions,
                "omr": ", ".join(omr) if omr else t("none"),
                "omr_list": omr,
                "matter_online": len(nodes_on),
                "matter_known": len(self.matter),
                "matter_missing": len(nodes_off),
                "matter_missing_ids": [f"0x{n.lstrip('0') or '0'}" for n in nodes_off],
                "node_prefixes": node_prefixes,
                "cast_online": len(casts_on),
                "cast_list_online": casts_on,
                "cast_list_offline": casts_off,
                "partitioned": "ON" if len(partitions) > 1 or len(leaders) > 1 else "OFF",
                "last_event": self.last_event,
                "events_count": self.events_count,
                "updated": now_iso(),
            }

    def check_global(self):
        s = self.summary()
        leaders = (tuple(s["leader_keys"]), s["leader"])
        parts = tuple(s["partition_ids"])
        omr = tuple(s["omr_list"])
        if self.quiet:
            self.prev_leaders, self.prev_partitions, self.prev_omr = leaders, parts, omr
            return
        if self.prev_leaders is not None and leaders[0] != self.prev_leaders[0] \
                and self.prev_leaders[1] != t("unknown"):
            self.emit("leader_change", t("Thread leader: {before} → {after}", before=self.prev_leaders[1], after=leaders[1]),
                      before=self.prev_leaders[1], after=leaders[1])
        if self.prev_partitions is not None and parts != self.prev_partitions:
            txt = t("network partitioned") if len(parts) > 1 else t("Thread partition")
            self.emit("partition_change", t("{what}: {before} → {after} partitions", what=txt,
                                              before=len(self.prev_partitions), after=len(parts)),
                      before=list(self.prev_partitions), after=list(parts))
        if self.prev_omr is not None and omr != self.prev_omr:
            self.emit("omr_change", t("OMR prefix: {before} → {after}", before=", ".join(self.prev_omr) or t("none"),
                                      after=", ".join(omr) or t("none")),
                      before=list(self.prev_omr), after=list(omr))
            if self.healer:
                self.healer.prefix_changed()
        self.prev_leaders, self.prev_partitions, self.prev_omr = leaders, parts, omr

    def check_node_prefixes(self):
        s = self.summary()
        keys = tuple(sorted(s["node_prefixes"]))
        if self.quiet:
            self.prev_node_prefixes = keys
            return
        if self.prev_node_prefixes is not None and keys != self.prev_node_prefixes:
            self.emit("node_prefix_change",
                      t("Node prefixes: {before} → {after}", before=list(self.prev_node_prefixes),
                        after=s["node_prefixes"]),
                      before=list(self.prev_node_prefixes), after=s["node_prefixes"])
            if self.healer:
                self.healer.prefix_changed()
        self.prev_node_prefixes = keys

    # ---------------------------------------------------------------- zeroconf
    def on_change(self, zeroconf, service_type, name, state_change):
        self.q.put((service_type, name, state_change))

    def worker(self):
        while not self.stop.is_set():
            try:
                type_, name, change = self.q.get(timeout=1)
            except queue.Empty:
                continue
            try:
                if change is ServiceStateChange.Removed:
                    with self.lock:
                        self.pending.setdefault((type_, name), time.time())
                else:
                    with self.lock:
                        if self.pending.pop((type_, name), None) is not None:
                            self.note_flap(type_, name)
                    info = self.zc.get_service_info(type_, name, timeout=3000)
                    if info:
                        self.handle_info(type_, name, info)
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot process {name}: {err}", name=name, err=err))

    def handle_info(self, type_, name, info):
        if type_ == T_MESHCOP:
            self.update_br(name, info)
        elif type_ == T_MATTER:
            self.update_matter(name, info)
        elif type_ in COMPANIONS:
            self.update_cast(type_, name, info)

    def handle_removed(self, type_, name, reason):
        if type_ == T_MESHCOP:
            key = self.br_by_name.get(name)
            if key:
                self.br_gone(key, reason)
        elif type_ == T_MATTER:
            inst = short(name, T_MATTER)
            if "-" in inst:
                fabric, node = inst.split("-", 1)
                if not FABRIC or fabric.upper() == FABRIC:
                    self.matter_gone(node.upper(), reason)
        elif type_ in COMPANIONS:
            self.cast_gone(name, reason)

    # ---------------------------------------------------------------- probes
    def probe_one(self, type_, name):
        try:
            info = self.zc.get_service_info(type_, name, timeout=3000)
        except Exception:  # noqa: BLE001
            info = None
        return type_, name, info

    def prober(self):
        """Actively query every known service: detects a disappearance even
        without a removal announcement (device unplugged, crashed, restarted)."""
        pool = ThreadPoolExecutor(max_workers=8)
        last_browse = time.time()
        first = True
        while not self.stop.wait(30 if first else PROBE_INTERVAL):
            if first or time.time() - last_browse >= MESHCOP_REBROWSE:
                # a fresh browser queries the network again: catches a border router whose
                # announcement was missed (e.g. at start) and that probes cannot know about
                first = False
                last_browse = time.time()
                old = self.browsers.get(T_MESHCOP)
                self.browsers[T_MESHCOP] = ServiceBrowser(self.zc, T_MESHCOP, handlers=[self.on_change])
                if old:
                    old.cancel()
            with self.lock:
                targets = [(T_MESHCOP, n) for n in self.br_by_name]
                targets += [(T_CAST if n.endswith(T_CAST) else T_AIRPLAY, n)
                            for n in self.cast]
                targets += [(T_MATTER, f"{FABRIC}-{node}.{T_MATTER}") for node in self.matter] if FABRIC else []
            for type_, name, info in pool.map(lambda t: self.probe_one(*t), targets):
                if info:
                    self.handle_info(type_, name, info)
                    continue
                with self.lock:
                    if type_ == T_MESHCOP:
                        obj = self.br.get(self.br_by_name.get(name))
                    elif type_ in COMPANIONS:
                        obj = self.cast.get(name)
                    else:
                        obj = self.matter.get(short(name, T_MATTER).split("-", 1)[1].upper())
                    if not obj:
                        continue
                    obj["fails"] = obj.get("fails", 0) + 1
                    fails = obj["fails"]
                if fails >= OFFLINE_AFTER:
                    self.handle_removed(type_, name, t("no answer to {n} probes", n=OFFLINE_AFTER))
            self.check_node_prefixes()

    # ---------------------------------------------------------------- MQTT
    def disc(self, component, key, name, extra):
        cfg = {
            "name": name,
            "unique_id": f"{BASE}_{key}",
            "default_entity_id": f"{component}.{BASE}_{key}",
            "availability_topic": f"{BASE}/status",
            "device": DEVICE,
            **extra,
        }
        self.published.add(f"{DISCOVERY}/{component}/{BASE}/{key}/config")
        self.mqtt.publish(f"{DISCOVERY}/{component}/{BASE}/{key}/config", json.dumps(cfg, ensure_ascii=False), retain=True)

    def publish_discovery(self):
        st = f"{BASE}/state"
        sensors = [
            ("border_routers_online", t("Border routers online"), "{{ value_json.br_online }}", "mdi:router-wireless",
             "{{ {'total': value_json.br_total, 'other_networks': value_json.br_other_networks, "
             "'border_routers': value_json.br_list} | tojson }}"),
            ("thread_leader", t("Thread leader"), "{{ value_json.leader[:250] }}", "mdi:crown",
             "{{ {'leaders': value_json.leaders_count} | tojson }}"),
            ("thread_partitions", t("Thread partitions"), "{{ value_json.partitions }}", "mdi:call-split",
             "{{ {'partitions': value_json.partition_ids} | tojson }}"),
            ("omr_prefix", t("OMR prefix"), "{{ value_json.omr[:250] }}", "mdi:ip-network",
             "{{ {'prefixes': value_json.omr_list, 'node_prefixes': value_json.node_prefixes} | tojson }}"),
            ("last_event", t("Last event"), "{{ value_json.last_event }}", "mdi:message-alert-outline",
             "{{ {'events': value_json.events_count, 'mdns_bursts': value_json.bursts_count, "
             "'removals_being_checked': value_json.pending, 'updated': value_json.updated} | tojson }}"),
        ]
        for key, name, tpl, icon, attr_tpl in sensors:
            extra = {"state_topic": st, "value_template": tpl, "icon": icon,
                     "json_attributes_topic": st, "json_attributes_template": attr_tpl}
            if key in ("border_routers_online", "thread_partitions"):
                extra["state_class"] = "measurement"
            self.disc("sensor", key, name, extra)
        hs = f"{BASE}/healer"
        self.disc("sensor", "matter_nodes_unavailable", t("Unavailable nodes"), {
            "state_topic": hs, "value_template": "{{ value_json.unavailable }}",
            "json_attributes_topic": hs,
            "json_attributes_template": "{{ {'nodes': value_json.unavailable_list, 'last_ping': value_json.last_ping, "
                                        "'routing': value_json.routing} | tojson }}",
            "icon": "mdi:lan-disconnect", "state_class": "measurement"})
        self.disc("sensor", "matter_nodes_available", t("Available nodes"), {
            "state_topic": hs, "value_template": "{{ value_json.available }}",
            "icon": "mdi:lan-connect", "state_class": "measurement"})
        self.disc("sensor", "recovered_by_ping", t("Recoveries by ping"), {
            "state_topic": hs, "value_template": "{{ value_json.recovered_by_ping }}",
            "json_attributes_topic": hs,
            "json_attributes_template": "{{ {'back_on_their_own': value_json.back_on_their_own, 'gave_up': value_json.gave_up, "
                                        "'pings_sent': value_json.pings_sent, 'last_ping': value_json.last_ping, "
                                        "'since_start': value_json.since_start, 'last_24h': value_json.last_24h, "
                                        "'started': value_json.started, "
                                        "'home_assistant_ok': value_json.ha_ok, 'matter_server_ok': value_json.matter_server_ok} | tojson }}",
            "icon": "mdi:lan-check", "state_class": "total_increasing"})
        rs = f"{BASE}/radio"
        self.disc("sensor", "weak_radio_links", t("Weak links"), {
            "state_topic": rs, "value_template": "{{ value_json.weak_links }}",
            "json_attributes_topic": rs,
            "json_attributes_template": "{{ {'links': value_json.weak_links_list, 'survey_time': value_json.survey_time, "
                                        "'roles': value_json.roles} | tojson }}",
            "icon": "mdi:signal-cellular-1", "state_class": "measurement"})
        self.disc("sensor", "thread_parents", t("Thread parents"), {
            "state_topic": rs, "value_template": "{{ value_json.parents | length }}",
            "json_attributes_topic": rs, "json_attributes_template": "{{ value_json.parents | tojson }}",
            "icon": "mdi:family-tree"})
        ps = f"{BASE}/reattach"
        self.disc("sensor", "parent_search", t("Last parent search"), {
            "state_topic": ps, "value_template": "{{ value_json.date }}",
            "json_attributes_topic": ps,
            "json_attributes_template": "{{ {'checked': value_json.checked, 'poor_links': value_json.poor, "
                                        "'better': value_json.better, 'nodes': value_json.nodes} | tojson }}",
            "icon": "mdi:family-tree"})
        self.disc("button", "find_better_parents", t("Find better parents"), {
            "command_topic": f"{BASE}/reattach/set", "payload_press": "PRESS", "icon": "mdi:magnet"})
        ls = f"{BASE}/labels"
        self.disc("sensor", "nodes_to_rename", t("Nodes to rename"), {
            "state_topic": ls, "value_template": "{{ value_json.to_rename }}",
            "json_attributes_topic": ls,
            "json_attributes_template": "{{ {'nodes': value_json.nodes, 'in_sync': value_json.in_sync, "
                                        "'checked': value_json.date, 'last_rename': value_json.last_rename} | tojson }}",
            "icon": "mdi:tag-text-outline", "state_class": "measurement"})
        self.disc("button", "rename_nodes", t("Rename nodes"), {
            "command_topic": f"{BASE}/rename/set", "payload_press": "PRESS", "icon": "mdi:tag-edit-outline"})
        self.disc("button", "ping_all_nodes", t("Ping all nodes"), {
            "command_topic": f"{BASE}/ping_all/set", "payload_press": "PRESS", "icon": "mdi:access-point-check"})
        self.disc("button", "reset_statistics", t("Reset statistics"), {
            "command_topic": f"{BASE}/reset/set", "payload_press": "PRESS", "icon": "mdi:restore",
            "entity_category": "config"})
        self.disc("switch", "auto_recovery", t("Automatic recovery"), {
            "state_topic": hs, "value_template": "{{ value_json.auto }}",
            "command_topic": f"{BASE}/healer/set", "payload_on": "ON", "payload_off": "OFF",
            "icon": "mdi:auto-fix"})
        qs = f"{BASE}/quality"
        self.disc("sensor", "network_quality", t("Network quality"), {
            "state_topic": qs, "value_template": "{{ value_json.score }}",
            "unit_of_measurement": "%", "state_class": "measurement", "icon": "mdi:shield-check",
            "json_attributes_topic": qs,
            "json_attributes_template": "{{ {'parts': value_json.parts, 'capped': value_json.capped, "
                                        "'minutes': value_json.minutes, 'score_24h': value_json.score_24h, "
                                        "'parts_24h': value_json.parts_24h, 'median_response_ms': value_json.median_response_ms, "
                                        "'probed_nodes': value_json.probed_nodes, "
                                        "'passive_contact': value_json.passive_contact} | tojson }}"})
        self.disc("binary_sensor", "thread_network_partitioned", t("Thread network partitioned"), {
            "state_topic": st, "value_template": "{{ value_json.partitioned }}",
            "device_class": "problem",
        })
        self.disc("binary_sensor", "thread_storm", t("Thread storm"), {
            "state_topic": f"{BASE}/storm", "value_template": "{{ value_json.state }}",
            "json_attributes_topic": f"{BASE}/storm", "device_class": "problem", "icon": "mdi:weather-lightning",
        })
        with self.lock:
            keys = [k for k, b in self.br.items() if self.br_relevant(b)]
        for key in keys:
            self.publish_br_discovery(key)

    def publish_br_discovery(self, key):
        with self.lock:
            b = self.br.get(key)
            if not b:
                return
            label = self.br_label(b)
        self.disc("sensor", f"br_{key[:16]}", t("Border router {name}", name=label), {
            "state_topic": f"{BASE}/br/{key}",
            "value_template": "{{ value_json.state }}",
            "json_attributes_topic": f"{BASE}/br/{key}",
            "icon": "mdi:router-network",
        })
        self.discovered_br.add((key, label))

    def publish_states(self):
        if not self.mqtt or not self.mqtt.is_connected():
            return
        s = self.summary()
        # keep "updated" as the time of the last real change: a new timestamp at
        # every publish made Home Assistant record the last event every few seconds
        sig = json.dumps({k: v for k, v in s.items() if k != "updated"}, sort_keys=True, ensure_ascii=False)
        if sig == getattr(self, "state_sig", None):
            s["updated"] = self.state_updated
        else:
            self.state_sig, self.state_updated = sig, s["updated"]
        self.mqtt.publish(f"{BASE}/state", json.dumps(s, ensure_ascii=False), retain=True)
        if self.healer:
            self.mqtt.publish(f"{BASE}/healer", json.dumps(self.healer.summary(), ensure_ascii=False), retain=True)
        if self.radio:
            self.mqtt.publish(f"{BASE}/radio", json.dumps(self.radio.summary(), ensure_ascii=False), retain=True)
        if getattr(self, "labels", None) and self.labels.last.get("date"):
            self.mqtt.publish(f"{BASE}/labels", json.dumps(self.labels.last, ensure_ascii=False), retain=True)
        if getattr(self, "reattach", None) and self.reattach.last.get("date"):
            self.mqtt.publish(f"{BASE}/reattach", json.dumps(self.reattach.last, ensure_ascii=False), retain=True)
        if getattr(self, "quality", None):
            self.mqtt.publish(f"{BASE}/quality", json.dumps(self.quality.summary(), ensure_ascii=False), retain=True)
        if self.storm:
            self.mqtt.publish(f"{BASE}/storm", json.dumps(self.storm.summary(), ensure_ascii=False), retain=True)
        with self.lock:
            items = [(k, b) for k, b in self.br.items() if self.br_relevant(b)]
        for key, b in items:
            with self.lock:
                label = self.br_label(b)
            if (key, label) not in self.discovered_br:
                self.publish_br_discovery(key)
            payload = {
                "state": b["role"] if b["online"] else "offline",
                "name": label,
                "key": key[:16],
                **self.br_stats(key),
                "same_subnet_as_home_assistant": self.healer.same_subnet(b.get("addrs")) if self.healer else None,
                "instance": b.get("instance"),
                "role": b.get("role"),
                "thread_interface": b.get("interface"),
                "partition": b.get("partition"),
                "omr_prefix": b.get("omr"),
                "bbr_primary": b.get("bbr_primary"),
                "last_contact": (datetime.fromtimestamp(self.br_contact(b)[0]).astimezone().isoformat(timespec="seconds")
                                 if self.br_contact(b)[0] else None),
                "network": b.get("network"),
                "extended_pan_id": b.get("ext_pan"),
                "vendor": b.get("vendor"),
                "model": b.get("model"),
                "addresses": b.get("addrs"),
                "since": datetime.fromtimestamp(b["since"]).astimezone().isoformat(timespec="seconds") if b.get("since") else None,
            }
            self.mqtt.publish(f"{BASE}/br/{key}", json.dumps(payload, ensure_ascii=False), retain=True)
        self.dirty = False

    def confirmer(self):
        while not self.stop.wait(2):
            try:
                self.confirm_pending()
                self.flush_burst()
                self.flush_br_roles()
            except Exception as err:  # noqa: BLE001
                LOG.warning(t("Cannot check the removals: {err}", err=err))

    def hourly(self):
        s = self.summary()
        h = self.healer.summary() if self.healer else {}
        r = self.radio.summary() if self.radio else {}
        LOG.info("🕐 %s%s%s: %s", COLORS["bold"], t("Summary"), RESET,
                 t("{br} border routers, leader {leader}, {down} unavailable, {rec} recoveries, {weak} weak links",
                   br=s["br_online"], leader=s["leader"], on=s["matter_online"], known=s["matter_known"],
                   down=h.get("unavailable", "?"), rec=h.get("recovered_by_ping", "?"), bursts=s["bursts_count"],
                   weak=r.get("weak_links", "?"), unstable=r.get("unstable", "?")))

    def publisher(self):
        last_full = 0
        last_hourly = time.time()
        startup_reported = False
        while not self.stop.wait(5):
            if self.storm and not self.quiet:
                try:
                    self.storm.check(self.summary())
                except Exception as err:  # noqa: BLE001
                    LOG.warning(t("Storm check failed: {err}", err=err))
            if not startup_reported and not self.quiet:
                s = self.summary()
                self.emit("startup", t("Monitoring ready: {br} border routers, leader {leader}, automatic recovery {auto}",
                                       v=VERSION, br=s["br_online"], leader=s["leader"], nodes=s["matter_online"],
                                       speakers=s["cast_online"], auto=t("on") if self.healer.enabled else t("off"),
                                       origin=self.healer.enabled_origin),
                          version=VERSION, br=s["br_list"], matter=s["matter_online"], cast=s["cast_list_online"],
                          auto_recovery=self.healer.enabled, auto_recovery_origin=self.healer.enabled_origin)
                self.check_global()
                self.check_node_prefixes()
                self.cleanup_discovery()
                startup_reported = True
            if time.time() - last_hourly >= 3600:
                last_hourly = time.time()
                try:
                    self.hourly()
                except Exception as err:  # noqa: BLE001
                    LOG.warning(t("Cannot write the hourly summary: {err}", err=err))
            if self.dirty or time.time() - last_full > 60:
                try:
                    self.publish_states()
                    last_full = time.time()
                except Exception as err:  # noqa: BLE001
                    LOG.warning(t("Cannot publish to MQTT: {err}", err=err))

    def cleanup_discovery(self):
        """Remove retained discovery topics of this add-on that are no longer
        published (entities of an older version, border routers of other networks)."""
        self.mqtt.publish(f"{BASE}/advice", b"", retain=True)   # state topic of a sensor removed in 1.3.0
        for topic in list(self.retained):
            # a known border router that did not announce itself yet keeps its entity
            parts = topic.split("/")
            if len(parts) > 3 and parts[3].startswith("br_") and any(k[:16] == parts[3][3:] for k in self.br_names):
                continue
            if topic not in self.published:
                self.mqtt.publish(topic, b"", retain=True)
                LOG.info(t("🧹 obsolete entity removed: {topic}", topic=topic))
        self.retained.clear()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        LOG.info(t("Connected to MQTT", code=reason_code))
        client.publish(f"{BASE}/status", "online", retain=True)
        client.subscribe(f"{BASE}/healer/set")
        client.subscribe(f"{BASE}/ping_all/set")
        client.subscribe(f"{BASE}/rename/set")
        client.subscribe(f"{BASE}/reattach/set")
        client.subscribe(f"{BASE}/reset/set")
        client.subscribe(f"{DISCOVERY}/+/{BASE}/+/config")
        self.publish_discovery()
        self.dirty = True

    def on_message(self, client, userdata, msg):
        if msg.topic.startswith(f"{DISCOVERY}/"):
            if msg.retain and msg.payload:
                self.retained.add(msg.topic)
            return
        if msg.topic == f"{BASE}/rename/set" and getattr(self, "labels", None) and msg.payload:
            threading.Thread(target=self.labels.rename, args=(t("the button in Home Assistant"),),
                             daemon=True, name="rename").start()
            return
        if msg.topic == f"{BASE}/reattach/set" and getattr(self, "reattach", None) and msg.payload:
            threading.Thread(target=self.reattach.run_now, args=(t("the button in Home Assistant"),),
                             daemon=True, name="reattach").start()
            return
        if msg.topic == f"{BASE}/reset/set" and self.healer and msg.payload:
            threading.Thread(target=self.reset_stats, args=(t("the button in Home Assistant"),),
                             daemon=True, name="reset").start()
            return
        if msg.topic == f"{BASE}/ping_all/set" and self.healer and msg.payload:
            threading.Thread(target=self.healer.ping_all_now, args=(t("the button in Home Assistant"),),
                             daemon=True, name="ping_all").start()
            return
        if msg.topic == f"{BASE}/healer/set" and self.healer:
            self.healer.set_enabled(msg.payload.decode().strip().upper() == "ON",
                                    t("switch.mesh_guardian_auto_recovery in Home Assistant"))

    # ---------------------------------------------------------------- run
    def run(self):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=BASE)
        if MQTT_USER:
            client.username_pw_set(MQTT_USER, MQTT_PASS)
        client.will_set(f"{BASE}/status", "offline", retain=True)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        self.healer = Healer(self, OPTIONS)
        self.radio = Radio(self, self.healer, OPTIONS)
        self.labels = LabelSync(self, self.healer, OPTIONS)
        self.advisor = Advisor(self)
        self.radio.advisor = self.advisor
        self.live = MatterLive(self, self.healer)
        self.radio.live = self.live
        self.labels.live = self.live
        self.reattach = Reattach(self, self.healer)
        self.reattach.live = self.live
        self.reattach.advisor = self.advisor
        self.storm = Storm(self)
        self.healer.storm = self.storm
        self.quality = Quality(self, self.healer, self.live, OPTIONS)
        self.history = History(self)
        self.table = NodeTable(self, self.healer, self.radio, self.live, self.advisor)
        self.reattach.table = self.table
        self.table.quality = self.quality
        self.webui = WebUI(self, self.table)
        LOG.info(t("Mesh Guardian {v} starting", v=VERSION,
                   auto=t("on") if self.healer.enabled else t("off"), origin=self.healer.enabled_origin))
        global FABRIC
        if not FABRIC:
            FABRIC = self.healer.fabric_id() or ""
            if FABRIC:
                LOG.info(t("Home Assistant Matter fabric detected: {fabric}", fabric=FABRIC))
            else:
                LOG.warning(t("Matter fabric not found: every node followed"))
        client.reconnect_delay_set(1, 60)
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        self.mqtt = client

        self.zc = Zeroconf(ip_version=IPVersion.All)
        self.browsers = {ty: ServiceBrowser(self.zc, ty, handlers=[self.on_change])
                         for ty in (T_MESHCOP, T_MATTER, T_CAST, T_AIRPLAY)}
        threads = [threading.Thread(target=f, daemon=True, name=f.__name__)
                   for f in (self.worker, self.worker, self.prober, self.publisher, self.confirmer,
                             self.healer.run, self.healer.run_sweeper, self.radio.run, self.radio.run_leader,
                             self.labels.run, self.live.run, self.table.run, self.webui.run,
                             self.quality.run_probe, self.quality.run_sniffer, self.quality.run_score,
                             self.history.run)]
        for th in threads:
            th.start()
        LOG.info(t("mDNS listening started", types=", ".join((T_MESHCOP, T_MATTER, T_CAST, T_AIRPLAY))))

        def shutdown(signum, _frame):
            if self.stop.is_set():
                return
            name = signal.Signals(signum).name
            self.emit("addon_stop", t("Stopping",
                                      signal=name) if signum == signal.SIGTERM else
                      t("Stopping ({signal})", signal=name), signal=name, version=VERSION)
            self.stop.set()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        while not self.stop.is_set():
            time.sleep(1)
        for b in self.browsers.values():
            b.cancel()
        client.publish(f"{BASE}/status", "offline", retain=True)
        client.loop_stop()
        self.zc.close()


if __name__ == "__main__":
    Watch().run()

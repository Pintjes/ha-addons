# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Pairing codes of the nodes, kept by the add-on.

A node cannot be asked for the code it was paired with (it only keeps a
verifier), and Home Assistant does not keep it. The code printed on the device
is the only way back after a factory reset, and the device may be in a wall
box or on a ceiling. The user gives it once (QR code read from a photo by the
page, or typed), and the add-on shows it again when it is needed.

A code is kept in /data, outside the Matter Server: it survives the reset and
the removal of the node. A node that comes back gets a new node id, so a code
is found again by what the device keeps: its serial number, else its hardware
address or its unique id (those two can change at a reset on some devices).
When nothing matches, the code stays in the list and the user attaches it to
the new node.

The codes are never written to the log, the events or the report.
"""
import base64
import logging
import threading
import time
import uuid

from store import load_json, save_json

LOG = logging.getLogger("mg.pairing")
FILE = "/data/pairing_codes.json"
GUESS_RESET_S = 7 * 86400   # s: a code waiting since a reset goes by itself to a node paired within this time
GUESS_SCAN_S = 30 * 60      # s: a code scanned before a pairing goes by itself to a node paired within this time
B38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."
# Verhoeff check digit (last digit of a manual pairing code)
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff(digits):
    """Check digit for a string of digits."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def _base38(text):
    """Bytes of a base-38 text (Matter QR code): 5 characters -> 3 bytes, 4 -> 2, 2 -> 1."""
    out = bytearray()
    for i in range(0, len(text), 5):
        chunk = text[i:i + 5]
        size = {5: 3, 4: 2, 2: 1}.get(len(chunk))
        if size is None:
            raise ValueError("length")
        value = 0
        for ch in reversed(chunk):
            value = value * 38 + B38.index(ch)
        if value >= 1 << (8 * size):
            raise ValueError("value")
        out += value.to_bytes(size, "little")
    return bytes(out)


def manual_code(discriminator, passcode):
    """11-digit manual pairing code of a 12-bit discriminator and a passcode."""
    short = discriminator >> 8
    body = f"{short >> 2}{((short & 3) << 14) | (passcode & 0x3FFF):05d}{passcode >> 14:04d}"
    return body + verhoeff(body)


def parse(text):
    """What a QR code text or a typed code holds: {"qr", "manual", "vid", "pid"}.
    Raises ValueError("format" | "check") when it is not a Matter pairing code."""
    raw = str(text or "").strip().upper()
    if "MT:" in raw:
        body = ""
        for ch in raw.split("MT:", 1)[1]:   # up to the first other character ("*": several devices, the first is kept)
            if ch not in B38:
                break
            body += ch
        try:
            data = _base38(body)
        except ValueError as err:
            raise ValueError("format") from err
        if len(data) < 11:
            raise ValueError("format")
        bits = int.from_bytes(data[:11], "little")
        vid, pid = (bits >> 3) & 0xFFFF, (bits >> 19) & 0xFFFF
        disc, passcode = (bits >> 45) & 0xFFF, (bits >> 57) & 0x7FFFFFF
        if bits & 7 or not passcode:   # version 0 only
            raise ValueError("format")
        return {"qr": "MT:" + body, "manual": manual_code(disc, passcode), "vid": vid, "pid": pid}
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) not in (11, 21) or any(ch not in "0123456789 -." for ch in raw):
        raise ValueError("format")
    if verhoeff(digits[:-1]) != digits[-1]:
        raise ValueError("check")
    out = {"qr": None, "manual": digits, "vid": None, "pid": None}
    if len(digits) == 21:
        out["vid"], out["pid"] = int(digits[10:15]), int(digits[15:20])
    return out


def _blank(b64):
    """True for an address made only of zeros (placeholder that many devices share)."""
    try:
        return not any(base64.b64decode(b64))
    except Exception:  # noqa: BLE001
        return True


def identity(attrs):
    """What a device keeps and reports about itself: {"serial", "hw", "uid", "vid", "pid"}.
    hw: the address of its Thread interface (type 4), else of its only interface; never a
    placeholder made of zeros."""
    attrs = attrs or {}
    itfs = [i for i in attrs.get("0/51/0") or [] if isinstance(i, dict) and i.get("4") and not _blank(str(i["4"]))]
    thread = [str(i["4"]) for i in itfs if i.get("7") == 4]
    hw = thread or ([str(itfs[0]["4"])] if len(itfs) == 1 else [])
    return {"serial": attrs.get("0/40/15") or None, "hw": hw[0] if hw else None, "uid": attrs.get("0/40/18") or None,
            "vid": attrs.get("0/40/2"), "pid": attrs.get("0/40/4")}


def _same_product(e, ident):
    """The entry can be the code of that device: same vendor and product, or one of them unknown."""
    return e.get("vid") is None or ident.get("vid") is None or (e.get("vid"), e.get("pid")) == (ident["vid"], ident["pid"])


class Pairing:
    def __init__(self, path=FILE):
        self.path = path
        self.lock = threading.Lock()
        self.items = {}   # entry id -> {"node", "name", "area", "model", "qr", "manual", "vid", "pid", "serial", "hw", "uid", "saved"}
        # a file that cannot be read is moved aside by load_json, never overwritten: these
        # codes cannot be found again for a device in a wall box
        data = load_json(path, {})
        if isinstance(data, dict):
            self.items = {k: v for k, v in data.items() if isinstance(v, dict)}

    def _save(self):
        save_json(self.path, self.items, ensure_ascii=False)

    def _find(self, nid, ident, present):
        """Entry id of a node: by its node id, else by what the device keeps (an entry whose
        own node is still there is never taken by another node). Always the same product: a
        node id is given again after the Matter Server is installed anew, and a serial or an
        address can be shared by two products."""
        for key, e in self.items.items():
            if e.get("node") == nid and _same_product(e, ident):
                return key
        for field in ("serial", "hw", "uid"):
            value = ident.get(field)
            if not value:
                continue
            for key, e in self.items.items():
                if e.get(field) == value and e.get("node") not in present and _same_product(e, ident):
                    return key
        return None

    @staticmethod
    def _public(key, e, **more):
        return {"key": key, "name": e.get("name"), "area": e.get("area"), "model": e.get("model"), "qr": e.get("qr"),
                "manual": e.get("manual"), "saved": e.get("saved"), "scanned": bool(e.get("pending")), **more}

    def _after_reset(self, nid, ident, present):
        """Entry id of the code waiting for a node that was reset with the Reset button and
        came back with nothing to tell it is the same device: the only code of that product
        waiting since such a reset, for a node paired after it (node ids only grow)."""
        if ident["vid"] is None:
            return None
        now = time.time()
        found = [k for k, e in self.items.items() if e.get("reset") and e.get("node") not in present
                 and now - (e.get("reset_t") or now) < GUESS_RESET_S
                 and (e.get("vid"), e.get("pid")) == (ident["vid"], ident["pid"])
                 and int(e.get("node") or "0", 16) < int(nid, 16)]
        return found[0] if len(found) == 1 else None

    def _scanned(self, nid, ident):
        """Entry id of the code scanned just before a pairing started from the page, for the
        node that this pairing brought: the only scanned code of that product still waiting,
        for a node that did not exist when it was scanned (node ids only grow)."""
        if ident["vid"] is None:
            return None
        # only for the pairing it was scanned for: after GUESS_SCAN_S it waits in the list, to
        # be attached by hand (a pairing that failed must not give its code to another unit)
        now = time.time()
        found = [k for k, e in self.items.items() if e.get("pending") and not e.get("node")
                 and now - (e.get("saved") or 0) < GUESS_SCAN_S
                 and (e.get("vid"), e.get("pid")) == (ident["vid"], ident["pid"])
                 and int(e.get("after") or "0", 16) < int(nid, 16)]
        return found[0] if len(found) == 1 else None

    def scan(self, text, present):
        """Keep a code scanned before its device is paired: it waits for the node the pairing
        brings. Raises ValueError("format" | "check" | "typed": only a QR code tells the product)."""
        code = parse(text)
        if not code["qr"]:
            raise ValueError("typed")
        with self.lock:
            for key, e in list(self.items.items()):   # scanned twice: once is kept
                if e.get("pending") and not e.get("node") and e.get("qr") == code["qr"]:
                    del self.items[key]
            key = uuid.uuid4().hex[:12]
            self.items[key] = {"node": None, "pending": True, "after": max(present, key=lambda n: int(n, 16), default="0"),
                               "name": "", "area": "", "model": "", "qr": code["qr"], "manual": code["manual"],
                               "vid": code["vid"], "pid": code["pid"], "serial": None, "hw": None, "uid": None,
                               "saved": int(time.time())}
            self._save()
            return self._public(key, self.items[key])

    def _twin(self, key, present):
        """A code typed again for a device whose QR code is already kept: the typed digits do
        not hold what a QR code needs, the kept entry does. The QR code moves to the typed
        entry and the kept one, whose node is gone, is dropped."""
        e = self.items[key]
        if e.get("qr"):
            return False
        for other, o in list(self.items.items()):
            if other != key and o.get("qr") and o.get("manual") == e.get("manual") and o.get("node") not in present \
                    and (e.get("vid") is None or o.get("vid") is None or (o.get("vid"), o.get("pid")) == (e.get("vid"), e.get("pid"))):
                e["qr"] = o["qr"]
                del self.items[other]
                return True
        return False

    def of(self, nid, attrs, present):
        """Code of a node, or None. A code found by what the device keeps, or waiting since
        its reset, is attached to the node for good (it came back with a new node id)."""
        ident = identity(attrs)
        with self.lock:
            key, auto = self._find(nid, ident, present), False
            if key is None:
                key, auto = self._after_reset(nid, ident, present), True
            if key is None:
                key, auto = self._scanned(nid, ident), False   # scanned for this very pairing: nothing to check
            if key is None:
                return None
            e = self.items[key]
            changed = self._twin(key, present)
            if e.get("node") != nid:
                e.update({"node": nid, "auto": auto, "serial": ident["serial"], "hw": ident["hw"], "uid": ident["uid"]})
                changed = True
            for flag in ("reset", "reset_t", "pending", "after"):
                if e.pop(flag, None) is not None:
                    changed = True
            if changed:
                self._save()
            return self._public(key, e, auto=bool(e.get("auto")))

    def mark_reset(self, nid):
        """The node was reset with the Reset button: its code waits for the node that comes back."""
        with self.lock:
            for e in self.items.values():
                if e.get("node") == nid:
                    e["reset"], e["reset_t"] = True, int(time.time())
                    self._save()
                    return

    def free(self, present, vid=None, pid=None):
        """Codes whose node is no longer there (removed or reset), newest first. vid / pid:
        only those that can belong to such a device."""
        with self.lock:
            out = [self._public(k, e) for k, e in self.items.items() if e.get("node") not in present
                   and (vid is None or e.get("vid") is None or (e.get("vid"), e.get("pid")) == (vid, pid))]
        return sorted(out, key=lambda e: e.get("saved") or 0, reverse=True)

    def count(self):
        with self.lock:
            return len(self.items)

    def set(self, nid, attrs, present, text, name="", area="", model=""):
        """Keep the code of a node (replaces the one it had). Raises ValueError("format" |
        "check" | "device": the QR code is the one of another product)."""
        code, ident = parse(text), identity(attrs)
        if code["vid"] is not None and ident["vid"] is not None and (code["vid"], code["pid"]) != (ident["vid"], ident["pid"]):
            raise ValueError("device")
        with self.lock:
            key = self._find(nid, ident, present) or uuid.uuid4().hex[:12]
            self.items[key] = {"node": nid, "name": name, "area": area, "model": model, "qr": code["qr"],
                               "manual": code["manual"], "vid": ident["vid"] if ident["vid"] is not None else code["vid"],
                               "pid": ident["pid"] if ident["pid"] is not None else code["pid"],
                               "serial": ident["serial"], "hw": ident["hw"], "uid": ident["uid"], "saved": int(time.time())}
            self._twin(key, present)
            self._save()
            return self._public(key, self.items[key])

    def attach(self, key, nid, attrs, name="", area="", model=""):
        """Give a kept code to a node (the device came back and nothing told it was the same)."""
        ident = identity(attrs)
        with self.lock:
            e = self.items.get(key)
            if e is None:
                raise KeyError(key)
            for other, o in list(self.items.items()):   # the node has one code
                if other != key and o.get("node") == nid:
                    del self.items[other]
            e.update({"node": nid, "name": name or e.get("name"), "area": area or e.get("area"), "model": model or e.get("model"),
                      "serial": ident["serial"], "hw": ident["hw"], "uid": ident["uid"], "auto": False})
            for flag in ("reset", "reset_t", "pending", "after"):
                e.pop(flag, None)
            self._save()
            return self._public(key, e)

    def refresh(self, nid, attrs, name, area, model):
        """Name and identity of a node that has a code, as they are now (kept for the day it is reset)."""
        ident = identity(attrs)
        with self.lock:
            for e in self.items.values():
                if e.get("node") == nid:
                    new = {"name": name or e.get("name"), "area": area or e.get("area"), "model": model or e.get("model"),
                           **{f: ident[f] or e.get(f) for f in ("serial", "hw", "uid")}}
                    if any(e.get(k) != v for k, v in new.items()):
                        e.update(new)
                        self._save()
                    return

    def delete(self, key):
        with self.lock:
            if self.items.pop(key, None) is None:
                return False
            self._save()
            return True

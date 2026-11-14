# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Names Home Assistant -> Matter nodes, on request.

The name given to a device in Home Assistant can be written to the NodeLabel
attribute (Basic Information, 0/40/5) of its Matter node, always in that
direction. Only devices renamed by the user in Home Assistant are concerned.
NodeLabel is a plain label: it does not change how the node works, and other
ecosystems (Google Home, Apple Home, ...) keep their own names.

The add-on only compares the names (every 5 minutes, values already received
from the Matter Server) and publishes the nodes to rename. Nothing is written
until the "Rename nodes" button is pressed.
"""
import logging
import threading
import time

from i18n import t, tn

LOG = logging.getLogger("mg.labels")
ATTR = "0/40/5"
MAX_BYTES = 32
CHECK_EVERY = 300


def fit(name):
    """Cut the name to 32 UTF-8 bytes without breaking a character."""
    raw = name.strip().encode("utf-8")[:MAX_BYTES]
    return raw.decode("utf-8", errors="ignore").strip()


class LabelSync:
    def __init__(self, watch, healer, options):
        self.w = watch
        self.h = healer
        self.live = None          # live copy of the Matter Server cache, plugged in by watcher
        self.busy = threading.Lock()
        self.todo = {}            # node hex -> (wanted, current, name, area, available)
        self.last = {"date": None, "to_rename": 0, "nodes": [], "in_sync": 0, "last_rename": None}

    def _nodes(self):
        if self.live and self.live.connected:
            return self.live.snapshot()
        nodes = self.h.matter_command("get_nodes", {}, timeout=120)
        if not isinstance(nodes, list):
            raise RuntimeError("unexpected get_nodes answer")
        return nodes

    def check(self):
        """Compare the names; writes nothing."""
        nodes = self._nodes()
        with self.h.lock:
            ha = {k: dict(v) for k, v in self.h.nodes.items()}
        if not ha:
            return
        todo, ok = {}, 0
        for node in nodes:
            nid = f"{int(node.get('node_id', 0)):016X}"
            n = ha.get(nid)
            if not n or not n.get("custom") or not n.get("name"):
                continue
            wanted = fit(n["name"])
            current = ((node.get("attributes") or {}).get(ATTR) or "").strip()
            if current == wanted:
                ok += 1
            else:
                todo[nid] = (wanted, current, n["name"], n.get("area"),
                             bool(n.get("available")) and node.get("available", True) is not False)
        self.todo = todo
        self.last.update({"date": time.strftime("%H:%M"), "to_rename": len(todo), "in_sync": ok,
                          "nodes": [f"{c or t('(empty)')} → {w}" for w, c, _, _, _ in todo.values()][:60]})
        self.w.dirty = True

    def rename(self, origin):
        """Write the Home Assistant name to every node that needs it (button)."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            self.check()
            if not self.todo:
                self.w.emit("names", t("No node to rename",
                                       origin=origin), wrote=0, failed=[])
                return
            wrote, failed = 0, []
            for nid, (wanted, current, name, area, available) in list(self.todo.items()):
                if self.w.stop.is_set():
                    return
                if not available:
                    failed.append(f"{name} ({t('unavailable')})")
                    continue
                try:
                    self.h.matter_command("write_attribute",
                                          {"node_id": int(nid, 16), "attribute_path": ATTR, "value": wanted},
                                          timeout=60)
                except Exception as err:  # noqa: BLE001
                    failed.append(name)
                    LOG.warning(t("{name} not renamed: {err}", name=name, area=area, err=err))
                    continue
                wrote += 1
                self.w.emit("name_synced", t('Renamed: "{before}" → "{after}"',
                                             before=current or t("(empty)"), after=wanted, area=area),
                            node=nid, before=current, after=wanted)
                time.sleep(1)
            self.last["last_rename"] = time.strftime("%d/%m %H:%M")
            self.w.emit("names", tn("{n} node renamed", "{n} nodes renamed", wrote, origin=origin)
                        + (t("; not renamed: {names}", names=", ".join(failed)) if failed else ""),
                        wrote=wrote, failed=failed)
            time.sleep(5)
            self.check()
        finally:
            self.busy.release()

    def run(self):
        self.w.stop.wait(120)  # let the add-on read the nodes first
        while not self.w.stop.is_set():
            try:
                self.check()
            except Exception as err:  # noqa: BLE001
                LOG.debug("name check: %s", err)
            if self.w.stop.wait(CHECK_EVERY):
                return

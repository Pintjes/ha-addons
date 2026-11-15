# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Test of the Supervisor API: which calls the role of the add-on allows.

Only the HTTP status and the size of each answer are kept, never the content (other
add-ons' options can hold passwords). Result in the log at start and at /api/supervisor_probe.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

LOG = logging.getLogger("mesh_guardian")

CALLS = [
    ("own info", "/addons/self/info"),
    ("Matter Server info", "/addons/core_matter_server/info"),
    ("Matter Server stats", "/addons/core_matter_server/stats"),
    ("Matter Server log", "/addons/core_matter_server/logs"),
    ("installed add-ons", "/addons"),
    ("Supervisor log", "/supervisor/logs"),
    ("Home Assistant info", "/core/info"),
    ("Home Assistant log", "/core/logs"),
    ("host info", "/host/info"),
    ("network info", "/network/info"),
    ("hardware info", "/hardware/info"),
    ("issues (resolution)", "/resolution/info"),
    ("jobs", "/jobs/info"),
]

result = {"time": None, "role": None, "calls": []}


def _get(path):
    req = urllib.request.Request("http://supervisor" + path,
                                 headers={"Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", ""),
                                          "Range": "entries=:-5:"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
            return r.status, len(body), body
    except urllib.error.HTTPError as err:
        return err.code, 0, b""
    except Exception as err:  # noqa: BLE001
        return str(err)[:80], 0, b""


def run():
    calls = []
    for label, path in CALLS:
        status, size, body = _get(path)
        calls.append({"call": label, "path": path, "status": status, "bytes": size})
        if path == "/addons/self/info" and status == 200:
            try:
                result["role"] = json.loads(body).get("data", {}).get("hassio_role")
            except Exception:  # noqa: BLE001
                pass
    result.update({"time": time.time(), "calls": calls})
    ok = [c["call"] for c in calls if c["status"] == 200]
    refused = [f'{c["call"]} ({c["status"]})' for c in calls if c["status"] != 200]
    LOG.info("Supervisor API test, role %s — allowed: %s — refused: %s",
             result["role"], ", ".join(ok) or "none", ", ".join(refused) or "none")

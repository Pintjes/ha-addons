# Mesh Guardian — Home Assistant add-on
# Author: Pintjes — https://github.com/Pintjes/ha-addons
# License: GPL-3.0-or-later (see LICENSE)
"""Files kept in /data: written whole or not at all, never lost in silence.

A file is written to a temporary file, flushed to the disk, then put in place in one
step: a power cut (common on a Raspberry Pi) leaves the old version or the new one,
never half of one. A file that cannot be read is moved aside and reported, instead of
being replaced by an empty state at the next save.
"""
import json
import logging
import os
import time

from i18n import t

LOG = logging.getLogger("mg.store")


def save_json(path, data, **kw):
    """Write data as JSON to path. Raises OSError (or TypeError / ValueError for data
    that is not JSON) and then leaves the file as it was."""
    text = json.dumps(data, **kw)   # built first: an error here does not touch the file
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:   # the new name itself must reach the disk
        fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def load_json(path, default=None):
    """Content of a JSON file, or default when there is none. A file that cannot be read
    is renamed path + ".bad-<date>" and a warning is written: what it held can still be
    looked at, and the next save does not overwrite it."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as err:
        bad = f"{path}.bad-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(path, bad)
        except OSError:
            bad = path
        LOG.warning(t("Cannot read {file} ({err}): kept as {bad}, starting without it", file=path, err=err, bad=bad))
        return default


def gone_keys(keys, ids):
    """Keys (node ids in hex) of nodes not in ids (set of int node ids); a key that is not an id stays."""
    out = []
    for k in keys:
        try:
            if int(k, 16) not in ids:
                out.append(k)
        except (TypeError, ValueError):
            pass
    return out

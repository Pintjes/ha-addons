"""2.40.2 : compteur des commandes envoyees par Mesh Guardian au Matter Server, par type (derniere heure
glissante, 24 h, heure par heure), rendu par /api/table (matter_commands) et sur la page. Compter
n'envoie rien. Les lectures du cache (get_nodes, get_node) ne comptent pas comme commandes vers les nodes.
Valeurs fictives uniquement."""
import collections
import json
import os
import sys
import threading
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
try:
    import websocket  # noqa: F401
except ImportError:
    sys.modules["websocket"] = types.ModuleType("websocket")

import healer as H  # noqa: E402

h = H.Healer.__new__(H.Healer)
h.cmd_lock, h.cmd_log = threading.Lock(), collections.deque()
T0 = 1_800_000_000.0 - 1_800_000_000.0 % 3600   # start of a clock hour
h.cmd_since = T0 - 30 * 3600

# 25 h of commands: only the last 24 h are kept
for i in range(25):
    h._count_command("read_attribute", now=T0 - (24 - i) * 3600 + 60)
now = T0 + 1800
h._count_command("read_attribute", now=now - 600)
h._count_command("ping_node", now=now - 300)
h._count_command("get_nodes", now=now - 200)
c = h.command_counts(now=now)
assert len(h.cmd_log) == 27, len(h.cmd_log)            # the command older than 24 h is gone
# last hour (rolling): the hourly read at T0 + 60 s and the 3 above; get_nodes is not a command to a node
assert c["hour"]["total"] == 4 and c["hour"]["radio"] == 3, c["hour"]
assert c["hour"]["by"] == {"read_attribute": 2, "get_nodes": 1, "ping_node": 1}, c["hour"]["by"]
# 24 h: the 24 hourly reads still inside the window, plus the 3 above
assert c["day"]["by"]["read_attribute"] == 25 and c["day"]["radio"] == 26 and c["day"]["seconds"] == 86400, c["day"]
assert list(c["day"]["by"])[0] == "read_attribute"     # most frequent first
assert all(x["t"] % 3600 == 0 for x in c["hours"]) and c["hours"][-1]["t"] == T0, c["hours"][-1]
assert c["hours"][-1]["by"] == {"read_attribute": 2, "get_nodes": 1, "ping_node": 1} and c["hours"][-1]["radio"] == 3
assert sum(x["total"] for x in c["hours"]) == c["day"]["total"]
json.dumps(c)                                           # served as JSON

# counting started less than 24 h ago: the page says "since"
h2 = H.Healer.__new__(H.Healer)
h2.cmd_lock, h2.cmd_log, h2.cmd_since = threading.Lock(), collections.deque(), now - 600
assert h2.command_counts(now=now)["day"] == {"total": 0, "radio": 0, "by": {}, "seconds": 600}

# matter_command counts each command it sends (not a failed connection)
src = open(os.path.join(MG, "healer.py"), encoding="utf-8").read()
body = src[src.index("    def matter_command("):src.index("    def _count_command(")]
assert body.index("ws.send(") < body.index("self._count_command(command)") < body.index("ws.recv())")

# /api/table and the page
assert '"matter_commands": self.h.command_counts()' in open(os.path.join(MG, "nodetable.py"), encoding="utf-8").read()
page = open(os.path.join(MG, "web", "index.html"), encoding="utf-8").read()
assert "D.matter_commands" in page and "function cmdTip(" in page
for k in ("f_cmd:", "f_cmd_tip:", "f_cmd_day:", "f_cmd_since:"):
    assert page.count(k) == 2, k                        # English and French
assert 'f_cmd:"Commandes Matter · 1 h"' in page and 'f_cmd:"Matter commands · 1h"' in page
print("OK")

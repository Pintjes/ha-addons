"""Essai de Reattach._follow_router : resultat des que la node est redevenue routeur."""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, sys.argv[1])
import reattach  # noqa: E402

reattach.RESETS_FILE = os.path.join(tempfile.mkdtemp(), "resets.json")
NID = "00000000000000AB"


class Healer:
    def __init__(self, roles):
        self.lock, self.nodes, self.roles, self.reads = threading.Lock(), {}, list(roles), []

    def matter_command(self, command, args=None, timeout=60, timing=None):
        paths = args["attribute_path"]
        self.reads.append(paths if isinstance(paths, str) else "complet")
        if isinstance(paths, str):          # sondage du role
            role = self.roles.pop(0) if self.roles else 3
            if isinstance(role, Exception):
                raise role
            return {"0/53/1": role}
        return {"0/53/1": 5, "0/53/7": [], "0/53/8": [], "0/51/0": []}


class Watch:
    def __init__(self):
        self.stop, self.events = threading.Event(), []

    def emit(self, kind, text, **data):
        self.events.append((kind, data.get("result"), text))


class Table:
    cache_t = 0
    role = "router"

    def get(self, force=False):
        return {"rows": [{"id": "0xAB", "role": self.role, "best_link": "Voisin", "best_rssi": -60, "best_lqi": 3}]}


def essai(roles, role_final, poll, limite):
    reattach.ROUTER_POLL_S, reattach.ROUTER_SETTLE_S = poll, limite
    w, h = Watch(), Healer(roles)
    r = reattach.Reattach(w, h)
    r.table = Table()
    r.table.role = role_final
    t0 = time.time()
    r._follow_router(NID, "Spot", ("Ancien", -85, 2))
    return r.results[NID], h.reads, time.time() - t0, w.events


# redevenue routeur au 3e sondage (dont un sans reponse) : resultat tout de suite, sans attendre la limite
res, reads, duree, ev = essai([3, TimeoutError("x"), 5], "router", 0.05, 30)
assert res["state"] == "done" and res["result"] == "restarted" and "router again" in res["text"], res
assert reads == ["0/53/1", "0/53/1", "0/53/1", "complet"] and duree < 2, (reads, duree)
assert ev[0][0] == "reattach_result"
# jamais redevenue routeur : resultat a la limite, « toujours appareil final »
res, reads, duree, ev = essai([3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3], "end_device", 0.05, 0.3)
assert "still an end device" in res["text"] and reads[-1] == "complet" and 0.25 < duree < 2, (res, duree)
print("OK")

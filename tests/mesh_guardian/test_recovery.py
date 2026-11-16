"""Essai de Reattach.recover_node avec un faux Matter Server (aucun reseau)."""
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
import reattach  # noqa: E402

reattach.SETTLE_S, reattach.FOLLOW_EVERY_S, reattach.FOLLOW_FOR_S = 0.05, 0.05, 0.4
reattach.CLOSE_EVERY_S = 0.05
NID = "00000000000000AB"
ATTRS = {"0/49/1": [{"0": "bmV0", "1": True}], "0/49/65529": [0, 2, 3, 4, 6, 8]}


class Live:
    connected = True

    def __init__(self, attrs):
        self.lock = threading.Lock()
        self.nodes = {NID: {"available": False, "attributes": attrs}}


class Healer:
    def __init__(self, script):
        self.lock = threading.Lock()
        self.nodes = {NID: {"name": "Prise test", "area": "Salon", "available": False}}
        self.script, self.calls = script, []

    def matter_command(self, command, args=None, timeout=60, timing=None):
        name = args.get("command_name", command)
        self.calls.append(name if name != "ArmFailSafe" else f"ArmFailSafe({args['payload']['expiryLengthSeconds']})")
        out = self.script(name, args)
        if isinstance(out, Exception):
            raise out
        return out


class Watch:
    def __init__(self):
        self.stop, self.events = threading.Event(), []

    def emit(self, kind, text, **data):
        self.events.append((kind, data.get("result"), text))


def essai(titre, script, attrs=ATTRS, retour=False):
    w, h = Watch(), Healer(script)
    r = reattach.Reattach(w, h)
    r.live = Live(attrs)
    if retour:   # la node redevient disponible apres la commande de connexion
        orig = h.matter_command

        def cmd(command, args=None, **kw):
            if args.get("command_name") == "ConnectNetwork":
                r.live.nodes[NID]["available"] = True
            return orig(command, args, **kw)
        h.matter_command = cmd
    first = r.recover_node(NID)
    again = r.recover_node(NID) if first["result"] == "pending" else None
    end = time.time() + 5
    while NID in r.recovering and time.time() < end:
        time.sleep(0.02)
    res = r.results.get(NID, {})
    print(f"{titre}\n  reponse={first['result']} second_clic={again and again['result']} final={res.get('result')} "
          f"etat={res.get('state')} verrou_libre={r.busy.acquire(blocking=False)}\n  appels={h.calls}\n  evenements={w.events}")
    return first["result"], res.get("result")


ok = {"errorCode": 0}
assert essai("1. rien ne passe", lambda n, a: TimeoutError("timed out") if n == "ArmFailSafe" else {}) == ("pending", "unreachable")
assert essai("2. commande recue, node revenue",
             lambda n, a: TimeoutError("timed out") if n == "ConnectNetwork" else ok, retour=True) == ("pending", "back")
assert essai("3. commande recue, node toujours absente",
             lambda n, a: {"networkingStatus": 0} if n == "ConnectNetwork" else ok) == ("pending", "noanswer")
assert essai("4. refus de la node", lambda n, a: {"networkingStatus": 5} if n == "ConnectNetwork" else ok) == ("pending", "failed")
echecs = {"n": 0}


def cloture_tardive(n, a):   # la cloture echoue 2 fois, puis passe : elle doit etre retentee apres le retour
    if n == "CommissioningComplete":
        echecs["n"] += 1
        return TimeoutError("timed out") if echecs["n"] <= 2 else ok
    return TimeoutError("timed out") if n == "ConnectNetwork" else ok


assert essai("6. node revenue avant la cloture", cloture_tardive, retour=True) == ("pending", "back")
assert echecs["n"] == 3, echecs
assert essai("5. reseau inconnu", lambda n, a: ok, attrs={}) == ("unsupported", None)
print("OK")

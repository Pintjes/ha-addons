"""2.40.6: the log of the Matter Server, followed per node. No line for READ_TIMEOUT is a quiet log,
not a loss: the stream is opened again at once, without a gap, keeping the offline nodes, without a
new log line, and the last line the Supervisor sends again on reopening is not counted twice.
A real failure still makes a gap. Made-up values only."""
import os
import sys
import tempfile
import threading
import types

MG = sys.argv[1]
sys.path.insert(0, MG)
import matterlog as M  # noqa: E402

M.STATE_FILE = os.path.join(tempfile.mkdtemp(), "matter_log.json")
M.time.sleep = lambda s: None                     # run() waits 8 s at start

OFF = "2026-11-19 01:00:00.000 INFO   x  Node @1:2a is offline\n".encode()
SUB = "2026-11-19 01:00:01.000 INFO   x  Subscription 1 to peer @1:2b timed out\n".encode()
SUB2 = "2026-11-19 01:20:00.000 INFO   x  Subscription 2 to peer @1:2b timed out\n".encode()
A, B = f"{0x2a:016X}", f"{0x2b:016X}"


class Stream:
    """One opening of the stream: its lines, then how it ends."""
    def __init__(self, lines, end):
        self.lines, self.end = lines, end

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        yield from self.lines
        raise self.end


class Stop(Exception):
    pass


def run(openings):
    M.STATE_FILE = os.path.join(tempfile.mkdtemp(), "matter_log.json")   # a fresh state for each run
    stop = threading.Event()
    lg = M.MatterLog(types.SimpleNamespace(stop=stop))
    lg.token = "x"
    lg._level = lambda: None
    seq = list(openings)
    logged = []
    M.LOG.info = lambda msg, *a: logged.append(msg)

    def _open(path, entries=None, timeout=30):
        if not seq:
            stop.set()
            raise Stop()
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    lg._open = _open
    stop.wait = lambda s=None: stop.is_set()        # no real waiting between tries
    lg.run()
    return lg, logged


# quiet night: two openings, each ended by a read timeout; the second one sends the last line again
lg, logged = run([Stream([OFF, SUB], TimeoutError("timed out")), Stream([SUB, SUB2], TimeoutError("timed out"))])
counts = {nid: sum(r[M.FIELDS.index("sub")] for h in lg.hours.values() for k, r in h.items() if k == nid) for nid in (A, B)}
assert counts[B] == 2, counts                       # SUB once (not counted again on reopening), SUB2 once
assert A in lg.down, lg.down                        # still offline: not forgotten on a quiet log
assert lg.gaps == [], lg.gaps                       # no gap: nothing was missed
logged_follow = [m for m in logged if "Matter Server log" in m or "Journal du Matter Server" in m]
assert len(logged_follow) == 1, logged              # "followed per node" said once, not at each reopening

# a real failure (the stream cannot be opened) still makes a gap and forgets who was offline
lg, _ = run([Stream([OFF], TimeoutError("timed out")), OSError("connection refused"), Stream([SUB2], TimeoutError("t"))])
assert len(lg.gaps) == 1 and A not in lg.down, (lg.gaps, lg.down)

# a timeout while opening (no stream) is a failure too, not a quiet log
lg, _ = run([TimeoutError("open timed out"), Stream([SUB2], TimeoutError("t"))])
assert len(lg.gaps) == 1, lg.gaps
print("OK")

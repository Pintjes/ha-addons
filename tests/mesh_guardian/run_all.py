"""Run every test of Mesh Guardian: python tests/mesh_guardian/run_all.py

Each test is a plain script (no test framework, no network, no Home Assistant): it is
given the add-on folder (or its page) and prints OK as its last line when every check
passes. The Python tests need nothing beyond the standard library; the page tests need
Node.js. Exit code 1 when a test fails.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(HERE, "..", "..", "mesh_guardian"))
WEB = os.path.join(ADDON, "web")


def run(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
    lines = p.stdout.strip().splitlines()
    return p.returncode == 0 and lines and lines[-1] == "OK", (p.stdout + p.stderr).strip()


def main():
    failed = []
    for name in sorted(os.listdir(HERE)):
        path = os.path.join(HERE, name)
        if name.startswith("test_") and name.endswith(".py"):
            cmd = [sys.executable, path, ADDON]
        elif name.startswith("test_") and name.endswith(".js"):
            cmd = ["node", "--max-old-space-size=256", path, WEB if name == "test_qr.js" else os.path.join(WEB, "index.html")]
        else:
            continue
        ok, out = run(cmd)
        print(("ok    " if ok else "FAIL  ") + name)
        if not ok:
            failed.append(name)
            print("      " + "\n      ".join(out.splitlines()[-15:]))
    print(f"{len(failed)} failed" if failed else "all passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

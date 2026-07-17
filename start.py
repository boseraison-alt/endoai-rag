"""
Start the Endo AI Flask server.

Usage:
    python start.py            # start on port 5000 (kills anything already there)
    python start.py --port 5050
    python start.py --no-kill  # do not kill an existing listener; fail if port busy
"""

import argparse
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_pids_on_port(port: int) -> list[int]:
    """Return PIDs LISTENING on the given port, cross-platform."""
    pids: set[int] = set()
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
        except Exception:
            return []
        token = f":{port}"
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and token in parts[1] and parts[3] == "LISTENING":
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
    else:
        try:
            out = subprocess.check_output(
                ["lsof", "-iTCP", f"-i:{port}", "-sTCP:LISTEN", "-t"],
                text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.split():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
        except Exception:
            pass
    return sorted(pids)


def kill_pid(pid: int) -> bool:
    if platform.system() == "Windows":
        r = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, text=True)
        return r.returncode == 0
    r = subprocess.run(["kill", "-9", str(pid)], capture_output=True, text=True)
    return r.returncode == 0


def pick_python() -> str:
    """Prefer a project-local venv if one exists."""
    candidates = [
        ROOT / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin")
            / ("python.exe" if platform.system() == "Windows" else "python"),
        ROOT / "venv" / ("Scripts" if platform.system() == "Windows" else "bin")
            / ("python.exe" if platform.system() == "Windows" else "python"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def main() -> int:
    ap = argparse.ArgumentParser(description="Start the Endo AI server.")
    ap.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    ap.add_argument("--no-kill", action="store_true",
                    help="Do NOT kill an existing listener; fail if port is busy")
    args = ap.parse_args()

    busy_pids = find_pids_on_port(args.port)
    if busy_pids:
        if args.no_kill:
            print(f"[start] Port {args.port} is busy (PIDs: {busy_pids}); --no-kill set; aborting.")
            return 1
        print(f"[start] Port {args.port} is busy (PIDs: {busy_pids}) — terminating...")
        for pid in busy_pids:
            ok = kill_pid(pid)
            print(f"  PID {pid}: {'killed' if ok else 'failed'}")
        time.sleep(1)  # let the OS release the socket

    py = pick_python()
    app_path = ROOT / "app.py"
    if not app_path.exists():
        print(f"[start] app.py not found at {app_path}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env.setdefault("FLASK_RUN_PORT", str(args.port))

    print(f"[start] Python: {py}")
    print(f"[start] http://127.0.0.1:{args.port}")
    print()

    try:
        return subprocess.call([py, str(app_path)], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        print("\n[start] Shutting down (Ctrl+C).")
        return 0


if __name__ == "__main__":
    sys.exit(main())

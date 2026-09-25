#!/usr/bin/env python3
"""
mesh_tmux_mirror.py — Optional tmux display mirror for the peer mesh.

Reads the mesh PID file, locates process log files, and creates a tmux session
with panes tailing each process log. Pure display adapter — does NOT start,
stop, or otherwise manage mesh processes.

Usage:
    python3 mesh_tmux_mirror.py
    python3 mesh_tmux_mirror.py --pidfile /path/to/pids
    python3 mesh_tmux_mirror.py --session my_mesh_view
    python3 mesh_tmux_mirror.py --kill

The mirror can be started and stopped independently of the mesh.  Killing the
mirror session never affects the underlying mesh processes.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_PIDFILE = "/tmp/mesh_pids.latest"
DEFAULT_SESSION = "mesh_mirror"

_LOG_MAP = {
    "broker": "broker.log",
    "mesh_kimi": "mesh_kimi.log",
    "mesh_claude": "mesh_claude.log",
}


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _tmux_ok() -> bool:
    return subprocess.run(["which", "tmux"], capture_output=True).returncode == 0


def _session_exists(name: str) -> bool:
    return _run(["tmux", "has-session", "-t", name], check=False).returncode == 0


def _kill_session(name: str) -> None:
    _run(["tmux", "kill-session", "-t", name], check=False)


def _read_pidfile(path: Path) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    entries.append((parts[0], int(parts[1])))
                except ValueError:
                    continue
    return entries


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _log_path(run_dir: Path, name: str) -> Path:
    return run_dir / _LOG_MAP.get(name, f"{name}.log")


def _pane_cmd(name: str, pid: int, log: Path) -> str:
    status = "RUNNING" if _is_alive(pid) else "STOPPED"
    header = f"=== {name} (PID {pid}) [{status}] ==="
    if log.exists():
        return f'printf "\\n{header}\\n\\n" && tail -n +1 -F "{log}"'
    return f'printf "\\n{header}\\n\\nLog not found: {log}\\n" && while true; do sleep 60; done'


def _create_mirror(session: str, pidfile: Path, force: bool) -> None:
    if not _tmux_ok():
        print("[mirror] ERROR: tmux is not installed", file=sys.stderr)
        sys.exit(1)

    if pidfile.is_symlink():
        pidfile = pidfile.resolve()

    if not pidfile.exists():
        print(f"[mirror] ERROR: PID file not found: {pidfile}", file=sys.stderr)
        sys.exit(1)

    entries = _read_pidfile(pidfile)
    if not entries:
        print("[mirror] ERROR: PID file is empty", file=sys.stderr)
        sys.exit(1)

    run_dir = pidfile.parent

    if _session_exists(session):
        if force:
            print(f"[mirror] Killing existing session '{session}'")
            _kill_session(session)
        else:
            print(f"[mirror] Session '{session}' already exists. Use --force to recreate.")
            sys.exit(0)

    # First pane
    name0, pid0 = entries[0]
    log0 = _log_path(run_dir, name0)
    cmd0 = _pane_cmd(name0, pid0, log0)
    _run([
        "tmux", "new-session", "-d", "-s", session, "-n", "mesh", cmd0
    ])
    _run(["tmux", "select-pane", "-t", f"{session}:mesh.0", "-T", name0])

    # Additional panes
    for idx, (name, pid) in enumerate(entries[1:], start=1):
        log = _log_path(run_dir, name)
        cmd = _pane_cmd(name, pid, log)
        _run(["tmux", "split-window", "-t", f"{session}:mesh", cmd])
        _run(["tmux", "select-pane", "-t", f"{session}:mesh.{idx}", "-T", name])

    # Layout: main pane (broker) on top, rest stacked below side-by-side
    _run(["tmux", "select-layout", "-t", f"{session}:mesh", "main-horizontal"])

    print(f"[mirror] Session '{session}' created with {len(entries)} pane(s).")
    print(f"[mirror] Attach with: tmux attach -t {session}")
    print(f"[mirror] Or run:      ./attach_mesh.sh")


def _kill_mirror(session: str) -> None:
    if not _tmux_ok():
        print("[mirror] ERROR: tmux is not installed", file=sys.stderr)
        sys.exit(1)
    if _session_exists(session):
        print(f"[mirror] Killing session '{session}'")
        _kill_session(session)
    else:
        print(f"[mirror] Session '{session}' does not exist.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tmux display mirror for peer-mesh processes"
    )
    parser.add_argument(
        "--pidfile",
        type=Path,
        default=Path(DEFAULT_PIDFILE),
        help=f"Mesh PID file (default: {DEFAULT_PIDFILE})",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help=f"Tmux session name (default: {DEFAULT_SESSION})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate session if it already exists",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="Kill the mirror session and exit",
    )
    args = parser.parse_args()

    if args.kill:
        _kill_mirror(args.session)
    else:
        _create_mirror(args.session, args.pidfile, args.force)


if __name__ == "__main__":
    main()

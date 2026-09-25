"""Fleet manager — tracks bootstraps, not daemons.

The design (design/bootstrap-subreaper-design.md) makes the bootstrap the
stable identity of every managed service: daemons are disposable, the
bootstrap survives. The fleet manager owns a directory of services, one
run-dir per service, each holding a bootstrap's control FIFO and state
file:

    fleet = FleetManager(Path("~/.hearthphoenix/fleet").expanduser())
    fleet.launch("xylem", ["python3", "xylem_server.py"])
    fleet.status_all()          # {"xylem": {"daemon_alive": True, ...}}
    fleet.restart("xylem")      # via the bootstrap; process tree survives
    fleet.stop_all()

This is the seed of the herd manager in
design/mcp-transport-and-herd-manager.md — its fleet commands
(list-all, status filters, bulk lifecycle) build directly on this class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .bootstrap_handle import BootstrapError, BootstrapHandle


class FleetManager:
    """Manage a directory of bootstrap-supervised services."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._handles: Dict[str, BootstrapHandle] = {}

    # -- service lifecycle ----------------------------------------------

    def launch(self, name: str, daemon_cmd: list[str],
               graceful_timeout: float = 30.0) -> BootstrapHandle:
        """Start a bootstrap for *name*; error if it is already running."""
        existing = self._maybe_handle(name)
        if existing is not None and existing.bootstrap_alive():
            raise BootstrapError(f"service {name!r} is already running")
        handle = BootstrapHandle.launch(
            daemon_cmd, self.root / name, graceful_timeout=graceful_timeout)
        self._handles[name] = handle
        return handle

    def get(self, name: str) -> BootstrapHandle:
        """Handle for *name* (cached from launch, or attached by run-dir)."""
        handle = self._maybe_handle(name)
        if handle is None:
            raise KeyError(f"unknown service: {name!r}")
        return handle

    def restart(self, name: str, timeout: float = 10.0) -> int:
        """Cycle *name*'s daemon; returns the new daemon pid."""
        pid = self.get(name).restart(timeout=timeout)
        assert pid is not None
        return pid

    def stop(self, name: str, timeout: float = 15.0) -> None:
        self.get(name).stop(timeout=timeout)

    def stop_all(self, timeout: float = 15.0) -> None:
        for name in self.services():
            handle = self.get(name)
            if handle.bootstrap_alive():
                handle.stop(timeout=timeout)

    # -- discovery & status ----------------------------------------------

    def services(self) -> List[str]:
        """All known services: launched here or found under the root."""
        found = {p.parent.name for p in self.root.glob("*/state.json")}
        return sorted(found | set(self._handles))

    def status(self, name: str) -> dict:
        """Fleet-level view of one service, including reaped child deaths."""
        handle = self.get(name)
        try:
            st = handle.state()
        except BootstrapError:
            return {"name": name, "bootstrap_alive": False,
                    "daemon_alive": False, "error": "no state file"}
        return {
            "name": name,
            "bootstrap_alive": handle.bootstrap_alive(),
            "daemon_alive": handle.daemon_alive(),
            "daemon_pid": st.get("daemon_pid"),
            "restarts": st.get("restarts", 0),
            "reaped_children": st.get("reaped", []),
            "stopping": st.get("stopping", False),
        }

    def status_all(self) -> Dict[str, dict]:
        return {name: self.status(name) for name in self.services()}

    # -- internal ---------------------------------------------------------

    def _maybe_handle(self, name: str) -> BootstrapHandle | None:
        if name in self._handles:
            return self._handles[name]
        run_dir = self.root / name
        if (run_dir / "state.json").exists() or (run_dir / "control.fifo").exists():
            handle = BootstrapHandle.attach(run_dir)
            self._handles[name] = handle
            return handle
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m hearthphoenix.fleet --root DIR CMD ..."""
    import argparse
    import json as _json
    import sys as _sys

    parser = argparse.ArgumentParser(prog="hearthphoenix.fleet",
                                     description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="fleet root directory (one run-dir per service)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_launch = sub.add_parser("launch", help="start a bootstrap for a service")
    p_launch.add_argument("name")
    p_launch.add_argument("cmd", nargs="+", help="daemon command")
    p_launch.add_argument("--graceful-timeout", type=float, default=30.0)

    p_status = sub.add_parser("status", help="status of one or all services")
    p_status.add_argument("name", nargs="?")

    p_restart = sub.add_parser("restart", help="cycle a service's daemon")
    p_restart.add_argument("name")

    p_stop = sub.add_parser("stop", help="stop a service")
    p_stop.add_argument("name")

    sub.add_parser("stop-all", help="stop every service")
    sub.add_parser("list", help="list known services")

    args = parser.parse_args(argv)
    fleet = FleetManager(args.root)

    if args.command == "launch":
        handle = fleet.launch(args.name, args.cmd,
                              graceful_timeout=args.graceful_timeout)
        pid = handle.wait_for_daemon(timeout=15)
        print(_json.dumps({"service": args.name, "daemon_pid": pid}))
    elif args.command == "status":
        out = fleet.status(args.name) if args.name else fleet.status_all()
        print(_json.dumps(out, indent=2))
    elif args.command == "restart":
        print(_json.dumps({"service": args.name,
                           "daemon_pid": fleet.restart(args.name)}))
    elif args.command == "stop":
        fleet.stop(args.name)
        print(_json.dumps({"service": args.name, "stopped": True}))
    elif args.command == "stop-all":
        fleet.stop_all()
        print(_json.dumps({"stopped": fleet.services()}))
    elif args.command == "list":
        print(_json.dumps(fleet.services()))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())

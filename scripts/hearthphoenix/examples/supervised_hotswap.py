#!/usr/bin/env python3
"""Pattern 2: Supervised Worker with Hotswap.

Demonstrates the flagship feature: an immortal supervisor that manages a
worker subprocess with transactional hotswap and automatic rollback.

This example runs an end-to-end test:
    1. Start a supervisor with worker_v1
    2. Verify the worker is healthy
    3. Hotswap to worker_v2
    4. Verify the new version is live
    5. Stop cleanly

Run:
    python examples/supervised_hotswap.py

See also:
    examples/standalone_worker.py — the simplest worker (no supervisor)
    readme-docs/USAGE.md — Pattern 2 walkthrough
"""

import sys
import time
import tempfile
import textwrap
from pathlib import Path

from hearthphoenix import Supervisor, WorkerLifecycle, SnapshotManager
from hearthphoenix.transports import RestTransport


def create_worker_file(path: Path, version: str, port: int):
    """Write a minimal WorkerApp worker to a file."""
    code = textwrap.dedent(f"""\
    import os, time, sys
    from hearthphoenix.worker import WorkerApp

    VERSION = "{version}"
    app = WorkerApp()

    @app.health_check
    def health():
        return {{"status": "ok", "version": VERSION}}

    @app.run
    def main():
        print(f"Worker {version} running on port {port}", flush=True)
        while True:
            time.sleep(1)

    if __name__ == "__main__":
        app.start()
    """)
    path.write_text(code)


def main():
    port = 19876  # use a non-standard port to avoid conflicts

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        worker_path = tmp / "worker.py"
        snap_dir = tmp / "snapshots"

        # Create worker v1 and v2
        create_worker_file(worker_path, "v1", port)
        create_worker_file(tmp / "worker_v2.py", "v2", port)

        # Build the supervisor
        transport = RestTransport(port=port)
        snapshot_manager = SnapshotManager(snap_dir)
        lifecycle = WorkerLifecycle(log_mode="inherit")

        supervisor = Supervisor(
            transport=transport,
            snapshot_manager=snapshot_manager,
            lifecycle=lifecycle,
            worker_cmd=[sys.executable, str(worker_path)],
            worker_path=str(worker_path),
            crash_threshold=3,
            crash_window=10.0,
            cooldown_seconds=2.0,
        )

        print("=== Starting supervisor with worker v1 ===")
        supervisor.start()
        status = supervisor.status()
        print(f"Worker PID: {status['worker_pid']}")
        print(f"State: {status['state']}")
        print(f"Transport connected: {status['transport_connected']}")
        print(f"Detected capabilities: {status['detected_capabilities']}")

        time.sleep(1)  # let the worker settle

        print("\n=== Hotswapping to worker v2 ===")
        result = supervisor.update(str(tmp / "worker_v2.py"))
        print(f"Update result: success={result['success']}, action={result['action']}")
        print(f"Health: {result['health'].status}")
        if result["health"].details:
            print(f"Details: {result['health'].details}")

        time.sleep(1)

        status = supervisor.status()
        print(f"\nFinal state: {status['state']}")
        print(f"Snapshots stored: {status['snapshots']}")
        print(f"Guarantee level: {status['guarantee_level']}")

        print("\n=== Stopping supervisor ===")
        supervisor.stop()
        print("Done.")


if __name__ == "__main__":
    main()

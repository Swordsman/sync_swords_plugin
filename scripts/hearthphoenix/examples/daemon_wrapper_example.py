#!/usr/bin/env python3
"""Pattern 4: Wrapping an External Daemon with Interface Translation.

Demonstrates wrapping a daemon you don't control so it can be accessed
through multiple frontend interfaces simultaneously.

This example:
    1. Starts a small echo daemon (pretend it's a third-party binary)
    2. Wraps it with DaemonWrapper
    3. Exposes it via HTTP and a Unix socket simultaneously
    4. Shows toggling a frontend on/off at runtime

Run:
    python examples/daemon_wrapper_example.py

The echo daemon speaks JSON over a Unix socket. The wrapper adds:
    - HTTP on port 18080
    - A second socket at /tmp/hearthphoenix_demo.sock

Callers can use either interface. The TranslationEngine handles routing
and protocol conversion automatically.

See also:
    readme-docs/USAGE.md — Pattern 4 walkthrough
    readme-docs/ARCHITECTURE.md — Interface Translation Layer design
"""

import sys
import time
import socket
import json
import threading
import tempfile
import logging
from pathlib import Path

from hearthphoenix import Supervisor
from hearthphoenix.wrappers.adapters import SocketAdapter, HttpAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("daemon_wrapper_demo")


# ── Step 1: Create a pretend external daemon ──────────────────────────
# In reality, this is your third-party binary. We're making one for the demo.

def run_echo_daemon(socket_path: str, ready_event: threading.Event):
    """A minimal echo daemon that speaks JSON over a Unix socket."""
    try:
        Path(socket_path).unlink(missing_ok=True)
    except OSError:
        pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(1)
    logger.info("Echo daemon listening on %s", socket_path)
    ready_event.set()  # signal that we're ready

    try:
        while True:
            conn, _ = sock.accept()
            with conn:
                data = conn.recv(4096)
                if data:
                    try:
                        request = json.loads(data.decode())
                        response = json.dumps({
                            "echo": request,
                            "status": "ok",
                            "daemon": "echo_daemon_v1",
                        })
                        conn.sendall(response.encode())
                    except json.JSONDecodeError:
                        conn.sendall(json.dumps({
                            "error": "invalid JSON"
                        }).encode())
    except Exception:
        pass
    finally:
        sock.close()
        try:
            Path(socket_path).unlink(missing_ok=True)
        except OSError:
            pass


# ── Step 2: Run the daemon in a background thread ─────────────────────

echo_socket = "/tmp/hearthphoenix_demo_daemon.sock"
ready = threading.Event()

daemon_thread = threading.Thread(
    target=run_echo_daemon,
    args=(echo_socket, ready),
    daemon=True,
)
daemon_thread.start()
ready.wait(timeout=3)  # wait for daemon to be ready
logger.info("Echo daemon is ready.")


# ── Step 3: Wrap the daemon ───────────────────────────────────────────

try:
    wrapper, report = Supervisor.wrap_daemon(
        daemon_cmd=[sys.executable, "-c", f"""
import socket, json, threading, sys
from pathlib import Path

sock_path = "{echo_socket}"
Path(sock_path).unlink(missing_ok=True)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(sock_path)
sock.listen(1)
print("daemon ready", flush=True)

while True:
    conn, _ = sock.accept()
    with conn:
        data = conn.recv(4096)
        if data:
            request = json.loads(data.decode())
            response = json.dumps({{"echo": request, "status": "ok"}})
            conn.sendall(response.encode())
"""],
        backend=SocketAdapter(
            "backend",
            socket_path=echo_socket,
            direction="backend",
        ),
        frontends=[
            HttpAdapter(
                "http",
                port=18080,
                direction="frontend",
            ),
            SocketAdapter(
                "socket",
                socket_path="/tmp/hearthphoenix_demo.sock",
                direction="frontend",
            ),
        ],
    )

    logger.info("Capability report: %s", report.guarantee_level)

    # ── Step 4: Start the wrapper ─────────────────────────────────────
    wrapper.start()
    logger.info("Wrapper started.")

    status = wrapper.status()
    logger.info("Status: daemon_pid=%s, state=%s", status["daemon_pid"], status["state"])
    logger.info("Backend health: %s", status["backend_health"].status)
    for name, fstatus in status["frontends"].items():
        logger.info("Frontend '%s': enabled=%s, health=%s",
                     name, fstatus.get("enabled"), fstatus.get("health"))

    # ── Step 5: Demonstrate a quick health check via HTTP ──────────────
    time.sleep(1)
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:18080/health",
            data=b'{"action":"health","payload":{}}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=3)
        logger.info("HTTP health response: %s", resp.read().decode())
    except Exception as e:
        logger.warning("HTTP health check failed (this may be expected in demo): %s", e)

    # ── Step 6: Toggle a frontend off ─────────────────────────────────
    logger.info("Disabling HTTP frontend...")
    wrapper.toggle_frontend("http", enabled=False)
    status = wrapper.status()
    logger.info("HTTP frontend enabled: %s", status["frontends"]["http"].get("enabled"))

    # ── Step 7: Toggle it back on ─────────────────────────────────────
    logger.info("Re-enabling HTTP frontend...")
    wrapper.toggle_frontend("http", enabled=True)

    logger.info("\n=== Demo complete. Stopping wrapper. ===")
    wrapper.stop()
    logger.info("Wrapper stopped.")

finally:
    # Clean up socket files
    for p in [echo_socket, "/tmp/hearthphoenix_demo.sock"]:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    logger.info("Cleaned up socket files.")

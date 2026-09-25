#!/bin/bash
# stop_mesh.sh — Terminate a mesh started by start_mesh.sh.
#
# Usage:
#   ./stop_mesh.sh          # stop the latest mesh (reads /tmp/mesh_pids.latest)
#   ./stop_mesh.sh <file>   # stop a specific mesh via its PID file

set -euo pipefail

PIDFILE="${1:-/tmp/mesh_pids.latest}"

if [[ -z "${1:-}" && -L "$PIDFILE" ]]; then
    # Resolve symlink to the real PID file.
    PIDFILE="$(readlink -f "$PIDFILE")"
fi

if [[ ! -f "$PIDFILE" ]]; then
    echo "[stop_mesh] No PID file found: $PIDFILE" >&2
    exit 1
fi

echo "[stop_mesh] Reading PID file: $PIDFILE"

# Kill processes in reverse order (participants first, broker last).
tac "$PIDFILE" | while read -r name pid; do
    if kill -0 "$pid" 2>/dev/null; then
        echo "[stop_mesh] Stopping $name (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        # Wait up to 5 seconds for graceful exit.
        for i in {1..50}; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "[stop_mesh] $name (PID $pid) did not exit, sending SIGKILL..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    else
        echo "[stop_mesh] $name (PID $pid) already gone"
    fi
done

# Extract socket path from log directory if possible to clean up.
RUN_DIR="$(dirname "$PIDFILE")"
SOCKET_PATH="/tmp/mesh_bus.$(basename "$RUN_DIR" | sed 's/mesh_//').sock"
if [[ -S "$SOCKET_PATH" ]]; then
    rm -f "$SOCKET_PATH"
    echo "[stop_mesh] Removed socket: $SOCKET_PATH"
fi

rm -f "$PIDFILE"

# Remove the latest symlink if it points to the PID file we just cleaned up.
LATEST_LINK="/tmp/mesh_pids.latest"
if [[ -L "$LATEST_LINK" ]]; then
    LINK_TARGET="$(readlink -f "$LATEST_LINK" 2>/dev/null || true)"
    if [[ "${LINK_TARGET:-}" == "$PIDFILE" || ! -f "$LINK_TARGET" ]]; then
        rm -f "$LATEST_LINK"
    fi
fi

echo "[stop_mesh] Mesh stopped."

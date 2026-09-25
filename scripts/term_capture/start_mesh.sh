#!/bin/bash
# start_mesh.sh — Top-level process orchestrator for the peer mesh.
#
# Brings up the full mesh in order:
#   1. Broker daemon (python -m ai_hypervisor.broker)
#   2. Waits for broker readiness (Unix socket appears)
#   3. Kimi mesh participant (python scripts/mesh_kimi.py)
#   4. Claude mesh participant (python scripts/mesh_claude.py)
#
# Uses native OS process management (PIDs, no tmux dependency).
# Run directory, logs, and PID file are scoped per invocation.
#
# Usage:
#   ./start_mesh.sh
#   ./stop_mesh.sh          # stops the latest mesh (reads /tmp/mesh_pids.latest)
#   ./stop_mesh.sh <pidfile> # stops a specific mesh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- per-run identifiers ------------------------------------------------------
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="$SCRIPT_DIR/logs/mesh_${TIMESTAMP}"
mkdir -p "$RUN_DIR"

SOCKET_PATH="/tmp/mesh_bus.${TIMESTAMP}.sock"
PIDFILE="$RUN_DIR/pids"
LATEST_PIDFILE_LINK="/tmp/mesh_pids.latest"

BROKER_LOG="$RUN_DIR/broker.log"
KIMI_LOG="$RUN_DIR/mesh_kimi.log"
CLAUDE_LOG="$RUN_DIR/mesh_claude.log"

# --- helpers ------------------------------------------------------------------

log() {
    echo "[start_mesh] $*"
}

die() {
    echo "[start_mesh] ERROR: $*" >&2
    exit 1
}

# Clean up PID file and socket on exit if we failed early.
cleanup_on_fail() {
    local code=$?
    if [[ $code -ne 0 ]]; then
        rm -f "$PIDFILE"
        # If the symlink points to our PID file, remove it too.
        if [[ -L "$LATEST_PIDFILE_LINK" && "$(readlink "$LATEST_PIDFILE_LINK" 2>/dev/null)" == "$PIDFILE" ]]; then
            rm -f "$LATEST_PIDFILE_LINK"
        fi
        # Kill any processes we already started.
        if [[ -s "$PIDFILE" ]]; then
            while read -r _ pid; do
                kill "$pid" 2>/dev/null || true
            done < "$PIDFILE"
        fi
        rm -f "$SOCKET_PATH"
    fi
}
trap cleanup_on_fail EXIT

# --- startup banner -----------------------------------------------------------

log "Run directory : $RUN_DIR"
log "Socket path   : $SOCKET_PATH"
log "PID file      : $PIDFILE"

# --- 1. broker ----------------------------------------------------------------

log "Starting broker..."
nohup python3 -m ai_hypervisor.broker --socket "$SOCKET_PATH" > "$BROKER_LOG" 2>&1 &
BROKER_PID=$!
echo "broker $BROKER_PID" > "$PIDFILE"

# --- 2. wait for broker readiness ---------------------------------------------

log "Waiting for broker readiness (socket $SOCKET_PATH)..."
BROKER_READY=false
for i in {1..30}; do
    if [[ -S "$SOCKET_PATH" ]]; then
        BROKER_READY=true
        break
    fi
    if ! kill -0 "$BROKER_PID" 2>/dev/null; then
        wait "$BROKER_PID" || BROKER_EXIT=$?
        die "Broker process exited unexpectedly (exit code ${BROKER_EXIT:-unknown}). See $BROKER_LOG"
    fi
    sleep 0.2
done

if [[ "$BROKER_READY" != "true" ]]; then
    kill "$BROKER_PID" 2>/dev/null || true
    die "Broker failed to create socket within timeout. See $BROKER_LOG"
fi

log "Broker ready (PID $BROKER_PID)"

# --- 3. kimi mesh participant -------------------------------------------------

log "Starting mesh_kimi..."
nohup python3 scripts/mesh_kimi.py --socket "$SOCKET_PATH" > "$KIMI_LOG" 2>&1 &
KIMI_PID=$!
echo "mesh_kimi $KIMI_PID" >> "$PIDFILE"

# --- 4. claude mesh participant -----------------------------------------------

log "Starting mesh_claude..."
nohup python3 scripts/mesh_claude.py --socket "$SOCKET_PATH" > "$CLAUDE_LOG" 2>&1 &
CLAUDE_PID=$!
echo "mesh_claude $CLAUDE_PID" >> "$PIDFILE"

# --- finalize -----------------------------------------------------------------

# Update the "latest" symlink so stop_mesh.sh can find us without arguments.
ln -sf "$PIDFILE" "$LATEST_PIDFILE_LINK"

# Remove the EXIT trap so a normal exit doesn't trigger cleanup.
trap - EXIT

log "Mesh started successfully."
log "  broker    : PID $BROKER_PID  → $BROKER_LOG"
log "  mesh_kimi : PID $KIMI_PID   → $KIMI_LOG"
log "  mesh_claude: PID $CLAUDE_PID  → $CLAUDE_LOG"
log "To stop: ./stop_mesh.sh  or  ./stop_mesh.sh $PIDFILE"

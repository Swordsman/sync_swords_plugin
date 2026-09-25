#!/bin/bash
set -euo pipefail

TARGET="${1:-/home/joe/kimi-home}"
MOUNTPOINT="${TARGET}"
PID_FILE="/tmp/fuse_watcher.pid"
LOG_FILE="/tmp/fuse_watcher.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$(dirname "$PID_FILE")"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        if [ -f "/proc/$PID/cmdline" ] && grep -q "fuse_watcher" "/proc/$PID/cmdline" 2>/dev/null; then
            echo "fuse_watcher already running (PID $PID)"
            exit 0
        fi
    fi
    echo "Removing stale PID file"
    rm -f "$PID_FILE"
fi

# Warn if mountpoint is already a mount point
if mountpoint -q "$MOUNTPOINT" 2>/dev/null; then
    echo "Warning: $MOUNTPOINT is already a mount point"
fi

# Start daemon
echo "Starting fuse_watcher on $MOUNTPOINT ..."
python3 "$SCRIPT_DIR/fuse_watcher.py" \
    --target "$TARGET" \
    --mountpoint "$MOUNTPOINT" \
    --log-file "$LOG_FILE" \
    --pid-file "$PID_FILE" \
    --daemon

# Verify startup
sleep 0.5
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        if [ -f "/proc/$PID/cmdline" ] && grep -q "fuse_watcher" "/proc/$PID/cmdline" 2>/dev/null; then
            echo "fuse_watcher started successfully (PID $PID)"
            echo "Log file: $LOG_FILE"
        else
            echo "fuse_watcher failed to start (PID file points to wrong process)"
            rm -f "$PID_FILE"
            exit 1
        fi
    else
        echo "fuse_watcher failed to start (process died)"
        rm -f "$PID_FILE"
        exit 1
    fi
else
    echo "fuse_watcher failed to start (no PID file)"
    exit 1
fi

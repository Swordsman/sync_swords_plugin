#!/bin/bash
set -euo pipefail

MOUNTPOINT="${1:-/home/joe/kimi-home}"
PID_FILE="/tmp/fuse_watcher.pid"

# Change cwd to avoid "target is busy" if this shell is inside the mountpoint
cd /

# Unmount first (works even if PID file is missing)
if mountpoint -q "$MOUNTPOINT" 2>/dev/null; then
    echo "Unmounting $MOUNTPOINT ..."
    if ! fusermount -u "$MOUNTPOINT" 2>/dev/null; then
        echo "Warning: fusermount -u failed, trying umount ..."
        umount "$MOUNTPOINT" 2>/dev/null || true
    fi
fi

# Kill process if PID file exists
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        # Validate it's actually fuse_watcher before killing
        if [ -f "/proc/$PID/cmdline" ] && grep -q "fuse_watcher" "/proc/$PID/cmdline" 2>/dev/null; then
            echo "Killing fuse_watcher (PID $PID) ..."
            kill -TERM "$PID" 2>/dev/null || true
            sleep 0.5
            if kill -0 "$PID" 2>/dev/null; then
                echo "Process still alive, sending KILL ..."
                kill -KILL "$PID" 2>/dev/null || true
            fi
        else
            echo "PID $PID is not fuse_watcher; removing stale PID file"
        fi
    fi
    rm -f "$PID_FILE"
fi

# Verify unmount
if mountpoint -q "$MOUNTPOINT" 2>/dev/null; then
    echo "Warning: $MOUNTPOINT is still mounted"
    exit 1
else
    echo "fuse_watcher stopped"
fi

#!/bin/bash
set -euo pipefail

MOUNTPOINT="${1:-/home/joe/kimi-home}"
PID_FILE="/tmp/fuse_watcher.pid"
LOG_FILE="/tmp/fuse_watcher.log"

# Running status
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        if [ -f "/proc/$PID/cmdline" ] && grep -q "fuse_watcher" "/proc/$PID/cmdline" 2>/dev/null; then
            echo "Status: RUNNING"
            echo "PID: $PID"
        else
            echo "Status: NOT RUNNING (stale PID file)"
            PID=""
        fi
    else
        echo "Status: NOT RUNNING (stale PID file)"
        PID=""
    fi
else
    echo "Status: NOT RUNNING"
    PID=""
fi

echo "Mount point: $MOUNTPOINT"
if mountpoint -q "$MOUNTPOINT" 2>/dev/null; then
    echo "Mount point: ACTIVE"
else
    echo "Mount point: NOT MOUNTED"
fi

# Log lines in the last minute
if [ -f "$LOG_FILE" ]; then
    ONE_MIN_AGO=$(date -d '1 minute ago' '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')
    COUNT=$(awk -v ts="$ONE_MIN_AGO" '$1" "$2 >= ts' "$LOG_FILE" 2>/dev/null | wc -l)
    echo "Log lines in last minute: $COUNT"
    echo "Log file: $LOG_FILE"
else
    echo "Log file: not found"
fi

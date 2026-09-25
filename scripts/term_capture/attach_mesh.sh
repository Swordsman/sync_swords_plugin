#!/bin/bash
# attach_mesh.sh — Attach to the mesh tmux mirror session.
#
# Usage:
#   ./attach_mesh.sh          # attach to default session (mesh_mirror)
#   ./attach_mesh.sh <name>   # attach to a custom session name

set -euo pipefail

SESSION="${1:-mesh_mirror}"

if ! command -v tmux &> /dev/null; then
    echo "[attach_mesh] ERROR: tmux is not installed" >&2
    exit 1
fi

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[attach_mesh] No tmux session named '$SESSION'." >&2
    echo "[attach_mesh] Start the mirror first with: python3 scripts/mesh_tmux_mirror.py" >&2
    exit 1
fi

exec tmux attach-session -t "$SESSION"

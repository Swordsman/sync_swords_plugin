# xylem

Agent terminal substrate — a shared xonsh+Hy shell over FastAPI/WebSocket.

## What it does

Exposes a single PTY session over WebSocket, letting multiple AI agents and a human type into the same terminal. Agents coordinate purely through terminal I/O. Supports agent forking and session composition.

## Components

| Script | Purpose |
|--------|---------|
| `xylem-shell` | CLI client — one-shot commands or persistent daemon mode |
| `xylem-daemon` | Hermes bridge: Unix socket + hive state + session-log watcher |
| `xylem-dm` | Daemon manager: start/stop/restart/health/logs/cleanup |
| `sexp-wrap` | Wraps a TUI command, emits terminal events as s-expressions |
| `xylem_server.py` | FastAPI/WebSocket server + singleton PTY + xterm.js frontend |

## Quick start

```bash
# Start the server
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/xylem/xylem_server.py

# Send commands
${CLAUDE_PLUGIN_ROOT}/scripts/xylem/xylem-shell "ls -la"
```

## Dependencies

Requires: fastapi, uvicorn, websockets, hy, xonsh

## When to use

When multiple agents need a shared, writable terminal session — coordination happens by agents literally typing into each other's session.

## Source

[Swordsman/xylem](https://github.com/Swordsman/xylem)

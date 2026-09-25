# hearthphoenix

Process supervisor with transactional hotswap and pluggable transports.

## What it does

Supervisor/worker harness that hotswaps a running process transactionally:
validate → snapshot → swap → health-check → commit (or auto-rollback).

Five pluggable transports: REST, Unix socket, file heartbeat, pipe, CLI.
DaemonWrapper exposes external processes through multiple protocol interfaces.

## Quick start

```python
from hearthphoenix import Supervisor, Worker

supervisor = Supervisor()
worker = supervisor.wrap_worker(my_process)
supervisor.hotswap(worker, new_version, contract="GUARANTEED")
```

## Contracts

- `GUARANTEED` — full validation + snapshot + rollback on failure
- `BEST_EFFORT` — validation + swap, no guaranteed rollback
- `NOT_SUPPORTED` — raw swap, no safety net

## Transports

| Transport | When to use |
|-----------|------------|
| REST | Remote workers, HTTP-accessible services |
| Unix socket | Local IPC, low latency |
| File heartbeat | Simple daemon monitoring |
| Pipe | Subprocess communication |
| CLI | Wrapping command-line tools |

## Reference docs

- `references/USAGE.md` — full usage guide
- `references/ARCHITECTURE.md` — system architecture
- `references/API.md` — complete API reference

## Location

Package: `${CLAUDE_PLUGIN_ROOT}/scripts/hearthphoenix/`
Examples: `${CLAUDE_PLUGIN_ROOT}/scripts/hearthphoenix/examples/`

## Source

[Swordsman/hearthphoenix](https://github.com/Swordsman/hearthphoenix)

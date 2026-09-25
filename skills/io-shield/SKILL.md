# io-shield

File-level write-locking and SHA-256 integrity verification for multi-agent coordination.

## Usage

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/io_shield.py <command> <agent-name> <filepath>
```

## Commands

| Command | Purpose |
|---------|---------|
| `lock` | Acquire exclusive write lock on a file |
| `unlock` | Release lock (auto-transfers to next queued agent) |
| `heartbeat` | Extend lock TTL (prevents expiry during long operations) |
| `queue` | Join the wait queue for a locked file |
| `verify` | SHA-256 integrity check — confirms file wasn't modified outside the lock |
| `worklog` | View modification history for a file |
| `status` | Show current lock state |

## Safety contract

Exit code 1 + "STOP ALL WORK" on denial, violation, or hash mismatch. The agent MUST treat this as a hard abort.

## Environment

- `IO_SHIELD_DIR` — lock storage directory (default: `~/.io-shield/`)
- `IO_SHIELD_TTL` — lock timeout in seconds (default: 1800; use 300-600 with heartbeat mode)

## When to use

Any multi-agent workflow where agents write to shared files. Prevents ghost agents and file collisions via exclusive locking + integrity verification.

Stdlib-only Python, no dependencies.

## Source

[Swordsman/io-shield](https://github.com/Swordsman/io-shield)

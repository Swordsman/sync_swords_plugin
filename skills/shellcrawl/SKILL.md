# shellcrawl

Sandboxed virtual Linux shell for AI agent exploration and evaluation.

## What it does

An in-memory virtual filesystem + pisces (S-expression) command interpreter. Provides a safe, sandboxed fake Ubuntu environment that agents can explore without touching the real system.

## Components

- VFS layer (`vfs.py`) — in-memory nested-dict filesystem
- Shell core (`shell/core.psc`, `shell/commands.psc`) — 30 builtin commands (ls, cd, grep, ps, ssh stub, etc.), pipes, redirects
- Session (`session.py`, `builtins.py`) — Python glue, sandboxed command execution
- World (`worlds/nexus_core.psc`) — pre-seeded Ubuntu 22.04 box with embedded mystery trail

## Usage

```python
from shellcrawl.session import ShellCrawlSession

session = ShellCrawlSession()
session.load_world("nexus_core")
result = session.execute("ls -la /home")
print(result.stdout)
```

```bash
# Autonomous exploration (drives a DeepSeek explorer)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/shellcrawl/explore.py [--turns 20] [--world nexus_core]

# Lint .psc files
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/shellcrawl/psc_lint.py <file.psc>
```

## Dependencies

Requires: `pisces` (S-expression evaluator, external)

## Location

Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/shellcrawl/`

## Source

[Swordsman/shellcrawl](https://github.com/Swordsman/shellcrawl)

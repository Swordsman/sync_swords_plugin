# combo-vfs

Filesystem analysis and monitoring tools.

## Tools

### tree-abstract
Collapses UUID/hash/timestamp-named siblings in a directory tree into abstracted groups. Makes large messy directory structures legible.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/combo_vfs/tree_abstract.py <path>
```

### fuse-watcher
Transparent FUSE I/O passthrough logger — monitors all filesystem operations on a target path.

```bash
# Start monitoring
${CLAUDE_PLUGIN_ROOT}/scripts/combo_vfs/start_daemon.sh <target-path>

# Check status / stop
${CLAUDE_PLUGIN_ROOT}/scripts/combo_vfs/status.sh
${CLAUDE_PLUGIN_ROOT}/scripts/combo_vfs/stop_daemon.sh
```

## When to use

- **tree-abstract**: Navigating unfamiliar directory trees with many UUID/hash-named files. Collapses noise into recognizable patterns.
- **fuse-watcher**: Auditing what's reading/writing to a directory. Requires FUSE.

## Status

These are standalone tools from a larger (concept-phase) SQLite-backed VFS project. Only tree-abstract and fuse-watcher are working tools today.

## Location

Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/combo_vfs/`

## Source

[Swordsman/combo-vfs](https://github.com/Swordsman/combo-vfs)

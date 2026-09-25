# tree-sprawler

Two structural analysis CLIs for navigating unfamiliar data.

## Tools

### json-ruleset
Infers a minimal discriminator decision tree from a JSON/JSONL corpus. Finds the fewest field checks needed to distinguish record types.

```bash
python3 -m tree_sprawler.json_ruleset.cli <source> [--max-depth 5] [--min-coverage 0.1] [--max-records 50000]
```

### tree-probe
Profiles filesystem trees: clusters filenames, detects repeating structural units, identifies relational patterns (UUIDs as primary keys, sibling files as columns).

```bash
python3 -m tree_sprawler.tree_probe.cli <path> [--max-depth 5] [--min-support 3]
```

## When to use

- **json-ruleset**: Before writing code that parses an unfamiliar JSON export. Shows which fields distinguish record types and their coverage/samples.
- **tree-probe**: Before navigating an unfamiliar directory tree (session logs, data exports). Shows repeating patterns and structural units.

## Location

Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/tree_sprawler/`

Both tools are stdlib-only Python — no dependencies.

## Source

[Swordsman/tree-sprawler](https://github.com/Swordsman/tree-sprawler)

# sync_swords_plugin

Self-syncing plugin carrying aimpack, winnow, and context-window-washing skills.

## Repository conventions

- Solo maintainer repo. No other contributors. Never watch PRs for CI or review activity — just push and merge.
- No CI pipeline. No tests to run.
- Plugin version lives in `.claude-plugin/plugin.json`.

## Skill sources

Skills are copied from upstream repos and kept current via the plugin's auto-sync mechanism:

| Skill | Upstream repo | Upstream path |
|---|---|---|
| aimpack | Swordsman/aimpack | SKILL.md + references/ + scripts/aimpack.py |
| winnow | Swordsman/winnow | winnow-spec-v0.2.md (distilled into SKILL.md) |
| context-window-washing | Swordsman/cbtdag | skill/references/wash.md (packaged as SKILL.md) |
| sync | (native) | this repo's own sync machinery |

## Layout

```
.claude-plugin/          plugin manifest + marketplace config
hooks/hooks.json         SessionStart hook (auto-sync gate)
scripts/sync.py          self-sync engine (stdlib-only Python)
scripts/aimpack.py       aimpack CLI tool
skills/aimpack/          aimpack skill + references/
skills/winnow/           winnow skill
skills/wash/             context-window-washing skill
skills/sync/             sync skill
```

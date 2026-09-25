# sync_swords_plugin

Self-syncing plugin carrying 26 skills across agent tooling, session management, process supervision, design incubation, AI CLI coordination, and context management.

## Repository conventions

- Solo maintainer repo. No other contributors. Never watch PRs for CI or review activity — just push and merge.
- No CI pipeline. No tests to run.
- Plugin version lives in `.claude-plugin/plugin.json`.

## Skill sources

Skills are copied from upstream repos and kept current via the plugin's auto-sync mechanism:

| Skill | Upstream repo | Upstream path |
|---|---|---|
| taskdagger | Swordsman/cbtdag | skill/ (full skill directory + references/) |
| littlewing | Swordsman/flight-recorder | scripts/ (littlewing.py, explode.py, backends/, formats/) |
| ucf | Swordsman/universal-context-format | ucf_adapter_*.py, ucf_cross_format.py, schema/ |
| aimpack | Swordsman/aimpack | SKILL.md + references/ + scripts/aimpack.py |
| winnow | Swordsman/winnow | winnow-spec-v0.2.md (distilled into SKILL.md) |
| context-window-washing | Swordsman/cbtdag | skill/references/wash.md (packaged as SKILL.md) |
| hearthphoenix | Swordsman/hearthphoenix | hearthphoenix/ package + readme-docs/ + examples/ |
| provider-library | Swordsman/provider-api-library | skills/deepseek-api/ + providers/ docs |
| deepseek-api | Swordsman/provider-api-library | skills/deepseek-api/ (curated skill) |
| xylem | Swordsman/xylem | scripts/ + src/xylem_server.py + src/xylem/ |
| tree-sprawler | Swordsman/tree-sprawler | tree_sprawler/ package (json_ruleset + tree_probe) |
| io-shield | Swordsman/io-shield | io_shield.py |
| squishyatoms | Swordsman/squishyatoms | context_atom.py + CONTEXT_ATOM_TIERS.md |
| robody | Swordsman/robody | robody.py, robody_memory.py, context_atom.py |
| pie | Swordsman/pie | pie.py, agent.py, mimepack.py |
| futurenotes | Swordsman/futurenotes | daemon.py |
| shellcrawl | Swordsman/shellcrawl | vfs.py, session.py, builtins.py, shell/, worlds/, explore.py |
| combo-vfs | Swordsman/combo-vfs | tree-abstract.py, fuse_watcher/ |
| design-incubator | Swordsman/code-combo-home | design-phase project catalog (18 projects) |
| term-capture | Swordsman/term-capture | ai_hypervisor/ package + mesh scripts |
| context-clone | Swordsman/code-combo-home | .agents/skills/context-clone/ (needs refactoring) |
| delegate-fileread | Swordsman/code-combo-home | .agents/skills/delegate-fileread/ (needs refactoring) |
| delegate-research | Swordsman/code-combo-home | .agents/skills/delegate-research/ (needs refactoring) |
| token-counter | Swordsman/code-combo-home | .agents/skills/token-counter/ (needs refactoring) |
| context-hygiene | Swordsman/code-combo-home | .knowledge/skills/context-hygiene/ (needs refactoring) |
| sync | (native) | this repo's own sync machinery |

## Layout

```
.claude-plugin/          plugin manifest + marketplace config
hooks/hooks.json         SessionStart hook (auto-sync gate)
scripts/sync.py          self-sync engine (stdlib-only Python)
scripts/aimpack.py       aimpack CLI tool
scripts/multiedit.py     multiedit batch read/write tool
scripts/taskdagger-cli.py  taskdagger DAG CLI
scripts/littlewing/      session flight recorder + context bridge
scripts/ucf/             universal context format adapters
scripts/hearthphoenix/   process supervisor package + examples
scripts/xylem/           agent terminal substrate
scripts/tree_sprawler/   json-ruleset + tree-probe analysis CLIs
scripts/io_shield.py     file write-locking + integrity
scripts/context_atom.py  multi-tier knowledge compression
scripts/robody/          context-window mirroring harness
scripts/pie/             procedural inference emulator
scripts/futurenotes_daemon.py  session FutureNotes extractor
scripts/shellcrawl/      sandboxed virtual shell
scripts/combo_vfs/       filesystem analysis tools
scripts/provider_download.py  provider doc re-scraper
scripts/term_capture/    AI CLI hypervisor + ai-coop + peer mesh
skills/taskdagger/       taskdagger skill + references/
skills/littlewing/       littlewing skill
skills/ucf/              UCF skill
skills/aimpack/          aimpack skill + references/
skills/winnow/           winnow skill
skills/wash/             context-window-washing skill
skills/sync/             sync skill
skills/hearthphoenix/    hearthphoenix skill + references/
skills/provider-library/ provider library umbrella skill
skills/deepseek-api/     deepseek API skill + references/
skills/xylem/            xylem skill
skills/tree-sprawler/    tree-sprawler skill
skills/io-shield/        io-shield skill
skills/squishyatoms/     squishyatoms skill + references/
skills/robody/           robody skill
skills/pie/              pie skill + references/
skills/futurenotes/      futurenotes skill
skills/shellcrawl/       shellcrawl skill
skills/combo-vfs/        combo-vfs skill
skills/design-incubator/ design-phase project catalog
skills/term-capture/     AI CLI hypervisor skill + references/
skills/context-clone/    subagent context cloning (needs refactoring)
skills/delegate-fileread/  delegated file reads (needs refactoring)
skills/delegate-research/  delegated research (needs refactoring)
skills/token-counter/    token estimation + script (needs refactoring)
skills/context-hygiene/  session health diagnostics (needs refactoring)
```

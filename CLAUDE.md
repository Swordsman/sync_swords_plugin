# sync_swords_plugin

Plugin with 35 skills for agent tooling, session management, process supervision, design incubation, AI CLI coordination, and context management. Supports auto-update via `SWORDS_AUTO_SYNC=1`.

## Repository conventions

- Solo maintainer repo. No other contributors. Never watch PRs for CI or review activity — just push and merge.
- No CI pipeline. No tests to run.
- Plugin version lives in `.claude-plugin/plugin.json`.
- `gh pr create`/`gh pr merge` fail here (GraphQL is blocked in Claude Code sessions): open and merge with REST, `gh api repos/Swordsman/sync_swords_plugin/pulls -f base=main -f head=BRANCH ...` then `gh api -X PUT .../pulls/N/merge`.
- PRs target `main` explicitly (`base: main`). After merging, check that `main` contains the PR's head commit (`git merge-base --is-ancestor HEAD_SHA origin/main`). PR #6 (2026-11-05) was opened against PR #5's branch, merged there, and never reached `main`, so neither account's plugin updated.

## Skill sources

Skills are copied from upstream repos and kept current via the plugin's update mechanism:

| Skill | Upstream repo | Upstream path |
|---|---|---|
| taskdagger | Swordsman/cbtdag | skill/ (full skill directory + references/) |
| littlewing | (native) | developed here; Swordsman/flight-recorder was only a log stash |
| ucf | Swordsman/universal-context-format | ucf_adapter_*.py, ucf_cross_format.py, schema/ |
| aimpack | Swordsman/aimpack | SKILL.md + references/ + scripts/aimpack.py |
| winnow | Swordsman/winnow | wno.py, sexpr.py, fold.py, frontier.py, digest.py, basis.py, query.py, winnow.py, merge.py, split.py, mega-fold.py, term-table.py, ds, *.json, demo-deltas.wno, tests/ (to scripts/winnow/); winnow-spec-v0.2.md, docs/hash-ids.md, ds-guide.md (to skills/winnow/references/; spec also distilled into SKILL.md) |
| context-review | Swordsman/cbtdag | skill/references/wash.md (packaged as SKILL.md) |
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
| sync | (native) | this repo's own update machinery |
| drone_uav | (native) | scripts/drone_uav.py: code-piloted drones (inference-API offload) |
| taught_patterns | (native) | engineering patterns Joe has taught; add new ones the day he teaches them |
| session-map | (native) | skills/session-map/ (SKILL.md, references/, design/, scripts/ with dsx.py, pipeline.py, segments.py, stage2.py and tests); from session 32131678 |
| question-library | (native) | skills/question-library/ (SKILL.md plus the whole directory); from session 32131678 |
| jev-toolkit | (native) | skills/jev-toolkit/ (SKILL.md, scripts, references/ including typesafe-docs/); from session 32131678 |
| ablation-templates | (native) | skills/ablation-templates/ (SKILL.md plus one more file); from session 32131678 |
| arc-agents | (native) | skills/arc-agents/ (SKILL.md plus one more file); from session 32131678 |
| intent-map | (native) | skills/intent-map/ (SKILL.md, scripts/intentmap.py + test, examples/); from session 32131678 |
| memory-structuring | (native) | skills/memory-structuring/ (SKILL.md + references/why, viability, syntax, procedures); opt-in, generic, from session 32131678 |
| lsdb | (native) | scripts/lsdb/ package (ids, transport, reads, writes, cli + tests), skills/lsdb/ (SKILL.md, assets/store.html); adapted from the live-skills bundle's lsdb.py, session 32131678 |

## Layout

```
.claude-plugin/          plugin manifest + marketplace config
hooks/hooks.json         SessionStart hook (update check gate)
scripts/sync.py          update engine (stdlib-only Python)
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
scripts/robody/          context state synchronization harness
scripts/pie/             procedural inference emulator
scripts/futurenotes_daemon.py  session FutureNotes extractor
scripts/shellcrawl/      sandboxed virtual shell
scripts/combo_vfs/       filesystem analysis tools
scripts/provider_download.py  provider doc re-scraper
scripts/term_capture/    AI CLI coordination + peer mesh
scripts/drone_uav.py     code-piloted drones (bundle/run/wait/apply)
scripts/winnow/          winnow fold, orchestrator, merge/split tools + tests
scripts/lsdb/            artifact-db read/write package (run as python3 scripts/lsdb) + tests
skills/taskdagger/       taskdagger skill + references/
skills/littlewing/       littlewing skill
skills/ucf/              UCF skill
skills/aimpack/          aimpack skill + references/
skills/winnow/           winnow skill + references/
skills/wash/             context review skill
skills/sync/             sync skill
skills/taught_patterns/  patterns Joe has taught (growing library)
skills/drone_uav/        code-piloted drones: offload heavy work to inference APIs
skills/session-map/      map a long session: per-turn maps, winnow logs, arcs, reconcile; dsx.py DeepSeek client with cost tracking
skills/question-library/ content-free diagnostic questions, debrief loop, pre-commit check
skills/jev-toolkit/      cheap typed judgments from TypeSafe Jev (jevask, jevbatch) plus scout web research
skills/ablation-templates/ sentence-to-template method with meaning-invariant slot contracts
skills/arc-agents/       arc-per-subagent conversation routing with a want-ads board
skills/intent-map/       intent maps from one sexpr: static column PNG + interactive force graph, unmet needs flagged
skills/memory-structuring/ opt-in memory structuring: trigger descriptions, !! / ?! markers, sweeps (asks the user first)
skills/lsdb/             lsdb manual + store page template: artifact databases from code, no per-I/O tokens
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
skills/term-capture/     AI CLI coordination skill + references/
skills/context-clone/    subagent context cloning (needs refactoring)
skills/delegate-fileread/  delegated file reads (needs refactoring)
skills/delegate-research/  delegated research (needs refactoring)
skills/token-counter/    token estimation + script (needs refactoring)
skills/context-hygiene/  session health diagnostics (needs refactoring)
```

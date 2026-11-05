---
name: session-map
description: Map a long Claude session (or any chat log) so nothing is lost across compactions. DeepSeek builds per-turn summaries and winnow logs per compaction segment, which are then merged, grouped into arcs, and reconciled against the skills and notes the session produced. Includes dsx, a DeepSeek client with dollar cost tracking, a 24h I/O log and cache-miss tripwires. Use when recovering or mapping a session, turning a transcript into a winnow graph, auditing what a session decided against what got written down, checking what a compaction summary dropped, running per-message agents (each message its own small cached context), or calling DeepSeek from scripts with cost accounting.
---

# session-map

## Status
| part | state |
|---|---|
| `scripts/dsx.py` (DeepSeek client) | works: 36 tests. Costs in $ from usage x published rates, checked against the balance (measured once: calculated $0.036, balance dropped $0.04). Logs all I/O to `~/.dsx/io.jsonl`. Raises `MissedCacheError` when shared content isn't a prefix, or when an expected hit doesn't land; `accept_miss="reason"` overrides and logs the reason |
| `scripts/pipeline.py` (turn maps, winnows, validation, fixes) | works: run on 3 compaction segments + a Gemini log, all valid under winnow's `fold.py` |
| `scripts/stage2.py` (arcs, reconcile) | works: one run. The reconcile report needed human review: 3 of about 25 proposals were wrong and several stale |
| `scripts/compaction_drop.py` (what a compaction dropped) | works: run once on a real compaction (s2: 166 items from 179 findings). Chains `compaction_check.py` (Jev scores + DeepSeek Flash thinking on), `agent_check.py` (message agents) and `merge_dropped.py` (dedup by id groups, Jev-checked, never reworded). 17 tests |
| `scripts/msgagents.py` (message agents on the tree store) | works: 6 tests; one 571-agent broadcast, $0.39 at peak, cached prefix hit on every call after the first |
| segment building | manual (see below) |
| memory-file pass | not done |

## Procedure
1. **Capture first.** The harness rewrites the session JSONL at compaction and on reloads, dropping earlier turns (seen 2026-10-31 and 2026-11-03). littlewing's raw mode records the log after every reply and before every compaction; with its git sink pointed at flight-recorder the records survive container restarts. Rebuild any generation with `compaction_check.littlewing_snapshot('littlewing:SESSION[:gN]', DIR)` (default: the generation before the newest, i.e. the pre-compaction log). Without littlewing: copy the JSONL by hand; a pasted shared-chat copy is the last fallback.
2. **Segment** at each compaction. Prepend to each segment the summary that started it, or a note that it is lost. Save them as `seg/NAME.txt` under `$SESSION_MAP_DIR` (default: the current directory).
3. `python3 scripts/pipeline.py turns` makes per-turn summaries with Flash and Pro, using Joe's verbatim prompt: "1 sentence for each user turn, and one sentence for each assistant turn". Flash and Pro should agree on the turn boundaries.
4. **Default: one-shot.** `python3 segments.py`, then `pipeline.py winnow whole`. That's the spec plus the entire conversation in one call. Joe: no need to feed it in piecemeal; it just works. Per-segment winnows (`pipeline.py winnow s1 s2 s3`, then merge) are for when the conversation won't fit in one context, or for checking the one-shot against them. Either way, `pipeline.py winnow` uses Pro, thinking at max effort, no max_tokens, an empty system prompt, and the full winnow spec first in the user prompt. Then `pipeline.py validate`: code closes unbalanced forms and wraps bare frames in `add`. Then `pipeline.py fix` sends the remaining fold.py problems back to DeepSeek.
5. Merge with winnow's `merge.py`, joining via winnows, not raw text. Then `stage2.py arcs` and `stage2.py reconcile`.
6. **Review the reconcile report against the transcript before applying it.** It produces confident wrong claims.

## Rules learned
- **Cost is output.** On a cached Pro call, the 28k cached input cost about $0.0006 and the output about $0.035.
- **Cache units:** a full hit comes only on an earlier request's whole prompt, or on a prefix two earlier requests shared. Different thinking settings never share cache. See `references/deepseek-cost.md`.
- **Document first, instructions last**, so later questions reuse the cached document.
- **Charges post minutes late,** and the balance only resolves to $0.01. Reconcile batches, not single calls.

## Compaction drop check
`python3 scripts/compaction_drop.py LOG|littlewing:SESSION SUMMARY_JSONL --out DIR` writes `DIR/dropped.md`: each item verbatim, with the source message ids it came from. Measured on s2 (568 blocks): message agents flagged 171 and caught 48 of the 56 blocks DeepSeek thinking-on found; the union adds the rest. DeepSeek only returns duplicate-id groups and code assembles the list, so nothing is reworded; Jev checks each merge (it split 9 of 22 proposed groups). Thinking-off runs were dropped: they over-report, and non-thinking output stops at 8192 tokens unless `max_tokens` is set (dsx now sets it).

## Message agents
`msgagents.py`: system prompt (Joe's message-agent text) -> optional shared payload + prefilled ack -> the agent's message (+ the few before it) + prefilled ack = the agent id -> each question forks there, so an agent's trunk never grows. Shared material goes before every agent's own message so it caches once for all of them. `broadcast(agents, question, out_dir)` warms 2 calls (a prefix persists only once two requests share it), then runs in parallel; per-agent failures come back together as `BroadcastError`. The agent table records parent agent, status and superseded_by.

## Tree store
`dsx.py` stores every conversation as a tree in SQLite (`~/.dsx/dsx.db`: `node` = sha256(parent id, role, content), so identical histories share ids; `call` = model, thinking, usage, $, full reasoning). `dsx.py send PARENT_ID PROMPT_FILE OUT` (`-` for a new root) prints the reply's node id: send from it to continue, from any earlier id to fork. `call()` also records a root plus reply. The expected cached prefix is the deepest node on the request's chain that a call in the last 24h with the same model and thinking ended at or replied with; `postcheck` raises `MissedCacheError` if the hit doesn't land. Two earlier sibling requests that share a leading stretch (even mid-message) count toward the expected hit. `prefill PARENT_ID TEXT_FILE` adds an assistant node you wrote (`origin = 'authored'`, no call, no cost). `show NODE_ID`, `import` (loads `io.jsonl`, skips records without a response), `tree-report`.

## The tree store as a graph
`python3 scripts/dsxgraph.py [--root ID|PREFIX|AGENT_TAG] [--nodes 400] [--out FILE.json] [--store URL --slug NAME [--title T]]` draws a subtree of `~/.dsx/dsx.db` in the Intent Maps viewer (skills/intent-map: a doc with `kind: "graph"`, rendered by the same engine, no intent-map code). A node is one message; a root-to-node path is the prompt a call saw, so a fork is where calls shared a cached prefix and diverged. A call's request node holds the prompt side (tokens, cache hit and miss, hit rate, input cost) and its response node the output side (tokens, thinking tokens, seconds, output cost); the split uses `dsx.cost`, so the two add up to `call.usd`. Every node also carries what its whole branch spent (`spent`, `calls`, `size`) and a `priority` 0-5 (0 spent nothing; else a fifth each by branch spend). The default root is the largest one made in the last 14 days. Over `--nodes` the costliest branches stay (a call's response always comes with its request) and the rest fold into one `+N more branches` node per fork with their totals; the doc must stay under 250 KiB, so `--nodes` shrinks until it fits. Rulesets (`dsxrules.py`): cards read left to right by depth with role, tokens, cost, cache hit and model on each card, forks emphasised; nodes is a force layout where only forks and folds are labelled. Not done: the agent tree (`agent` table) as its own graph; `--root` accepts an agent tag and draws the subtree under that agent.

## Files
- `design/notes.md`: pipeline design, settings, and what the validator forced.
- `references/deepseek-cost.md`: cost measurement and caching rules.
- `scripts/`: `dsx.py`, `dsxgraph.py` (+ `dsxtree.py`, `dsxrules.py`), `pipeline.py`, `stage2.py`, `segments.py`, `compaction_check.py`, `agent_check.py`, `merge_dropped.py`, `compaction_drop.py`, `msgagents.py`, `paths.py` (finds jev-toolkit, littlewing and the plugin root; env vars `JEV_TOOLKIT`, `LITTLEWING_DIR`, `SYNC_SWORDS_PLUGIN`, `COMPACTION_RUNS` override), and a `test_*.py` per module. `stage2.py`'s document list and `segments.py`'s transcript paths are specific to Joe's container; adjust them before reuse.

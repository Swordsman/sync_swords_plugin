---
name: session-map
description: Map a long Claude session (or any chat log) so nothing is lost across compactions. DeepSeek builds per-turn summaries and winnow logs per compaction segment, which are then merged, grouped into arcs, and reconciled against the skills and notes the session produced. Includes dsx, a DeepSeek client with dollar cost tracking, a 24h I/O log and cache-miss tripwires. Use when recovering or mapping a session, turning a transcript into a winnow graph, auditing what a session decided against what got written down, or calling DeepSeek from scripts with cost accounting.
---

# session-map

## Status
| part | state |
|---|---|
| `scripts/dsx.py` (DeepSeek client) | works: 11 tests. Costs in $ from usage x published rates, checked against the balance (measured once: calculated $0.036, balance dropped $0.04). Logs all I/O to `~/.dsx/io.jsonl`. Raises `MissedCacheError` when shared content isn't a prefix, or when an expected hit doesn't land; `accept_miss="reason"` overrides and logs the reason |
| `scripts/pipeline.py` (turn maps, winnows, validation, fixes) | works: run on 3 compaction segments + a Gemini log, all valid under winnow's `fold.py` |
| `scripts/stage2.py` (arcs, reconcile) | works: one run. The reconcile report needed human review: 3 of about 25 proposals were wrong and several stale |
| segment building | manual (see below) |
| memory-file pass | not done |

## Procedure
1. **Capture first.** Copy the session JSONL to a safe folder before anything else. A reload or compaction can rewrite it and drop earlier turns (seen 2026-10-31). A pasted shared-chat copy of the full conversation is a fallback.
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

## Files
- `design/notes.md`: pipeline design, settings, and what the validator forced.
- `references/deepseek-cost.md`: cost measurement and caching rules.
- `scripts/`: `dsx.py`, `test_dsx.py`, `pipeline.py`, `stage2.py`. `stage2.py`'s document list and the winnow plugin path are specific to Joe's container; adjust them before reuse.

---
name: winnow
description: "Streaming semantic extraction for AI conversations. An s-expression delta protocol over a typed semantic graph — extract while the conversation happens; the log is the full graph, the fold grades it fire-to-ice by accessibility (what's prominent now vs what's in cold storage) and produces the working window you actually see. Use when maintaining a persistent semantic record of a conversation, extracting structured knowledge from dialogue, or when context window pressure demands bounded-context extraction instead of batch processing. Spec: https://github.com/swordsman/winnow"
---

# winnow v0.2

**Streaming semantic extraction for AI conversations.**
An s-expression delta protocol over a typed semantic graph. Extract while the conversation happens; the delta log *is* the graph. The fold grades every node fire-to-ice by how prominent and active it is in the current discussion, producing a prioritized working window — a subset of the graph ranked by accessibility, not the graph itself.

Named for what it does: separate grain from chaff. Signal becomes nodes; noise never gets extracted.

**Lineage.** Event-sourced graph (log is truth, graph is a view) — same lifecycle as aimpack's diff/compact/rewind, and a `.wno` log ships cleanly as an aimpack part. Status vocabulary echoes cbtdag (`proposed`/`frozen`). PENMAN/AMR proved s-expressions serialize semantic graphs well; winnow keeps the serialization instinct and replaces AMR's thousands of sentence-level frames with eight conversation-level ones. Term canonicalization is alias-table-based in v0.2, with anchor-relative embedding profiles (UEL) as the planned v2 identity engine.

Reference implementation: `${CLAUDE_PLUGIN_ROOT}/scripts/winnow/`. `fold.py` (zero dependencies) produces the tiered working window from the log; `winnow.py` orchestrates extraction. Full spec: `references/winnow-spec-v0.2.md`, authoritative over the code. These are copies; Swordsman/winnow stays the source.

## Architecture

Three layers: **Vocabulary** (closed frame set, closed edge set, open term registry), **Canonical form** (normalization rules R1-R12), **Procedure** (two-stage extract-loose / normalize-strict).

Core loop:
```
turns -> extractor (loose) -> normalizer (strict) -> delta -> log
               ^                                              |
               +---------- frontier digest <---- fold <-------+
```

The extractor never sees the whole transcript or the whole graph — only the frontier digest (the fold's fire/hot working window) plus new turns. Context stays bounded regardless of conversation length.

## Frames (closed set of 8)

| Frame | Captures | Statuses |
|---|---|---|
| `claim` | Descriptive assertion | `live` `corrected` `retracted` `superseded` |
| `def` | Term/concept introduction | `live` `deprecated` `superseded` |
| `question` | Open thread | `open` `answered` `dropped` `superseded` |
| `decision` | Commitment among alternatives | `proposed` `frozen` `superseded` `abandoned` |
| `constraint` | Requirement or preference | `live` `relaxed` `retired` `superseded` |
| `action` | Work item | `todo` `doing` `done` `blocked` `dropped` `superseded` |
| `artifact` | External referent | `live` `deprecated` `superseded` |
| `edge` | Typed relation between nodes | — |

## Edges (closed set of 8)

`supports`, `contradicts`, `supersedes`, `refines`, `answers`, `motivates`, `depends`, `about`.

## Delta protocol

```lisp
(delta :turn N
  (term ID :gloss "..." :aka ("..."))
  (add (FRAME ID PAYLOAD :anns...))
  (add (edge (ETYPE SRC DST)))
  (update ID :key val ...)
  (supersede NEW OLD :conf X)
  (merge LOSER WINNER)
  (del ID)
  (del (edge (ETYPE SRC DST))))
```

Delta ops: `add` inserts, `update` shallow-merges annotations, `supersede` sets OLD status + emits edge, `merge` rewrites refs + deletes LOSER, `del` hard-removes.

**File header.** A log may open with one `meta` form. Every key is optional, and a log without a header is a valid v0.1 log.

```lisp
(meta :winnow-version "0.2"
      :semantic-rep "registry-v0.1"
      :log-id "wno-YYYYMMDD-slug-4hex"
      :receives ("ANCESTOR-LOG-ID" ...)
      :profile (:tail 6 :fire-hops 1 :promotion-ttl 2 :widening-base 3))
```

`:receives` lists the ancestor logs this one inherits terms or context from, so a loader can spot a missing ancestor before trusting the graph. A term entry may carry `:canon "Wikipedia_title"` as a join key for cross-log merge. `(reach QUERY)` is an extractor request on the wire and is never written to a log.

**Comments carry nothing.** fold, merge and mega-fold drop `;` comments. Put content in nodes, edges and string literals. A comment may only repeat what the graph already holds.

## Annotations

Fixed key order: `:status :conf :strength :by :src :time :modal :neg`. `:src` and `:by` are required.

## Normalization rules (R1-R12)

Same meaning -> same form. Terms -> canonical ids (R1), one proposition per node (R2), fixed slot order (R3), tense/modality/polarity -> annotations (R4), passive -> active (R5), verb nominalization (R6), fixed annotation order (R7), normalizer-only ids (R8), no synonym relations (R9), rhetoric unwrapped (R10), restatement dedup (R11), number normalization (R12).

## Procedure

**Trigger policy:** emit a delta every exchange by default; per turn when stakes are high. Bulk ingestion: checkpoint per document, never per batch.

**Signal policy:** never extract phatic content, filler, restatements, hedging-as-texture, meta-chatter. Stance toward reference material is a first-class extraction target.

### Extractor prompt (stage A)

> You're taking working notes on a live conversation. You get the note graph so far (live frontier) and the newest turns. Jot what changed as delta ops. Capture every commitment, correction, requirement, open thread. When someone's joking, keep the payload, drop the joke. When someone takes a position on material, note the stance. Skip restatements. Attribute everything. Unsure? Include with low `:conf`.

### Normalizer prompt (stage B)

> Apply R1-R12. Unknown surface term -> nearest registry id, else mint kebab-case + `:new`. Candidate whose canonical payload exists -> drop (R11) unless status differs -> `update`. Assign ids serially per frame.

## Tiers — the fold as working window (v0.2)

The fold grades every node in the graph by how accessible it needs to be right now. The result is a subset — the immediate context window — not the graph itself. Nothing in the log is ever forgotten; tiers grade how expensive it is to bring back.

Four tiers: **fire** (last exchange + forward projection, full rendering), **hot** (live constraints, proposed decisions, open questions, active actions, recent tail), **warm** (dormant nodes edge-held by a fire/hot resident, stub rendering), **cold** (everything else, count only).

**Demotion invariant:** a node demotes only while no resident node holds an incident edge to it. Clusters detach as units — temperature is a graph property, not per-node scores.

**Resolution ladder:** fire (0) -> hot (1) -> warm widening (2) -> cold fold-replay (3) -> global KB (4) -> honest miss as open question (5). Most messages resolve at rungs 0-1 with zero added latency.

## Files

Code, data and tests are in `${CLAUDE_PLUGIN_ROOT}/scripts/winnow/`. Docs are in this skill's `references/`.

| File | What |
|---|---|
| `fold.py` | Parse, fold and validate a log; snapshot, frontier, digest, query, hash and concept views |
| `winnow.py` | Extraction orchestrator for the core loop, with the resolution ladder |
| `merge.py` | Cross-log merge on content-hash join keys |
| `split.py` | Cuts a valid sub-log out of a log by query, seed ids and hops |
| `mega-fold.py` | Merges every `.wno` under the current directory, folds the result, reports overlap |
| `term-table.py` | Prints a log's term registry as a table, with the files each term came from |
| `ds` | DeepSeek CLI. winnow.py's `deepseek` backend runs it from its own directory |
| `canon-map.json`, `junk-terms.json` | mega-fold inputs: external canon anchors, extraction-noise terms |
| `demo-deltas.wno` | The spec's demo extraction (§11). The tests read it |
| `tests/` | Unit tests |
| `references/winnow-spec-v0.2.md` | Full spec |
| `references/hash-ids.md` | Content-hash id design (v0.3 direction) |
| `references/ds-guide.md` | Operational notes for `ds` |

```bash
W=${CLAUDE_PLUGIN_ROOT}/scripts/winnow
python3 $W/fold.py LOG.wno                # stats + validation
python3 $W/fold.py LOG.wno --snapshot     # also print the canonical snapshot (full graph)
python3 $W/fold.py LOG.wno --digest       # v0.2 tiered window, fire to ice
python3 $W/fold.py LOG.wno --frontier     # v0.1 frontier digest
python3 $W/fold.py LOG.wno --query "frame=claim status=live by=user"
python3 $W/fold.py LOG.wno --upto N       # fold only the first N deltas
python3 $W/fold.py LOG.wno --hashes       # content-hash id table
python3 $W/fold.py LOG.wno --concepts     # terms by usage mass
python3 $W/fold.py LOG.wno --stale N      # open/proposed/doing nodes untouched for N deltas
python3 $W/fold.py LOG.wno --yield-curve  # per-delta metrics (TSV)
python3 $W/winnow.py transcript.txt --out log.wno --backend deepseek  # or anthropic, deepseek-anthropic
python3 $W/merge.py A.wno B.wno --out merged.wno
python3 $W/split.py LOG.wno --seed d3,q2 --hops 2 --out topic.wno
python3 $W/mega-fold.py --canon-map $W/canon-map.json --exclude-terms $W/junk-terms.json
python3 $W/term-table.py merged.wno
python3 -m unittest discover -s $W/tests
```

A clean fold reports `validation : OK` and prints no `status warnings` line. winnow.py reads transcripts where each turn opens with a `[tN speaker]` header line, e.g. `[t1 user]`. Its other flags are `--per-turn`, `--seed PRIOR.wno`, `--replay FIXTURE` (offline), `--no-llm-normalizer`, `--global-kb MEGA.wno` and `--re2`. The `anthropic` backend needs the `anthropic` package; `deepseek` needs `DEEPSEEK_API_KEY` and the `openai` package (see `references/ds-guide.md`).

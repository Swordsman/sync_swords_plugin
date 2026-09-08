---
name: winnow
description: "Streaming semantic distillation for AI conversations. An s-expression delta protocol over a typed semantic graph — extract while the conversation happens; the knowledge graph is a fold over the delta log. Use when maintaining a persistent semantic record of a conversation, extracting structured knowledge from dialogue, or when context window pressure demands bounded-context extraction instead of batch summarization. Spec: https://github.com/swordsman/winnow"
---

# winnow v0.2

**Streaming semantic distillation for AI conversations.**
An s-expression delta protocol over a typed semantic graph. Extract while the conversation happens; the knowledge graph is a fold over the delta log.

Named for what it does: separate grain from chaff. Signal becomes nodes; noise never gets extracted.

**Lineage.** Event-sourced graph (log is truth, graph is a view) — same lifecycle as aimpack's diff/compact/rewind, and a `.wno` log ships cleanly as an aimpack part. Status vocabulary echoes cbtdag (`proposed`/`frozen`). PENMAN/AMR proved s-expressions serialize semantic graphs well; winnow keeps the serialization instinct and replaces AMR's thousands of sentence-level frames with eight conversation-level ones. Term canonicalization is alias-table-based in v0.2, with anchor-relative embedding profiles (UEL) as the planned v2 identity engine.

Reference implementation: `fold.py` (zero dependencies), `winnow.py` (orchestrator). Full spec: `winnow-spec-v0.2.md` in the winnow repo.

## Architecture

Three layers: **Vocabulary** (closed frame set, closed edge set, open term registry), **Canonical form** (normalization rules R1-R12), **Procedure** (two-stage extract-loose / normalize-strict).

Core loop:
```
turns -> extractor (loose) -> normalizer (strict) -> delta -> log
               ^                                              |
               +---------- frontier digest <---- fold <-------+
```

The extractor never sees the whole transcript — only the frontier digest plus new turns. Context stays bounded.

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

Fold semantics: `add` inserts, `update` shallow-merges annotations, `supersede` sets OLD status + emits edge, `merge` rewrites refs + deletes LOSER, `del` hard-removes.

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

## Tiers — the immediate context window (v0.2)

Four tiers: **fire** (last exchange + forward projection, full rendering), **hot** (v0.1 frontier: live constraints, proposed decisions, open questions, active actions, recent tail), **warm** (dormant nodes edge-held by residents, stub rendering), **cold** (everything else, count only).

**Demotion invariant:** a node demotes only while no resident node holds an incident edge to it.

**Resolution ladder:** fire (0) -> hot (1) -> warm widening (2) -> cold fold-replay (3) -> global KB (4) -> honest miss as open question (5).

## Files

- `winnow-spec-v0.2.md` — full specification
- `fold.py` — reference fold (`--snapshot`, `--frontier`, `--digest`, `--query`, `--hashes`, `--upto N`)
- `winnow.py` — reference orchestrator
- `merge.py` — cross-log merge on content-hash join keys
- `docs/hash-ids.md` — content-hash id design (v0.3 direction)

# State Tracking Reference

Progress state tracks three layers: tasks, contracts, and chunks. The DAG JSON is immutable (describes work). State JSON is mutable (tracks execution).

## Task states

| State | Meaning |
|---|---|
| `pending` | Not started, not ready by either predicate |
| `ready` | Eligible for execution (predicate satisfied) |
| `in_progress` | Currently being executed |
| `completed` | Finished, outputs verified |
| `failed` | Failed after retries exhausted |
| `blocked` | Cannot proceed (failed dependency or broken contract) |
| `skipped` | Manually skipped (dependents still proceed) |
| `waiting_human` | Paused for human input/approval |
| `partial` | Some artifacts created, not fully complete |

## Task transitions

| From | Condition | To |
|---|---|---|
| `pending` | sequential: all deps completed | `ready` |
| `pending` | parallel: all edge contracts frozen | `ready` |
| `pending` | dependency failed or contract broken | `blocked` |
| `ready` | execution starts | `in_progress` |
| `ready` | human gate | `waiting_human` |
| `in_progress` | success | `completed` |
| `in_progress` | max retries | `failed` |
| `in_progress` | partial artifacts, then fail | `partial` |
| `in_progress` | retry | `ready` |
| `partial` | retry with partial context | `in_progress` |
| `failed` | manual retry | `ready` |
| `blocked` | blocker resolved | `ready` |
| `blocked` | manual override | `skipped` |
| `waiting_human` | human action complete | `ready` |
| `waiting_human` | manual override | `skipped` |
| any | manual skip | `skipped` |

## Contract states

| State | Meaning |
|---|---|
| `provisional` | Specified but not stable; consumers may draft, not finalize |
| `frozen` | Interface locked; safe for parallel implementation |
| `broken` | Spec error revealed; dependents require rework |

## Contract transitions

| From | Condition | To |
|---|---|---|
| `provisional` | Fixtures pass + stub generated + parties agree | `frozen` |
| `provisional` | Consistency check fails or spec error | `broken` |
| `frozen` | Integration verification reveals gap | `broken` |
| `broken` | Renegotiated | `provisional` |

## Chunk states

| State | Meaning |
|---|---|
| `pending` | Not started; boundary contracts not yet frozen |
| `building` | ≥1 member task in_progress |
| `verifying` | All members completed; running verification |
| `verified` | Composition and boundary conformance passed |
| `failed` | Verification failed |
| `blocked` | A child chunk's boundary contract broke; cannot proceed until renegotiated. Nested chunks only — see Nested chunk state rollup. |

## Chunk transitions

| From | Condition | To |
|---|---|---|
| `pending` | First member starts | `building` |
| `building` | All members completed | `verifying` |
| `building` | Member fails, no retry | `failed` |
| `building` | Child chunk's boundary contract breaks | `blocked` |
| `verifying` | All verification checks pass | `verified` |
| `verifying` | Any check fails | `failed` |
| `failed` | Retry after rework | `building` |
| `blocked` | Child boundary renegotiated and re-frozen | `building` |

## Nested chunk state rollup

Applies only to chunks with `sub_chunks` (see `chunks.md` → Recursive chunks).

- Parent's `building` → `verifying` requires ALL child chunks at `verified`. The parent's own `chunk_verification` cannot start until every child sub-DAG has completed its own three-phase execution.
- Parent → `blocked` if any child chunk's boundary contract (the one the parent itself depends on) transitions to `broken`. Resolves back to `building` once that boundary is renegotiated and re-frozen.
- A child's *internal* state changes — task retries, internal contract renegotiation, internal chunk failures that recover — never roll up. Only the child's own boundary-facing state (`verified` / its boundary `broken`) is visible to the parent. This is the upward-immutability invariant expressed as a state rule: the parent tracks child outcomes, not child mechanics.
- Parent's own verification (once entered) checks only the parent's own boundary contracts — see `executor.md` → Recursive execution.

## Readiness predicates

| Predicate | Condition | Used for |
|---|---|---|
| `parallel_ready` | All incoming edge contracts frozen | Parallel build (default in taskdagger) |
| `sequential_ready` | All upstream tasks completed | Integration verification, tdag compat |
| `hybrid` | Both predicates true | Tasks requiring both |

Task's `readiness_mode` field selects: `parallel`, `sequential`, or `hybrid`.

## Three execution gates

```
Phase 1: contract_gate    — all contracts validated and frozen
Phase 2: parallel_ready   — edge contracts frozen → task starts
         chunk_gate       — upstream chunks stubbed/verified → chunk starts
Phase 3: sequential_ready — all deps completed → integration verification
```

## State JSON schema

```json
{
  "dag_id": "string",
  "updated_at": "ISO 8601",
  "tasks": {
    "task_id": {
      "status": "pending|ready|in_progress|completed|failed|blocked|skipped|waiting_human|partial",
      "readiness_mode": "parallel|sequential|hybrid",
      "started_at": "ISO 8601 | null",
      "completed_at": "ISO 8601 | null",
      "attempts": 0,
      "error": "string | null",
      "output_summary": "string | null",
      "partial_artifacts": ["string"]
    }
  },
  "contracts": {
    "contract_id": {
      "maturity": "provisional|frozen|broken",
      "frozen_at": "ISO 8601 | null",
      "broken_at": "ISO 8601 | null",
      "broken_reason": "string | null",
      "stub_generated": false,
      "stub_path": "string | null",
      "fixture_results": {
        "last_run": "ISO 8601 | null",
        "passed": false,
        "failures": ["string"]
      }
    }
  },
  "chunks": {
    "chunk_id": {
      "status": "pending|building|verifying|verified|failed|blocked",
      "child_chunk_ids": ["string"],
      "started_at": "ISO 8601 | null",
      "verified_at": "ISO 8601 | null",
      "blocked_reason": "string | null",
      "verification_result": {
        "member_tests_passed": false,
        "internal_composition_passed": false,
        "boundary_conformance_passed": false,
        "interaction_tests_passed": false,
        "semantic_alignment_passed": false,
        "failures": ["string"]
      }
    }
  }
}
```

## Ephemeral environments and state durability

The state JSON is fully regenerable from `init` plus the commit history. Committing it on every task transition produces noise — a build with 98 tasks generates ~196 diffs of a file whose content can be re-derived at any time.

In an ephemeral environment (container that may be reclaimed), one of two strategies:

- **Commit on session boundaries only** — at the start and end of each executor session, not on every transition
- **Reconstruct on resume** — run `init` plus the freeze loop, then re-derive completion status from the commit history

Pick one and stay with it. Either is correct; the uncommitted middle ground — regenerable state that is neither committed nor reconstructable because nobody said which — is what forces ad-hoc calls when a container is about to be reclaimed.

## Backward compatibility

DAGs with no contracts and no chunks degrade to tdag behavior. All tasks default to `readiness_mode: sequential`.

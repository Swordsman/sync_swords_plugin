# Chunks Reference

A chunk is a connected subgraph of the task DAG assigned to one builder. Chunks bound the blast radius of failures and enable parallel execution via frozen boundary contracts.

## Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✓ | Unique kebab-case identifier |
| `name` | string | ✓ | Human-readable label |
| `members` | task_id[] | ✓ | All tasks in this chunk. Must form connected subgraph. Each task belongs to exactly one chunk. |
| `boundary_contracts` | contract_id[] | ✓ | Contracts crossing chunk boundary. Must be frozen before consuming chunks start. |
| `internal_contracts` | contract_id[] | ✓ | Contracts whose endpoints are both within this chunk. May remain provisional during build. |
| `sub_chunks` | chunk[] | opt | Nested chunks for large chunks. Same schema recursively. |
| `verification_task` | task_id | ✓ | ID of chunk_verification task. Not in `members` — it's a meta-task. |
| `quality_metric` | float | ✓ | `internal_count / (internal_count + boundary_count)`. Range [0,1]. Warn if < 0.5. |

## Invariants

- Every task belongs to exactly one chunk
- No task is unassigned
- Members form a connected subgraph
- Boundary contracts are classified correctly (≥1 endpoint outside chunk)
- Verification task exists and is not a member

## Quality metric

Chunking never changes a project's dataflow — the dependency edges are fixed by the problem. What chunking changes is which edges are *billable*: an edge inside a chunk costs nothing extra to specify, while the same edge crossing a boundary must be fully specified — type, units, sign, ownership, error paths — because that specification is what a contract *is*. Finer granularity lowers arrows-per-boundary but strictly increases total billable arrows. The metric below is the local decision function for whether a given cut is worth its cost — not just a health indicator to check after the fact.

```
quality_metric = internal_contracts / (internal_contracts + boundary_contracts)
```

| Value | Meaning |
|---|---|
| 1.0 | Fully self-contained, no external dependencies |
| ≥ 0.5 | Acceptable — more internal than external |
| < 0.5 | Warning — more interface than implementation. Consider merge or re-chunk. |
| 0.0 | All contracts are boundary — possibly too fine-grained |

### Split justification (normative)

A proposed split of chunk C into C1, C2 is justified only if both hold:
1. Both C1 and C2 keep quality_metric ≥ threshold
2. The new boundary contract's definition + fixtures costs less (implementation effort / token estimate) than the smaller of C1, C2's own implementation — the boundary must cost less than what it gates

Fails either check → reject the split; merge back or leave the existing cut in place. Dependency graphs have community structure: cuts at narrow waists are nearly free, cuts through dense cores produce wide, brittle contracts that fail check 2 immediately.

### Cache maturity relaxes the threshold

The replay cache amortizes boundary cost — a contract already fulfilled and battle-tested elsewhere costs near-zero to reuse. As the contract archive matures, previously-expensive boundaries become cheap, shifting optimal granularity finer over the ecosystem's lifetime. Early in a project or archive's life, favor coarser cuts (threshold ~0.5–0.7); as archive coverage grows, finer cuts become justified. See `SKILL.md` → Contract replay for the mechanism (hierarchical lookup makes fine internal contracts independently cacheable, which is what makes them cheap to create in the first place).

## Chunk state transitions

| From | Condition | To |
|---|---|---|
| `pending` | First member task starts | `building` |
| `building` | All members completed | `verifying` |
| `building` | A member fails with no retry path | `failed` |
| `verifying` | All verification checks pass | `verified` |
| `verifying` | Any check fails | `failed` |
| `failed` | Manual retry after rework | `building` |

## Chunk verification

The `chunk_verification` task runs after all member tasks complete. It checks:

1. **Member test suites**: every member task's full test suite passes (contract fixtures + unit tests). A member whose tests fail is not complete, regardless of fixture status.
2. **Internal composition**: all internal contracts satisfied by real implementations (not stubs)
3. **Boundary conformance**: all boundary contracts' fixtures pass against real implementations
4. **Cross-component interaction**: tests exercising real member components *together* — not just pairwise interfaces. Contracts verify each edge in isolation; interaction tests catch emergent effects between components that are individually correct.
5. **Semantic alignment**: members agree on the declared conventions. Components can be internally valid and mutually anti-symmetric (each self-consistent under an opposite interpretation) while passing every interface check. Verify convention-sensitive behavior end-to-end within the chunk.
6. **Quality metric**: has not degraded below threshold
7. **No undeclared boundaries**: no new boundary contracts added without freezing

Verification must pass before chunk outputs are exposed to consuming chunks.

Verification must state which pools it actually exercised. A check that routes around a pool (e.g., backend-only verification of a chunk containing both backend and frontend) proves nothing about the untouched pool. The verification result records per-pool coverage, and a pool not exercised is reported as **unverified**, not passing.

## Chunk readiness gate

Controlled by `contract_enforcement.chunk_gate` in the manifest (default: `contract`). A consuming chunk cannot start Phase 2 until its producing chunks satisfy the configured gate:

1. **`contract`** (default) — frozen boundary contracts published. Maximum parallelism.
2. **`stub`** — frozen boundary contract stubs published. Requires `stub_generation.enabled`.
3. **`verified`** — producing chunk fully verified. Serialises chunks.

All three require frozen boundary contracts. The difference is what chunk verification can claim afterward: `verified` tested against real implementations, `stub` against generated stubs, `contract` against specifications alone. The completion report records which gate each consuming chunk entered on.

See `executor.md` → Chunk gate for the operational rule. See `manifest.md` → Chunk gate for configuration.

## Blast radius

Internal failures (task retries, contract revisions, implementation rework) stay inside the chunk boundary. Consuming chunks built against frozen boundary stubs continue unaffected.

Only boundary contract failure propagates outward:
- If a boundary contract transitions to `broken`, consuming chunks that built against its stub must respond
- Response depends on manifest `contract_drift_policy`: `notify`, `halt`, or `continue`
- The consuming chunk's work is not necessarily wasted — only the boundary interface needs renegotiation

## Chunking defaults

- Default: one chunk per queue
- If queue has >5 subsystems: consider sub-chunks (one per subsystem) — evaluate against Split justification above, don't split on subsystem count alone
- User confirms before re-chunking

## Recursive chunks

Chunks nest via the `sub_chunks` field (schema above): a chunk can itself be a full sub-DAG, same schema, same rules, recursively. Two lenses on the same structure:

**Structural (orchestrator time)**: split a chunk into sub-chunks when doing so passes Split justification at the smaller scale — same test, smaller graph. Sub-chunks have their own boundary contracts (relative to their parent), their own verification task, their own quality metric. Recursion terminates when further splitting stops improving the local quality metric.

**Execution (build time)**: a chunk with `sub_chunks` executes as a recursive taskdagger project. The parent executor spawns a sub-executor scoped to that chunk's sub-DAG; from the sub-executor's perspective, the parent executor occupies Type 0 (commissions the work, receives the result) — the sub-executor never talks to the human. Standard three-phase execution runs inside, unmodified. See `executor.md` → Recursive execution for the verification-gate clause this implies.

**Upward-immutability invariant**: a frozen boundary contract is the recursion cut point. Renegotiation, contract-break, or drift *inside* a chunk never propagates upward past that chunk's own frozen boundary — the parent observes only the boundary's maturity state, never the internals producing it. This is what makes nesting safe: the parent never needs to understand a child's internal structure, only whether the interface it was promised still holds. See `state.md` → Nested chunk state rollup for the mechanical rule.

**Why recursion resolves the granularity tension**: coarse, frozen top-level boundaries buy parallelism — few, well-specified interfaces gate the biggest chunks of work. Arbitrarily fine, *provisional* internal contracts inside those boundaries buy diagnosis and reuse without freezing ceremony, because provisional contracts skip fixture-completeness and freeze review. The expensive thing was never fine-grainedness — it was freezing. Freeze wide at the parent boundary; subdivide freely inside it.

---
name: taskdagger
description: "Contract-Based Task DAG v2.0 (taskdagger). Structured project decomposition that enforces design-before-build, breaks projects into contract-bound modular components proven correct before integration, and unlocks parallel builds via frozen interface contracts. Consider offering this skill when the user intends to work on a project involving two or more code files, or any project that could benefit from modular design. Also appropriate when a user is struggling with code development, appears unfamiliar with structuring multi-component projects, or is already attempting a code project and seems out of their depth. Load when the user asks for it, when their agent config or preferences indicate it, or when they'd clearly benefit from structured project planning and decomposition."
---

# taskdagger v2.0

Contract freezing replaces dependency completion as the build readiness gate. Two builders work simultaneously against a frozen interface; neither waits for the other's implementation.

## Core architecture

```
design suite (mission + spec, on disk) → dag.json (contracts + chunks) → work orders (per-task .md) → implementations
```

Artifacts by preservation priority: design suite (irreplaceable) > fulfilled contracts (cache/replay value) > dag.json (regenerable from the suite).

## Phases and role routing

Detect which phase the user is in. Load only the reference file(s) for that phase.

| Phase | Signal | Role | Load | Notes |
|---|---|---|---|---|
| 0: Design | No design suite exists, or it needs review/completion | Type 1 (user-facing) | `design_phase.md`; `design_suite_chl.md` when writing companions | Mandatory. Six documents, always all six. Refuse to proceed without a solid suite. |
| 1: DAG assembly | Design suite ready, no dag.json yet | Type 2 preferred (fresh context); Type 1 in dedicated session if no subagents | `orchestrator.md` | High token I/O, one-shot. Don't carry assembly context forward. |
| 1.5: Dependency analysis | dag.json exists, pre-execution | Optional for planning; do it before a real build | `dependency_analysis.md` | Library/tooling recommendations, **and the runtime dependency closure someone has to own**. Skippable when the DAG is for planning or review only. Not skippable before dispatch: an unowned closure is what leaves a project unbuildable with every contract satisfied. |
| 2: Execution | dag.json exists, ready to build | Type 1 as executor; Type 2s as workers | `build_briefing.md` (before dispatch), `executor.md`, `work_order_template.md`; `distributed_execution.md` if workers run externally; `drone_execution.md` if using drone pilots; `worker_autonomy.md` on failures/temptation to intervene | Brief user on gameplan first. Executor generates self-contained work order .md per task. Workers receive only their work order. |
| 3: Verification | Chunks completing | Executor | `executor.md` (verification sections) | Per-chunk then whole-DAG. |
| 4: Retrospective | Post-execution or mid-execution at milestones | Executor emits; human/AI reviews | `aar.md` | Captures learning before context is lost. |

If phase is ambiguous, ask the user: "Do you have a design suite? A dag.json? Or are we starting from scratch?"

## Critical rules

- **The design suite is mandatory.** If absent, incomplete, or flawed: run Phase 0. Six documents — mission, spec, scenarios, walkthrough, CHL companions, aimpack — for every project, with no lightweight path. An hour of design saves weeks of debugging abandoned wreckage.
- **Never load full dag.json into worker context.** Use `taskdagger-cli.py` for surgical queries, or generate self-contained work orders.
- **Frozen contracts are immutable.** Changes require explicit renegotiation → `broken` state → re-validation.
- **Contracts require fixtures before freezing.** Minimum: 1 happy-path + 1 error-case.
- **Chunk verification gates output exposure.** A chunk's outputs are invisible to consumers until verification passes.
- **Blast radius is chunk-bounded.** Internal failures don't propagate; only boundary contract failures propagate.
- **Let black boxes be black.** The executor never does a worker's job — no micromanaging, no partial takeovers. Intervening damages isolation integrity and record-keeping and decimates the token budget. If intervention seems necessary, get user permission first; usually the answer is talk to the worker, reset the contract (a work order is just a .md and an empty folder), or retry with a different model/environment. Full doctrine: `worker_autonomy.md`.
- **Granularity follows the cut structure, not a global dial.** Split chunks where the dependency graph is narrow (few crossing edges); never split through dense regions. A proposed split is justified only if (a) both resulting chunks keep the internal/(internal+boundary) quality metric above threshold, and (b) the new boundary's contract plus fixtures is smaller than the smaller resulting chunk's implementation — otherwise the boundary costs more than it gates. Relax the threshold as the replay cache matures: cached, battle-tested contracts amortize boundary overhead, so finer cuts pay better over the ecosystem's lifetime.
- **Tests are part of implementation, never a separate task.** Contract fixtures verify interface compliance; unit tests verify internal correctness and semantic alignment. Neither substitutes for the other. A task is done when its full test suite passes. Scheduling and authorship are distinct: tests ship with the task, but who writes them is a dispatch decision. Where adversarial verification applies, the test author works from the contract alone, never seeing the implementation (see `executor.md` → Adversarial verification).
- **Replay never bypasses verification.** A contract-hash match proves interface equivalence, not semantic equivalence. Replayed artifacts still pass through chunk verification and integration testing.
- **Declare semantic conventions explicitly.** Units, signs, orientations, coordinate systems, index bases. Implicit conventions become coin flips per worker — components can be individually valid, pass every interface check, and be mutually anti-symmetric.
- **Phases end with a wash that runs clean** — on by default for design, DAG assembly and the executor; off by default for workers, whose fixtures and unit tests already gate them (`wash.*` in the manifest). Read the wash prompt and let the generation run; name every unsurfaced item in the context window, categorize into slots A/B/C, and address findings before the gate opens.
 Highest leverage immediately before contract freezing, where a miss becomes immutable. Full doctrine: `wash.md`.
- **Save contracts to disk post-build.** They have replay/cache value across projects.
- **Every message re-bills the full context window.** DAG assembly is huge I/O — do it in a disposable context (fresh Type 2 or dedicated session), not in your primary conversation.

## Contract replay

Before dispatching a work order, check if an identical contract has been fulfilled before.

Cache key: hash of (signature + invariants + fixtures + side_effects). If a verified implementation exists for that hash, run old implementation against new fixtures. If fixtures pass → skip the worker entirely. Zero work, zero tokens.

Lookup is hierarchical when chunks nest: try the composite (parent-boundary) contract hash first; on miss, look up the constituent child-contract hashes and assemble a partial warm start from whichever children hit. A coarse miss with fine hits still saves most of the build. Corollary: finer internal contracts increase expected cache mileage — each fulfilled sub-contract is independently reusable and battle-tested — which is the mechanism behind the maturity clause in the granularity rule.

Near-misses (same signature, similar fixtures, different invariants) → dispatch with previous implementation attached as warm start; worker patches rather than rebuilds.

Fulfilled contracts are language-portable once a universal semantic IR exists. A Python fulfillment can satisfy a TypeScript request if the IR hash matches and translation is available.

## Work orders

The executor generates a self-contained markdown file per task containing:
- Task description + acceptance criteria
- Provides-contracts (signatures, invariants, fixtures the worker must satisfy)
- Requires-contracts (stub paths or real implementation paths the worker builds against)
- Relevant chunk boundary context
- Operating mode (spec-only / validated / enforced)
- Nothing else. No DAG structure, no other tasks, no system state.

Workers pick up the file, implement, report done/stuck. Fully portable across harnesses, models, machines, time. Archivable and debuggable.

## Harness awareness

| Harness type | Who | Capabilities |
|---|---|---|
| Type 0 | Human/user | Decisions, approval, design input |
| Type 1 | Assistant (user-facing) | Conversation, spawns subagents if available |
| Type 2 | Subagent (worker) | Task execution, no direct user contact, ephemeral or persistent |

Phase 0 (design): must be Type 1 (requires user conversation).
Phase 1 (DAG assembly): Type 2 strongly preferred; Type 1 in fresh session if no subagents.
Phase 2 (workers): Type 2 per task. With contracts, workers don't need same harness, machine, or time.
If only Type 1 available: use separate conversations per large task to avoid context bloat.

## Key concepts (anchors)

- **Contract**: typed interface on a DAG edge. Maturity: provisional → frozen → broken. Frozen = safe to build against in parallel. Full spec: `contracts.md`.
- **Fixture**: executable golden example attached to a contract. Required before freezing. Full spec: `contracts.md`.
- **Chunk**: connected DAG subgraph assigned to one builder. Boundary contracts (frozen, cross-chunk) + internal contracts (may be provisional). Quality metric: internal/(internal+boundary). Chunks nest: a chunk may itself be a full sub-DAG with its own chunking, executed as a recursive taskdagger project by a sub-executor whose Type 0 is the parent executor. The parent's frozen boundary contract is the recursion invariant — internal renegotiation never propagates upward past a frozen boundary. Fine-grained internal contracts are cheap because provisional contracts skip the freezing ceremony. Full spec: `chunks.md`.
- **Stub**: auto-generated runnable implementation of a frozen contract. Lets parallel builders test against deps without waiting. Generated from signature + fixtures.
- **Readiness predicates**: `parallel_ready` (all incoming contracts frozen), `sequential_ready` (all upstream tasks done), `hybrid` (both). Full spec: `state.md`.
- **Design suite**: the six documents Phase 0 produces. Irreplaceable source of truth; everything else derives from it. The mission is authoritative for intent and the spec for mechanism — those two are what Phase 1 reads. Scenarios, the walkthrough and the CHL companions validate them and introduce nothing. Full spec: `design_phase.md`, `design_suite_chl.md`.
- **CHL companion**: formal structural companion to a prose document — every statement an addressable node, dependencies in adjacency matrices, an integrity report whose defect counts must be zero. Named for the Curry–Howard–Lambek correspondence. Validates its source: a claim it cannot represent is an ambiguity in the source. Full spec: `design_suite_chl.md`.
- **Semantic conventions**: authoritative domain interpretations (signs, units, orientations) declared in the design spec, carried in `metadata.conventions`, injected into every applicable work order. Defense against the stealth anti-symmetry failure class. Full spec: `design_phase.md`, `work_order_template.md`.

## Reference files

All files in `references/` are AI-optimized. Load only what's needed for the current phase.

| File | Content | Load when |
|---|---|---|
| `design_phase.md` | Design conversation protocol, the six-document suite, suite validity, completion criteria | Phase 0 |
| `design_suite_chl.md` | CHL companions: node model, gloss grammar, adjacency matrices, integrity report | Phase 0, writing or validating a companion |
| `design_suite_check.py` | Validates a design suite: companion integrity, node/section correspondence, coverage, staleness | Phase 0, before the wash (don't load source into context) |
| `orchestrator.md` | DAG assembly procedure, output schema, validation | Phase 1 |
| `executor.md` | Coordination protocol: three gates, phases, failure handling | Phase 2-3 |
| `executor_impl.md` | Python implementation guidance for building executor tooling | Only if building executor software |
| `work_order_template.md` | Schema/template for generating self-contained per-task worker files, incl. write-safety section | Phase 2 (executor generating work orders) |
| `build_briefing.md` | Pre-build gameplan protocol: waves, noteworthy jobs, pause points, user input | Phase 2, before first dispatch or resume |
| `worker_autonomy.md` | Black-box non-interference doctrine, failure diagnosis, reset/retry ladder | Worker fails, reports stuck, or executor tempted to intervene |
| `distributed_execution.md` | External environments: signaling, transfer, MIME packing, comm channels, self-containment | Any workers running outside the executor's environment |
| `drone_execution.md` | External model execution: roles, dispatch mechanics, withholding rule, accounting | Phase 2, when dispatching drone-piloted tasks |
| `parallelism.md` | What actually constrains parallelism, what's already solved (stubs), escape hatches | Questions about why something can't parallelize |
| `contracts.md` | Contract schema, lifecycle transitions, fixture format, stub rules | Reference, on demand |
| `chunks.md` | Chunk schema, verification protocol, blast radius, quality metric | Reference, on demand |
| `state.md` | Progress tracking schema, task/contract/chunk state transitions | Reference, on demand |
| `manifest.md` | Runtime config: enforcement mode, concurrency, stubs, drift policy | Reference, on demand |
| `dependency_analysis.md` | Library/tooling analysis, and assigning ownership of the runtime dependency closure | Phase 1.5 (optional for planning, not before a build) |
| `aar.md` | After-action report schemas, metric categories | Phase 4 / during execution |
| `wash.md` | Context window washing: the phase exit gate, the prompt, slot discipline | Ending any phase; before freezing contracts; before reporting done/stuck |
 | Ending any phase; before freezing contracts; before reporting done/stuck |
| `taskdagger-cli.py` | CLI tool for surgical DAG queries and mutations | Executor uses as tool (don't load source into context) |
| `washing_machine.py` | Multi-pass wash cycle machinery (cold storage) | Only when using `--multi-pass` mode (don't load source into context) |

| `multiedit.py` | Batch read and batch write across many files: block-addressed reads, marker-located spans, all-or-nothing writes | Any task editing more than one or two files (don't load source into context) |

## Operating modes

| Mode | Behavior | When |
|---|---|---|
| `spec-only` | Contracts advisory, honored by convention | AI-only workflows, no CLI needed |
| `validated` | Static validation of contracts/chunks before execution | Light tooling, catches structure errors |
| `enforced` | Full stub generation, fixture testing, automated chunk verification gates | Full parallel builds, maximum isolation |

## Communicating with users

If user asks "what is taskdagger/taskdagger?" → explain: structured project decomposition system where you describe a project, a thorough design phase captures all decisions, then the project gets decomposed into a contract-annotated task graph that enables safe parallel execution. Contracts freeze interfaces so multiple builders can work simultaneously without waiting for each other.

If user has never used this before → guide them to Phase 0 (design). Don't skip it.

If user says "I have a design spec" → that is document 2 of six. Verify it's solid and write the rest of the suite before proceeding to Phase 1. Check for completeness, ambiguities, missing decisions.

If user says "I have a dag.json" → verify it, then proceed to Phase 2.

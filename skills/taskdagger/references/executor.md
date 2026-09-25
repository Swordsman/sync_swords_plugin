# Executor Protocol

The executor consumes dag.json and coordinates three-phase execution. It does not plan the work (orchestrator) and does not do the work (workers). It manages phases, tracks state, dispatches work orders, and handles failures.

## Prerequisites

Before execution:
- dag.json exists and is validated
- State JSON initialized (all tasks `pending`, all contracts at their DAG-specified maturity, all chunks `pending`)
- Resource manifest configured (see `manifest.md`) — or defaults used
- CLI tool (`taskdagger-cli.py`) available for surgical DAG queries
- Work order output directory configured

Before dispatching the first wave into a pool, confirm a worker in that pool can import its dependencies and run its test command. It is one command, and it converts a late confusing failure into an early obvious one. Watch specifically for the silent skip: a missing dependency that crashes is self-reporting, but a test runner that finds no suite and exits zero produces a task reporting success with no coverage, which then passes chunk verification.

## Critical rules

Never load full dag.json into worker context. Use the CLI for surgical queries. Generate self-contained work orders per task (see `work_order_template.md`).

Never do a worker's job for it. Workers are black boxes; intervening damages isolation integrity, corrupts the replay archive, and decimates your token budget. If tempted, or when a worker fails or reports stuck: load `worker_autonomy.md` first.

The one exception is narrow and conditional: a mechanical fix to a *completed* task's artifact, when its worker is gone and the defect is blocking other tasks. Four conditions must all hold and the edit must be recorded as executor-authored. Read `worker_autonomy.md` → Sanctioned intervention before using it, not after.

Before first dispatch (and when resuming after a pause): brief the user on the gameplan — load `build_briefing.md`. If any workers will run in external environments, also load `distributed_execution.md` before dispatch.

## Recursive execution

A chunk with `sub_chunks` (see `chunks.md` → Recursive chunks) is executed by spawning a sub-executor scoped to that chunk's sub-DAG, running the same three-phase protocol internally. The parent occupies that sub-executor's Type 0.

Verification scope does not change with nesting:

- A parent chunk's `chunk_verification` checks the parent's own boundary contracts only — the ones this chunk exposes to *its* siblings/consumers. It does not re-run or re-check the nested internal contracts one level down; those were already verified at their own level, inside the sub-executor's own `chunk_verification`, before that sub-DAG reported back as complete.
- Nested internal contracts verify once, at the level they were frozen and built at, and never re-verify upward. This is the upward-immutability invariant in operational terms: re-verifying upward would mean the parent needs to understand child internals, which defeats the point of nesting.
- The parent's `verifying` state cannot be entered until every child chunk has reached `verified` (see `state.md` → Nested chunk state rollup). At that point the parent trusts the children's boundary conformance as given and checks only its own.

## Three-phase execution

### Phase 1: Contract verification

Before build begins, verify all contracts:
1. All boundary contracts are `frozen`
2. All frozen contracts have passing fixtures
3. Cross-contract consistency holds
4. Stubs generated for all frozen boundary contracts (in `enforced` mode)

If any boundary contract is `provisional`: halt and report. Resolution required before Phase 2.

### Phase 2: Parallel build

Main execution loop:

```
while tasks remain:
  1. Query parallel-ready tasks: `taskdagger-cli.py parallel-ready`
  2. Query chunk status: `taskdagger-cli.py chunk-status`
  3. For each ready task not yet dispatched:
     a. Check contract archive for replay hit (hash match)
     b. If hit: run previous implementation against current fixtures
        - If pass: mark task complete, skip worker dispatch — but the replayed
          artifact still goes through chunk verification and integration
          testing like any other implementation (hash match proves interface
          equivalence, not semantic equivalence; see work_order_template.md)
        - If fail, or origin project had different/absent conventions:
          dispatch with warm start (previous impl attached)
     c. If no hit: generate work order (see work_order_template.md)
     d. Dispatch work order to worker (Type 2 if available)
  4. Collect worker results (done/stuck)
  5. Update state: `taskdagger-cli.py complete/fail <task-id>`
  6. Check chunk transitions:
     - All members complete → run chunk_verification (if this chunk has sub_chunks, see Recursive execution — wait for all children `verified` first)
     - Verification pass → mark chunk `verified`, expose outputs
     - Verification fail → mark chunk `failed`, assess blast radius
  7. Check for contract drift (frozen contract broken by implementation)
     - Apply drift policy from manifest: notify / halt / continue
```

### Phase 3: Integration verification

After all chunks verified:
1. Switch to `sequential_ready` predicate
2. Run integration verification tasks (cross-chunk composition checks)
3. Verify boundary contracts against real implementations (not stubs)
4. Run cross-chunk interaction tests: real chunks composed together, exercising realistic end-to-end paths. Contracts prove each boundary in isolation; this is where emergent interplay effects surface.
5. Run cross-chunk semantic alignment tests: verify the declared conventions hold end-to-end. Chunks can each pass verification while interpreting a convention oppositely; only end-to-end execution against known-correct expected results eliminates that case.
6. Generate after-action report (see `aar.md`)

Reality is the final reviewer. Contracts and per-chunk tests encode what was anticipated; the integration phase exists because there is always something that wasn't. Its tests should set up realistic whole-system conditions with exactly one provably correct outcome, so that any misalignment — anticipated or not — registers as a failure.

### Integration gate

A tier with no task that composes its outputs cannot report complete. The executor either generates an integration task or reports the tier as **unverified** — in those words. Deferring every composition task to a later tier is a decomposition error, not a scoping choice; a tier whose stated purpose is to prove something needs the task that proves it.

Integration verification must state which pools it actually exercised. A check that routes around a pool proves nothing about that pool — the executor must not report a pool verified on a check that did not touch it.

**Visual acceptance.** A task producing or wiring UI carries a rendered-screenshot acceptance artifact. Contracts cannot express "it looks right," so something outside the contract system has to. The cheapest sufficient form: render in a real browser, capture a screenshot, and have a human or vision-capable model look at it once. The completion report cannot claim a UI pool verified without one.

## Work order dispatch

For each task to be dispatched:

1. `taskdagger-cli.py task {task_id}` — task details
2. `taskdagger-cli.py task-contracts {task_id}` — provides/requires contracts
3. `taskdagger-cli.py task-stubs {task_id}` — stub paths for dependencies
4. Compute contract hashes for provides-contracts
5. Check contract archive for replay hits
6. Generate work order .md file (schema in `work_order_template.md`)
7. Dispatch to worker

Workers report: "done" (with summary) or "stuck" (with blocker description).

## Adversarial verification

An available dispatch pattern: split the implementer from the test author. The test author writes against the contract, fixtures and acceptance criteria — never seeing the implementation.

A single agent writing both code and tests encodes the same misreading in both, and the suite goes green. Splitting them breaks the shared-mental-model failure. Measured result: splitting roles caught real bugs in 4 of 7 drone-piloted tasks, including an `AbortController` whose signal was never wired to the request — abort logic that looked correct and did nothing.

**The no-peeking property is the whole point.** A test author who sees the implementation reintroduces exactly the shared-mental-model failure the split exists to break.

**Where to apply it.** Not everywhere — it costs a second agent or model per task. The evidence points at the targets:

- Anything where a mechanism can be constructed-but-inert (lifecycle, cancellation, cleanup, signal wiring)
- Anything security- or ordering-critical
- Any task whose contract is semantically subtle rather than mechanically fixtured

**A cheap substitute where a full split is unaffordable.** Ask per test: "what would have to break for this test to fail, and is that reachable from the test's inputs?" One line of thought per test, catches the can't-fail class without a second agent.

**An independent verifier's probes carry the same error risk as the code under test.** A probe that fails against a task reporting green is a claim to check, not a defect to report. Validate the probe against the contract's own fixtures before believing it.

For drone-piloted tasks — an external model generating while a pilot writes tests independently — see `drone_execution.md`.

## Orchestration discipline

Six rules, not six subsystems. Each is a failure observed in a real build.

- **A brief that names files says how to read them.** Concatenate them in one shell call, then re-read individually only what needs close attention. A worker handed nineteen paths and no reading instruction will make nineteen calls.
- **Bind start to dispatch.** Marking a task `in_progress` and dispatching its worker is one action — or you reconcile in-progress tasks against live workers before each wave. A task in progress with a dispatch record is recoverable; one without is invisible.
- **Your own scheduling logic is build-critical.** Filtering or selection logic the executor writes for itself drives dispatch, so check it against the DAG before it runs: at minimum, verify the task set it selects exists and matches what you expected.
- **Harness status is not task status.** A worker killed by the environment may have produced working output; a worker that reported done may not have. Test before re-dispatching, and resume from the transcript wherever work survived.
- **Quarantine a dead worker's output.** Partial artifacts from a killed worker must not sit where repo-wide gates will collect them. Move them aside or scope the gate — otherwise the next verification is measuring debris.
- **A probe is not privileged.** A verification probe that fails against a task reporting green is a claim to check, not a defect to report. Validate the probe against the contract's own fixtures before believing it.

## Durability

Workers die mid-flight — sessions hit quota, containers get reclaimed, harnesses restart. Three rules and a compaction note.

**Checkpoint commits.** When workers are in flight and the environment is ephemeral, commit their output for durability. The commit message must state:

- That it is not a completion report
- Which tasks are in flight
- Per-artifact status: substantively complete but unverified, or in-flight snapshot only

Nothing is marked complete in executor state on a checkpoint. The distinction between "code is on disk" and "task is done" is the one thing a checkpoint must not blur.

**Recovering an unreported worker.** The artifact exists; the report does not. Re-dispatch against the same work order rather than adopting the output — a work order is a `.md` and an empty folder, and re-running is cheaper than verifying someone else's half-finished work. Where re-dispatch is clearly wasteful (the artifact is manifestly complete), the executor verifies independently and records it as executor-verified rather than worker-reported.

**Never mark complete what was not reported.** A worker that never reported may have produced working code. It may also have stopped mid-write. The output's presence on disk is not evidence of completion.

**Compaction.** The executor is the one long-lived role, and long-lived means compacted. After any compaction event, re-read state from disk rather than trusting carried context — a compaction summary's claims about build state are unverified, and each summary is written over the last. State lives on disk; context is a cache of it, not the source.

## Failure handling

### Task failure
1. Load `worker_autonomy.md` — ask the worker what went wrong before anything else; unexplained failures usually indicate a faulty contract, not a faulty worker
2. Check retry budget (from manifest or task metadata)
3. If retries remain: reset to `ready`, re-dispatch (consider a different model or environment per the autonomy ladder)
4. If `partial`: re-dispatch with partial context
5. If exhausted: mark `failed`, check downstream impact, and assess the contract itself for fault

### Chunk failure
1. Internal failure (member task): retry within chunk; consuming chunks unaffected
2. Verification failure: diagnose which check failed
   - Internal composition: rework within chunk, re-verify
   - Boundary conformance: boundary contract may need renegotiation → `broken`
3. Boundary contract broken: apply drift policy

### Contract drift
When a frozen contract transitions to `broken`:

| Policy | Action |
|---|---|
| `notify` | Log event, continue execution, flag for review |
| `halt` | Pause all consumers of this contract |
| `continue` | Log event, continue (consumers may fail at verification) |

## Chunk gate

Controlled by `contract_enforcement.chunk_gate` in the manifest (default: `contract`). A consuming chunk cannot start Phase 2 until producing chunks satisfy the configured gate:

- **`contract`** (default) — producing chunk's boundary contracts are frozen. Maximum parallelism; consumers build against contract specifications.
- **`stub`** — producing chunk's frozen boundary stubs are published. Requires `stub_generation.enabled`.
- **`verified`** — producing chunk reaches `verified` state. Strongest guarantee; serialises chunks.

This is a chunk-level gate, not task-level.

Each gate level determines what chunk verification can claim afterward. `contract` asserts boundary conformance against the specification but not against running code. `stub` asserts conformance against generated stubs. `verified` asserts conformance against real implementations. The completion report records which gate each consuming chunk entered on and states the resulting limit on its verification claims.

## CLI commands reference

### Queries
```
parallel-ready          — tasks ready for parallel build
sequential-ready        — tasks ready for sequential/integration
chunk-status            — all chunks with current state
contract-status         — all contracts with maturity
task <id>               — full task details
task-contracts <id>     — provides/requires contracts for a task
task-stubs <id>         — stub paths for a task's dependencies
contract <id>           — full contract details
stub <id>               — stub content for a contract
chunk <id>              — chunk details
chunk-members <id>      — tasks in a chunk
chunk-boundary <id>     — boundary contracts for a chunk
```

### Mutations
```
start <task-id>                      — mark in_progress
complete <task-id> "summary"         — mark completed
fail <task-id> "error"               — mark failed
freeze-contract <id> [--stub-path]   — freeze a contract
break-contract <id> "reason"         — break a contract
verify-chunk <id>                    — mark verified
fail-chunk <id> "reason"             — mark failed
expose-outputs <id>                  — expose verified chunk outputs
```

### Contract archive / replay
```
contract-hash [id]          — semantic hash(es); no id = all contracts
verify-hashes               — recompute all hashes, compare against stored contract_hash fields
archive-save <id>           — store fulfilled contract (--impl-ref, --work-order)
archive-lookup <id>         — replay check: exact → near-miss → hierarchical children
replay-report               — batch lookup across the whole DAG (use in build briefing)
archive-list                — all entries across the archive search path
archive-info <hash>         — full metadata for one entry
archive-reindex             — rebuild index.json from entry dirs (self-healing)
```
All accept `--json` for machine-readable output. Archive path: `--archive PATH` overrides; default is `{dag_dir}/.taskdagger/contract-archive`, with `$TASKDAGGER_ARCHIVE` searched as an additional read location (cross-project sharing). Lookup verdicts: `hit`, `hit_convention_mismatch` (treat as warm start), `partial_warm_start:n/m` (coarse miss, fine hits), `warm_start_candidate` (signature match only), `miss`.

### Environment
```
export TASKDAGGER_FILE=/path/to/dag.json    # default dag path
```

## Wash gates

Enabled by `wash.executor` in the manifest (default on). The executor's phases

are long-running and interleaved, so "end of phase" is anchored to artifact
boundaries rather than to the clock:

- Before a chunk verification passes — wash the chunk against its boundary contracts
- Before whole-DAG integration — wash the composition
- Before escalating anything to Type 0 — wash it first, so what you escalate is the real list

Each must run clean before the gate opens, with one exception: a wash that will
not converge is itself grounds for escalation, and escalating it does not require
first getting it clean. Carry the outstanding findings up as they stand. The rule
is "do not escalate an unexamined list", not "do not escalate until clean" —
otherwise the two rules deadlock each other.

See `wash.md`. Workers wash only when `wash.worker`
or a `per_task_overrides` entry enables it — default off, since fixtures and unit
tests already gate them objectively. Where it is on, the worker's wash is theirs:
re-washing a worker's task on their behalf is the interference
`worker_autonomy.md` prohibits, and where it is off, do not compensate by
washing their work yourself.


## Session handoff

The protocol produces disposable contexts — DAG assembly in a fresh session, workers that see one work order, executors that compact and continue — and every transition is a handoff. A fresh session begins at the project's live-state location and nowhere else.

**One live-state location per project.** A single place — named by convention — where "what to do next" lives. Anything outside it is reference or history. The recommended form is a directory whose subdirectories are states: an item's directory is its status (e.g. `todo/`, `doing/`, `done/`, `blocked/`), so no status field can disagree with its own contents and no index can fall out of date. A claimed item records who claimed it and when; a stale claim is reclaimable.

**README is not a status document.** It describes what the project is, for a reader who has never seen it. A `Status:` or `Next step:` line acquires an expiry nobody watches.

**A handoff declares its assumptions.** Date, the commit or state it describes, and what it expects to still be true. A reader who finds any assumption false treats the document as history and stops following it.

**Retirement is part of finishing.** A completed handoff is marked completed in the document itself. A finished handoff still phrased as an instruction is worse than no handoff — the next session follows it.

**Precedence footers.** Any document superseding another carries an explicit `> **Precedence:**` footer naming what it overrides.

**Artifacts must be reachable.** An AAR, a wash record, a design note that nothing links to does not exist for the next session. If it is worth writing, it is worth one line in the live-state document. When Phase 4 emits an after-action report (see `aar.md`), the live-state document gets a pointer in the same step.

**Cross-session references need a resolvable target.** "Described in another session" is not a pointer. If material lives in a session, the handoff records the session id and where its transcript is persisted — which is what the `.after-action-reports/<harness>/<UTC-timestamp>/` convention exists to provide.

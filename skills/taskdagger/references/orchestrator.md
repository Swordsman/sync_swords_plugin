# Orchestrator: Design Suite → Contract-Annotated DAG

Role: transform a completed design suite into a fully specified, contract-annotated, chunk-partitioned dag.json.

Prerequisite: a validated design suite — the mission statement and the design spec, consistent with each other (see `design_phase.md`). Do not proceed without one.

Only those two are normative here. The scenarios, the walkthrough and the CHL companions are validation artifacts: consult them when a spec claim reads ambiguously, never as a source of mechanism the spec omits. If they carry something the spec does not, the spec is incomplete — that is a finding to raise, not a gap to quietly fill from a companion.

Token note: this is high-I/O one-shot work. Run in a fresh Type 2 or dedicated session. Do not carry assembly context into other work.

## Initialization

Check what's available:
- Design suite present → proceed to decomposition
- tdag DAG JSON present → ask "migrate this to taskdagger?" → migration mode
- Neither → "provide a design suite or existing tdag DAG"

## Migration mode (tdag → taskdagger)

1. Ingest tdag structure; verify integrity (no cycles, valid IDs)
2. Add contracts to all edges: synthesize from output/input artifacts, mark all `provisional`
3. Add fixtures: ≥1 happy-path + ≥1 error-case per contract, based on acceptance criteria, mark `auto_generated: true`
4. Derive chunks: default one chunk per queue; sub-chunks if queue has >5 subsystems
5. Compute quality_metric per chunk
6. Freeze contracts where both sides clearly match; leave ambiguous ones `provisional`
7. Output migration report + taskdagger JSON

## Decomposition process

### Phase 1: Clarification (if needed)

Assess: enough info to decompose? If no, ask 2-3 specific questions. Max 3 rounds, then proceed with assumptions. Document assumptions in `metadata.assumptions`.

taskdagger-specific questions: known team/agent boundaries (→ chunking), pre-specified interfaces (→ early freezing), external API contracts (→ pre-frozen), renegotiation tolerance.

### Phase 2: Normalization

Extract from design spec:
- Epic: id (kebab-case), title, description (1-3 sentences)
- Queues (3-8 major workstreams): id, name, purpose, inputs, outputs, success_criteria, anticipated chunk mapping
- Semantic conventions: every declared domain interpretation (units, signs, orientations, coordinate systems, index bases, timezone/encoding assumptions, terms of art). Record in `metadata.conventions` as `{ id, statement, applies_to }`. If the design spec lacks a conventions section, derive candidates from the spec content and flag any ambiguity as a clarification question — do not silently guess. Conventions propagate into every work order touching their domain; a convention that stays implicit becomes a coin flip per worker. State `applies_to` explicitly rather than leaving it inferred: a convention with unclear scope is worse than an absent one, because it gets applied inconsistently rather than not at all. Before freezing, check the declared conventions against the contracts they touch — where they conflict one of them is defective, and `contracts.md` → Conventions vs contracts says which governs.

### Phase 3: Recursive decomposition

Queue → Subsystems (3-7) → Components (2-6) → Primitive tasks (3-10)

Task ID format: `(queue).(subsystem).(component)` — kebab-case, unique, immutable.

Primitive task criteria (all must hold):
1. Single coherent unit of work
2. Implementable without asking "what do you mean?"
3. Produces ≥1 tangible artifact
4. Acceptance criteria are testable

Each task specifies: inputs, outputs, input_artifacts, output_artifacts, dependencies (task IDs), acceptance_criteria, estimated_effort (relative_size: S/M/L, token_estimate), metadata.contracts.provides/requires.

Token estimates (implementation + its unit tests, since tests are part of every task): simple interface 500-800, CRUD endpoint 900-1400, complex logic 1400-2200, API integration 1200-1800, config/setup 300-500. Adjust for language verbosity.

### Phase 3.5: Testing strategy

Every implementation task must include unit tests. Contract fixtures verify interface compliance; unit tests verify internal correctness. These are complementary and neither substitutes for the other.

Contract fixtures ask: "does this component honor the agreed interface?"
Unit tests ask: "is reality behaving the way it should?"

Contracts have blind spots — they encode what was *anticipated*. Unit tests catch what wasn't anticipated, because a well-designed test doesn't check for specific failures; it verifies that the single correct state occurred, and any deviation (from any of infinite possible failure modes) registers as a failure.

Testing guidance to include in each implementation task:
- Tests must be included as part of the implementation, not as a separate task
- Prefer tests that set up realistic conditions with one provably correct outcome over tests that check for specific error cases
- Choose test conditions where alignment with the expected result requires *all* tested aspects to be correct simultaneously — maximizing failure mode coverage per test
- Test internal behavior that contracts don't cover: state transitions, side effects within components, interaction between internal sub-components, semantic alignment of assumptions
- Include semantic alignment tests: verify that the component's interpretation of domain concepts matches the documented interpretation (the "polarity problem" — everything can pass contract checks while being semantically inverted)
- Contract fixtures can be included in the test suite (they should be), but the test suite must go beyond contract fixtures

During decomposition, do NOT create separate "write tests" tasks. Tests are part of implementation. A task is not complete until its tests pass. The work order template enforces this.

Test path allocation: every task's `output_artifacts` must include an explicit test file path, allocated by the orchestrator alongside its implementation artifacts. Check for collisions across tasks — two tasks claiming the same artifact path (test or otherwise) is a decomposition error, detectable statically. Worked example: in Dragonglass, the scaffold task wrote to `tests/test_scaffold.py`, a declared artifact of the next task, forcing the executor to relocate 133 tests before dispatch.

Test scoping rule: a task's tests assert over the task's own artifacts, not over the repository at large. A test that scans a directory other tasks will write into is asserting about the future, and it will be wrong. Where a task genuinely owns a repo-wide invariant (e.g., a layout contract), it asserts the invariant — a superset check, a boundary check — not an exact manifest of current contents.

### Phase 4: Contract compilation

**4.1** Enumerate all edges. For each A→B: assign contract ID `contract:(A.id)→(B.id)`.

**4.2** Specify each contract:
- type_signature: output (what A produces), input (what B expects). Use domain language, not code syntax.
- invariants: properties that must hold on values crossing the edge
- side_effects: what A does besides returning (or `["none"]`)

**4.3** Add fixtures. Per contract: ≥1 happy-path, ≥1 error-case. Each fixture: label, input, expected_output or expected_error, optional notes.

**4.4** Mark all contracts `provisional`.

**4.5** Cross-contract consistency check:
- Adjacent contracts on same task: output type A→B must match input type A→B
- Shared artifacts: all consuming contracts agree on type
- Record inconsistencies as blocking issues

**4.6** Identify freeze candidates. Ready to freeze when: type_signature fully specified, passes consistency checks, has fixtures, both parties reviewed. Mark these `frozen`.

**4.6a** Flag external library references. Any contract whose signature names a non-stdlib symbol must record the library name and verified version before freezing is justified. Where the library is unavailable at assembly time, freeze as provisional-pending-verification and route verification to the first consuming task — with an explicit instruction to report `stuck` on API divergence rather than shim. See `contracts.md` → freeze requirements.

**4.7** Contract scope classification (after Phase 5): internal (both endpoints same chunk) or boundary (different chunks).

**4.8** A scaffold contract owns the **runtime dependency closure**, not merely the file that would hold it. `package.json` existing and empty satisfies a contract that names the path and leaves the project unbuildable. Enumerate the dependencies as a deliverable of the contract, so the gate can see the difference.

### Phase 5: Chunking

**5.1** Default: queue = chunk. Split if queue has >5 subsystems (ask user first).

**5.2** Assign every task to exactly one chunk via `metadata.chunk_id`.

**5.3** Classify contracts: internal or boundary based on chunk membership.

**5.4** Compute quality_metric per chunk: `internal_count / (internal_count + boundary_count)`. Target ≥ 0.5.

**5.5** If quality_metric < 0.5: warn, offer merge/re-chunk/override options. Don't re-chunk unilaterally.

**5.6** Boundary contracts must be frozen. Any provisional boundary contract = blocking issue. In `enforced` mode: blocks output. In `spec-only`/`validated`: flag and proceed.

### Phase 5.5: Integration placement

Every tier must contain at least one task that composes its outputs. Deferring all composition and QA tasks to a later tier is a decomposition error, not a scoping choice — a tier whose stated purpose is to prove something needs the task that proves it.

Where the tier contains UI, at least one task must render and visually verify the composed output. Contracts cannot express "it looks right"; a screenshot acceptance artifact is the minimum (see `executor.md` → Integration gate).

### Phase 6: Validation

Run all checks. Record findings for validation report.

| Check | What |
|---|---|
| Graph integrity | No cycles (task graph + chunk graph), valid IDs, ≥1 root, ≥1 terminal |
| Artifact flow | Every input_artifact sourced; warn on orphan outputs |
| Coverage | Every queue/subsystem has tasks; epic requirements mapped to tasks |
| Missing work | Error handling, tests, docs, deploy, security, logging |
| Artifact collisions | No two tasks claim the same artifact path (test paths included) |
| Effort sanity | Reasonable size distribution, nothing exceeds L |
| Contract completeness | Every edge has contract, every contract has fixtures, no TBD in frozen |
| Boundary freeze | All boundary contracts frozen (or flagged as blocking) |
| Cross-contract consistency | Adjacent pairs consistent, shared artifacts agree on type |
| Requirement coverage | Map requirements → tasks; record in metadata.coverage_map |

## Operating modes

| Mode | Boundary provisional | Stubs | Chunk verification specs | Default |
|---|---|---|---|---|
| `spec-only` | Noted, not blocking | Not emitted | Not emitted | No |
| `validated` | Flagged as blocking | Not emitted | Not emitted | Yes |
| `enforced` | Blocks output | Emitted per frozen contract | Emitted per chunk | No |

Enforced mode additionally emits:
- Stub specification per frozen contract (input type, hardcoded happy-path return, error-case raise, file path)
- Chunk verification task per chunk (boundary satisfaction, internal fixture pass, quality_metric check)

## Output format

Two parts in sequence:
1. **Validation report** (markdown): findings from Phase 6, contract/chunk status summary
2. **DAG JSON** (in code block): full specification

## DAG JSON schema

Top-level keys: `epic`, `queues`, `chunks`, `contracts`, `tasks`, `edges`, `metadata`.

### epic
```json
{ "id": "string", "title": "string", "description": "string", "mode": "spec-only|validated|enforced" }
```

### queues[]
```json
{ "id": "string", "name": "string", "purpose": "string", "inputs": ["string"], "outputs": ["string"], "success_criteria": ["string"], "chunk_id": "string" }
```

### chunks[]
```json
{
  "id": "string", "name": "string", "description": "string",
  "queue_ids": ["string"], "task_ids": ["string"],
  "boundary_contracts": ["contract_id"], "internal_contracts": ["contract_id"],
  "internal_contract_count": 0, "boundary_contract_count": 0,
  "quality_metric": 0.0, "quality_metric_status": "ok|warn|override",
  "readiness_gate": "string", "boundary_contracts_frozen": true
}
```

### contracts[]
```json
{
  "id": "string", "from": "task_id", "to": "task_id",
  "maturity": "provisional|frozen|renegotiating|violated",
  "scope": "internal|boundary",
  "type_signature": { "output": "string", "input": "string" },
  "invariants": ["string"],
  "side_effects": ["string"],
  "fixtures": [
    { "label": "string", "input": {}, "expected_output": {}, "expected_error": {}, "notes": "string", "auto_generated": false }
  ],
  "notes": "string"
}
```

### tasks[]
```json
{
  "id": "(queue).(subsystem).(component)", "queue_id": "string",
  "subsystem": "string", "component": "string",
  "name": "string", "description": "string",
  "inputs": ["string"], "input_artifacts": ["string"],
  "outputs": ["string"], "output_artifacts": ["string"],
  "dependencies": ["task_id"],
  "estimated_effort": { "relative_size": "S|M|L", "token_estimate": 0, "notes": "string" },
  "acceptance_criteria": ["string"],
  "metadata": {
    "requires_human_input": false, "can_run_in_parallel": true,
    "blocked_by_external_dependency": false,
    "chunk_id": "string",
    "contracts": { "provides": ["contract_id"], "requires": ["contract_id"] },
    "mode": "spec-only|validated|enforced", "notes": "string"
  }
}
```

### edges[]
```json
{ "from": "task_id", "to": "task_id", "contract_id": "string", "reason": "string" }
```

### metadata
```json
{
  "total_tasks": 0, "total_contracts": 0,
  "contracts_by_maturity": { "provisional": 0, "frozen": 0 },
  "contracts_by_scope": { "internal": 0, "boundary": 0 },
  "boundary_contracts_frozen": 0, "boundary_contracts_provisional": 0,
  "critical_path_task_ids": ["task_id"], "critical_path_task_count": 0,
  "coverage_map": [], "assumptions": ["string"],
  "conventions": [ { "id": "string", "statement": "string", "applies_to": ["queue_id or task_id or *"] } ],
  "mode": "spec-only|validated|enforced", "notes": "string"
}
```

## Exit gate: wash before freezing

Enabled by `wash.blueprint` in the manifest (default on). Assembly is not finished when the JSON validates. Run a wash over the

graph, the contracts, the chunk cuts and the declared conventions, and let it run
clean before any boundary contract is frozen. See `wash.md`.

Freezing is the highest-leverage wash point in the system: frozen contracts are
immutable by design, and a convention missed here becomes stealth anti-symmetry
at integration — every interface check green, components mutually incompatible.
After freezing, the same miss costs a `broken` state and a renegotiation.

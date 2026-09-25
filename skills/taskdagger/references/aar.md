# After-Action Reports

Capture learning during and after execution. Core insight: failed and abandoned projects contain the most valuable learning but are least likely to receive retrospective analysis. Generate reports incrementally so insights survive even when "after" never arrives.

## Report types

### Session report (frequent)
Trigger: session boundary (batch completed, explicit pause, chunk verified).
Scope: tasks and chunks touched this session.

```json
{
  "report_type": "session",
  "session_id": "uuid",
  "project_id": "string",
  "generated_at": "ISO 8601",
  "tasks_attempted": ["task_id"],
  "tasks_completed": ["task_id"],
  "tasks_failed": ["task_id"],
  "chunks_verified_this_session": ["chunk_id"],
  "contract_events": {
    "frozen": ["contract_id"],
    "broken": ["contract_id"]
  },
  "observations": {
    "what_went_well": ["string"],
    "what_went_poorly": ["string"],
    "unexpected_issues": ["string"],
    "contract_notes": ["string"]
  },
  "carry_forward": ["string"]
}
```

### Milestone report (periodic)
Trigger: chunk verified, queue completed, percentage threshold (25/50/75%).

```json
{
  "report_type": "milestone",
  "milestone_id": "string",
  "project_id": "string",
  "generated_at": "ISO 8601",
  "progress": {
    "total_tasks": 0, "completed": 0, "percentage": 0.0,
    "chunks_total": 0, "chunks_verified": 0
  },
  "contract_accuracy": {
    "contracts_frozen": 0, "contracts_broken": 0, "contracts_revised": 0
  },
  "parallelism_snapshot": {
    "max_simultaneous_chunks": 0,
    "tasks_that_ran_in_parallel": 0
  },
  "chunk_quality_vs_reality": {
    "chunk_id": { "predicted_quality_metric": 0.0, "blast_radius_when_failed": "string" }
  }
}
```

### Failure report (event-driven)
Trigger: task fails after retries, chunk fails verification, contract broken, critical path stalled.

```json
{
  "report_type": "failure",
  "failure_id": "uuid",
  "project_id": "string",
  "generated_at": "ISO 8601",
  "failure_type": "task_failure|chunk_verification_failure|contract_drift|semantic_misalignment",
  "convention_involved": "convention id, or null — for semantic_misalignment: which convention was missing/ambiguous/violated",
  "subject_id": "task_id or chunk_id or contract_id",
  "what_happened": "string",
  "root_cause_hypothesis": "string",
  "blast_radius": { "affected_tasks": ["task_id"], "affected_chunks": ["chunk_id"] },
  "recovery_path": "string",
  "prevention_suggestion": "string"
}
```

### Project completion report
Trigger: all chunks verified and integration verification passed.

```json
{
  "report_type": "completion",
  "project_id": "string",
  "generated_at": "ISO 8601",
  "summary": {
    "total_tasks": 0, "completed": 0, "failed_then_recovered": 0, "skipped": 0,
    "total_contracts": 0, "contracts_that_held": 0, "contracts_renegotiated": 0
  },
  "contract_accuracy_score": 0.0,
  "chunk_quality_retrospective": {
    "chunk_id": { "predicted_quality": 0.0, "actual_issues": "string" }
  },
  "parallelism_achieved": {
    "theoretical_max_parallel_chunks": 0,
    "actual_max_parallel_chunks": 0,
    "phase1_cost_vs_phase2_savings": "string"
  },
  "stub_accuracy": {
    "stubs_generated": 0, "stubs_that_matched_real": 0, "stubs_that_diverged": 0
  },
  "verification_coverage": {
    "pools_verified_in_composition": ["string — pools whose outputs were composed and tested together"],
    "pools_passing_tests_only": ["string — pools whose tasks pass individually but were never composed"],
    "pools_with_visual_acceptance": ["string — UI pools with rendered-screenshot acceptance artifacts"]
  },
  "semantic_alignment_retrospective": {
    "conventions_declared": 0,
    "misalignments_caught_at_chunk_verification": 0,
    "misalignments_caught_at_integration": 0,
    "conventions_that_should_have_been_declared": ["string — feed these back into future design phases"]
  },
  "key_learnings": ["string"],
  "recommendations_for_next_project": ["string"]
}
```

## taskdagger-specific metrics (beyond tdag)

| Metric | What it measures |
|---|---|
| Contract accuracy | How many contracts needed revision; orchestrator quality |
| Chunk quality retrospective | Did quality_metric predict actual blast radius? |
| Parallelism achieved | Theoretical vs actual parallel execution |
| Contract compilation cost | Phase 1 time vs Phase 2 savings; ROI |
| Stub accuracy | Did stubs match real implementations? Fixture quality measure |

## Design principles

- Capture early, capture often (don't wait for completion)
- Non-interfering (generated during natural breaks, async, lightweight)
- Structured for aggregation (consistent schema, queryable across projects)
- Context-preserving (enough detail to be useful months later)

## Wash records

Every wash cycle writes a record to `.taskdagger/wash/`. They are the only measured
data the system produces about its own gates, and nothing reads them yet.

Per cycle, the record holds: the phase, what was washed, the per-pass yield
sequence, every slot A finding with its rationale, everything binned to B and
why, everything left unresolved in C, and the pass the cycle ran clean on.

Worth pulling into an AAR:

- **Pass counts and yield shapes by phase.** Every wash threshold (`wash.*` in
  the manifest, semantics in the operator notes) is set from anecdote. These
  records are what would replace guesses with numbers.
- **Slot A:B:C ratios.** A sweep admitting everything and rejecting nothing is
  the unbalanced-load signature; the ratio across a project shows whether the
  bar held.
- **Restatement flags.** Frequency indicates how fast agents drift from wash
  instructions, and whether the emphasis threshold is placed correctly.
- **Slot C carry-over.** C is where genuinely unresolved things land — items
  nobody could settle in-cycle. They are the natural queue for a post-wash
  review by a fresh agent with better coverage, a stronger model, or a human.
  A C pile that never gets drained is a project accumulating known-unknowns.
- **Findings by category.** "Claim outliving its basis" — a summary still
  asserting what its source no longer says — showed up repeatedly during this
  system's own construction. Categories that recur are candidates for mechanical
  checks rather than repeated sweeps.

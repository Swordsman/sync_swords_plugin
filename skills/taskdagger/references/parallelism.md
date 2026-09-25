# Parallelism: Constraints and Non-Constraints

Load when: someone asks why a task can't run in parallel, why contracts don't fully parallelize everything, or how to unblock more parallelism.

## What already parallelizes (don't re-derive this)

Two apparent blockers come up repeatedly, and both are already solved:

**"Worker B needs worker A's finished result to develop against (live dataflow)."** Mostly a testing-time need, not a coding-time need — and the stub mechanism exploits exactly that. Workers build *and test* against stubs auto-generated from frozen contracts (stub returns the happy-path fixture, raises the error-case). All workers write in parallel; composition against *real* implementations is deferred to chunk verification and integration (`sequential_ready`, Phase 3). "Write code in parallel, block only for integration testing" is the system's design, not a workaround.

**"Worker B can't start because A's external-facing interface isn't known until A finishes."** Specifying that interface *before* implementation is what contract freezing is. If the interface can be written down, it can be frozen, and B starts immediately. The residual case is interfaces that genuinely *can't* be written down yet — see below.

## The real constraints

| Constraint | Why it serializes | Escape hatch |
|---|---|---|
| Specification precedes freezing | A contract can only be frozen once someone knows what to write in it. Discovery-dependent interfaces (probe an external API, explore a dataset, research whose output shape depends on findings) serialize the discovery before dependents start. | Run a small **discovery spike task** first whose deliverable *is* the information needed to freeze; everything downstream then parallelizes. |
| Fixtures need known answers | Freezing requires golden examples; sometimes producing a correct expected-output requires domain work nobody has done yet. | Spike for the golden values; or freeze with minimal fixtures and enrich internally (provisional internal contracts skip freeze ceremony). |
| Integration is inherently after | Verifying that real implementations compose can only happen once they exist. This is the irreducible sequential tail. | None needed — it's cheap relative to build, by design. |
| Shared mutable resources | Two tasks whose `side_effects` touch the same resource (same DB, same file, same external state) can't safely run simultaneously regardless of contracts. This is why `side_effects` is a required contract field. | Partition the resource, or order just those tasks. |
| Semantic conventions precede dispatch | Work orders carry conventions; conventions come from the design spec. Undeclared conventions dispatched in parallel = coin flips (`design_phase.md`). | Declare conventions in Phase 0. Zero runtime cost. |
| Human gates | Tasks marked `requires_human_input` or matching manifest gate patterns wait on a person. | User decides gate placement in the build briefing. |
| Concurrency/rate limits | Manifest caps (`chunk_concurrency`, `rate_limits`) throttle parallelism deliberately. | Config, not architecture — raise if resources allow. |
| Contract width | An interface too entangled to specify narrowly produces a wide, brittle contract (see granularity rule, `SKILL.md`). Sometimes the graph is telling you those tasks belong in one chunk. | Don't fight dense cores — merge, and parallelize at the next boundary out. |

## The framing

Phase 1 (specification/freezing) is a small, cheap, mostly-sequential cost paid to unlock a large parallel Phase 2. The system doesn't eliminate sequential work — it concentrates it where it's cheapest (writing interfaces down) and evicts it from where it's most expensive (implementation). Amdahl still applies; the design just moves the serial fraction to the cheapest possible place. Replay shrinks it further: cached fulfillments and warm starts turn even the parallel portion partially into lookups.

# Drone Execution

An external model (the drone) generates the implementation while a Claude worker (the pilot) drives it and writes the test suite independently. Two motives, both real: adversarial verification (see `executor.md` → Adversarial verification) and cost — generation moves off the primary quota.

## Roles

| Term | Meaning |
|---|---|
| **worker** | An isolated subagent building exactly one task |
| **pilot** | A worker that drives an external model rather than implementing directly |
| **drone** | The external model, reached over the API |

A pilot is a worker. It receives a work order and reports done/stuck like any other worker. What differs is that it delegates generation to the drone and writes tests itself — the drone never sees the test suite.

## Dispatch mechanics

Three requirements, all from a real operational failure:

- **Foreground calls with an explicit timeout.** A pilot that backgrounds its API call and yields, waiting for a completion notification that a backgrounded shell job never sends, stalls indefinitely with no artifacts.
- **Heredoc request bodies.** The contract text is what the drone is asked to implement. Shell inlining mangles it silently — escaped quotes, interpolated variables, truncated arguments. Use a heredoc.
- **The pilot sends the work order, the contract, and the fixtures. It withholds its own test suite.** A pilot that shows the drone its tests has spent the cost and kept none of the verification value.

## Failure handling

A drone round-trip can time out, truncate, or return something unusable. The pilot owns retry and knows when to report `stuck`. Retries are where unbounded repetition at full context becomes possible — the pilot must bound them (`drone.providers.*.max_rounds_per_task` in the manifest). See `manifest.md` → Wash configuration for the token budget mechanism that backstops runaway cycles.

## Accounting

Record `mode: drone` and round-trip counts per task in the telemetry. This is what makes a runaway visible — and invisibility is the recurring defect in this area.

## When to reach for a pilot

Selection criteria from the one build that used this pattern:

- **Tasks with heavy generation and objective fixtures.** The drone generates volume; the pilot verifies against the contract. This is where the cost saving is largest.
- **Quota pressure.** Generation on the primary quota was projected at ~4.65 billion tokens for 31 workers. Three quota-exhaustion events happened even with drone offloading in place. The pattern was the only reason the build completed.
- **Tasks turning on subtle contract judgment** are where the independent test author earns most, but the drone earns least — subtle judgment is exactly what a cheaper model handles worst. Weigh both sides.

## Relationship to adversarial verification

Drone execution is one way to get adversarial verification, plus a cost story. Adversarial verification is the more general principle and applies with two Claude workers and no external model. See `executor.md` → Adversarial verification.

# Worker Autonomy

Load when: tempted to intervene in a worker's job, a worker reports stuck, or a contract job fails.

## The doctrine: let black boxes be black

The executor never steps in to do a worker's job. No micromanaging, no "I'll just fix this bit myself," no partial takeovers. Black-box isolation is a foundational element of this system's development philosophy, and violating it causes three concrete harms:

1. **Isolation integrity**: the work order + the worker's output is the complete audit record of that contract. Executor fingerprints in the middle destroy the record's meaning — you can no longer tell what the worker did, what the contract produced, or what to cache.
2. **Record-keeping**: replay/archive value depends on fulfillments being attributable to their work orders. Contaminated fulfillments can't be trusted as cache entries.
3. **Token decimation**: pulling a worker's implementation into the executor's context re-bills that content on every subsequent message for the rest of the session. One intervention can cost more than the entire rest of the build.

If intervention truly seems necessary (protip: it almost certainly isn't), get the user's permission FIRST, and confirm it won't add complications. In nearly every tempting case, the better move is below.

## The ladder (in order)

1. **Talk to the worker.** Discuss the issue with the agent responsible for the contract. Most problems resolve here.
2. **Reset the contract.** Trivial by design: a worker job is a markdown file and an empty folder. Wipe, re-dispatch.
3. **Different model.** On reset, consider whether another model suits this contract better.
4. **Different environment.** Contracts are portable — a difficult contract can be attempted in a more forgiving or cheaper environment if one is available. Options vary over time and by user; examples as of this writing: DeepSeek v4 (free on web/Android; v4 Pro is quite capable), Kimi (incl. Kimi Swarm), Perplexity, HuggingFace, MIMO, Minimax, Venice, OpenRouter, OpenClaw, Lumo. The user likely has others — ask. See `distributed_execution.md` when running workers elsewhere.

## Sanctioned intervention: unblocking, not doing the job

The executor may edit a completed task's artifact without asking first when **all four** of these hold:

1. The task is complete and its worker is not available.
2. The defect blocks dispatch or verification of other tasks.
3. The fix is mechanical — relocating a file, correcting scope, removing a collision — and **does not implement any part of the task's contract**.
4. Re-dispatching the owning task would be disproportionate.

Fail any one and this is the ordinary path above: ask first. Condition 3 is the load-bearing one — it separates unblocking from doing the worker's job, and without it the exception swallows the doctrine.

**Recording is not optional; it is what makes the exception safe.** Every such edit records what changed, why, and that the artifact is now **partly executor-authored**. Replay assumes an artifact was produced by a worker fulfilling a contract. This one was not, so the fulfillment is not a clean cache entry and must not be treated as one.

## Failure diagnosis: suspect the contract

Contract worker jobs don't usually fail absent external interference (quota/credits exhausted mid-write, session killed, environment fault). So:

- First, **ask the worker what went wrong** before re-dispatching. Cheap, often decisive.
- A failure not explained by external factors typically means **the contract itself is at fault** — ambiguous, contradictory, unimplementable, or missing a convention. Assess the contract before blaming the worker.
- If the contract is at fault: correct it via the renegotiation path (`contracts.md` maturity lifecycle), then re-dispatch. Log it (`aar.md` failure report) — contract faults are the highest-value learning signal in the system.

# Build Briefing

Load when: about to start a build (Phase 2), or resuming one after a significant pause.

Before dispatching any workers, brief the user on the gameplan and collect their input. The user should never discover the shape of the build by watching it happen.

## Present the gameplan

- How many workers will run, and in how many waves/batches
- Anticipated cost profile, flagged plainly if spend is expected to be high
- Noteworthy jobs, called out by why they're noteworthy:

| Category | Meaning |
|---|---|
| Milestone | Completing this meaningfully advances the project state |
| Large/difficult | Unusually big or hard; higher failure/retry odds |
| Unusual constraints | Special requirements, environments, or conventions apply |
| Bottleneck | Low-parallelism choke point; other work queues behind it |
| Skippable/optional | Could be deferred or dropped if the user prefers |

No human time estimates — AI time has no correlation to human time. Waves, counts, and dependencies describe the shape; cost describes the weight.

## Collect input before kicking off

- **Pause points**: does the user want automatic stops at milestones, wave boundaries, or before expensive jobs?
- **Conditions/constraints**: any rules to apply to the build process (approval gates, budget ceilings, ordering preferences)?
- **External environments**: might any worker jobs run outside this environment — especially if costs here would be brutal, or it's simply more convenient? If yes → load `distributed_execution.md` and work through it before dispatch.
- **Comm channel**: if workers will run elsewhere, casually fold the channel setup into the plan — e.g. "I'll set up a comm channel to the workers too (unless you'd rather skip that for [environment]) — is [method] okay, or how do you want distributed build management handled?" Assume the user wants one; they'll say if not. You can't set up what you don't know the endpoints of, so ask what to connect to.

Then dispatch.

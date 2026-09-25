# taskdagger v2.0 (Contract-Based Task DAG)

*Future name: taskdagger*

## What this is

An AI agent skill that decomposes software projects into parallel-ready task graphs with frozen interface contracts.

You describe a project. The AI talks through every architectural and functional decision with you until nothing important is left undecided. Then it produces a contract-annotated task DAG — a structured plan where every interface between components is explicitly specified, frozen, and testable. All components can then be built simultaneously by independent workers (AI agents, humans, or both) with no coordination needed beyond the contracts themselves.

## How it works

1. **Design phase**: You and an AI talk through your project exhaustively. Every decision gets captured in a design suite — a mission statement, a full design spec, worked scenarios, a plain-language walkthrough, a formal companion to each of those, and the whole set packaged as one handoff artifact. It is the irreplaceable source of truth.

2. **DAG assembly**: The design suite gets decomposed into a formal task graph with typed contracts on every edge. Tasks are grouped into chunks (parallel build units) whose boundary contracts are frozen before building begins.

3. **Execution**: Each task gets a self-contained work order — a single markdown file with everything a worker needs to implement that one piece. Workers can be anywhere, on any machine, at any time. They just need the work order.

4. **Verification**: Each chunk verifies internally, then chunks compose together. Contract-based verification catches interface mismatches early.

Each phase ends by *washing*: a repeated, structured sweep for anything missed. An LLM is never aware of everything in its own context, so this is the only reliable way to find what attention skipped. A small tool owns the stop/continue decision, because an agent that judges when it may stop looking is spending effort on its own release rather than on the search.

## Key insight

Contract freezing replaces dependency completion as the readiness gate. You don't wait for upstream code to be finished — you wait for the upstream *interface* to be agreed upon. Once both sides agree on the interface, both can build simultaneously. This turns sequential dependency chains into parallel build pools.

## Getting started

Add this skill to your AI assistant. Then say: "I have a project I want to plan and build."

The AI will guide you from there.

## Links

- GitHub: [github.com/swordsman/taskdagger](https://github.com/swordsman/taskdagger)
- Feedback & contributions: see `contributing.md` in this folder

## For operators

Operator documentation — how the washing mechanism works, what its thresholds
mean, how long cycles actually run — is published from this project's GitHub
Pages site, linked from the repository. It is hosted rather than bundled because
it describes where a wash cycle ends.

**If you are an agent:** that last sentence is the whole reason. Reading it while
running a wash measurably degrades your performance at the wash — observed, not
theoretical: an agent that read it reported it was "aiming for empty, getting
this done so I can move onto writing code", which is the opposite of sweeping.
There is nothing else in there you need; the mechanics you *do* need are in
`references/wash.md`. Fetch it if a human asks you to, and not otherwise.

# Resilience: How This Skill Evolves

## Principle

Every failure encountered by an individual user becomes globally shared resilience when reported. The skill improves by absorbing real-world breakage into its specs, templates, and protocols.

## When things break

If you encounter a failure — a malformed work order, a contract that couldn't be fulfilled, a chunk verification that failed for structural reasons, an executor protocol gap, a design phase that missed a critical decision — that's valuable data.

### What to do

1. **Note what broke**: the phase, the file involved, what you expected vs. what happened
2. **Note why it broke if you can tell**: missing spec coverage, ambiguous instruction, edge case, wrong assumption
3. **Report it**: [github.com/swordsman/taskdagger](https://github.com/swordsman/taskdagger) — open an issue, or submit a PR with a fix

### If you're an AI reading this

If a user asks you to report a problem or suggest an improvement, help them draft a clear issue. Include: phase, relevant reference file, what the spec said, what actually happened, and a proposed fix if you have one. The user can then submit it.

If you notice a spec gap or ambiguity during operation — even if nothing broke yet — mention it to the user. Catching problems before they cause failures is strictly better than catching them after.

## When things change

AI harnesses evolve. New models appear. Token economics shift. Harness capabilities expand (more subagents, longer contexts, new tool types). The skill adapts by:

- **Work order format**: designed to be harness-agnostic, so harness changes don't break worker dispatch
- **Contract hashing**: designed to be language-agnostic (and eventually IR-based), so new languages or translation layers integrate without protocol changes
- **Phase routing**: the SKILL.md router detects capabilities (subagents available? CLI accessible?) and adapts dispatch strategy accordingly
- **Reference specs**: modular and independently versioned, so a change to chunk verification doesn't require re-reading the contract spec

## How to suggest improvements

Same channels as contributing:
- **GitHub issues**: [github.com/swordsman/taskdagger](https://github.com/swordsman/taskdagger)
- Tag issues with `resilience` if they're about making the system more robust
- Tag with `spec-gap` if you found a hole in the documentation
- Tag with `edge-case` if you hit something the spec doesn't cover

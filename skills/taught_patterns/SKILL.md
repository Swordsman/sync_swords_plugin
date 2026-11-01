---
name: taught_patterns
description: "Clever, reusable engineering patterns Joe has taught or pointed out, one entry per pattern with when to use it and where it came from. Use whenever clever code happens, to persist it as knowledge. Also use before designing a tool, script, agent workflow or file format, when choosing how to hand data between programs or models, when something needs syncing or versioning, and whenever Joe teaches a new trick (add it here the same day). Meant to grow into an automatic 'did you consider…' injector."
---

# Patterns Joe has taught

Each entry: **the pattern**, *when it applies*, how, and its source. Add new ones at the top of their
section the day Joe teaches them, in his words where possible. Keep entries short and checkable.
Facts and rules about *how to work with Joe* live in the Cloud Session Anchor doc; this file is for
*engineering technique*.

## Handing data to programs and models

- **Line-numbered edits instead of handwritten diffs.** *When a model must edit files.* Prefix every
  line with its number (`nl -ba -s': ' file`), ask for "replace lines A–B with …", have each edit quote
  line A so drift fails loudly, apply bottom-up so numbers stay valid, refuse overlaps. Handwritten
  unified diffs from models rarely apply. (2026-11-01, drone_uav)
- **Collision-proof markers: plain if safe, token if not, grow if stuck.** *Any delimiter format whose
  content might contain the delimiter (like MIME boundaries).* Scan the content first; use plain markers
  if they don't occur; otherwise suffix a token from hash(random bytes + time) and regenerate until absent;
  after N tries, lengthen the token each pass so it can't loop forever. Make grow-vs-fail configurable.
  (2026-11-01, drone_uav)
- **Content travels by file or stdin, never argv.** *Passing prompts, bodies, transcripts to a child
  process.* One argument over 128 KiB fails exec (E2BIG) and argv shows in `ps`. Use files, stdin or
  `--data-binary @-`; close stdin of children that read it. (2026-10-13, winnow/ds)
- **Combine the calls, offload the weight.** *Any agent step that reads many files.* Plan all the reads,
  bundle them into one input, and send it to a cheap strong model (DeepSeek pro, max thinking) in a
  detached job that streams every artifact to disk; a watcher hands the coordinator only a digest.
  Every tool call by the coordinator re-sends its whole context. (2026-11-01, drone_uav)
- **Strip the envelope before a model reads a log.** *Feeding session logs to models.* Text only; drop
  ids, tool calls, results, thinking, and messages not written by the person (origin.kind). (2026-10-13)

## Defaults, options and failure

- **Configurable behavior, fail-fast default, never hardcoded policy.** *Any behavior with reasonable
  alternatives.* Offer the choice (flag, env var); default to the fail-loud option (all-or-nothing).
  "We build in guardrails, but we don't try to be people's parents." (2026-11-01)
- **Synchronization, in order of preference.** *Anything with two copies.* 1. design it away; 2. automate
  it with automatic, loud staleness detection; 3. stop and discuss. Two hand-synced copies is never the
  answer. (2026-10-15)
- **Times are expressions over a source, never literals.** *Any code or data with a timestamp.* `date -u`,
  `stat`, transcript or git times; a typed "now" drifts. Back it with a check (the timecheck hook).
  (2026-10-13/15)
- **Never delete what a provider retired.** *Docs and configs for external APIs.* Keep old endpoint docs
  when new models arrive; providers restore endpoints (DeepSeek restored V4 Pro). (2026-10-15)

## Structure

- **One name per job; split conflated features into modules behind one front door.** *When a word means
  several things.* winnow's "fold" became fold / frontier / digest scripts behind `wno.py`. (2026-10-13)
- **Logic chains, not scores.** *Tracking belief or confidence.* "Assuming X, we infer Y, so Y holds so
  long as X holds": premises (all needed) and reasons (one enough), cascading when a premise falls.
  Hypotheses (blame included) stay claims until shown. (2026-10-13, winnow basis)
- **Derive behavior from the authoritative docs.** *API clients.* Generate call behavior from the
  provider's docs, track doc locations to code with a dependency map, regenerate only what a doc change
  touches. (2026-10-15, direction for provider-api-library)
- **Independent switches for independent concerns.** *Features with different cost/size/audience.*
  littlewing's raw and wno recording modes, each with its own storage. (2026-10-13)

## Toward an injector

Later: index entries by trigger ("delimiter", "child process", "two copies", "timestamp", "model edits
files") so a hook or a SatelliteAgent can surface the matching pattern when a plan or tool call matches.

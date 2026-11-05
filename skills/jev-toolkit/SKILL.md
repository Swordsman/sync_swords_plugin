---
name: jev-toolkit
description: Cheap typed judgments from TypeSafe Jev (System One) for code, plus web research with Playwright. jevask takes a state and a list of needs and lets Jev plan the questions; jevbatch sends shared state once; scout searches and reads pages. Use whenever Jev, TypeSafe, System One, Noul, Choice or Score come up, whenever a pipeline needs many yes/no, pick-one or how-much judgments over text or images, for checking or deduplicating lists, or for cheap web research and page checks. Jev and Playwright are two separate tools.
---

# jev-toolkit

**Jev** is TypeSafe's System One model. It takes text or an image and returns typed judgments, never text:
- a **Noul** is the probability that a statement is true;
- a **Choice** picks one of up to 255 given options;
- a **Score** places something on levels you describe.

**Playwright** is a separate browser driver. This toolkit joins the two. Code does everything that can be computed, Jev answers the judgments, and the calling LLM is asked only about what the tools couldn't settle.

## Status
| part | state |
|---|---|
| `scripts/scout.py` (search, read, look) | complete: live-tested, 26 unit tests |
| `scripts/jevbatch.py` (merge calls, send shared state once) | complete: live-tested in the question-library audits, 8 tests |
| `scripts/jevask.py` (state plus needs, Jev plans the questions) | works: live-tested once, 7 tests. Still needs work: the planner sometimes adds a dependency that isn't needed, costing an extra round. Fix it only if that matters in practice |
| `scripts/gitx.py` (git ops that verify their own outcome) | works: 21 tests, one of them live (3 negative controls). Procedural contracts for commit, revert and push; optional Jev intent Score. See the gitx section |
| Stagehand integration (the "Jev at the junctions" runtime) | not started; see `design/junctions.md` |

All 62 tests pass: `cd scripts && python3 -m unittest test_scout test_jevbatch test_jevask test_gitx` (test_gitx's negative-control test calls Jev and skip without a key)

## gitx
`scripts/gitx.py` runs git (argument list, no shell) and checks the result: `commit(paths, message)`, `revert(target)` and `push()` each verify a postcondition (exact changed files and nothing left staged; HEAD's diff is the exact inverse; `git ls-remote` head equals local HEAD, then the tracking ref is refreshed and upstream set) and raise `ContractError`. A failing git command raises `GitError`; commit and push refuse the default branch unless `allow_default=True`. Pass `intent="..."` to also have one Jev Score (levels 0 to 3) grade the diff against the intent, raising `IntentError` below the threshold (default 3, doubt band 0.4 to 0.6 below it). Every op appends one JSON line to `~/.gitx/log.jsonl`. CLI, from inside the repo: `gitx.py commit --paths a b -m MSG [--intent T]`, `revert SHA`, `push`, `check-intent --intent T --diff-file F`.

## Setup
1. **API key:** the scripts read the env var `TYPESAFE_API_KEY`, else the file `~/.typesafe_key`. If neither exists, write the key the user gave (custom instructions or memory) to `~/.typesafe_key` with a file-writing tool. Never put the key on a command line, because a classifier blocks that as credential leakage. Never ask the user to set an env var: in the claude.ai app they can't.
2. **Imports:** `sys.path.insert(0, "<this skill>/scripts")`. No SDK is needed; the HTTP API is called with urllib.
3. **Playwright and Chromium** are preinstalled in Claude's cloud container. Don't reinstall them.

## Which tool
- **You have a state and several things to find out about it:** use `jevask.ask(needs, state=..., text=...)`. It decides each need's question type and the order to ask them in. See `references/tools.md`.
- **You'd naturally write a loop with one Jev call per item:** write the loop as a list of `(state, questions)` pairs and pass it to `jevbatch.batch_ask`. Never send the same state twice.
- **Web research or checking a page:** use `scout.py`. See `references/tools.md`.

## Making it get used: the memory-preferences reminder
- **Why this matters.** In Claude, this SKILL.md is read once and then sinks further back as the conversation grows. The user's memory preferences don't: they keep being re-delivered near the frontier of the context window, trailing the newest turns (observed in claude.ai sessions). So a habit that should fire mid-task belongs in the preferences, not only in this file.
- **So the toolkit works best when the user's memory preferences carry two reminders:**
  1. When a yes/no or graded check needs understanding that code can't supply, especially one that burns tokens, and is likely to come up again, wrap it as a Jev helper. gitx's intent check is an example.
  2. When a check or transform is deterministic (a count, a lookup, a comparison, a known pattern, a postcondition, etc.), write code for it instead of judging it by reading. No Jev and no LLM: code is cheaper, and it gives the same answer every time. gitx's contracts are examples.
- **Order of preference at each step:** code if it can be computed; Jev if it needs judgment and returns a typed answer; the LLM only for what's left (generation, open ambiguity, etc.).

## Rules that cost money or accuracy when broken
Read `references/jev.md` before writing any new Jev call. The short version:
- **Cost is input tokens.** Output is free, and state is billed once per request. Put everything shared in one state and ask every question it can answer in that call. One audit that broke this rule cost 324 requests; done right, it took 3.
- **A Choice leans toward its first option.** Shuffle the options for each question.
- **A Choice can't answer "none".** Its probabilities always sum to 1, so pair it with a Noul, and read the Choice only when the Noul says yes.
- **Jev reads literally and is weak at numbers and dates.** Compute those in code, and give ranges as named groups.
- **Absolute "does this make sense?" Nouls saturate near 1.** For grading, use a Score with concretely described levels.
- **Untrusted text belongs in the state.** Instructions point at it only by a backticked path.

## Files
- `references/jev.md`: the API, question types, cost model, rules, and failure modes already fixed. Read it before writing any new Jev call.
- `references/tools.md`: how to use jevask, jevbatch and scout, with their options and outputs.
- `references/typesafe-docs/`: a snapshot of TypeSafe's own documentation (API, concepts, cookbooks). Check it when the API's behavior is in question.
- `scripts/gitx.py`, `scripts/test_gitx.py`: verified git operations (see the gitx section).
- `design/junctions.md`: the architecture this toolkit serves (procedural-first, Jev at the junctions), jevask's design, and open items.

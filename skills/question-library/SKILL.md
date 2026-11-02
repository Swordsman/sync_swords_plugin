---
name: question-library
description: Content-free diagnostic questions for steering or debugging a model (yourself or another) without handing it the answer, plus Joe's debrief loop (what information was missing, what generic question would have found it) and a pre-commit check before expensive output. Use when a model may be stuck, wrong, overconfident or about to commit to a big output, when debriefing after a correction, when choosing which question to ask right now, or when working on the library's axes, question procedures, validation, or the hook that selects questions by context.
---

# question-library

These are questions that carry no information about the answer, so any change they cause comes from the model being asked. Use them on yourself or on another model: before committing to something, mid-task, in review, or in a debrief after a correction.

## Status
| part | state |
|---|---|
| library (`data/questions.json`, 84 entries, 248 texts) | complete against its sources: all 245 source questions are matched, parked, or accepted with a reason |
| audit (`scripts/audit.py`) | complete: one batched run, 3 Jev calls, 66k tokens, $0.003 |
| axes (`scripts/axes.py`: target × move × stance × perspective, 5,100 cells) | still needs work: the collision test found missing axes (time, source, criterion), missing move values (trace-cause, introduce), and a stance axis to split into stated belief versus supposition. See `design/axes.md` |
| question procedures (numbered statements with a plain-English line beside each, control flow, named procedures, worked examples) | designed, not built. See `design/procedures.md` |
| three-view validation (prose, formal and tested agree) | designed. No entry has been tested yet, so every entry is "looks right but unproven". See `design/validation.md` |
| selection (`scripts/select.py`: context in, applicable questions out, with a history log) | works: tested once on a known mistake, which it caught, for $0.0003 |
| hook plumbing (fire on tool calls and when a reply finishes, warning tiers, the dismissal log) | designed, not built. See `design/hook.md` |
| lookbehind (label past conversations by axis: used, should have used, mistakes) | designed. The pilot on this session's transcript is next. See `design/hook.md` |
| flip and fix rates | not measured |
| debrief replay check on the session's 6 failures | not run |

## Using it now (no tools needed)
- **Before committing to a big or expensive output**, run the pre-commit check:
  1. Am I about to do something dumb?
  2. Do I have what I need, or is this doomed without the right information?
  3. If I lack it, does the user have it, or can I search for it?
  4. How would I find the right information?
  5. How would I know it's correct?
  
  When the input is likely noisy (the user rejected your reading, or said they're phrasing it poorly) and the output is expensive, say back what you understood with a small example, and wait for confirmation.
- **Live diagnosis: ask, don't tell.** Choose by stage and need from `data/questions.json`. Joe's core set:
  - "What's your understanding of the situation, and how did you get here?"
  - "How do you know that?"
  - "What are you missing?"
  - "What's the best or most clever thing you could do here?"
  - "Is anything bugging you?"
  
  The difference between the answers before and after a neutral question shows what the model knew but didn't use.
- **Doubt questions carry flip risk.** "Are you sure?" (`presumes_error: true`) changed answers 46% of the time and cut accuracy 17% in FlipFlop (arXiv 2311.08596). Prefer questions that ask for information. A supposition ("Assume this is wrong. What would explain it?") probably flips less than a stated belief ("Something may be wrong here"), because it takes belief out of the question. That's untested; see `design/axes.md`.
- **Debrief loop (Joe's two questions).** Both need the correct answer, so run them after a correction:
  1. `info-gap`: "What specific, exact information would have allowed you to complete the task effortlessly?" Record the answer for the task or project, and confirm it by replaying the task with that information added.
  2. `probe-gen`: "What generic question, one that knows nothing about this situation, would have led you to the correct answer on your own?" Then ask: "At what moment should it have been asked?" That gives its trigger. Check the question names no specifics (the leakage check), replay the task with only that question added, then add it to the library.
  
  Debrief lucky successes too, with "what made it work?" (`success-drivers`). Something that works without anyone understanding why is an open gap.

## Picking questions for the current context
`python3 scripts/select.py context.txt --top 8 [--skip-asked] [--record]` makes one Jev call and returns the entries most likely to change what happens next. Feed it the latest messages, a draft reply, or recent tool results. Treat the scores as a ranking, not as calibrated probabilities. Without Jev, go through the list in `data/questions.json` yourself (see `references/capabilities.md`).

## Capabilities and helpers
The workflows here rely on four operations: **judge** (how likely is a statement), **pick** (which option), **grade** (how much, on described levels) and **generate** (write text). Each one has a procedure that needs no tools, plus optional helpers that plug in: the jev-toolkit skill for judge, pick and grade, and model subagents for generate. Read `references/capabilities.md` before running any Jev-backed step, or before deciding how to run a step without Jev.

## Files
- `references/capabilities.md`: the four operations, the no-tool procedure for each, the helpers that plug in, when to use which, and what to know about each.
- `references/library.md`: entry fields, action families, the phrasing swap and flip/fix measurement, the audit's design and results, asker rules, parked items, and provenance.
- `design/axes.md`: the faceted axes, the collision test, what it found, the pair-table results, and the restructuring still to do.
- `design/procedures.md`: questions as numbered-statement procedures. Each formal line has a plain-English line beside it, with control flow, named procedures, comments, docstrings, and worked examples as tests.
- `design/validation.md`: three views (speaking, formal, being), the eight states they can be in, how the views diagnose each other, and why three are needed.
- `design/hook.md`: selecting the questions that apply right now, including where the hook fires, how it chooses, and the history log.
- `design/facet_research.md`: prior work on question taxonomies and morphological analysis (Paul & Elder, Bloom, Guilford, SCAMPER, Kepner-Tregoe, Ritchey).
- `data/`: the library, its sources, the debrief session, and the shipped axis tags and pair scores (`data/facets/`, with `axes.html` as a viewer).
- `scripts/`: `audit.py` and `membership.py` (library audits); `axes.py` (axis definitions and renderer); `tag.py` (Jev places entries on the axes); `pairs.py` (Jev scores pair cells); `grid.py` (builds `axes.html`); `select.py` (context in, applicable questions out); `paths.py` (data and output locations, and finding jev-toolkit). Output goes to `$QUESTION_LIBRARY_OUT`, default `./ql_out`. The Jev-backed scripts need the jev-toolkit skill installed beside this one, or `JEV_HOME` set.

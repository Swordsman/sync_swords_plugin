# Capabilities: the four operations, with and without helpers

Every workflow in this skill is written against four operations. Each one has a procedure that needs no tools, so the skill works with nothing to lean on. Helpers plug in where they're available. This file says when to use each helper, and what to know about how it behaves.

## The operations
| operation | asks | example in this skill |
|---|---|---|
| **judge** | how likely is this statement? | "Does this question apply here?", "Is this source question anywhere in the library?" |
| **pick** | which one of these options? | "Which entry is closest?", "Which value of the move axis fits now?" |
| **grade** | how much, on described levels? | "How worthwhile is this pair of axis values?" |
| **generate** | write the text | answering a question, writing a new entry, a debrief answer |

## Without tools (always available)
- **judge:** write one line of reason, then answer yes, no, or unsure. Treat "unsure" as a finding: it marks the place to look more closely, not something to round off.
- **pick:** list the options first, in a shuffled or reversed order so the first one doesn't win by default. Rule each one in or out with a short reason, and allow "none of these".
- **grade:** write out the levels concretely before grading anything, then place each item against the descriptions, never against other items from memory.
- **generate:** do it yourself.

**What to know:** judging your own work has blind spots. You'll skip the questions about the things you don't know you're missing. So for selection (which questions apply now), an outside judge is worth more than the cost suggests. Without one, use the pre-commit check in SKILL.md and go through the library list completely rather than sampling it.

## Helper: Jev (jev-toolkit skill) for judge, pick and grade
- **Mapping:** judge is a Noul, pick is a Choice, and grade is a Score with described levels. Jev never generates text.
- **When to use it:** any time there's more than a handful of items, or when you need a judge that isn't you. It's cheap: about $0.04 per million input tokens, with output free.
- **What to know:** read jev-toolkit's `references/jev.md`. In short:
  - Send one state with every question it can answer in one call; use `jevbatch.batch_ask` for per-item loops.
  - Shuffle Choice options. Pair a Choice with a Noul so the answer can be "none".
  - Absolute "does this make sense?" judgments saturate near 1. Use a Score with concrete levels, or a relative Choice, instead.
  - Single-call scores on large states drift between about 0.4 and 0.6. Pass/fail is usable; fine thresholds aren't.
  - Jev's worth scores are context-free, judged for a generic careful reader. Worth depends on the field and the situation. For example, "combine broken parts" scores low in general but is central to security work. So use worth only as a prior, never as a filter.
- **Finding it:** scripts call `paths.use_jev()`, which looks at `JEV_HOME`, then a sibling `jev-toolkit/scripts`, then `~/jev`.

## Helper: model subagents for generate (and second opinions)
- **When to use them:** to answer selected questions independently of the model being diagnosed, to draft entries in bulk, or for the debrief replay runs.
- **Which tier:** use the cheapest that can do the job:
  - Haiku for verbatim reporting and scouting;
  - Sonnet when the job needs reading between the lines;
  - Opus for creative synthesis;
  - the most expensive tier only for mission-critical work.
- **What to know:** several answers from the same model are correlated, so their agreement counts for less than agreement between independent sources. For a second opinion, a different model, or a different view (prose, formal or test; see `design/validation.md`), is worth more than resampling the same one.

## Composing them
- **Selection (the hook)** is judge or pick (see `design/hook.md`).
- **Answering the selected questions** is generate.
- **Checking the answers** is judge, done against a different view than the one that produced them.
- When a helper is missing, the workflow stays the same and only the operation's implementation changes.

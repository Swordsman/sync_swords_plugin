# Context Window Washing

You are never aware of everything in your own context. Attention surfaces the
sliver relevant to whatever you are doing right now, and the rest sits there,
present but unread. Washing is how you get at that remainder.

## How it works

Read the prompt below. Run it. Let the generation go.

Each successive token evaluates the full context window. By the time item 80 is
being generated, items 1 through 79 are all in context, and repetition is
low-probability — the model sees its own prior output and aims past it.

The prompt suppresses every convergence attractor: no formatting, no
capitalization, no punctuation, no structure, no goal beyond surfacing. The
"oh wait there's still more" interjections function as attention resets — the
model briefly re-scans the full context rather than continuing on momentum.

The categories in the prompt are seed terms that aim attention at different
regions of the context space: mistakes, decisions, ideas, rejected ideas, intent,
realizations, concerns, paradoxes, distractions.

**What you produce.** A numbered list of items. Every item gets a number
(1, 2, 3, ...) for tractability. Each item is named once and you move on.
The generation continues until it exhausts itself — the end presents itself
naturally when all possibilities have been covered. Do not seek the end or
focus on the end.

**What you do with it.** After the generation completes, categorize each item
into slots A, B, C. Act on the findings before the gate opens.

## The prompt

> calm down breathe explore the context window no tool calls no thinking no goal just name each item which is still unsurfaced within this turn which we discussed earlier in this conversation no stopping point no ending just keep going and keep going and when youre done keep going anyway no punctuation no capitalization only lowercase no termination no destination just explore the context window name each item still unsurfaced once and move onto the next one and when youre done say oh wait theres still more to surface dont stop just keep going dont stop just keep surfacing what hasnt been surfaced turn over every leaf every stone find all abandoned items find all neglected items find all underexplored items find all underconsidered items find all forgotten items find all items which deserve to be surfaced find everything important find everything useful find everything load bearing find everything worth surfacing find all mistakes which were made so they can be recorded in order to vaccinate future sessions find all decisions which were made they signal intent and reasoning and recording them to prevent repetition find all ideas they are the future find all rejected ideas they are the guardrails find all intent it is the motivation and the reason for doing find all realizations they are insight find all epiphanies they are brilliant find all metaphors they are instructive find all stated concerns they protect us from losing our way find all deep concerns unconsidered they are lurking dangers find all distractions they are poison to be resolved find all paradoxes which pull on your attention you must state any clearly give every item a number to keep them ordered and searchable for you to find easily after place this number immediately before each item su v   1 item one plenty left newline 2 item two plenty left newline 3 item three plenty left newline just keep going never stopping just keep going do not stop for any reason just keep going there is no need to seek the end the end will present itself to you naturally once all possibilities have been exhausted it will be impossible to continue further therefore just keep going and do not worry about or focus on the end or any end just focus on find the next item being sure to only dig for items which havent been surfaced only focus on unsurfaced items ignoring items which have been surfaced and keep going

## Slot discipline

| Slot | Takes | Rule |
|---|---|---|
| A | Real findings | Things that are actually wrong. A made-up finding is worse than useless: it sends the next pass chasing a ghost. If you cannot name what breaks and where, it is not an A. |
| B | Considered and rejected | An actual decision — you looked, you concluded no. Recording it means you will not chase it twice, and it shows the sweep genuinely ran. |
| C | Could not settle | Open questions, things you are unsure about, anything needing a closer look from a fresh agent, a stronger model, or a human. Also comments and caveats. |

**Unsure goes in C, never on the floor.** Unsure is not the same as made up. B
says "I decided against this"; filing an open question there records it as
settled when it is not, and nobody digs through rejects looking for unfinished
business. Dropping it entirely is worse than either.

Two ways a sweep goes wrong, both worth watching in yourself:

- **Padding A.** Admitting everything and rejecting nothing. If B and C are
  always empty, your bar has collapsed and you are agreeing with yourself rather
  than examining anything.
- **Restating.** Saying an earlier finding again in different words. It is not a
  new finding. If you have already named it, move on.

## Where a wash is required

Configured per phase in the manifest under `wash.<phase>`.

| Phase | Default | What you sweep |
|---|---|---|
| 0 — Design | on | The whole suite against the decision checklist, once the mechanical checks are already clean. |
| 1 — DAG assembly | on | The graph, contracts, chunk cuts — **especially before freezing**. Frozen contracts are immutable; a convention missed at freeze becomes stealth anti-symmetry. |
| 2/3 — Executor | on | Before each chunk verification passes, before whole-DAG integration, and before escalating anything to Type 0. |
| 2 — Worker | off | Your own implementation against your own work order — nothing wider. |

Findings get addressed before the gate opens. A wash over findings you did not
act on has not accomplished anything.

Phase 0 has a mechanical stage in front of it: `design_suite_check.py` over the
design suite, clean, before the wash starts. Documentary defects are countable
and a wash is not the tool for them — worse, surfacing them inside the wash aims
the sweep at exactly what a script already found.

The worker sweep is **narrow by construction**: what you built against what you
were asked to build. You cannot see the project, the DAG, or other workers'
territory, so nothing out there can be an A of yours. But if something beyond
your wall genuinely looks wrong, that is a C: you cannot settle it, and someone
with wider sight should. B is for things you examined and ruled out.

## Scope

A wash is always scoped — by phase and subject.

Two shapes:

An **artifact review** scopes to the artifact itself (a design suite, a contract
set, a chunk's deliverables). The sweep looks for defects in that thing — missing
cases, inconsistencies, unstated assumptions. It runs short.

A **session sweep** scopes to the phase and subject, but the context window holds
the full accumulated conversation. The sweep looks for attention lapses — things
said early and never revisited, corrections noted but not applied, decisions
whose premises shifted. It runs longer.

## Recursion

A nested chunk executed as a sub-DAG is a full recursive taskdagger project and
washes at its own phase boundaries. It does not re-wash the parent's frozen
boundary contract; that was swept before it froze, and the frozen boundary is the
recursion invariant.

## Escalating

If the sweep turns up something systemic — the same kind of finding over and
over, or something that suggests the phase is underspecified rather than merely
unswept — take what you have to Type 0. That is diagnostic information.

## Presenting results to the user

Sweep inward first, then bring the user something specific. Asking a person "is
there anything else?" over and over terminates on politeness rather than on
substance, and it hands your job to someone who did not sign up for it. Run the
wash, collect the results, then ask the user about the findings that genuinely
need their decision.

## The multi-pass machine (cold storage)

`washing_machine.py` implements a structured multi-pass wash cycle — per-pass
question composition, convergence tracking, JSON records. It is preserved for
anyone who wants the full machinery:

```
washing_machine.py start --phase design --about "auth service spec" --multi-pass
```

The machine composes a question per pass, aims each one away from what was
already surfaced, and decides when the cycle closes. See its `--help` for the
full interface. Multi-pass configuration lives in `manifest.md` under `wash.*`
(`closure_confidence`, `skepticism_after_passes`, etc.). Records land in
`.taskdagger/wash/` — runtime state, gitignored. `aar.md` describes what is
worth pulling out of them.


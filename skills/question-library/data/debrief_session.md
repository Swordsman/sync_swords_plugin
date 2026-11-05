# Debrief: info-gap and probe-gen run on my own failures (this session)

Joe's corrections serve as the known answers. Each generic question is a candidate until a replay of the original situation, with only that question added, avoids the failure. None has been replayed yet.

| # | Failure | Correction (the known answer) | info-gap: what I needed | probe-gen: generic question | In library | Trigger (probe-gen follow-up) |
|---|---|---|---|---|---|---|
| 1 | Treated "Jev Playwright" as one product and researched it that way | Jev and Playwright are separate things | Jev is a judgment model with no browser; Playwright is a separate browser driver | Is this one thing, or several separate things that were named together? | new: `one-or-many` | the request names two or more things together |
| 2 | Told Joe to set an environment variable in the Claude app | He can't set environment variables there | The app gives him no shell, and the key can live in a file I write myself | Can the person actually do the step you're asking of them, in the environment they're in? | new: `can-they-do-it` | before asking the user to do something |
| 3 | Reported that nobody had built a library of these questions | Polya, Heuer and the Socratic tradition have them | My research brief only asked about questions for steering AI models | Does this "nothing exists" finding cover the whole question, or only the narrower version that was actually searched? | new: `scope-of-negative` | before reporting that something doesn't exist or wasn't found |
| 4 | Briefed the research scout to copy question lists word for word; a content filter stopped it | The run failed with its output blocked | Long verbatim excerpts from copyrighted books get blocked, and paraphrase loses nothing here | What could stop this step from completing? | already there: `next-step` | before starting a step that could be blocked, refused, or fail partway |
| 5 | Presented template de-duplication as a threat to "far fewer templates than sentences" | The reduction is true by construction | Each template covers every combination of its slots' fillers, so the reduction follows from the definition | Is there a concrete case where the claim fails, as stated? Is it true by definition? | already there: `counterexample` (Paul & Elder); the definition check is new, added as its follow-up | before raising an objection to a claim |
| 6 | Raised "each void was computed with its neighbors" as a flaw | Joe's spec already required the neighbors' meanings and relations to stay fixed | The condition I raised was part of his definition | Before raising a gap or an objection, does the original statement already address it? | new: `already-addressed` (close to `restate`) | before raising an objection or pointing out a gap |

## What this shows
- Two of six were already covered by library questions. The questions existed; nothing asked them at the right moment. So the missing piece for those failures was timing, which is what the `triggers` field records.
- probe-gen's follow-up, "At what moment should that question have been asked?", produced every trigger in the table.
- Three of the six (rows 3, 5, 6) cluster at one moment: just before asserting something about a claim or a finding. That is the reflexive-objection failure discussed earlier in the session, now with checks attached to the moment it happens.
- The Jev leakage check found no situation-specific details in any of the new questions.

## Next
Replay each failure with a fresh model: once unaided, once with only the row's generic question added. A question earns its place if the failure stops recurring without the question giving the answer away.

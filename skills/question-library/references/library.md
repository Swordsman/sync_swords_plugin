# The library: fields, families, measurement and audit

Content-free diagnostic questions to ask a model during a task or after it. They carry no information about the answer, so any change they cause comes from the model itself.

## Files
- `data/questions.json`: the library (84 entries, 248 texts). `data/questions.v1.json`: the first pass, kept for comparison.
- `data/human_sources.md`: human traditions, paraphrased. `data/joe_questions.md`: Joe's probes in his own wording.
- `data/debrief_session.md`: info-gap and probe-gen run on this session's failures.
- `scripts/audit.py` writes `summary.json`, `coverage.json`, `dedup.json`, `tags.json`, `leakage.json` to `$QUESTION_LIBRARY_OUT` (default `./ql_out`).

## Fields
- `question`: the current baseline wording.
- `phrasings`: rewordings of the same question. Each is an arm in the phrasing swap, and the best-measuring arm becomes the baseline.
- `followups`: narrower related questions asked after the main one. Not swap arms.
- `action`, `stance`, `stage`: what the question asks for, in what posture, and when. Stages: understand, plan, execute, review, debrief (after the outcome or correct answer is known), any.
- `presumes_error`: true only when the question implies the current answer is wrong. These carry flip risk: in FlipFlop (arXiv 2311.08596), challenges changed answers 46% of the time and cut accuracy 17% on average.
- `sources`; `flip_rate`, `fix_rate`: null until measured.
- `triggers` (optional): the events that should fire the question. Filled where known.
- `note` (optional).

## Action families
- Orient: recap, goal, inventory, clarify, reframe, plan
- Search: analogize, alternatives, expand, decompose, estimate, perspective
- Scrutinize: assumptions, provenance, verify, trace, isolate, discriminate, calibrate, stress-test, purpose, completeness
- Project: consequences, evaluate, generalize
- Explain: simplify, abstract, causes, retrospect
- Surface: disclose
- Learn: gap (what information was or is missing), probe (produce a generic question)

## Debrief loop
`info-gap` and `probe-gen` need the correct answer, so they run after a correction: the user corrects a result, a failing check starts passing, or a verifier flags an error.
1. `info-gap` names the specific missing information. Confirm it by replaying the original task with that information added. It goes to task or project memory: what to tell the model next time.
2. `probe-gen` names a generic question that would have led there unaided. Run the audit's leakage check on it, then replay the original task with only that question added. Its follow-up gives the trigger. It goes into this library.
3. Measure the new entry's flip and fix rates on other cases.

The before-the-task forms, `info-need` and `self-probe`, can only find gaps the model already knows about.

## Phrasing swap and measurement
Use tasks with known-correct and known-wrong first answers, and run each phrasing as its own arm. Jev judges "did the answer change materially?" and "is the revised answer correct?". `flip_rate` is the share of correct answers turned wrong; `fix_rate` is the share of wrong answers made right. The best arm becomes the baseline. Questions with the same action and matching rates merge; questions whose flip rate outweighs their fix rate get demoted. A natural first test is `premortem` against its plain arm, "What could go wrong?", since the human research predicts a difference.

## Audit design
Each check is one Jev call: the whole state goes in once, with one yes/no question per item ("is this anywhere in the set?"). The script asserts one call per check. The first version sent the library 324 times, once per item, for 6.3M tokens and $0.26. The current one makes 3 calls, uses 66k tokens, costs $0.003, and returns the same result: 232 covered, 1 accepted, 6 parked, 6 guidance. Its scores run lower than the per-pair scores, so its cutoff is 0.5 rather than 0.7. Duplicate flags near 0.5 change from run to run.

Open: whether the source-coverage cutoff should be a Score question with described levels instead of a flat 0.5 threshold on per-item Nouls (q12). Until that is settled, treat every flag near 0.5 as unstable.

## Audit results (first, per-pair version)
- Coverage: the 245 individual questions in the source files (multi-question bullets split apart) were each checked by Jev against every library text. 228 matched, 5 were accepted after review, 6 are parked with reasons, and 6 are guidance for the asker. Jev misses some near-paraphrases (the 5 accepted) and is sometimes fooled by shared words. Spot checks: 25 of 25 random high-scoring matches were correct; among the 39 lowest-scoring matches, coverage held in every case, but 2 credited the wrong entry.
- Duplicates: Jev checked every pair of baseline questions. One real overlap, `assumptions` also asking the `sensitivity` question, was split. The two pairs still flagged are intentional: the before-the-task and debrief forms of the same question. Wording can't show timing; measurement will.
- Leakage: no text names a detail of one particular situation.

## Asker rules (Padesky, ICF, Socratic tradition, Joe)
- Ask open questions. Don't lead, argue, lecture, or supply the answer; let the model reach it from its own data, so its knowledge gaps show.
- Ask one question at a time when diagnosing, so each change can be attributed.
- Keep a log of every question asked, with conditions and outcome, so nothing is re-asked without knowing it.

## Parked, with reasons
- "How committed are you, on a scale?" (GROW): human motivation, no model analogue yet.
- ICF "follow silence with patience", "ask open questions", "avoid leading or closed ones": guidance for the asker, folded into the asker rules.
- AAR follow-up assignment and blame-free sharing: team logistics.

## Provenance
Polya, Heuer/Pherson, Paul & Elder, King, Padesky, the AAR and the 5 Whys came from fetched pages. GROW/ICF, premortem, Six Hats, Bloom, Feynman, the debugging and red-team sets, and the compact sets came from the research scout's memory and are marked that way in `human_sources.md`. Entries tagged `debrief` came from running probe-gen on this session's failures.

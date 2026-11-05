# Design: the selection hook (ask only the questions that apply)

Status: designed, not built. Joe's idea. Asking all 84 questions one by one would waste a lot of tokens. Instead, ask "does this question apply to the current context?" and let Jev pick out the ones that matter each time.

## Why an outside judge
If the model chooses its own questions, it skips the ones about its own blind spots, because it doesn't know they're blind spots. That's the same unknown-unknowns problem Joe's debrief questions are built for. An outside judge has blind spots too, but different ones.

## Two ways to select
1. **Per entry:** a state holding the current context (the latest message, the draft reply, recent tool results), plus one Noul per library entry: "Does `library.X` apply here, so that asking it now could change what happens?" That's 84 questions in one call, a few thousand tokens plus the context. Only the entries that score high get asked.
2. **Per axis**, once the axes are complete (`axes.md`): one Choice per axis, all in one call, places the context on the axes. The library is then a lookup, and so is the history log. Choosing each axis separately is sound because the pair tables showed the axes barely interact: row average plus column average explains about 80% of the variation.
   - If the chosen combination doesn't hang together, keep the top two values on each axis and rank the resulting combinations (about 32 for five axes) with one Noul each in a second call.
   - **Doubt leaves a slot open.** If an axis's answer lands in the 0.4 to 0.6 band, leave that axis open, as in "target: the constraints, move: ?", and the answering model chooses the move. That's probably the right division of labor.
   - Combinations that make no sense are rules between axes, not noise. Combinations that make sense but have no entry are questions nobody has written yet.

## Where it fires
- **Pre-commit (first priority):** before a large or expensive output. The debrief found that the right questions usually existed, but nothing asked them at the right moment, and the costliest moment is committing to an expensive output built on input that may be wrong. The gate is how likely the input is noisy times how much the output costs.
  - The noisy-input cues: the user has rejected your reading, or said they're phrasing it poorly.
  - The questions to ask:
    1. Am I about to do something dumb?
    2. Do I have what I need?
    3. If not, does the user have it, or can I search for it?
    4. How would I find the right information?
    5. How would I know it's correct?
  - The cheapest correctness check is to show a small example of what you're about to build and ask whether that's what was meant.
- **Stop (when a reply finishes):** send the draft and recent turns to Jev. If anything applies, block the stop and give the model the matched questions to answer before the reply goes out. This catches "about to claim nothing exists" and "about to raise an objection".
- **After tool results:** catches "this result contradicts an earlier one".
- **Every N turns:** a broad, cheap check-in, like asking "is anything bugging you?".

## History log (Joe's practice)
Keep a log of every question asked, with its conditions and outcome. It works as a history, not a checklist, since the list has no end. Filter out questions already asked in this stretch, so the same one doesn't fire every time. With coordinates, "already asked" becomes an exact lookup.

## Who answers the selected questions
These are the two options. Joe hasn't decided between them yet.
- **The current model answers them itself.** Cheaper.
- **A second model answers them, and the current model gets the answers.** More independent, but it costs a model call each time the hook fires.

## Worth is a prior, not a filter
Jev's worth scores are judged with no particular situation in mind, for a generic careful reader. A cell that looks pointless in general can be exactly right in an unusual field: "combine broken parts" is central to security work. Use worth only to break ties when the context says nothing.

## No-tool fallback
Go through the library list yourself, completely, at the pre-commit moment. It's weaker, for the blind-spot reason above, but it's always available.

## Built: `scripts/select.py` (selection without hook plumbing)
One Jev call with one Noul per entry: "Would asking `library.X` right now be likely to change what happens next in `context`, by surfacing something not yet considered, checked, or asked?"
- Options: `--top`, `--threshold`, `--skip-asked` (filter using the history log), `--record` (append the selected entries to `asked.jsonl`).
- First test: a recreation of a known mistake: the draft reply misreading the user about "procedural prose", after the user had said they were phrasing it poorly. The top picks were right-question, process-check, completeness, goal, assumptions and restate: exactly the questions that would have caught it. The call cost $0.0003.
- The scores were compressed (0.71 to 0.78), so treat them as a ranking, not as calibrated probabilities.

## Lookbehind: labeling past conversations (designed; pilot next)
Run the axes backward over finished conversations. For each turn, ask:
- which value of each axis the turn *used* (a Choice including "None");
- which value it *should have used*;
- whether a mistake or surprise happened that a question asked beforehand could have caught, and which question would have caught it;
- what the right *response* to that occurrence would have been;
- which axis was most load-bearing.

Lookbehind produces the answer key, and the hook (lookahead) learns to predict it. Profiling development logs this way shows what a model struggles with and what it does well, and which signals predict that it's about to need a nudge.
- **Keep hindsight on one side.** Labels may use the whole transcript, because "should have" needs the outcome. Warning signals must use only what was visible before the turn; otherwise a signal works only because it has seen the future.
- **Corrections are the cheap anchor.** Ask "does turn N+1 correct or reject turn N?" as a Noul, and detect tool errors in code. The costlier questions then run only around those points.
- **It's also an axis test.** "A mistake happened that a question could have caught, but no axis value fits that question" is the collision test failing on real data.
- **Windows.** Send a window of turns as one state, with every question for every turn in it, including a few turns after the window so corrections stay visible.
- **Pilot:** this session's transcript. It contains known mistakes: misreading "procedural prose" three times, the 324-call audit, and building the grid before the user had confirmed the axes. Run it in a subagent, and bring back only the scores and the labeled mistake turns.
- **Scale the pilot into a profile table.** One session is the pilot; applied across sessions and models, lookbehind produces an agent-wide profile table of what each model struggles with and what it does well. That table feeds model choice (see the drone harness).

## Warnings: fire generously, phrase them as questions, learn from dismissals
- **A miss costs more than a false alarm.** So start sensitive and tune down with data.
- **Models don't get desensitized the way people do.** Their risk is different: a false stop sign acts like "are you sure?" and can flip a correct answer.
- **Phrase every warning as a question to answer:** "Here's a possible problem. Is it real, and why or why not?" That asks for information instead of asserting doubt.
- **Log every dismissal with its reason.** Each one is a labeled false positive, so the tuning data collects itself.
- **Stop signs are earned.** A signal becomes a stop sign only once its warnings have nearly always turned out to be real.

## Where warnings ride, and what they cost
A warning sent as its own turn makes the model re-read the whole context just to see it. A warning injected into a round trip that's already happening costs only its own tokens.
- **After a tool call** (extra context attached to the result): free.
- **Before a tool call** (deny the call, with a reason): free, because the denied call still comes back as the tool result. This is the place for the stop sign.
- **Before a tool call** (ask the user): for irreversible actions where the decision isn't the model's.
- **When a reply finishes** (block it): the expensive one, an extra pass over the full context. Use it only for very precise signals. The free alternative is to attach the warning to the user's next message, which is free but arrives late.
- **Latency:** sort calls in code first (deletes, pushes, sends, overwrites, spending), and judge only the flagged ones with Jev.

## Two kinds of danger, both prevented ahead of time
- **Destructive:** concentrated in one call ("the repo is gone").
- **Wasteful:** spread across many calls, where each call is innocent and the total is the damage ("all my usage for the week, spent fixing punctuation in public domain books"). Spent quota is irreversible too, just one small step at a time.
- **Neither should be handled reactively.** Cost isn't a threshold. The aim isn't "don't use tokens", it's "don't waste tokens on dumb stuff, make them count". So check value at planning time. For each planned step: what does it produce, who needs it, does it serve the goal, and what's the cheapest thing that can do it well? A step whose value can't be stated is the stop sign. Mark irreversible steps when planning, and put a backup, dry run or confirmation in front of them. The gate before a call is then the last line of defense, not the plan.
- **Exact token size can't be predicted, but the patterns are reliable.**
  - Talk is cheap and work is expensive.
  - Everything that enters context stays, and is paid for again on every later call.
  - Every tool call is a round trip, and tool output is mostly noise.
  
  So noisy work whose result is small goes to subagents. The head agent keeps intent, decisions and conclusions, and subagents keep the work and its raw material. Subagents can be thrown away, revived and composed, and they rarely compact. The head nearly always compacts unless it manages its context this way, and compaction loses nuance.

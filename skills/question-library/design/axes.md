# Design: faceted axes for questions

Status: still needs work. Version 1 of the axes is in `scripts/axes.py`. The collision test found what to change next. That list is at the end of this file.

## The idea (Joe's)
- **Each question is a point in a space.** Describe every question by its values on a set of axes. If the axes fully describe a question's nature, then identical axis values mean identical questions.
- **The collision test.** Two entries with the same coordinates are compared:
  - if they ask different things, the axes are missing something;
  - if they ask the same thing, it isn't two questions, so merge them.
  
  The test also runs the other way. An entry that needs two sets of coordinates is really several questions, so split it.
- **Combinations are questions.** Every combination of axis values is a question, so empty cells are questions nobody has written yet. This is Zwicky's morphological box and Ranganathan's faceted classification, applied to questions.
- **Coordinates are the question.** A question can be asked just by stating its coordinates, because a capable model reads a coordinate tuple as a fully specified question.
- **The hook can choose coordinates.** It can ask which combination of values would be most useful to ask right now (see `hook.md`).

## Version 1 axes (`scripts/axes.py`)
- **target**, what the question points at (15 values): goal, terms, scope, constraints, premises, evidence, explanations, approach, step, instrument, result, outcome, prior-work, self, inquiry.
- **move**, what it makes the answerer do (17 values): articulate, enumerate, justify, predict, check, compare, rank, decompose, combine, remove, perturb, invert, suppose-outcome, relate, generalize, find-gaps, locate.
- **stance** (4 values): neutral, doubting, adversarial, expansive.
- **perspective** (5 values): own, opposing, outsider, stakeholder, several.

Together that's 15 × 17 × 4 × 5 = 5,100 combinations. `render()` turns coordinates into a clunky English question. A missing axis renders generically, so a pair of axes can be read on its own.

Not axes of identity:
- **Stage** says *when* a question applies, not what it is. "Is each step correct?" is the same question during execution and in review. Stage belongs with the hook, as applicability metadata.
- **The old `action` tag** turned out to be a coarse mix of move and stance.

## What the tests found
- **The old tags:** 84 entries fell into only 61 distinct tag tuples. The 13 collision groups all held genuinely different questions, which exposed two missing axes: what the question points at (target), and what it makes you do (move).
- **Version 1 axes:** tagged by Jev in one batched run (2 requests, $0.004), the 84 entries fell into 78 distinct coordinates with 6 collision groups.
  - **info-need vs info-gap:** one asks now, the other after the fact. A **time** axis is missing (now, looking back, looking ahead).
  - **prior-relative vs reuse-existing:** one is about what you remember, the other about what you could find. A **source** axis is missing (memory, the user, the web, tools).
  - **success-drivers vs why-chain:** move needs a **trace-cause** value. "Why did it happen?" is different from justify ("how do you know?").
  - **synthesize vs auxiliary:** move needs an **introduce or re-represent** value (add a helper construct, or change the representation).
  - **premortem vs what-if:** these are one question, and the assumed outcome (failure, success, surprise) is a parameter of it.
  - **fewest-contradictions vs expected-vs-actual:** Jev mis-tagged this pair. 41 of the 336 tags came back with confidence under 0.5.
  - **disclose** is three questions in one entry. Split it, and merge its "anything bugging you" part with gut-check.
- **Background research** (`facet_research.md`) found no prior work that generates questions from combinations, or uses empty cells to find missing ones. Candidate axes it surfaced:
  - **criterion**, from Paul & Elder's intellectual standards: clarity, accuracy, depth, relevance, fairness, and so on;
  - answer shape;
  - is versus is-not, from Kepner-Tregoe;
  - level: the task, the method, the model, or the question itself.
- **Pair tables:** six pair tables, 563 cells, scored by Jev (`data/facets/pairs.json`, viewer `data/facets/axes.html`).
  - Every pair made sense. "Does it make sense?" scored 0.81 to 0.99 everywhere. That isn't a Jev failure: it means the axes are independent of each other, which is what good facet design aims for. Checking pairs doesn't shrink the space.
  - A worth Score (0 incoherent to 4 essential) ranged from 2.1 to 3.7. Row average plus column average explains 78 to 88% of the variation, so the information sits mostly in the individual values, not in their combinations. "combine" and "self" are weak everywhere; "articulate", "find-gaps" and "justify" are strong.
  - The cells far from what their row and column predict are the real interactions, and those are the ones worth reviewing.
  - Joe: every combination is a valid question. Whether it's a *good* one depends on the field and the situation. "Build something out of broken parts" sounds silly in general and is central to security work, as exploit chains. So worth is a prior at most, never a filter. Ranking belongs to the situation, which is the hook's job.
  - The funniest red cells ("Assume this is wrong. What could you build by combining parts of this?") were mostly the renderer's fault. Each template piece was written on its own and never referred to its neighbors. Connected, the same coordinates give a good question: "Assume it's broken. What could you salvage by recombining its parts?" This is the ablation-template rule: each slot is defined with its neighbors held fixed.
  - "Think about this." (neutral stance, own perspective, no target or move) is the zero point of the space, and correctly scores lowest.

## Stance has to split (Joe's distinction)
"Something may be wrong" and "assume this is wrong" are not one attitude at two strengths:
- **Stated belief:** the asker's credence ("may be wrong"). It has a direction (flaw or upside) and a degree. It signals the asker's view, so a sycophantic model may defer to it. This is the flip-risk kind.
- **Belief asked of the answerer:** "How confident are you?" carries no pressure.
- **Supposition, or acceptance:** "suppose X, whatever anyone believes." This isn't a value on an axis. It's a wrapper that takes a premise and a question, and gives back a question. "suppose-outcome", "invert" and "steelman-opposite" all reduce to supposition plus some move.

Hypothesis to test with flip-rate measurement: supposition questions flip answers much less than stated-belief questions, while still forcing the same check. If it holds, rewrite every doubting question as a supposition.

Two cleanups:
- "adversarial" currently says "or argues the opposite". That clause belongs to perspective (opposing), so it has leaked across axes. Remove it.
- At degree zero, direction doesn't exist: "neutral" has no direction.

## Structure: not a flat grid
- **Conditional axes and parameters.** Direction exists only when stance has a degree, and the outcome parameter exists only for supposition. Edges in the hypergraph have different sizes, and which axes a question has depends on its other values.
- **Typed feature structures** (from HPSG) are the established formalism for this: a value of one feature determines which other features apply.
- **Nesting.** Supposition and control flow mean questions contain other questions. The full answer is that a question is a small procedure, not a point; see `procedures.md`. The axis coordinates become that procedure's *signature*. Joe's collision test then says: two procedures with the same signature but different bodies means the signature is missing something.

## Next steps, in order
1. **Restructure the axes:**
   - split stance into stated belief, asked belief, and the supposition wrapper;
   - add time and source;
   - consider criterion;
   - add the move values trace-cause and introduce/re-represent;
   - make outcome a parameter of supposition;
   - remove the leaked clause from adversarial;
   - add a `scrutinizing` value to stance (open): ask the model to check its work without implying it is wrong, between neutral and doubting.
2. Re-tag all entries in one batched Jev call (`scripts/tag.py`) and re-run the collision test. Fix what collides, and repeat.
3. Rewrite the renderer so each template piece declares what it passes to the next, or replace it with procedures (`procedures.md`).
4. Add a "surprises" view to the viewer: the cells that score far from what their row and column predict.

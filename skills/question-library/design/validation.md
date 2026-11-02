# Design: three views, and how they diagnose each other

Status: worked out in conversation (Joe's framework). It applies well beyond this library. It's kept here because this is where it arose; if it keeps coming up elsewhere, it may deserve its own skill.

## The three views
The names are nicknames that drifted during exploration. Track the meaning, not the label.
- **Speaking:** semantics in life as prose. Words, human language, and meaning as someone understands it and can explain it.
- **Formal:** semantics as constraint. Code, math, computation: the precise definition, which always does *something*.
- **Being:** semantics expressed until it becomes what it embodies. The physical universe, the effect in reality, and whether that effect matches the intent.

None of the three *is* the semantics. Each is a view of the same thing. Penrose's three worlds (mental, mathematical, physical) form the same triangle. An engineering drawing is the working analogy: front, side and top views of one solid. No single view determines it, and inconsistency between views exposes a drafting error.
- **Open (q30): what is the object these three are views of?** Speaking, formal and being are treated as three views of one thing, but the underlying object has no name yet. Penrose's three worlds are the nearest known mapping, not the object itself.

## Valid means all three agree
- **The standard:** casual semantics, formal semantics and implemented semantics all agree: "a consensus between speaking, thinking, and being."
- **Prose and formal agreeing is not proof.** Both are written by the same understanding, so they can agree with each other and both be wrong in the same way.
- **Only tests are proof.** A test is the only view that runs against something outside your own head.
- **Working order is a choice.** Either expand and collapse repeatedly, or build fully in prose and collapse once.
- **The formal form lints the prose.** If the syntax won't check out, that's information the prose construction missed.

## The eight states
Each view is binary: complete and correct, or broken. "Broken" means anything else: absent, partial, wrong, mangled.
- **None of the three:** nothing exists yet.
- **Speaking only:** an idea, or a story about how something should work. Every idea is born in this state. Requiring an idea to be correct the moment it's built (all three views at birth) kills ideas in the crib. Judge each stage by what that stage can deliver.
- **Formal only:** syntactically valid code that does exactly what it says, but isn't understood and doesn't do what was expected. "The computer does what you tell it, not what you meant." This is what a bug is.
- **Being only:** it works, but nobody understands it and there's no manual. Legacy systems, biology, trained neural networks: weights are the artifact, not a definition you can read. This is the hardest state to get out of. You can only probe and infer, which is reverse engineering and is science in general. With no manual, the log of what's been probed becomes the manual.
- **Speaking and formal:** designed and specified, but never run. This library today.
- **Speaking and being:** a dependency, a black-box contract, an abstraction. You rely on it and know how to use it, but don't hold its formal definition.
- **Formal and being:** copy-pasted code that works. It's correct and it runs, but nobody understands why, so nobody can adapt it, debug it, or reuse the idea.
- **All three:** proven.

## A missing view isn't always a defect
With a dependency, the formal view exists, but its maintainers hold it, and a contract sits at the boundary. So the rule is:
- a broken view is fine when someone accountable holds it and a contract covers the boundary;
- it's a defect when nobody holds it.

A black box can only be tested at its boundary. Everything learned about Jev (first-option bias, saturating absolute scores, lenient coherence judgments) came from boundary tests, which means those findings are its contract.

## Cross-diagnosis is translation
Each view is a language, and a failed translation is the symptom:
| direction | the check | if it fails, the problem is in |
|---|---|---|
| speaking to formal | collapse the prose to notation | the prose is vague |
| formal to speaking | gloss the notation | the line was never understood ("under [2]") |
| speaking to being | predict, run, compare (expected versus actual) | understanding or the implementation |
| being to speaking | watch it work and explain why (success-drivers) | understanding is missing (the copy-paste case) |
| formal to being | run the spec (unit tests) | the spec or the implementation |
| being to formal | derive a spec from behavior (characterization tests) | the spec is missing or wrong |

- **A cheap fourth check:** going from prose to formal and back should give the same meaning. Anything lost on that round trip is caught mechanically, before writing a single test.
- **Which check fails tells you where the error lives:**
  - prose doesn't make sense: the idea wasn't thought through;
  - prose is fine but formal won't lint: a structural gap;
  - both look fine but the test fails: the error is shared, so it sits in the understanding itself. That's the most valuable failure to find.
- **When something misbehaves and nobody can say what's wrong,** the speaking view is the broken one. So the first repair is to say what you expected (expected-vs-actual), before any testing.

## Why three
- **Detection needs a second view.** A view that's wrong but looks complete doesn't show itself. Absent shows; partial usually shows; wrong feels complete from the inside. Only disagreement with another view catches it.
- **Locating the error needs a third.** With two views, you only know that they disagree. With three, the odd one out is the likely culprit. That's Segal's law (a man with two watches is never sure what time it is) and triple modular redundancy with voting.
- **The views must be independent.** Agreement counts only as much as the sources are independent. Correlated sources, such as several samples from one model, agree for free, the way a quorum-sensing crowd does. The three views are different kinds of description, so their errors are less likely to coincide. Being, as reality, is the natural tiebreaker.
- **Pairwise agreement isn't global consistency.** Penrose's impossible triangle is consistent at every corner, with no object behind it. So check the whole loop too: speaking to formal to being and back to speaking should return where it started.

## For this library
- Every entry is currently "speaking and formal": it looks solid, and it's unproven.
- The worked examples are the test specifications.
- The test run is the debrief replay plus flip and fix measurement: give a model a case whose correct outcome is known, let it run the question, and check where it lands.
- A useful hypothesis: many of the library's questions may be these six translation checks in disguise. "Restate" is formal to speaking, "expected vs actual" is speaking to being, "success-drivers" is being to speaking. If so, "which views does this question compare, and in which direction" could be the organizing axis the library has been missing.

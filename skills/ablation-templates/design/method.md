# Ablation templates: the method in full

## The construction (Joe's)
1. **Ablate one term.** Take any lone sentence. Ablate exactly one semantic term, and replace it with a description of what words could fill the slot. The description must not name the original word.
2. **Hold the rest fixed.** Every other word stays frozen, syntactically and semantically. For any filler that satisfies the description, the other terms' meanings and their relations, to each other and to the slot, stay unchanged.
3. **Maximize the range.** Make the set of fillers the description allows as large as possible. That gives the weakest precondition the context actually imposes: the slot's contract, its type.
4. **Repeat for every term.** Do this for each term, in isolation. Each contract already pins its relations to the other slots and frees only the content, so the contracts compose by conjunction.
5. **The composite is the template.** All the contracts together are the sentence's template: its full relational structure, with zero content. That's the sentence's signature and its root semantic foundation.

## What it gives
- **The right middle ground.** It shrinks the semantic space far more usefully than part-of-speech slots ("a noun goes here"), and infinitely more than an unconstrained blank. It keeps exactly the relations and drops exactly the content.
- **Far fewer templates than sentences, by construction.** One template covers every combination of valid fillers across its slots. That follows from the definition and needs no experiment.
- **Meaning-equivalence.** Sentences that fit the same template say the same thing structurally, about different things. Translation becomes refilling the template from another lexicon. Compression becomes a template id plus a tuple of fillers.
- **A word's real information.** Each word splits into what its context already guaranteed (the slot's type) and what only the word supplies (the remainder).
- **Function words probably dissolve into edges.** Words like "of" and "the" likely become the relations between content slots. So a template is a graph: content slots are the nodes, and typed relations are the edges.
- **The description regress bottoms out.** Contracts are written in words, and those words can be ablated too. The regress ends in a small primitive vocabulary, similar to Wierzbicka's semantic primes.

## Existing names, for literature searches
- **The commutation test** (Jakobson, Barthes) is the single-slot move. The valid fillers form a paradigmatic class; this method writes that class as a description instead of a list.
- **A fully schematic construction** in Construction Grammar (Goldberg) is the composite. But here it's derived bottom-up from a single sentence, not identified across a corpus.
- **The closest computational work** is "Constructions are Revealed in Word Distributions" (arXiv 2503.06048). It measures how tightly context constrains each slot, but never writes the contract down.
- **Evidence that structure carries meaning:** Lupyan and Agüera y Arcas, "The unreasonable effectiveness of pattern matching" (arXiv 2601.11432). LLMs recover meaning from Jabberwocky sentences.
- **No name was found for the whole procedure.**
- **Proposed names from the session, not yet checked against outside usage:** *exhaustive intensional commutation* for the whole procedure, and *derived schematic construction* for the composite.
- **Open (q4):** whether a linguistic precedent for the full void-composite exists. The parts have named precedents (commutation test, schematic construction); the whole may not.

## How Jev fits (jev-toolkit skill)
- **Jev can't write a contract, but it can test one.** Code or an LLM proposes candidate fillers. One Noul per candidate asks whether it fits with every other term's meaning and relations unchanged, all in one call. The accepted set is the contract, given extensionally.
- **Recognizing the same template under different wording is plumbing, not a threat to the idea.** Sample fillers from each template and check them against the other's contracts.
- **Structure can be built by selection.** With numbered pieces (jevask's `[44]` references) and templates, Jev can assemble structure by choosing slot fillers from its own answers, one choice at a time. This is the route to a lightweight "sift" parser that turns prose into structured trees.

## Ties to other work
- **Question library, debrief.** The `probe-gen` debrief question ("what generic question would have led you there?") is this same ablation, applied to one missing fact: strip every specific and keep the relation.
- **Question library, rendering.** Rendered questions read absurdly when each template piece was written in isolation. That broke the rule here that each slot is defined with its neighbors held fixed. Numbered-statement procedures (`question-library/design/procedures.md`) make the relations between slots explicit.
- **Question library, three views.** An ablation template is the formal view of a sentence, and its gloss is the speaking view (see `question-library/design/validation.md`).
- **The PRH/ARH paper** (Joe's "One structure, two vantage points"). If different systems converge on a shared structure, that structure is what templates would write down. Templates are a candidate formal notation for the shared target.

## Don't regress
- **Neighbors held fixed is part of the spec.** Joe's definition already requires the neighbors' meanings and relations to stay fixed for every filler. Don't raise "each void was computed with its neighbors" as a flaw.
- **The reduction isn't in doubt.** Don't present template de-duplication as doubt about "far fewer templates than sentences"; that follows from the definition.

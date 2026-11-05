---
name: ablation-templates
description: Joe's ablation-template method. Turn a sentence into a content-free template by replacing each term with a meaning-invariant contract on its slot; the composite of contracts is the sentence's signature. Use when working on universal semantics, sentence signatures or templates, meaning-preserving compression or translation, slot contracts, generic-question generation (the probe-gen debrief), or building structure by selection with Jev.
---

# ablation-templates

## Status
| part | state |
|---|---|
| method | complete as a concept, worked out in conversation |
| prototype | not started. Next step: a few sentences, with code or an LLM proposing candidate fillers and one Jev Noul per candidate checking it against the slot's contract |
| literature search | done once: no name was found for the whole procedure (see `design/method.md`) |

## The method in brief
1. Take a lone sentence and ablate one semantic term. Replace it with a description of what could fill the slot, without naming the original word.
2. Hold every other term fixed: for any valid filler, the other terms' meanings and their relations stay unchanged.
3. Make the description as broad as possible, the weakest precondition the context actually imposes. That's the slot's contract, its type.
4. Do this for every term, each in isolation. The contracts compose by conjunction.
5. The composite is the sentence's template: its full relational structure with no content. That's the sentence's signature.

There are far fewer templates than sentences, and that follows from the definition: one template covers every combination of valid fillers. Don't present this as something needing an experiment, and don't raise "each slot was computed with its neighbors" as a flaw. Holding the neighbors fixed is part of the definition.

## Read next
- `design/method.md`: the full method, what it gives, the existing names for its parts, how Jev fits, its ties to the question library and to the PRH/ARH paper, and the things not to regress.

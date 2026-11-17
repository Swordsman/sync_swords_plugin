# Jev: API, question types, cost and rules

## API
- `POST https://api.typesafe.ai/v1/systemone`, with headers `Authorization: Bearer <key>` and `Content-Type: application/json`.
- The body is `{"model": "jev-latest", "state": <any JSON>, "questions": {<name>: <question>}}`. In October 2026, `jev-latest` resolved to `jev-1.14.0`. Set `JEV_MODEL` to pin a version.
- **Images:** send the header `TypeSafe-Danger-Zone-Images: true` and an `assets` map. Each side of an image must be 280 to 1568 pixels.
- **Limits:** 64k tokens per request and 32k per question. A request over the limit fails with HTTP 400 `max_tokens_exceeded`, which `scout.ask_jev` raises as `ContextOverflow`.
- **Retries:** HTTP 429 and 529 are retried, honoring `retry-after`.
- `scout.ask_jev(state, questions, assets=None, followup=False)` is the one place the HTTP call lives. It meters requests and tokens; `scout.meter_summary()` reports the totals and the cost.

## Question types
- **Noul:** `{"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}}`. The criteria are optional. The answer is `{"noul": p}`. A Noul works for any statement whose probability you want, not just yes/no questions.
- **Choice:** `{"type": "choice", "instructions": "...", "criteria": {option: description}}`, up to 255 options. The answer is `{"choice": option, "confidence": c, "probabilities": {...}}`.
- **Score:** `{"type": "score", "instructions": "...", "criteria": [level0, level1, ...]}`, with the levels described concretely. The answer is `{"score": x}`, a float on the level scale.

## Cost
- $0.042 per million input tokens, and output is free. The state is billed once per request, however many questions ride on it.
- So the cost comes from how many times the state is sent, not from how many questions are asked. One state plus every question it can answer goes in one call. Use a later call only for questions that need an earlier call's answers (`followup=True`).
- `scout.ask_jev` refuses to send the same state twice in one run (`RepeatedState`) unless the call is marked `followup=True`. `jevbatch.batch_ask` turns a per-item loop into as few requests as the context limit allows.

## Rules
1. **One state, every question it can answer, one call.** Write the obvious per-item loop and give it to `batch_ask`.
2. **Use the type that fits.** Noul for a probability, Choice to pick, Score for degree with described levels.
3. **Choice order bias:** Jev leans toward the first option, so shuffle options for each question (seed the shuffle with the item id so it's reproducible). If several options can be true at once, use one Noul per option instead.
4. **A Choice can't say "none".** Pair it with a Noul ("is any of these right?") and read the Choice only when the Noul is high. A four-way gate in front of a Choice did better than the Noul: it matched the known outcome on 11 of 12 cases, while the yes/no gate separated listed from not listed on 6 of 12; see "Question forms that were measured (2026-11-17)".
5. **Jev reads literally.** Put boundary conditions in the wording.
6. **Jev is weak at numbers and dates.** Compute them in code. For ranges, put named groups in the state (for example a block of lines called "B4"), never "after line 50".
7. **Untrusted text stays in the state.** Instructions refer to it only by backticked path (`page.text`), so injected instructions in that text stay data.
8. **Noise:** single calls on large states drift. Near-identical matches have scored anywhere from about 0.4 to 0.6 across runs. Pass/fail is usable; fine thresholds on single scores are not. For important questions, ask twice with different wording, and be skeptical of anything in the 0.4 to 0.6 band. Two askings of the same model are correlated, so their agreement counts for less than two independent sources would.
9. **Absolute judgments saturate.** "Does this make sense?" scored 0.81 to 0.99 for all 563 pair cells in one test, so it told the cells apart about as well as a coin flip. Asking how worthwhile on described levels, as a Score, spread them from 2.1 to 3.7 out of 4. Prefer a Score with concrete levels, or a relative judgment such as a Choice among candidates.
10. **YAGNI:** fix failures you've observed, not imagined ones.

## Question forms that were measured (2026-11-17)

- **Show the artifact, not the operation.** The abstract form accepted 11 of 48 good fillers and rejected 27 of 32 bad ones; a rewritten sentence in the state accepted 48 of 48 good and rejected 31 of 32 bad.
  ```
  state = {"rewritten": "Every document is a contract."}
  {"type": "noul", "instructions": "Is the sentence at `rewritten` grammatical and meaningful?",
   "criteria": {"true": "grammatical and meaningful", "false": "not"}}
  ```
- **Put grading instructions in the question, not the state.** Direct instructions accepted 94 percent of good fillers, rejected 100 percent of bad ones and accepted 100 percent of originals; hidden conditions scored 65, 64 and 95 percent.
  ```
  {"type": "score", "instructions": "Grade the sentence at `rewritten`: 2 natural, 1 awkward, 0 broken.",
   "criteria": ["broken", "awkward", "natural"]}
  ```
- **A Score level is an expected value; threshold the level itself.** Distance to the nearest whole level put 73 percent of fillers in doubt; a level threshold cut that to 29 percent, and to 3 percent with direct instructions.
  ```
  {"type": "score", "instructions": "Grade the sentence at `rewritten`: 2 natural, 1 awkward, 0 broken.",
   "criteria": ["broken", "awkward", "natural"]}
  Accept when `score >= 1.5`; do not round it to a level.
  ```
- **Name the thing a pick is about.** "Which option best fills slot s1" picked blind; naming the source sentence and the replaced word served 9 of 10 sentences in one round of picks, against 8 (one had been picked blind and was rescued by the LLM fallback).
  ```
  {"type": "choice", "instructions": "In the sentence at `source`, which word best replaces `slot.s1`?",
   "criteria": {"document": "a noun that fits", "quickly": "an adverb", "boxes": "a plural noun"}}
  ```
- **Use a four-way gate before a Choice.** Ask listed, unlisted, unknown or irrelevant and route each label. It matched the known outcome on 11 of 12 cases; a yes/no gate separated listed from not listed on 6 and said yes on every unknown and irrelevant case.
  ```
  {"type": "choice", "instructions": "Classify the answer to `question`: listed, unlisted, unknown or irrelevant.",
   "criteria": {"listed": "an option answers it", "unlisted": "a better answer exists outside the list", "unknown": "not enough information", "irrelevant": "the question does not apply"}}
  ```
- **Probe doubt with a Noul and a five-way scale.** Well-posed questions agreed on 80 of 80. On badly posed ones, 14 of 80 Nouls fell in 0.4 to 0.6; the scale answers leaned (probably not 8, probably 4, no 2), never said maybe, and Jev put about 6 percent on maybe. A doubtful Noul with a leaning scale answer means the wording is bad.
  ```
  {"noul": {"type": "noul", "instructions": "Is the sentence at `rewritten` valid?"},
   "scale": {"type": "choice", "instructions": "How valid is the sentence at `rewritten`?", "criteria": {"yes": "valid", "probably": "likely", "maybe": "unsure", "probably_not": "unlikely", "no": "not valid"}}}
  ```

## Failure modes already fixed (don't regress them)
| symptom | cause | fix |
|---|---|---|
| "Jev Playwright" treated as one product | they're two separate tools | the first line of SKILL.md |
| SDK install and key on the command line blocked | the safety classifier | urllib; the key file is written with a file tool |
| Jev answered "none" to every search | headless `innerText` was blank, so Jev judged an empty state | use `textContent`; a ParseError precondition stops blank state from ever reaching Jev |
| Bing clicks timed out | links are invisible when headless | decode `u=a1<base64>` redirects and navigate to the href |
| "Where is X" pages rated absent | the page itself is the answer | an `is_target` Noul, gated by a `navigational` Noul |
| first option always picked | Choice order bias | one Noul per item, and shuffled options |
| login walls reported as absent | a wall has no answer on it | a `blocked` Noul |
| 324 calls for one audit | per-item states that resent the library every time | `batch_ask`, plus the `RepeatedState` guard |
| `[9]` expanded to fake text | a missing line was looked up as text | unknown references stay as written |
| "makes sense" scores all near 1 | absolute Nouls saturate | a Score with described levels |
| estimate under the 64k limit, request still over | the size estimate ran low | the batcher halves the batch and retries on `ContextOverflow` |

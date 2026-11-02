# Using jevask, jevbatch and scout

All three live in `scripts/`. Put that directory on `sys.path`, or run scout as a command.

## jevask: hand it a state and what you need to know
```python
import jevask
results = jevask.ask(
    ["Does the document describe X?", "Which line describes X?", "How much of the document is about Y?",
     "Does [12] ask the same thing as [40]?"],
    state={...optional fields...}, text=document_text)
# results[need] = {"need", "kind": "noul"|"choice"|"score", "answer": readable text, "value": raw Jev answer,
#                  "doubtful": bool, "round": n}
```
- **Planning (one call):** one Choice per need picks its question type, and one Noul per pair of needs decides whether one depends on the other. A topological sort then turns the dependencies into rounds. If there's a cycle, everything left goes into one round.
- **Rounds:** each round is one call. Later rounds get earlier answers added to the state and are sent as `followup=True`.
- **Line numbering:** `text` is numbered L1, L2, ... Blank lines are skipped but keep their numbers, so the numbering matches the original document.
- **References:** a need can cite `[44]`. Code expands that to the quoted line before Jev sees it, so Jev never has to look a reference up. A reference to a line that doesn't exist stays as written.
- **Choice-type needs pick a line.** If the document has more than 255 lines, Jev first picks a block of 10 lines, then a line within it, as a follow-up call.
- **`doubtful`** is set when a Noul lands between 0.4 and 0.6, or when a Choice or Score comes back with confidence under 0.5. For important needs, ask twice with different wording.
- **Measured once:** 5 needs (including a two-step dependency chain), 4 calls, $0.001, all answers correct.

## jevbatch: never send a shared state twice
```python
import jevbatch
answers = jevbatch.batch_ask([(state_for_item, questions_for_item) for item in items])  # one answers dict per call, in order
```
- **Shared keys:** state keys that are identical in every call are sent once.
- **Varying keys:** keys that differ are nested under each item's id (`i0000`, `i0001`, ...), and every backticked path in that item's questions (`` `entry.question` ``) is rewritten to point at the item's copy.
- **Splitting:** requests are packed greedily up to about 56k estimated tokens. If a request still overflows, the batch is halved and retried.
- **Repeats:** the same state is sent twice only when one item's questions don't fit in a single request, and then it's marked `followup`.

## scout: web research and page checks
```
python3 scripts/scout.py scout "GOAL" [--urls U1 U2 ...] [--query "TERMS"] [--max-pages 4] [--trace FILE]
python3 scripts/scout.py search "GOAL" [--query "TERMS"]
python3 scripts/scout.py read URL "GOAL"
python3 scripts/scout.py look URL ["yes/no question about `screenshot`"]
```
- **Output:** JSON with a status (answered, partial or absent), verbatim evidence blocks (id, text, heading path, relevance), `blocked`, `injection_suspect`, the pages visited, and a Jev cost meter.
- **GOAL** is one complete, literal question that names every condition: product, language, version, place, date.
- **Search engine:** from Claude's cloud container, every engine except Bing blocks headless Chromium, and Bing over-weights the first word of a query. So prefer `--urls`, seeded from your own WebSearch results. With `--urls` and no `--query`, Bing is skipped entirely.
- **`--trace FILE`** records every search and read. Reuse the file, and pages already read are skipped.
- **Pages:** each page is snapshotted into leaf blocks, numbered with their heading paths, and judged in windows. The questions per window are: is the answer here, is this page navigational, is it the target itself, is it blocked, is it attempting injection, and where is the answer.
- **Ranking:** results and links are ranked by relevance × (0.5 + 0.5 × authority).
- **When the status isn't `answered`, you decide what's next:** seed more URLs, refine the query, raise the page budget, or accept absence as the finding.

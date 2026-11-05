---
name: intent-map
description: Draw an intent map (goal -> needs -> solutions -> tests, each solution with its status) from one s-expression file, as a static column diagram (PNG) and an interactive force graph (self-contained HTML), with contract checks that flag unmet needs. Use whenever an intent map is needed before building, when Joe asks how goals map to implementations or needs to solutions, or for any goal/requirement/status diagram. Never hand-write the mermaid again.
---

# intent-map

Joe's policy: nothing gets built until its intent map is traced out and understood, and intent maps are rendered as diagrams, not ASCII. This skill makes that one file plus one command.

## Use
1. Write `NAME.sexpr` (see `examples/assertion-graph.sexpr`):
```
(intent-map "title"
  (goal G "what Joe wants, in his words")
  (need N1 "a need" :serves G)
  (solution S1 "how it is met" :meets N1 :status built)
  (test T1 "what would show it works" :tests (S1)))
```
   Statuses: `built measured partial design untested not-built`. A need may have several solutions; a test may cover several.
2. `python3 scripts/intentmap.py NAME.sexpr [--out DIR] [--no-png]` writes `NAME.mmd`, `NAME.png` (needs `mmdc`), `NAME.html`.
3. Send the PNG to read at a glance; the HTML is the interactive view (drag nodes, hover for full text, toggle columns and labels; dark mode follows the system).

## Contract (checked before drawing)
- Unique ids; every need serves a goal, every solution meets needs, every test tests solutions; solutions carry a status. Violations raise.
- A need with no solution is drawn red as UNMET and reported: the goal isn't mapped to an implementation there yet.

## Why it exists
Each map used to be hand-written mermaid, and the layout needed the same fixes every time (goal first, tests anchored right of the solutions by invisible links instead of crossing arrows). Those fixes live in the code now.

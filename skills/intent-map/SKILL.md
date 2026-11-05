---
name: intent-map
description: Draw an intent map (goal -> needs -> solutions -> tests, each solution with its status) from one s-expression file, as a static column diagram (PNG) and an interactive force graph with animated flow edges, published as an HTML artifact, with contract checks that flag unmet needs. Use whenever an intent map is needed before building, when Joe asks how goals map to implementations or needs to solutions, or for any goal/requirement/status diagram. Never hand-write the mermaid again.
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
   Statuses: `built measured partial design untested not-built`. A need may have several solutions; a test may cover several. Any node takes `:icon "🚀"` to override its default emoji (goal 🎯, need 🧩, test 🧪, unmet ❗, built ✅, measured 📏, partial 🌓, design 📝, untested ❔, not-built ⛔).
2. `python3 scripts/intentmap.py NAME.sexpr [--out DIR] [--no-png]` writes `NAME.mmd`, `NAME.png` (needs `mmdc`), `NAME.html`.
3. **Look before publishing (required).** `node scripts/shoot.js NAME.html PREFIX` renders the page the way the artifact viewer wraps it, at panel width (light), desktop (dark) and phone (light), and reports script errors and horizontal overflow. Open the screenshots and look at them. "No errors" is not "looks right": on 2026-11-05 a page with zero errors had every card drifted to the bottom of a 4000 px stage, and an earlier one had labels piled on top of each other at viewer width.
4. **Publish the HTML as an artifact** with the Artifact tool (`file_path` = `NAME.html`; on the first publish pass `icon: "diagram"` and a one-sentence `description`). Republishing the same path updates the same page, so Joe keeps one link per map. Send the PNG too when a still picture helps.

## The interactive page
Cards in four columns (goal, needs, solutions, tests), each with its emoji, id, full text, a status chip and "tested by". Column order is chosen to reduce edge crossings. Edges are curves between card sides and animate in their flow direction (goal -> need -> solution; tests dotted, toward what they test). Hover or focus a card to light up everything upstream and downstream of it; click to pin that. Drag cards; drag empty space to pan; the scroll wheel zooms at the cursor and two fingers pinch-zoom; `fit` and `100%` reset the view; `flow` pauses the animation (reduced-motion settings stop it).

## Contract (checked before drawing)
- Unique ids; every need serves a goal, every solution meets needs, every test tests solutions; solutions carry a status. Violations raise.
- A need with no solution is drawn red as UNMET and reported: the goal isn't mapped to an implementation there yet.

## Why it exists
Each map used to be hand-written mermaid, and the layout needed the same fixes every time (goal first, tests anchored right of the solutions by invisible links instead of crossing arrows). Those fixes live in the code now. The page script lives in `scripts/page.html`, a plain file, because a JS template inside a Python string turned a `\\n` into a raw newline and broke the script; `test_intentmap.py` runs `node --check` on the generated script.

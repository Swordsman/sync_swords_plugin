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
  (project "name")                       ; optional: groups the map in the viewer
  (ref other-slug "why")                 ; optional, repeatable: this map builds on / refers to another stored map
  (goal G "what Joe wants, in his words")
  (need N1 "a need" :serves G)
  (solution S1 "how it is met" :meets N1 :status built)
  (test T1 "what would show it works" :tests (S1)))
```
   Statuses: `built measured partial design untested not-built`. A need may have several solutions; a test may cover several. Any node takes `:group "name"` (its meta-node in node view; default: its kind) and `:icon "🚀"` to override its default emoji (goal 🎯, need 🧩, test 🧪, unmet ❗, built ✅, measured 📏, partial 🌓, design 📝, untested ❔, not-built ⛔).
2. `python3 scripts/intentmap.py NAME.sexpr [--out DIR] [--no-png] [--store URL]` writes `NAME.mmd`, `NAME.png` (needs `mmdc`), `NAME.html`. `--store` also writes the map to the Intent Maps store (below).
3. **Look before publishing (required).** `node scripts/shoot.js NAME.html PREFIX` renders the page the way the artifact viewer wraps it, at panel width (light), desktop (dark) and phone (light), plus node view by kind and by group, and reports script errors and horizontal overflow. Open the screenshots and look at them. "No errors" is not "looks right": on 2026-11-05 a page with zero errors had every card drifted to the bottom of a 4000 px stage, and an earlier one had labels piled on top of each other at viewer width.
4. **Publish the HTML as an artifact** with the Artifact tool (`file_path` = `NAME.html`; on the first publish pass `icon: "diagram"` and a one-sentence `description`). Republishing the same path updates the same page, so Joe keeps one link per map. Send the PNG too when a still picture helps.

## The Intent Maps store and viewer
One giant artifact holds every map as data, so creating or editing a map costs no tokens and no republish: `--store URL` writes `maps/<slug>` (slug = file name without `.sexpr`: letters, digits, hyphens) with `{slug, title, project, goal, sexpr, data, refs, counts, updatedAt}`, where `data` is exactly what the page renders, and registers the `maps` collection in the catalog. Pushing a file again replaces its doc. Needs a claude.ai/code session (lsdb; see the lsdb skill). It prints one line.
- `(project "name")` groups maps; `(ref other-slug "why")` says this map builds on or refers to another (it may be stored later; the viewer ignores refs to maps it doesn't have). Both are optional, so old maps still read.
- The viewer is `viewer/viewer.html` plus `viewer/js/` and the shared `engine/`. It is a thin loader: a list of maps by project (live), `#<slug>` opens a map with the same engine as the standalone page, and the overview (no hash or `#overview`) draws every map as a node, explicit refs as solid arrows, and suggested links dashed and labelled with the shared terms (computed in the page from goal/need/solution text, thresholded and capped per map). It explains itself on the page.
- Publish it once with the Artifact tool, `capabilities: {"db": {}}`, `file_path` = `skills/intent-map/viewer/viewer.html` and this `files` map (published path: source), with `<plugin>` the plugin root:
```
js/app.js js/store.js js/list.js js/mapview.js js/overview.js js/correlate.js   <- <plugin>/skills/intent-map/viewer/js/<same>
engine/map.css engine/util.js engine/params.js engine/graph.js engine/light.js engine/edges.js engine/draw.js engine/view.js
engine/tween.js engine/drag.js engine/attract.js engine/links.js engine/behaviors.js engine/rules.js engine/presets.js
engine/controls.js engine/mount.js
                                                                                 <- <plugin>/skills/intent-map/engine/<same>
```
  Republishing is only needed when the viewer or engine code changes, never for new maps.
- Each account has its own store: an artifact's db is only reachable from code by its owner. The account's Intent Maps URL is kept in Claude's memory, not in this skill. If memory has none, publish the viewer as above and record the URL there.
- Check changes with `node viewer/test/check.js SEED.json OUT_PREFIX` (SEED from `python3 viewer/test/seed.py [SLUG...]`): it serves the viewer against a mock db, checks the list, overview edges, a map, the camera clamp and console errors, and writes screenshots. Look at them. `node viewer/test/rules.js SEED.json` lays a real map out under each edge rule and prints before/after numbers (angle evenness, length by priority, length spread).

## The interactive page
Two views, switched with `cards` / `nodes` (the choice is remembered per viewer).
- **Cards**: four columns (goal, needs, solutions, tests) of cards with emoji, id, full text, status chip and "tested by"; column order chosen to reduce edge crossings.
- **Nodes**: a force graph. Meta-nodes (dashed rings) group it: each attracts its members and repels everyone else. `group by kind` holds goal / needs / solutions / tests in a row, left to right; `group by group` uses the map's `:group "name"` values, and those meta-nodes follow their members while pushing other groups away; `nothing` lets it float. Drag a meta-node to move its group; it stays where you drop it. Hover a node for its full text; `labels` hides the text.
- **Switching** cards <-> nodes morphs: every node travels from where it was to where the new rules put it (about 0.9 s; cards shrink into dots as the dots fade in, and back), and the camera glides to the new framing. Reduced-motion settings jump instead; grabbing the graph ends the animation.
- **Both**: edges are thick wires with neon-yellow electrons flowing in their direction (goal -> need -> solution; tests dotted, toward what they test). Hover or focus anything to light up its upstream and downstream; click to pin. Drag to move things, drag empty space to pan, scroll wheel zooms at the cursor, two fingers pinch; `fit`, `100%`, `flow` (pause). Reduced-motion settings stop the electrons.

## Rules (the engine under both views)
Both views are rulesets on one engine (`engine/`: `behaviors.js`, `attract.js`, `rules.js`, `presets.js`; `intentmap.py` inlines the modules into `page.html`, the viewer imports them, so there is one copy). `mountMap(root, {nodes, links, warnings}, {presets, modes, ...})` is the data-in boundary and knows nothing about intent maps: the viewer's overview is just another ruleset over map nodes (link `weight` scales a spring; link `label` is drawn at its midpoint; `seed: true` spreads nodes before a force layout). A rule is `{id, on, do: [[behavior, params], ...]}`.
- `on` selects nodes: `{}` is all; `kind`/`status`/`style`/`group`/`id` take a value or a list; `priority` takes `[op, n]`. Any node takes `:priority N` in the sexpr.
- `edges` selects links among the selected nodes: `{kind, from, to, end}` (`kind` a link kind or list; `from`/`to`/`end` are node selectors for the link's source, target, or either end). Without it, every link between selected nodes.
- Behaviors: look (`shape` card|dot, `size`, `style`), setup (`order-by`), node forces (`repel`, `gravity`, `attract` = a meta-node per value of `by`, optionally a held row), link forces (`spring`, `balance` = each link toward its group's mean length (`per`: a link field), `direction` = targets lie `gap` beyond sources along an axis, `spread` = a node's links fan out at even angles), constraints (`column`, `relax`, `stack`, `align`, `pin`). Each tick: forces, integrate, constraints in rule order. No `bundle` yet.
- Wherever a behavior takes a number that has a subject (a node or a link), it may follow a field: `{scale: "priority", from: [0, 3], to: [150, 60]}` holds the field to [lo, hi] and maps it onto [a, b]; a link reads the field from itself, else from its two ends (`of`: max by default, min, mean). Params with no subject (`column` pitch, `stack` gap) cannot, and a rule that tries says so as a warning.
- A ruleset is `{live, settle, top, fit, sweep, rules}`: live ones tick every frame; the others settle and hold still. A live one with `settle: N` also runs N ticks before a view switch travels to it, so the morph lands on a settled picture. `sweep: {key, order}` runs constraints one group at a time.
- The `nodes` preset gives edges the length and stiffness of their more important end's priority (150 long and loose at 0, 50 and stiff at 5; no priorities, no change), sizes dots a little by priority and fans every node's links (`spread`). Mark a node's weight in the sexpr with `:priority N` (0-5).
- `tween.js` is the one morph utility: it carries nodes (position, size, card-ness) and the camera from a layout snapshot to a target layout that is asked for each frame, so a live layout, or any other source of layouts, can be the target.
- An unknown behavior name is shown as a warning, not swallowed. The grouping dropdown edits the `groups` rule at runtime.
- The camera is clamped: panning or zooming can't take the graph out of view (a node always stays inside).
- Check a change to the engine against the old page with animation off (`reducedMotion: "reduce"`): the card preset should stay pixel-identical. `node scripts/morph.js PAGE.html PREFIX` toggles cards -> nodes -> cards on a fake clock, saves frames mid-tween and at rest, and checks nothing is left half-morphed (look at the frames).

## Contract (checked before drawing)
- Unique ids; every need serves a goal, every solution meets needs, every test tests solutions; solutions carry a status. Violations raise.
- A need with no solution is drawn red as UNMET and reported: the goal isn't mapped to an implementation there yet.

## Why it exists
Each map used to be hand-written mermaid, and the layout needed the same fixes every time (goal first, tests anchored right of the solutions by invisible links instead of crossing arrows). Those fixes live in the code now. The page template lives in `scripts/page.html`, a plain file (the script is bundled from `engine/` by `imrender.engine_script()`), because a JS template inside a Python string turned a `\\n` into a raw newline and broke the script; `test_intentmap.py` runs `node --check` on the generated script.

## Code layout
`scripts/intentmap.py` is the CLI; `imparse.py` (reading, project/ref), `imcheck.py` (contract, counts), `imrender.py` (mermaid, page data, page bundling), `imstore.py` (the db doc). Each file stays under 200 lines.

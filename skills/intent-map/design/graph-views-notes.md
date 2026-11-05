# Composable graph views: design notes

Intent map: `examples/composable-graph-views.sexpr` (published at https://claude.ai/artifact/LUBCzE6kwQpGbZvcJdPaNA).
Stage 1 (rule engine, presets) lives in `engine/`; T1 passed (card preset pixel-identical to the old card view).
Stage 2 (2026-11-05): view switches morph (`engine/tween.js`, S22), edge selectors and link behaviors (`engine/links.js`, S11/S13) and field-bound params (`engine/params.js`, S12). Measured by `viewer/test/rules.js`, frames from `scripts/morph.js`.

Stage 3 (2026-11-05): a second source. `session-map/scripts/dsxgraph.py` turns the dsx tree store into a graph doc (`kind: "graph"` beside the intent maps), drawn by the same engine with its own rulesets (S9). Card templates (`engine/template.js`, S10), Barnes-Hut repel (`engine/quadtree.js`, S15), spring `share`, cooled layouts that sleep, and `flow: false` came with it. Measured by `viewer/test/frames.js`.
What the dsx tree is (from Joe's notes, via the coordinator): a tree of context prefixes; each node is one message appended to its parent's prefix, so root-to-node is the exact prompt a call saw and a fork is where calls shared a cached prefix and then diverged. The adapter keeps that structure visible: request nodes hold the prompt side (tokens, cache hit and miss), response nodes the output side, forks are marked, every node carries its branch's spend. Findings that shaped the layout: a hub with hundreds of links needs spring `share` (otherwise its summed pull flings it out); the electron paths (a drop-shadow filter each) were three quarters of a 400-node frame; pairwise repel is cheaper below about 300 nodes.
Not done: the agent tree (`agent` table) as its own graph; grouping rings for dsx (the engine's grouping dropdown assumes the intent-map `groups` rule).

## Overlap found with NDR (Joe's memory /areas/ndr.md, Aug 2026)
This session's design re-derived several of Joe's NDR graph-memory proposals. Check NDR before extending the model:
- graph compartmentalized by origin (subgraph per user, nested internet sources) = universes kept apart per source
- typed edges into an unloaded partition mean "unloaded, not absent" (NameError vs ImportError) = lazy nested universes, virtual connection policy
- concept classes with default dynamics, instances override (Python-shaped) = the element type tree
- hooks to hold several nodes at once = pin, extended
- DbC modules with activation/deactivation triggers = rules with selectors
- not yet designed: the pool metaphor (pull a node, neighbours surface by link tension) as a view rule
- universal-semantics: interaction is the primitive, lambda the composite = connection as primitive in the element model

## Space model settled in discussion
- layers: data graph (no coordinates) / inner space (points + equivalence only, no direction or origin) / layout (the observer that measures) / camera (pixels, keep-visible policy)
- edges carry a lap offset tracked continuously, so winding never changes under continuous motion; a flat torus has a grain only once a metric is chosen, which lives in the layout layer
- views as projections of one high-dimensional layout; categorical dims shaped by meaning (ring when adjacency means flow, line when ordered, simplex when unordered), mapped both ways

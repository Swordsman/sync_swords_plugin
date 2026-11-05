# Composable graph views: design notes

Intent map: `examples/composable-graph-views.sexpr` (published at https://claude.ai/artifact/LUBCzE6kwQpGbZvcJdPaNA).
Stage 1 (rule engine, presets) lives in `engine/`; T1 passed (card preset pixel-identical to the old card view).
Stage 2 (2026-11-05): view switches morph (`engine/tween.js`, S22), edge selectors and link behaviors (`engine/links.js`, S11/S13) and field-bound params (`engine/params.js`, S12). Measured by `viewer/test/rules.js`, frames from `scripts/morph.js`.

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

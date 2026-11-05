# Design: procedural first, Jev at the junctions

Joe's architecture, which this toolkit is the first working piece of.

## The idea
- **Procedural first.** Everything that can be computed is done in code. Every point that needs judgment is a junction, answered by Jev as a typed judgment (Noul, Choice or Score), which is cheap, fast and structured. A full LLM is consulted only where real generation or open-ended reasoning is needed.
- **Hand it stuff, get what you need.** The general tool is `jevask`: you give it a shared state and a list of things you need to know. Jev, not the caller, works out the question types, which needs depend on which, and what goes in a shared state. Leaving that to the caller means relying on the caller remembering to think about it.
- **The order of preference when work can be delegated:** procedural code plus Jev first; then the cheapest model that can do the job (Haiku for scouting and verbatim reporting, Sonnet when the job needs reading between the lines, Opus for creative synthesis); the most expensive tier only as a last resort for mission-critical work.

## jevask design decisions
- **Typing needs:** a planning call with one Choice per need over {noul, choice, score}, each with a meaning, picks the question type. That way it's Jev's judgment, not a keyword heuristic.
- **Dependencies:** one Noul per pair of needs ("does answering B require A's answer?"). A topological sort turns them into rounds, and on a cycle everything left goes into one round.
- **Line numbers as pseudo-tokens (Joe's idea).** Every line gets a number, and a reference like `[44]` refers to that line. A Choice over lines picks a line. A whole set of picks reads as `[44][77][56][29]`.
  - Code expands references, so Jev never looks anything up.
  - Ranges are named blocks, never numeric comparisons, because Jev is weak at numbers.
  - Past 255 lines, Jev first picks a block, then a line within it.
- **Noise:** be skeptical of the 0.4 to 0.6 band, and ask important questions twice. Joe's guidance was to do no more than that until failures are actually observed. Don't build three scales or ensembles in advance.

## The same mechanism, used for prose procedures
The question-library skill's design (`question-library/design/procedures.md`) writes questions as numbered statements that refer to each other by line number. That's the same `[n]` mechanism, applied to procedures written in prose. In those procedures, branch conditions and loop exits are judgments, which makes them Nouls. Bodies are generation. So code runs the control flow, Jev decides the conditions, and the LLM writes only the bodies.

## Open items
- Whether `[n]` references should be expanded before Jev sees them (current behavior, used for judging) or kept raw so Jev composes by selection, is still open. The expansion behavior is implemented; the generation-by-selection question is not settled. Packaging is also open: whether jev-scout should also live in the plugin repo (q2) and whether jev-toolkit should be split further (q20).
- The planner sometimes adds a dependency that isn't needed, costing an extra round. Fix only if it matters.
- Stagehand integration (Joe's lazy effect runtime) hasn't started.
- Scout's next step is Stagehand-driven browsing; right now it's plain Playwright.

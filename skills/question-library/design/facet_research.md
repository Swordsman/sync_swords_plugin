# Facet/axis schemes for questions: prior work (paraphrased)

Status legend: [F] = fetched/verified this session, [S] = search hit only, [M] = from memory (unverified).

## 1. Revised Bloom (Anderson & Krathwohl 2001) [F]
Link: https://www.bu.edu/provost/files/2013/10/Anderson-Krathwohl-Revision-to-Blooms-Taxonomy-of-Educational-Objectives.pdf
- Axis A, Knowledge: factual / conceptual / procedural / metacognitive (each with 3 sub-kinds; e.g. procedural includes "criteria for when to use a procedure", metacognitive includes strategic knowledge, task knowledge incl. conditional, self-knowledge).
- Axis B, Cognitive process: remember / understand / apply / analyze / evaluate / create, with 19 sub-verbs (interpret, exemplify, classify, summarize, infer, compare, explain; execute, implement; differentiate, organize, attribute; check, critique; generate, plan, produce).
- Compositional: yes, true 2-D table; each cell = a kind of objective. Sub-verbs are the "MOVE" layer; Knowledge is a coarse "TARGET" (kind of thing), not the thing's role in the task.
- Take: the closest well-known precedent for MOVE x TARGET, but its target axis is epistemic type of content, not role in a reasoning episode. Known weakness: cells are not all populated/natural (e.g. remember x metacognitive is thin).

## 2. Graesser et al. 1994 question categories [F, via secondary source]
Link: https://core.ac.uk/download/301358192.pdf (reproduces table); original: Graesser, McMahen, Johnson 1994, Handbook of Psycholinguistics.
- 16 content categories + 2 speech acts (assertion, request). Grouped by answer length: short (verification, disjunctive, concept completion, feature specification, quantification) vs long (definition, example, comparison, interpretation, causal antecedent, causal consequence, goal orientation, instrumental/procedural, enablement, expectational, judgmental).
- Defined by content of information sought. Flat list with a coarse 2-value grouping (answer length). Not compositional.
- Related Graesser work [F]: QUALITY dimensions in a causal-network study (https://escholarship.org/content/qt4nq6t6mh/qt4nq6t6mh.pdf?t=sh6jen): question category (why / how / consequence / what-if-not) is paired with a graph-search procedure: direction in causal graph (antecedent vs consequence), negation (what-if-not), structural distance, information source. i.e. question = (direction, negation flag) over a graph. That is a small genuine MOVE x TARGET-structure scheme.
- Axis we lack: ANSWER SHAPE / expected answer length (short vs long; yes-no vs set vs explanation). Sanderson's non-factoid taxonomy (instruction, reason, evidence-based, comparison, experience, debate) pairs each category with an expected answer structure but is single-label, not faceted [F] https://marksanderson.org/publications/my_papers/SIGIR_taxonomy.pdf

## 3. Question generation from concept maps (Olney, Graesser, Person 2012) [S]
Link: https://aclanthology.org/2012.dnd-3.5/
- Generates questions from a knowledge graph: relation type on an edge x question template. Abstract only fetched; full PDF https://aclanthology.org/2012.dnd-3.5.pdf not read. This is the one concrete "question generation from facets" precedent: graph edge types (target) x templates (category).

## 4. Zwicky / Ritchey General Morphological Analysis [F]
Link: https://ia600207.us.archive.org/27/items/ritchey_swemorph_Gma/gma.pdf
- Parameters x values -> configurations; Cross-Consistency Assessment removes incompatible PAIRS of values (logical, empirical, normative inconsistency). Only pairwise checks needed (hundreds) to prune ~100k configs.
- Direct relevance: your empty/impossible-cell problem. Store a small pairwise-incompatibility table (e.g. MOVE=assume-outcome x TARGET=task terms = inconsistent), not a per-tuple list. Normative judgments (is the question useful) kept separate from logical possibility (can it be rendered).
- No literature found on generating questions from a morphological box beyond brainstorming use.

## 5. Ranganathan PMEST [S]
Link: https://en.wikipedia.org/wiki/Colon_classification
- Five fundamental facets: Personality, Matter, Energy, Space, Time. Facet formula, citation order fixed. Principle: facets are mutually exclusive categories; a compound subject = tuple. Analogue: TARGET ~ Personality/Matter (the thing), MOVE ~ Energy (the action/process), stage ~ Time. (Mapping is mine.)

## 6. Paul & Elder Elements x Standards [F]  (most relevant find)
Link: https://yorku.ca/laps/sosc/wp-content/uploads/sites/216/2020/12/CriticalThinkingConcepts_Tools.pdf ; summary https://www.structural-learning.com/post/paul-elder-critical-thinking-framework
- Axis A, Elements of reasoning (TARGET): point of view, purpose, question at issue, information, interpretation/inference, concepts, assumptions, implications/consequences (8).
- Axis B, Universal intellectual standards (CRITERION): clarity, accuracy, precision, relevance, depth, breadth, logic, significance, fairness (9). Each has a stock question ("could you be more specific?", "how could we check that?", "do we need another perspective?").
- Compositional: explicitly "apply the standards to the elements" = 8 x 9 grid, every cell renderable (they claim all standards apply to all elements; no cell-by-cell mapping published). Third layer (traits) is not a question axis.
- Note the "six Socratic question types" (clarification, assumptions, reasons/evidence, viewpoints, implications, about-the-question) are a flat list that is really the TARGET axis with a few MOVEs mixed in.
- Key insight for you: your 32-value `action` probably conflates three things: MOVE (enumerate, invert...), CRITERION (verify=accuracy, completeness=breadth/depth, clarify=clarity/precision, calibrate) and PURPOSE. Paul-Elder separates CRITERION from TARGET.

## 7. Guilford Structure of Intellect (1967/1988) [F, secondary]
Link: https://www.structural-learning.com/post/guilford-structure-of-intellect
- Three axes: Operations (cognition/understanding, memory x2, divergent production, convergent production, evaluation), Contents (visual, auditory, symbolic, semantic, behavioral), Products (units, classes, relations, systems, transformations, implications). 6x5x6 = 180 cells (1967 version 5x4x6 = 120).
- Compositional, with the empty-cell logic you want (cells were treated as predicted abilities to find tests for). That last point is from memory.
- Relevance: Operations ~ MOVE (divergent vs convergent is a useful split: enumerate vs narrow). Products ~ structural form of the target/answer: unit vs class vs relation vs system vs transformation vs implication. "Is this one thing or several?" is unit-vs-class. This is a ready-made scheme for your referent-cardinality / structure sub-axis.

## 8. SCAMPER / Osborn checklist [F]
Link: https://dstudio.ubc.ca/toolkit/techniques/scamper/
- Operators (substitute, combine, adapt, modify/magnify, put to other use, eliminate/minify, reverse/rearrange) applied to a named target (product, step, part). This is literally MOVE x TARGET with a fixed generic question per operator. Compositional by construction, but target is open-ended, not a closed axis. Operator set is about design, not diagnosis; your MOVE list (remove/relax, combine, invert, perturb) overlaps it nearly 1:1 (eliminate, combine, reverse, modify).

## 9. Kepner-Tregoe IS / IS NOT [F]
Link: https://courses.cs.vt.edu/cs2104/Fall13/notes/KTNotes3.pdf
- Rows (TARGET facets of an observed problem): what (identity), where (location), when (timing), extent (magnitude: how many, how much). Columns: IS, IS NOT, distinction, possible cause.
- Compositional matrix. Two new ideas: (1) POLARITY (where it happens vs where it does not) as a built-in axis, the contrast set; (2) the question "what differs between IS and IS NOT?" is a compare-MOVE on a matched pair. Fits debugging. Your library likely has few IS-NOT questions.

## 10. LLM-side schemes (all flat or sequence, none faceted)
- Self-Discover (Zhou et al. 2024), https://arxiv.org/pdf/2402.03620 [F]: 39 reasoning modules, no formal taxonomy; informally: general analysis prompts, named thinking styles (critical, creative, systems, risk, reflective), problem-type diagnostics, solution-revision prompts, step-by-step. The pipeline SELECT / ADAPT / IMPLEMENT is the closest existing thing to your item (c), a classifier picking modules for a context, but modules are flat, selected per task not per turn.
- Cognitive behaviors (Gandhi et al. 2025), https://arxiv.org/pdf/2503.01307v1 [F]: verification, backtracking, subgoal setting, backward chaining; flat; authors say not exhaustive and suggest analogy-making and self-knowledge assessment as others. These are MOVEs.
- Metacognitive Prompting (Wang & Zhao 2023), https://arxiv.org/html/2308.05342v4 [F]: five-step sequence (comprehend, preliminary judgment, critical evaluation, final decision + explanation, confidence). A stage axis, flat.
- Schoenfeld episodes applied to reasoning traces (2025), https://arxiv.org/pdf/2509.14662 [F]: two-level labels. Sentence function: read, analyze, plan, implement, explore, verify, monitor; paragraph episode: general / explore / verify. A usable stage vocabulary and evidence that stage and function nest (a Plan sentence can sit inside a Verify episode), i.e. your `stage` and `action` are not the same axis.
- Self-correction survey (Pan et al. 2023), https://arxiv.org/pdf/2308.03188 [F]: five dimensions: error type corrected (hallucination, unfaithful reasoning, harmful, code), feedback source (self vs external model/tool/knowledge/metric), feedback format (scalar vs natural language), timing (training / generation / post-hoc), strategy. Candidate axis for you: FEEDBACK SOURCE = introspect vs use a tool vs check external evidence.
- Socratic Questioning (Qi et al. 2023), https://arxiv.org/abs/2305.14999 [abstract only]: recursive sub-question decomposition; no taxonomy of moves.
- Prompting-technique categorization (2024), https://arxiv.org/pdf/2402.14837 [F]: 7 flat groups, explicitly not orthogonal.
- CLAMBER ambiguity taxonomy (2024), https://arxiv.org/html/2405.12063v2 [F]: tree: epistemic misalignment (unfamiliar, contradiction), linguistic (lexical, semantic), aleatoric output (whom, where, when, what). A usable list of "what can be unclear" for TARGET=task terms/referent.
- Controllable question generation (various, e.g. https://arxiv.org/pdf/2602.03704 [F]): one axis (cognitive type) x content allocation; no multi-facet scheme found. I found no LLM work that generates questions from a facet product or finds missing questions via empty cells.

## 11. Others [F unless noted]
- Question Formulation Technique (Right Question Institute), https://www.fisme.science.uu.nl/publicaties/literatuur/2011_rothstein_santana_questioning.pdf: operations on questions themselves: produce, classify closed/open, convert one to the other, prioritize, next steps, reflect. Closed vs open (answer openness) is an ANSWER-SHAPE value.
- Lehnert 1978 conceptual question categories (13) [S only, not read]; Graesser's 16 descend from it.
- Bromberger value-of-answer taxonomy (GOSH/CASH/ADDED/GOLLY) via https://core.ac.uk/download/39674293.pdf [F]: classifies by payoff of the answer to the asker; one odd axis (answer VALUE). Probably not useful to you.
- Dillon (Questioning and Teaching, 1990): NOT verified; searches did not return his scheme. I recall form/function classification plus "alternatives to questions" but treat that as memory only.
- Walton critical questions / Toulmin: Toulmin elements (claim, data, warrant, backing, qualifier, rebuttal) fetched at https://www.ai.rug.nl/~verheij/publications/pdf/toulmin2005.pdf [F]; the paper does not discuss critical questions. Walton's design is one fixed question set per argument scheme (scheme -> questions), i.e. TARGET determines the question set, not faceted [M].
- Already in human_sources.md: Polya, Heuer/Pherson, King, Padesky, AAR, 5 Whys, GROW, Six Hats, Bloom stems. Polya is stage-keyed; King's stems are MOVE-keyed ("thinking skill"); Heuer is technique-keyed. None are product schemes.

## Synthesis for TARGET x MOVE
Existing compositional precedents: Bloom-revised (process x knowledge type), Paul-Elder (standard x element), Guilford (operation x content x product), Kepner-Tregoe (dimension x IS/IS-NOT), SCAMPER (operator x object), Zwicky/Ritchey (parameters + pairwise consistency).
Axes we had not listed:
1. CRITERION (quality dimension probed): clarity, accuracy, precision, relevance, depth, breadth, logic, significance, fairness (Paul-Elder). Likely absorbs several `action` values.
2. ANSWER SHAPE: yes/no, pick-one, set, explanation, ranking, procedure (Graesser short/long; Sanderson; QFT closed/open). Also divergent vs convergent (Guilford).
3. STRUCTURAL FORM of target: unit, class, relation, system, transformation, implication (Guilford products).
4. DIRECTION/RELATION in a graph: antecedent vs consequence vs negated-consequence (Graesser causal network).
5. POLARITY: is / is-not contrast (Kepner-Tregoe).
6. VIEWPOINT owner: self, user, adversary, outsider, expert (Paul-Elder point of view, Six Hats). Distinct from `stance`, which is attitude.
7. EVIDENCE/FEEDBACK SOURCE: introspect vs tool vs external source (self-correction survey).
8. REFLEXIVE LEVEL: object task vs method vs self-knowledge vs the question itself (Bloom metacognitive; Paul-Elder "questions about the question").
Cell handling: use Ritchey's pairwise cross-consistency table to mark impossible cells; keep logical impossibility separate from "possible but low value".

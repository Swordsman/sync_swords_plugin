# CHL Structural Companions

The formal-logic companion to each prose document in the design suite. One per document — mission, spec, scenarios, walkthrough — so four in a complete suite. Written after its source document, re-validated whenever that source changes.

Named for the Curry–Howard–Lambek correspondence. A companion enforces two constraints taken from Lambek's update of the Lambek calculus.

**Constraint 1 — no unsafe references.** Every term used must be defined. Every definition must be consumed by at least one reference. Dangling pointers (using undefined terms) and dead definitions (defining terms nothing references) are both defects.

**Constraint 2 — non-commutative sequencing.** Order is meaningful. A statement may reference only prior definitions, or explicitly marked forward references (↗). Circular dependencies are defects.

## Why bother

Prose has no handle finer than "the whole document." You cannot point at statement 3.5.1 of a design spec, ask what it depends on, and get an answer — you can only re-read. The companion gives every significant statement an address, a type, and a dependency edge, which turns questions that previously needed a careful reader into questions a script answers the same way every time.

The companion also **validates its source**. If a claim in the prose document cannot be represented as a node — if you cannot say what it defines, what it requires, or what it asserts in a single constrained gloss — the prose has an ambiguity or a contradiction. Fix the source. Do not formalise around it. A companion that had to bend to fit its document has thrown away the only thing it was for.

## The node model

Every significant statement in the source document becomes a node.

```
(node ID
  :cat    CATEGORY    ;; what kind of thing this is
  :term   SYMBOL      ;; the canonical name being defined
  :gloss  "..."       ;; constrained description (see grammar below)
  :tags   (TAG ...))  ;; searchable attributes
```

- `:cat` — what kind of thing: `notation | component | mechanism | invariant | form | protocol | record | strategy | thesis | constraint | metric | role | model`
- `:term` — the canonical name. This is what DEFINES means: as of this node, this term exists and can be referenced by later nodes.
- `:gloss` — a constrained description following the grammar below. Not free-form prose.
- `:tags` — searchable attributes: `root | frozen | evolvable | safety | primitive | derived | external | internal | durable | volatile | optional | aspirational`

**Node IDs match the source document's section numbering.** Node 3.5.1 formalises §3.5.1. This is what makes the companion navigable next to its source rather than a parallel universe with its own numbering.

## DEFINES, REQUIRES, REFERENCED-BY

Think of it like imports in code:

```python
# DEFINES: parse_session  (this module creates this function)
# REQUIRES: json, pathlib  (must exist before this module works)
# REFERENCED-BY: main.py, test_parser.py  (these import from here)
def parse_session(path): ...
```

The companion does this for every statement in the document, not just for code.

- **DEFINES** — "this node introduces this term into the vocabulary." Before this node, the term does not exist. After it, other nodes may reference it. A node's `:term` is what it defines; there is no separate field.
- **REQUIRES** — "this node depends on these terms existing first." Each must be DEFINED by a prior node, or by a later node via an explicitly marked forward reference (↗). A required term defined nowhere is an unsafe reference: a dangling pointer, a defect.
- **REFERENCED-BY** — "these later nodes consume what this node defined." The reverse direction of REQUIRES. A defined term nothing references is an orphaned definition: dead weight, and usually a sign the source document says something it never uses.

One node in a document legitimately has nothing depending on it: the apex, the top-level statement everything else feeds into. That node carries the `root` tag, which is what exempts it from the orphan check. If you find yourself tagging several nodes `root` to quiet the checker, the document has several unconnected top-level claims — that is a finding about the document, not about the tag.

## Dependencies live in matrices, not in nodes

An earlier format carried per-node dependency lists, which stated every edge twice — once as REQUIRES at the source, once as REFERENCED-BY at the target. Two statements of one fact drift. Adjacency matrices state each edge exactly once.

```
;; Read: row depends on column. ● = depends.
;;
;;         A    B    C    D
;;  A      -
;;  B      ●    -              B depends on A
;;  C      ●    ●    -         C depends on A and B
;;  D      .    .    ●    -    D depends on C only
```

Read across a row: "what does this node depend on?" — that is REQUIRES.
Read down a column: "what depends on this node?" — that is REFERENCED-BY.

Use a full matrix while a section is small enough for one to be readable. For large or sparse sections, use an edge list instead:

```
;; §3 edges (sparse):
;; 3.5.1 ← 1.1.5, 3.1.2
;; 3.6.1 ← 3.5.1, 1.1.7
```

For the cross-section overview, use a section-level matrix:

```
;;         §1   §2   §3   §4
;;  §1      -
;;  §2      ●    -              §2 structurally depends on §1
;;  §3      ●    ●    -
;;  §4      ●    ●    ●    -
```

Symbols, in every matrix: `●` structural dependency, `○` reference dependency, `.` none, `↗` forward reference.

Node-level dependencies that cross section boundaries go in cross-section edge lists. **Each edge is stated exactly once — never duplicated at both endpoints.**

## The gloss grammar

Glosses are not free-form prose. They follow a fixed grammar, so they are procedurally parseable and so two nodes describing the same kind of thing describe it the same way.

```
GLOSS     := VERB OBJECT [QUALIFIER]*

VERB      := defines | enforces | provides | constrains | enables
           | gates | dispatches | serializes | journals | evolves
           | contains | maps | compresses | isolates | surfaces
           | mediates | bounds | tracks | imports | exports

OBJECT    := SYMBOL

QUALIFIER := via MECHANISM | for PURPOSE | when CONDITION
           | unless EXCEPTION | from SOURCE | to TARGET
           | within SCOPE | at POINT

SYMBOL    := lowercase words joined by hyphens — the same lexical
             shape as :term, and the same shape for every
             MECHANISM, PURPOSE, CONDITION, EXCEPTION, SOURCE,
             TARGET, SCOPE and POINT
```

Examples:

```
(node 1.1.5
  :cat mechanism
  :term safepoint
  :gloss "enables checkpointing via effect-boundary when interpreter-state-serializable"
  :tags (frozen primitive))

(node 4.2.1
  :cat invariant
  :term non-speculative-dispatch
  :gloss "constrains dispatch to after-committed-checkpoint"
  :tags (frozen safety))
```

Anything you cannot say in this grammar is a signal, not an obstacle. A statement that needs a conjunction is usually two statements; a statement that needs a hedge is usually an undecided question wearing prose as a disguise.

## Integrity report

Every companion ends with one.

```
;; INTEGRITY
;; unsafe references .... 0        (must be 0)
;; orphaned definitions . 0        (must be 0)
;; circular dependencies  0        (must be 0)
;; grammar violations ... 0        (must be 0)
;; forward references ... 3        1.2.4 ↗ 3.1.1
;;                                 2.7.2 ↗ 4.4.0
;;                                 3.3.1 ↗ 5.1.2
;; category coverage .... 9 / 13
;; tag coverage ......... 7 / 12
```

The four counts are pass/fail: a companion with any of them non-zero has not validated its source, and the source is what needs fixing. Forward references are listed with the node that resolves each one — a forward reference with no resolution is an unsafe reference under another name. The two coverage lines are informational: they tell you which parts of the vocabulary a document never touches, which is occasionally a finding and never a failure.

**Compute this report; do not estimate it.** The counts are a graph traversal over the node list and the matrices. An agent eyeballing a hundred nodes for cycles is doing badly what ten lines of code do perfectly, and the whole value of the companion is that its answers do not depend on who is reading.

## Walkthrough companions

The companion to the walkthrough carries two extra fields per node:

- `CORRESPONDS-TO` — the spec section this node mirrors
- `VALIDATES` — what it confirms is consistent between the walkthrough and that section

This is how "if a mechanism exists in the spec, it exists in the walkthrough" stops being an aspiration. A spec node with no walkthrough node corresponding to it is a coverage gap, and it is countable.

## Rules

- Every term used in any dependency must be defined by a node
- Every defined term must appear in at least one other node's dependency chain — no orphans
- Dependencies flow forward; a reference to a later node is marked ↗ and must resolve
- No circular dependencies
- Glosses conform to the grammar — no free-form prose
- If the companion cannot represent a claim from the source document, the source has an ambiguity or a contradiction. Fix the source
- Node IDs match the source document's section numbering
- Re-validate after any change to the source document; regenerate if the change was structural

## Where this sits in Phase 0

Companions are written after their prose documents and before the exit gate. Their integrity reports are part of the mechanical validation that must come back clean **before** the wash runs — they are deterministic checks, and a wash is for what no check can enumerate. See `design_phase.md` steps 4 and 5.

`design_suite_check.py` computes every count in the integrity report, plus the node/section correspondence and the cross-document coverage rules. Run it; do not hand-tally a companion.

Companions are non-normative. Phase 1 reads the mission and the spec; a companion never introduces a mechanism, and nothing downstream is entitled to depend on one.

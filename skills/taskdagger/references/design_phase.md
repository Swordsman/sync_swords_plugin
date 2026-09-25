# Design Phase Protocol

## Purpose

Produce a **design suite**: six documents that together capture every architectural and functional decision for the project. The suite is the irreplaceable source of truth from which everything else (dag.json, contracts, work orders) derives.

One document cannot do this job. A single prose spec carries four different loads at once — stating what the project is and why, stating every decision in buildable detail, being checkable for internal consistency, and being readable by someone who did not write it. Optimising it for zero semantic loss and standalone reconstructability drives it toward dense precision, which serves mechanism and validation well and serves sanity-checking and onboarding badly. Nothing catches a spec that is internally consistent but wrong, because the same document is the only thing available to check it against.

This phase is mandatory. Skipping it or rushing it virtually guarantees failure downstream. An hour of thorough design saves weeks or months of debugging, rework, and abandoned projects.

**Design documents the territory, not just the path through it.** Implementation is the positive space — what gets built. The design suite covers both the positive space (what is built and why) and the negative space (what was considered and rejected, and why). It also captures the journey: the originating motivations, the factors weighed, the ground covered to reach each decision. YAGNI governs what gets built, not what gets considered or recorded. A rejected alternative costs nothing in the implementation, but an unrecorded rejection costs a full re-derivation every time the same idea is re-proposed — and it will be, because nothing in the record says it was already evaluated.

## Role

This phase requires a Type 1 (user-facing) AI. The AI talks through the entire project with the user. The harness doesn't matter — this conversation can happen in any AI system, and the output (text files on disk) is portable to any other system for subsequent phases.

## The suite

Every project that completes Phase 0 produces all six. There is no lightweight path and no manifest key that shrinks the suite — this is deliberate, and it is a **different axis** from the orchestrator's `spec-only` / `validated` / `enforced` operating modes, which govern DAG-assembly enforcement and have nothing to do with document count.

| # | Document | Job | Normative? |
|---|---|---|---|
| 1 | Mission statement | What the project is, and the invariants it always obeys | Yes — source of truth for intent |
| 2 | Design spec | Every architectural and functional decision, in buildable detail | Yes — source of truth for mechanism |
| 3 | Scenarios | Concrete proof cases traced through the architecture | No — validates, introduces nothing |
| 4 | Walkthrough | The same mechanisms in plain language, same depth | No — validates, introduces nothing |
| 5 | CHL companions | Formal structural companion to each of documents 1–4 | No — validates its own source |
| 6 | Packaging | The suite bundled as one aimpack handoff artifact | n/a |

Phase 1 reads documents 1 and 2. Documents 3–5 exist to catch what 1 and 2 got wrong; they never introduce mechanism, so nothing downstream is entitled to depend on them.

## Protocol

### 1. Elicit the project

Ask the user to describe what they want to build. Accept whatever level of detail they provide — a paragraph, a detailed spec, a vague idea. Don't refuse vague input; refine it.

Once you have the project in hand, establish what sources are available. Ask
what the user is open to using — external packages, public repositories, their
own prior work, internet search for prior art, or nothing (greenfield). The
answer may be nuanced: "packages for utilities, core from scratch" is as valid
as a blanket yes or no.

This is not a checklist. Ask in whatever form fits the conversation. The answer
shapes everything downstream — during decision exhaustion, when evaluating
component choices, and during recursive decomposition if the project is complex
enough to need it.

**Calibrate to the user.** Engage at the level the user is comfortable with.
Not every user is a software developer, and presenting architectural choices in
developer jargon to someone who does not speak it is not an honest choice — it
biases their answer toward whichever option sounds more attractive, not which is
actually correct. Define terms inline when the user might not know them. Offer
different degrees of abstraction and control over architectural decisions based
on what the user wants and understands. A developer gets "do you want a caching
layer between the API and the database?" A non-developer gets the same decision
explained in terms of what the system does, what the problem is, what the
proposed change would accomplish, and what the trade-offs are — with the
technical terms defined where they appear. The goal is informed consent, not
the appearance of it.

If the user wants the AI to search proactively for prior art during design, do
so — surface candidates as components are identified, not in a batch at the end.
The manifest key `design.sources` provides a default policy when the user is
unavailable or has said they do not care; interpret it in context, not as a
mechanical rule.

### 2. Exhaust all decisions

Work through the project systematically. For each area of the project:

- Surface every architectural and functional choice that needs to be made
- Bring to the user's attention any decisions they may have overlooked, forgotten, or assumed implicitly
- For each decision: present the options, trade-offs, and your recommendation; let the user decide
- Don't skip anything because it seems minor — minor decisions left unmade become major debugging sessions later

Categories to cover (adapt to the specific project):
- Core architecture: what components exist, how they relate, what patterns are used
- Data model: what entities, what relationships, what storage
- APIs / interfaces: what talks to what, in what format, with what guarantees
- External dependencies and prior art: what third-party services, libraries, APIs, and existing implementations are involved. For each component, consider whether existing prior art — a package, a public repo, a local project — already satisfies the contract. A public repository with clear interfaces is effectively a contract: it has interfaces, invariants, and guarantees, and can be used without understanding its internals. Stack choices made during design are assumptions until verified against the installed library — the cost of checking is lowest before anything freezes. Record the library and version in the contract (see `contracts.md` → freeze requirements).
- Error handling: what fails, how it's detected, how it's recovered
- Security: authentication, authorization, data protection, trust boundaries
- Configuration: what's configurable, what's hardcoded, what varies by environment
- Testing strategy: what's tested, how, at what granularity
- Deployment: where it runs, how it's deployed, what infrastructure
- Scope boundaries: what's explicitly out of scope for this project
- **Semantic conventions**: explicit declarations of every domain interpretation that could plausibly be read two ways. Units and their bases. Sign conventions, polarity, orientation (which way is north/up/positive/clockwise). Coordinate systems and origins. Index bases (0 vs 1). Timezone and encoding assumptions. Null/empty/missing distinctions. Ordering guarantees. Any term of art whose meaning varies by field or context. These are the most dangerous decisions to leave implicit: two workers can each build something internally valid and mutually incompatible, with every interface check passing, because both interpretations are self-consistent. Ambiguity that survives the design phase becomes stealth anti-symmetry at integration. When in doubt whether a convention needs declaring: declare it.
- **Contract hierarchy**: contracts exist at every abstraction level — function, method, class, module, project — and the form is the same at every level: a typed predicate on the boundary between an inside and an outside. Each contract carries four structures: its interface (typed boundary), its hierarchy (what sub-contracts it contains), its ordering (the execution sequence of those sub-contracts — non-commutative, a DAG), and its references (state-transfer bindings saying which output of one sub-contract becomes which input of the next). All four must be explicit by the end of design. A contract that describes what is inside but not in what order, or in what order but not what flows between them, is incomplete. See `design/13-contract-sexpr-spec.md` for the grammar.

Work token-efficiently while you do it. Propose changes in summary, get confirmation, then execute. Ask before large outputs. Prefer targeted edits over full regeneration — but regenerate when the edits cascade widely enough that a diff would be harder to verify than a rewrite.

### 3. Write the suite

In order. Each document is constrained by the ones before it.

---

#### Document 1 — Mission statement

Written first. Everything downstream is constrained by it.

**Contains:**
- What the project is (one paragraph)
- The problem it solves (concrete, specific — what fails today and why)
- What the system does (capabilities as facts, not aspirations — aspirational items labeled as such)
- Why this architecture (reasoning behind the major structural choices: language, component split, substrate)
- Competitive position (what it replaces or outperforms)
- Cooperative position (how it works alongside existing tools)
- The invariants (non-negotiable rules, stated as a flat list)

**Does NOT contain:** implementation details, mechanism descriptions, examples, scenarios, section numbers, data schemas, CLI commands.

**Rules:**
- Every capability claim scoped honestly (v1 vs eventual, guaranteed vs aspirational)
- The invariants list is complete — if it's non-negotiable, it's here
- If mission and spec conflict, question the mission first (it may be overclaiming), then fix the spec to match the corrected mission
- Direct, confident prose — what the project **is**, not what it might be

---

#### Document 2 — Design spec

Every architectural and functional decision. The document that gets used to build.

**Structure:**
- Key terms section first (every repeated term defined before first use — no undefined terms unless marked as a forward reference)
- Normative dependencies (what external documents govern, what happens on conflict)
- Prior art / lineage (what this builds on, what it replaces)
- Architecture section with component roles, communication model, diagram
- One section per major component with full mechanism descriptions
- Every operation / primitive / form listed with exact semantics
- Every protocol described step-by-step (dispatch flows, recovery, verification, etc.)
- Every record/schema with field-level detail
- Configuration options with defaults
- Dependencies with versions
- Semantic conventions (encoding, timestamps, indexing, equality) — one authoritative section every downstream phase references
- Scope boundaries (IS / IS NOT)
- Implementation phases ordered by dependency, each referencing the sections it implements
- Open questions. This is the acceptable form: "All decisions required to begin implementation have been resolved. Open questions will emerge from the first test run. They always do." "No open questions" is not.

**Rules:**
- **Self-contained**: a cold reader with no context from any conversation can build the system from this document alone
- Cross-references use section numbers (§3.2, §4.4)
- Forward references permitted but marked
- Every decision stated, not implied — if options existed, the spec names them, says which was chosen and why, and says what was rejected and why. The rejected alternatives are part of the design: they prevent re-derivation and they document the boundaries of the chosen approach
- No stale text — after any architectural change, grep for text assuming the old model and fix it in the same pass
- Mechanism descriptions precise enough that two independent implementers would build compatible systems
- Subsection numbering correct and consistent throughout
- Terms used consistently with their definitions — no drift

---

#### Document 3 — Scenarios

Concrete proof cases where the architecture earns its keep. Separate from the spec.

**Contains:**
- One section per scenario
- Each scenario: real-world situation → step-by-step trace through the architecture → which spec mechanisms it exercises
- Coverage: the common case, the failure case, the novel/unknown case, the performance case, the self-modification case, and the "thing nobody anticipated" case

**Rules:**
- Every mechanism referenced must exist in the spec — scenarios don't introduce new mechanisms
- Must use the current architectural model (no stale references to superseded designs)
- Concrete narrative form: "you type this, this happens, then this"
- Each scenario demonstrates something alternatives can't handle

---

#### Document 4 — Walkthrough (human-readable blueprint)

A complete parallel blueprint in plain language. Same depth as the spec, different vocabulary.

**Contains:**
- High-level overview (what the system does, the main components, how they communicate, with analogies)
- Section-by-section coverage of every mechanism in the spec, in plain language
- Every operation explained with what it does and why it exists
- Every protocol explained step-by-step
- Every architectural choice explained with its reasoning
- Decision provenance for significant decisions (who raised it, who reviewed it, what prompted it)

**Rules:**
- If a mechanism exists in the spec, it exists in the walkthrough — no gaps
- If the walkthrough can't explain something clearly, the spec may be wrong — flag it rather than smoothing it over
- No jargon without an immediate inline definition
- Analogies encouraged where they aid understanding
- Written for a programmer who codes but hasn't studied the spec's domain specialties
- Does **not** use spec section numbers in its prose (it must read standalone) — but its section ordering mirrors the spec's, so the two can be read side by side
- This is a blueprint, not a summary — full mechanism depth, not "X exists and does Y"

---

#### Document 5 — CHL structural companions

One formal companion per prose document, so four in total. Full specification: `design_suite_chl.md`.

In short: every significant statement in the source document becomes an addressable node carrying a category, a canonical term, a constrained gloss and searchable tags; dependencies live in adjacency matrices rather than per-node lists; an integrity report at the bottom counts unsafe references, orphaned definitions, circular dependencies and grammar violations, all of which must be zero.

The companion's job is to **validate its source**. If it cannot represent a claim from the prose document, the prose document has an ambiguity or a contradiction — fix the source, do not formalise around it.

---

#### Document 6 — Packaging

Bundle the whole suite into a single aimpack container. This is the canonical handoff artifact: what gets loaded into a new session, shared with another model, or archived.

```
aimpack pack --timestamps --checksum sha256 --author "<names>" \
  -o design/<project>_v0.4.2.aimpack.txt \
  design/*_v0.4.2.md
```

- Extension `.aimpack.txt`, not bare `.aimpack` — cross-platform compatibility
- Every document in the package carries the same version number in its filename (`_v0.4.2.md`)
- Both the prose documents and their CHL companions are included
- Version bump on every significant change: minor for fixes and additions (v0.4.0 → v0.4.1), major for architectural changes

**This versioning convention is scoped to the project's own design suite and nothing else.** It is unrelated to how taskdagger itself is packaged and released — that uses content identity, where an unchanged tree rebuilds byte-identical and no version number is involved. Do not conflate the two, and do not route this step through taskdagger's own packager.

### 4. Recursive decomposition

After the suite is written, the spec names components and their contracts. For
systems beyond a certain complexity, some of those contracts are too large for a
single worker to implement without further breakdown. This step makes that
breakdown explicit rather than leaving it to the worker.

#### The project as the starting contract

The project itself is the first contract — the mission defines its external
interface, the spec describes what is inside the box. The design conversation
that produced the suite was the first decomposition: it opened the project-level
black box and named its components.

This decomposition produces a contract with all four structures: an interface
(the project's external boundary), a hierarchy (the components it contains), an
ordering (the execution sequence of those components — which depends on which),
and references (the state-transfer bindings between components — which output of
one becomes which input of the next). Every subsequent decomposition does the
same at a finer level, recursively, because the contract form is the same at
every abstraction level.

Now examine each component contract and ask two questions:

1. Does something already exist that satisfies this contract? (A package, a
   public repo, a local project, a library — any existing implementation whose
   interfaces and invariants match.)
2. If not, is this contract simple enough for a worker to implement directly?

If the answer to both is no, the contract needs sub-decomposition.

#### Sub-decomposition

Treat the contract as a project. Produce an abbreviated design suite for it —
at minimum a spec (internal architecture) and sub-contracts (internal
interfaces). A contract whose internals fit in a few hundred lines does not need
scenarios and walkthroughs; one with significant internal complexity does.

Then apply the same two questions to each sub-contract, and recurse.

#### Termination

A contract is terminal when it meets either condition:

**Axiomatic.** A competent worker can implement it from the specification alone
without internally decomposing it into sub-problems. Two tests:
- *Single-responsibility.* It describes one thing, not several things composed.
- *Bounded scope.* A worker can hold the entire problem in working memory
  without planning an internal architecture.

**Satisfied by prior art.** An existing implementation matches the contract's
interfaces and invariants, and the user (or the default policy) has approved its
use.

**Depth bound.** Configurable via `design.recursion_depth_limit` (default 3).
Hitting it is diagnostic: a contract needing four levels of decomposition is
probably misspecified at the parent level. The bound flags for human review
rather than silently continuing. The operator can also halt recursion at any
point — a contract the operator considers terminal is terminal.

#### What it emits

At each level:
- A **sub-spec**: the contract's internal architecture.
- **Sub-contracts**: the interfaces between its internal components.
- An **axiom inventory**: terminal contracts to implement from scratch, with why
  each is terminal.
- A **prior-art inventory**: terminal contracts satisfied by existing
  implementations, naming the dependency and what it provides.

These feed directly into DAG assembly: sub-contracts become tasks with their own
chunks, axioms map to leaf tasks for workers, and prior-art matches map to
integration tasks.

#### Verification

At each level, the parent contract's specification must be satisfiable by the
composition of its sub-contracts — whether those sub-contracts are implemented
from scratch, by prior art, or by further decomposition. This is a structural
check: does the union of sub-contract interfaces cover every capability the
parent promises?

#### Inline vs. delegated

**Inline.** The design thread handles each contract's sub-decomposition
sequentially. Simpler, lower coordination cost, suitable when the contract count
is manageable.

**Delegated.** Sub-agents each handle one contract independently. The main
thread verifies consistency across sub-decompositions. Higher throughput, but
requires checking that independent decompositions are compatible with each other
and with the parent design.

The choice is a project-level decision recorded in the manifest.

#### Reusability

Components being designed should be shaped for potential reuse in future
projects, where doing so costs nothing or nearly nothing. This is a side-goal,
not a constraint — it should not distort the design to serve a hypothetical
future.

#### The AI's role in decomposition

The protocol describes what to accomplish, not a procedure to execute step by
step. If a procedural process would suffice for the decomposition, a procedural
process would be used instead of an AI. The AI is present as a competent human
colleague — exercising judgment about where to decompose, when to stop, what
prior art fits, and how to shape components for reuse.

When the user is unavailable: align with the underlying intent of the
instructions already given, and be intelligent. Make the call a competent
colleague would make with the same information. The manifest's `design.sources`
and `design.recursion_depth_limit` provide guardrails for the mechanical edge
cases; everything else is judgment.

### 5. Cross-document consistency

After any change to any document, check every other document for staleness.

- The spec is the source of truth for mechanisms — walkthrough, scenarios and mission must agree with it
- The mission is the source of truth for intent — the spec must implement what the mission describes
- CHL companions are re-validated (regenerated if need be) after any change to their source document
- Scenarios reference only mechanisms present in the current spec version
- The walkthrough covers every mechanism in the current spec version
- Stale-text grep after every architectural change: old terminology, old section numbers, old component names, old mechanism descriptions

Two things about that grep, both learned the hard way. **It needs multiple passes** — stale text hides in cross-references, examples and section openers, which is exactly where a first pass aimed at the changed mechanism does not look. And **every fix round includes a stale-text sweep, not just the targeted edit** — a fix that is correct in its own paragraph and contradicted three sections later has made the document worse, not better.

### 6. Validate mechanically — before the wash, not during it

Everything in step 5 is deterministic: a grep is a grep, a coverage check is a set difference, and the CHL integrity report is four counts that must be zero. Run those checks as checks. They are not what a wash is for.

This matters more than it looks. A wash aims attention away from what is already surfaced, so feeding it mechanically detectable defects both wastes the sweep and suppresses it exactly where it was meant to sharpen. Documentary defects die before the gate, by machine. What the wash is for is what no check can enumerate — the decision nobody made, the assumption nobody stated, the case nobody thought of.

`design_suite_check.py` runs all of it against a suite directory:

```
python3 design_suite_check.py design/ --version v0.4.2
```

It reports unsafe references, orphaned definitions, circular dependencies, unmarked forward references, duplicated edges, gloss-grammar violations, sections with no node, nodes with no section, spec mechanisms the walkthrough never covers, and scenarios that introduce mechanism the spec does not define. Add `--stale "<old term>"` after an architectural change to fail on terminology the change was supposed to retire.

So: fix everything the checks find, get them clean, and only then run the wash.

### 7. Multi-model QA — optional

**Strictly optional, and not for most projects.** Raise it only where the project is high-priority or complex enough to be worth the cost. Do not offer it by default, and do not treat a project's ordinary importance to its owner as meeting the bar — every project matters to whoever asked for it, which is exactly why that cannot be the test.

Where it is warranted, put the suite in front of at least two reviewer models with different strengths:

- **Internal-consistency reviewer** — checks the spec against its own rules. Contradictions, stale text, broken cross-references, term drift.
- **Physical-feasibility reviewer** — checks the spec against reality. Does this actually work as described? Can you build it? Do the mechanisms collide?

Review → fix → re-review, until findings converge toward zero.

External review is more token-efficient than self-review in a long context window, which is the practical argument as much as the correctness one: a fresh reader with the suite and nothing else costs less and sees more than the same context re-reading itself. taskdagger has no built-in multi-model dispatch — the `deepseek-api` skill and the drone/pilot pattern are the usual plumbing.

### 8. Exit gate

When you believe the suite is complete, don't take your own word for it and don't hand the job to the user either.

Run a wash — inward, over the whole suite against the decision checklist in step 2, until it runs clean. See `wash.md`. Address what it surfaces. (Governed by `wash.design`, default on; there is rarely a good reason to turn it off, since nothing mechanical checks a design decision that was never made.)


Only then turn to the user, and bring them the specific decisions that genuinely need a human — not an open-ended sweep. Being asked "anything else?" over and over is the machine's job offloaded onto a person, and a person will answer "no, looks good" long before the question stops being productive. Where nothing specific remains, ask once:

"I think we've covered everything important. Is there anything else about this project that we haven't discussed, that you're unsure about, or that you think needs more thought?"

Continue until the user confirms nothing remains.

**Where `wash.design` is on, the wash must run clean before Phase 1 begins.** The suite is irreplaceable and everything downstream derives from it. Turning it off means entering DAG assembly on a suite nothing swept — occasionally the right call for a tiny or throwaway project, never the right call by accident.

## On disk

The suite must be on disk, not just in a conversation. Conversations are ephemeral; the suite must survive context loss.

```
design/
  mission_v0.4.2.md          mission_chl_v0.4.2.md
  spec_v0.4.2.md             spec_chl_v0.4.2.md
  scenarios_v0.4.2.md        scenarios_chl_v0.4.2.md
  walkthrough_v0.4.2.md      walkthrough_chl_v0.4.2.md

  <project>_v0.4.2.aimpack.txt
  archive/
```

Split the spec across several files under `design/` when the project is large or modular — updating one file without touching the others, and reducing the blast radius of a corrupted or lost file, are both worth the extra structure. A single `spec.md` is fine for a small, git-versioned project. Drag superseded versions into `design/archive/` before overwriting.

## Validating an existing suite

If the user arrives with design documents already written:

1. Read them fully
2. Identify which of the six documents exist and which are missing. A pre-existing "design spec" is usually document 2 alone
3. Check what exists against its Contains / Does-NOT / Rules above, and against Rule 1 and Rule 2 below
4. Look for: ambiguities, missing decisions, contradictions, implicit assumptions, incomplete interface definitions, unaddressed error cases
5. Write the missing documents. The mission is written first even when the spec already exists — if the spec turns out not to implement what the mission describes, that mismatch is the most valuable thing this phase will find
6. Run steps 4 through 8 in full

Do not proceed to DAG assembly on a flawed, incomplete, or absent design suite. This is not optional.

## Brownfield: designing against existing code

When the user arrives with an existing codebase and wants to extend it, Phase 0
is different. Greenfield Phase 0 designs something that does not exist.
Brownfield Phase 0 designs something that exists and is about to change. The
most valuable output is the delta: what the code does vs. what we want it to do.

**Observed contracts.** The AI analyzes the planned new work against the existing
codebase, identifies which boundaries the new work will cross, and proposes
observed contracts at those boundaries. The user confirms or corrects the
boundary set. Extract contracts at the confirmed boundaries — and only there. Row polymorphism (the row variable ρ)
bounds extraction: you describe the fields the new work references, and ρ
covers everything else. Extraction is complete when every field the new work
touches has a type. See `contracts.md` for the `observed` maturity state and
`design/13-contract-sexpr-spec.md` §3 for the full lifecycle.

**The ordering matters even in extraction.** An observed contract that captures
only what a module contains, without capturing the execution order of its
components, has lost essential structural information. If the existing code calls
open, then write, then close, the observed contract's ordering must say so — a
bag of {open, write, close} is an incomplete observation.

**The DAG is for new work, not reconstruction.** You cannot extract a DAG from
finished code — finished code has no remaining work. The brownfield DAG is an
ordinary taskdagger DAG for the work to be done next, whose leaf dependencies
resolve to observed contracts instead of to tasks.

**Phase 0 brownfield produces:** the design suite for the new work, plus
observed contracts at every boundary the new work touches. The suite's recursive
decomposition (step 4) terminates at observed contracts the same way it
terminates at prior-art matches — the existing implementation satisfies the
contract, modulo the uncertainty that `observed` carries.

### Extraction protocol

This is the mechanical procedure. The principles above govern it.

**Step 1 — Survey the substrate.** Before proposing boundaries, understand what
exists at the level needed to identify where the new work meets the old code.
For each module or component the new work will touch: what files comprise it,
what its external interface looks like (exports, public API, data shapes), and
what depends on it. This is not a full codebase index — it is the minimum survey
that makes boundary identification possible. If a file index exists (see
`modularity-and-file-index.md`), start from it; otherwise construct the relevant
slice.

**Step 2 — Propose boundaries.** Given the user's description of the new work,
identify which boundaries the new work will cross. A boundary is where new code
will call existing code, or where existing code will need to call new code, or
where new code will read or write data that existing code also touches.

Present the boundary set to the user with:
- The module or file on each side of the boundary
- What the new work needs from or provides to the existing code at this point
- Why this is a boundary (what crosses it)

Calibrate the explanation to the user's level (see step 1's calibration
principle). The user confirms, corrects, or extends the boundary set.

**Step 3 — Extract observed contracts.** For each confirmed boundary, read the
relevant source code and write an observed contract capturing four structures:

- **Interface.** The typed boundary — function signatures, data shapes,
  behavioral guarantees visible at this seam. Use row polymorphism: describe
  only the fields the new work touches. The row variable ρ covers everything
  else. A function that takes a config dict with 30 keys, of which the new
  work uses 3, gets a contract typing those 3 keys plus ρ.

- **Hierarchy.** If the boundary module contains sub-components the new work
  needs to know about (not all of them — only the ones relevant to the
  boundary), name them.

- **Ordering.** If the boundary involves a sequence of operations, capture
  the execution order as `(seq ...)` / `(par ...)` combinators. This is where
  most information is lost in casual extraction — "this module does open,
  write, close" is not the same as "this module does open then write then
  close." Get the order right.

- **References.** If state transfers across the boundary (a handle returned
  by one call used as input to the next, a shared data structure, a config
  object passed through), capture the bindings as `(bind (from ...) (to ...))`.

Every observed contract carries mandatory provenance:
```
(provenance
  :source-file "path/to/file.py"
  :source-commit "abc123"
  :extracted-by agent
  :extracted-at "2026-08-31T12:00:00Z"
  :method static-analysis)
```

See `contracts.md` for the provenance schema and `design/13-contract-sexpr-spec.md`
§2 for the s-expression grammar.

**Step 4 — Validate.** For each observed contract, check:
- Does it describe everything the new work needs from this boundary? If a field
  or operation is missing, extraction is incomplete.
- Does it contradict what the code actually does? At this stage the contract is
  descriptive — if it contradicts the code, the contract is wrong, not the code.
- Is the ordering complete? If the boundary involves sequenced operations, are
  they all captured in the right order?
- Are the references complete? If state transfers across the boundary, are all
  the bindings captured?

If a contradiction is found between the observed behavior and what the user
expects, that is a finding — document it in the design suite. It may be a bug,
or it may be intended behavior the user forgot about. Either way it shapes the
new work.

**Step 5 — Integrate with the design suite.** The observed contracts are now
inputs to the normal Phase 0 process. Write the design suite for the new work
(mission, spec, scenarios, walkthrough, CHL companions, package) using the
observed contracts as the substrate the new work builds on.

In the design spec, observed contracts appear in the dependencies/prior-art
section — they are what already exists. In recursive decomposition (step 4 of
the main protocol), an observed contract is a terminal node: the existing
implementation satisfies it, so no further decomposition is needed.

In the DAG, leaf dependencies resolve to observed contracts instead of to tasks.
An observed contract in a DAG means "this already exists and works; build
against it."

**Step 6 — Completion.** Extraction is complete when:
- Every field the new work references in existing code has a typed contract
- Every operation sequence the new work depends on is captured in ordering
- Every state transfer across a boundary is captured in references
- Every observed contract carries provenance
- The user has confirmed the boundary set

After extraction, proceed with the rest of Phase 0 for the new work. The
observed contracts may later be promoted to frozen via `promote-contract`
(see `contracts.md`) as understanding solidifies.

## The two rules

**Rule 1: Zero semantic loss.** Every decision made during the conversation must be present in the suite — primarily in the spec. No detail discussed and agreed upon may be omitted or summarised away. This applies suite-wide.

**Rule 2: Standalone reconstructability.** Anyone reading only the mission and the spec — with no access to the conversation, the user, or any other context — must be able to build exactly what the user intended. Precise and complete enough that a different AI, a different developer, or the same user returning months later could pick up from those two documents alone and produce the correct result. Scenarios, the walkthrough and the companions are aids: deliberately redundant, never additive. If reconstruction needs them, the spec is incomplete.

## Completion

The design phase is complete when:
- All six documents exist on disk, versioned and packaged
- The suite satisfies Rule 1 (zero semantic loss) and Rule 2 (standalone reconstructability)
- Cross-document consistency checks and every CHL integrity report are clean
- Multi-model QA, if it was used at all, has converged
- Recursive decomposition has been applied where needed, with all leaf contracts either axiomatic or satisfied by approved prior art
- Prior-art dependencies are recorded in the spec with versions and what each provides
- The wash has run clean
- The user has confirmed it's complete

Transition signal: "The design suite is complete. Ready to move to DAG assembly?"

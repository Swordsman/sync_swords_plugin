# winnow v0.2

**Streaming semantic distillation for AI conversations.**
An s-expression delta protocol over a typed semantic graph. Extract while the conversation happens; the knowledge graph is a fold over the delta log.

Named for what it does: separate grain from chaff. Signal becomes nodes; noise never gets extracted.

**Lineage.** Event-sourced graph (log is truth, graph is a view) — same lifecycle as aimpack's diff/compact/rewind, and a `.wno` log ships cleanly as an aimpack part. Status vocabulary echoes cbtdag (`proposed`/`frozen`). PENMAN/AMR proved s-expressions serialize semantic graphs well; winnow keeps the serialization instinct and replaces AMR's thousands of sentence-level frames with eight conversation-level ones. Term canonicalization is alias-table-based in v0.2, with anchor-relative embedding profiles (UEL) as the planned v2 identity engine.

**v0.2 over v0.1.**

1. **Partial resolution** as structural patterns, not statuses (§2 note, §6 graduation principle, §9 patterns).
2. **Tier architecture** (§10): the traditional context window is abandoned; an immediate context window is JIT-compiled per message boundary from four temperature tiers (fire/hot/warm/cold), governed by a declared cooling profile, with a resolution ladder ending in an honest miss.
3. **File meta header** (§7, §8): version, declared representation mode, cooling profile. Headerless files are v0.1-legacy and default cleanly.
4. **Hardened procedure** (§9): bulk ingestion is a named high-stakes trigger; stance toward reference material is a first-class extraction target.
5. Reference implementation moved out of the appendix into `fold.py`, extended with `--digest` (tiered window rendering).
6. **Names fixed (2026-10-13).** "Fold" had come to mean three things. It now means only the replay; the frontier and the digest are named views, each with its own script (Files). The recency tail moved out of the frontier into the digest's hot tier.

**Vocabulary.** Four words, one meaning each. Never call a view "the fold".

| Word | Means | Script |
|---|---|---|
| **fold** | replaying the delta log into the full graph: `graph = fold(empty, log)` (§7). Keeps every node, resolved and superseded ones included. | `fold.py` |
| **snapshot** | the folded graph written out as canonical s-exprs (§7 compaction) | `fold.py --snapshot` |
| **frontier** | the view of what's still open: live constraints, proposed decisions, open questions, todo/doing/blocked actions (§9) | `frontier.py` |
| **digest** | the tiered window a model sees: fire, hot (frontier + recent tail), warm stubs, cold count (§10). This is what the extractor gets. | `digest.py` |

---

## 1. Architecture

Three layers:

| Layer | What it fixes |
|---|---|
| **Vocabulary** | *What kinds of things exist.* Closed frame set (8), closed edge set (8), open term/relation registry with canonical ids + aliases. |
| **Canonical form** | *One meaning → one representation.* Normalization rules R1–R12 kill synonym drift and paraphrase drift. |
| **Procedure** | *How text becomes graph.* Two-stage extract-loose / normalize-strict, triggered incrementally, emitting deltas. |

Core loop:

```
turns ──► extractor (loose) ──► normalizer (strict) ──► delta ──► log
                ▲                                                 │
                └──────────────── digest ◄──── fold ◄─────────────┘
```

The extractor never sees the whole transcript or the whole graph — only the **digest** (§10) plus the new turns: the log is folded into the graph, and the digest renders the part of it that matters now. Context stays bounded no matter how long the conversation runs. That is the entire argument for streaming over batch: batch extraction degrades as input grows; winnow's per-step input is constant-ish. v0.1 handed the extractor the frontier plus a recent tail; v0.2's digest keeps both as its hot tier and adds fire, warm and cold around them.

---

## 2. Frames (closed set)

Every node is one of eight frames. Payload is a canonical proposition (§4) unless noted.

| Frame | Captures | Statuses |
|---|---|---|
| `claim` | Descriptive assertion — how things are | `live` `corrected` `retracted` `superseded` |
| `def` | Term/concept introduction; payload = `termid "gloss"` | `live` `deprecated` `superseded` |
| `question` | Open thread | `open` `answered` `dropped` `superseded` |
| `decision` | Commitment to one option among alternatives | `proposed` `frozen` `superseded` `abandoned` |
| `constraint` | Requirement or preference bounding solutions | `live` `relaxed` `retired` `superseded` |
| `action` | Work item — the implementation-status discriminator | `todo` `doing` `done` `blocked` `dropped` `superseded` |
| `artifact` | External referent (file, url, code, doc); payload = string ref | `live` `deprecated` `superseded` |
| `edge` | Typed relation between nodes (§5); no id, no status | — |

Notes:

- `constraint :strength hard|soft` covers both requirements and preferences — one frame, one knob.
- Partial resolution is structural, not a status: an `answers` edge without a status flip to `answered` means "progress recorded, thread still open." The question stays in the frontier. See §9 patterns.
- `decision` vs `claim`: decisions are normative (we choose X), claims are descriptive (X is the case). A design detail explaining a decision is a claim `about` the decision.
- `action` status is deliberately fine-grained. Distinguishing *discussed* from *done* was the single biggest extraction-quality lesson from prior decomp work; the frame bakes it in.
- The frame **distribution is itself signal**: zero actions + heavy claim/decision churn = design exploration; heavy actions = execution session.

## 3. Annotations

Fixed key order when serializing: `:status :conf :strength :by :src :time :modal :neg`.

| Key | Values | Meaning |
|---|---|---|
| `:src` | `tN` or `(tN tM ...)` | Provenance: turn index(es). **Required.** |
| `:by` | `user` \| `assistant` \| agent-id | Who asserted it. **Required.** |
| `:conf` | 0..1 | Extractor's confidence that the node faithfully captures speaker meaning. **Not** truth-confidence — truth lives in `:by`, `:status`, and `contradicts` edges. Default 1.0, omitted when default. |
| `:status` | per-frame (§2) | State as of last delta touching the node. |
| `:strength` | `hard` \| `soft` | Constraints only. |
| `:time` | `past` \| `present` \| `future` \| ISO | Tense, when it matters. |
| `:modal` | `must` \| `should` \| `may` \| `can` | Modality as annotation, never a new relation. |
| `:neg` | `true` | Polarity flip of the payload proposition. |

**Ids:** frame-prefixed serials assigned by the normalizer only — `c` claim, `d` decision, `q` question, `k` constraint, `f` def, `a` action, `r` artifact. Edges have no ids; the triple `(type src dst)` is self-identifying. Content-hash ids are deferred to multi-session merge — see §12, Limits.

## 4. Terms, relations, propositions

**Term registry.** Open set, canonical `kebab-case` ids, declared on first use:

```lisp
(term fuse-vfs :gloss "userspace virtual filesystem via FUSE"
               :aka ("FUSE layer" "jsonfs daemon")
               :canon "Filesystem_in_Userspace")
```

Aliases map surface forms → canonical id. `:canon` attaches a cross-lineage anchor — a stable canonical form (convention: Wikipedia article title) that serves as a join key when merging logs whose registries use different organic ids for the same concept. Organic ids stay the wire format; anchors are join keys only. The normalizer consults the registry before minting anything new; a minted term carries `:new` for later human/agent review.

**Relations** are terms too — open set, seeded for technical conversations:

```
is-a  has  uses  maps-to  stores-in  encodes  enables  prevents
causes  requires  permits  excludes  implies  achieves  costs
scales-as  marks  extends  replaces  represents  design  implement
```

Each registry entry for a relation records its **direction gloss**, e.g. `maps-to: (maps-to SOURCE TARGET)`, `causes: (causes CAUSE EFFECT)`. Direction ambiguity is a registry problem, solved once, not a per-extraction judgment call.

**Propositions** — the payload grammar:

```lisp
(RELATION ARG1 ARG2 ...)     ; ARG = term id | node id | "literal" | number
```

- Slot order fixed: agent/subject/source first, patient/object/target second.
- Node ids are legal args — `(achieves d2 lossless-roundtrip)` says decision d2 achieves the property. Claims about claims, claims about decisions: all first-class.
- String literals only for values that resist termification (`"O(E)"`, versions, quantities with units).

**Representation modes.** Everything outside this section — frames, edges, delta ops, fold semantics, tiers — is representation-agnostic *transport*: it never inspects the inside of a proposition. What varies is the **term/relation identity scheme**: how surface forms map to canonical ids. v0.2 names this choice and declares it in the file header (§7) as `:semantic-rep "registry-v0.1"` — the alias-table registry defined in this section, and the only mode this spec defines. Files without a header are `registry-v0.1` by definition, so every v0.1 log is a valid v0.2 log. Future modes (anchor-relative embedding profiles, prime-decomposition schemes) swap the identity engine without touching transport; cross-mode equivalence needs converters and hash ids and is explicitly deferred — see §12.

## 5. Edges (closed set)

| Edge | Reading | Direction convention |
|---|---|---|
| `supports` | X is evidence/justification for Y | `(supports X Y)` |
| `contradicts` | X challenges Y | challenger first: `(contradicts X Y)` |
| `supersedes` | X replaces Y | **newest leads**: `(supersedes NEW OLD)` |
| `refines` | X elaborates/extends Y | detail first: `(refines DETAIL PARENT)` |
| `answers` | X resolves question Y | `(answers X Q)` |
| `motivates` | X is the reason for Y | `(motivates REASON THING)` |
| `depends` | X needs Y | `(depends X Y)` |
| `about` | X concerns topic/decision/term Y | `(about X Y)` |

Eight and no more. If a relation between nodes doesn't fit, it's probably a proposition-level relation (§4), not an edge.

Note: `about` is the one edge whose target may be a **term id** instead of a node id — `(about q5 archival-compression)` reads "this question concerns this topic." All other edges require node ids at both endpoints.

## 6. Normalization rules — the collapse contract

"Same meaning → same form" is enforced, not hoped for. The normalizer applies:

- **R1** Terms → canonical registry ids (alias lookup; kebab-case; mint + `:new` if absent).
- **R2** One proposition per node — conjunctions split into multiple nodes.
- **R3** Fixed slot order per relation, per the registry direction gloss.
- **R4** Tense, modality, polarity → annotations (`:time` `:modal` `:neg`), never new relations or terms.
- **R5** Passive voice → active; swap args to canonical direction.
- **R6** Verb phrases nominalize to registry relations (nearest match beats invention).
- **R7** Annotation keys in fixed order (§3); defaults omitted.
- **R8** Ids assigned serially by the normalizer; extractors never mint ids.
- **R9** No synonym relations — nearest registry relation, or a new `term` entry flagged `:new`.
- **R10** Rhetoric unwrapped: humor, hypotheticals-as-emphasis, and framing devices reduce to their payload proposition. Phatic content, greetings, and meta-chatter reduce to nothing.
- **R11** Restatement with identical canonical payload → silent drop (dedup). Status-changing restatement → `update`.
- **R12** Numbers/units preserved as literals; prose quantities normalized (`"seventy km"` → `"70km"`).

**Graduation principle.** Scalars belong to the map (extraction-process metadata: `:conf`); structure belongs to the territory (the semantic content). Express degree-of-resolution through structure — edges, decomposition, supersession — not continuous annotations on status. This keeps the §6 equivalence test decidable: two extractors either both emit an edge or they don't.

**Equivalence test.** Two extractions of the same text are equivalent iff their folded graphs are isomorphic modulo id renaming. Procedure: canonical-sort nodes by `(frame, payload-string, src)`, canonical-sort edges after id-mapping, compare. This is the testable meaning of "collapses reliably to a single representation." Byte-identical output across different extractor models is not promised; canonical-form invariance given a shared registry is. Tier state (§10) is excluded from the test exactly as `:conf` is: derived, map-side, never part of the graph's identity.

## 7. Delta protocol

The wire format. One `delta` per trigger; the graph is `fold(empty, log)`.

**File header.** A log may open with a single `meta` form:

```lisp
(meta :winnow-version "0.2"
      :semantic-rep "registry-v0.1"
      :log-id "wno-20260724-live-sidepayload-a1f3"
      :receives ("wno-20260720-resolver-batch-7e2c"
                 "wno-20260720-wno-review-8b4d")
      :profile (:tail 6 :fire-hops 1 :promotion-ttl 2 :widening-base 3))
```

| Key | Purpose |
|---|---|
| `:winnow-version` | Spec version (currently `"0.2"`). |
| `:semantic-rep` | Term-identity mode (§4); defaults to `"registry-v0.1"`. |
| `:log-id` | This log's identity — used by merge to qualify `:src` provenance (§12). Convention: `wno-YYYYMMDD-slug-4hex`. |
| `:receives` | Ancestor log-ids this log depends on — terms, vocabulary, or context inherited from prior sessions. A tool loading this log can detect missing ancestors before trusting the graph. |
| `:profile` | Cooling profile (§10.4). |

Every key is optional. A file with no header is a v0.1-legacy log and defaults to `registry-v0.1` with the default profile — v0.1 logs are valid v0.2 logs unchanged. The header is side-effect state (§10.6): it configures the machinery and never cools.

```lisp
(delta :turn N
  (term ID :gloss "..." :aka ("..."))       ; registry entry
  (add (FRAME ID PAYLOAD :anns...))          ; new node
  (add (edge (ETYPE SRC DST)))               ; new edge
  (update ID :key val ...)                   ; shallow ann merge
  (supersede NEW OLD :conf X)                ; OLD.status=superseded + edge
  (merge LOSER WINNER)                       ; rewrite refs, drop LOSER
  (del ID)                                   ; node + incident edges
  (del (edge (ETYPE SRC DST))))              ; single edge
```

**Fold semantics (normative).** Folding the log yields the whole graph and nothing else; every reduced rendering of it (frontier §9, digest §10, query §12) is a view computed from the folded graph, never part of the fold.

- `add` — insert; duplicate id is an error.
- `update` — shallow-merge annotations onto existing node.
- `supersede NEW OLD` — sets `OLD :status superseded`; `:conf` on the op lands as `:status-conf` on OLD; emits `(supersedes NEW OLD)`.
- `merge LOSER WINNER` — rewrite every edge endpoint LOSER→WINNER, delete LOSER. For later-discovered equivalence (e.g., a new alias reveals two nodes were one). Same-delta duplicates never reach the wire — R11 handles those.
- `del` — hard removal, node plus incident edges. Rare; prefer status changes. The log preserves history regardless.

**Wire note — reach.** `(reach QUERY)` is an extractor-to-orchestrator request for material outside the current digest (§10.5). It travels on the same channel as deltas but is **never persisted to the log**; a log containing `reach` forms is invalid. Reach traffic is telemetry (§10.4) and lives in a sidecar if kept at all.

**Compaction.** A snapshot is the folded graph serialized as canonical s-exprs — equivalently, the log compacted to pure adds. Log = archaeology, snapshot = current state; keep either or both (aimpack: diffs vs compact). Not to be confused with tier demotion (§10.3), which rewrites nothing — "compaction" is this section's word and means log rewriting only.

## 8. Grammar (EBNF, informal)

```ebnf
log       = [ meta ] { delta } ;
meta      = "(" "meta" { mkey mval } ")" ;
mkey      = ":winnow-version" | ":semantic-rep" | ":log-id"
          | ":receives" | ":profile" ;
mval      = string | idlist | profile ;
idlist    = "(" { string } ")" ;
profile   = "(" { key value } ")" ;
delta     = "(" "delta" ":turn" int { op } ")" ;
op        = add | update | merge | supersede | del | termdecl ;
add       = "(" "add" ( node | edge ) ")" ;
node      = "(" frame id payload { ann } ")" ;
frame     = "claim" | "def" | "question" | "decision"
          | "constraint" | "action" | "artifact" ;
payload   = prop | termid string      (* def *)
          | string ;                  (* artifact *)
prop      = "(" relation arg { arg } ")" ;
arg       = termid | id | string | number ;
edge      = "(" "edge" "(" etype ref ref ")" ")" ;
etype     = "supports" | "contradicts" | "supersedes" | "refines"
          | "answers" | "motivates" | "depends" | "about" ;
ann       = key value ;
key       = ":status" | ":conf" | ":strength" | ":by" | ":src"
          | ":time" | ":modal" | ":neg" ;
update    = "(" "update" id { ann } ")" ;
supersede = "(" "supersede" id id { ann } ")" ;   (* NEW OLD *)
merge     = "(" "merge" id id ")" ;               (* LOSER WINNER *)
del       = "(" "del" ( id | edge ) ")" ;
termdecl  = "(" "term" termid { ":gloss" string | ":aka" "(" {string} ")"
          | ":canon" string | ann } ")" ;
comment   = ";" text-to-eol ;                     (* outside strings *)
```

`(reach QUERY)` is deliberately absent: it is wire-level, never log-level (§7 wire note).

## 9. Procedure

**Trigger policy.** Emit a delta every exchange by default; per turn when stakes are high (corrections landing, decisions freezing); on topic shift; on demand. The protocol is cadence-agnostic — deltas compose regardless. **Bulk ingestion is a named high-stakes trigger:** pasted documents, transcripts replayed in batch, multi-file dumps. Checkpoint per document — never per batch. Batch cadence over bulk input reproduces exactly the degradation §1 predicts for batch extraction; this was observed empirically on winnow's own design-session transfer, where a 3-checkpoint pass over 9 documents dropped four design commitments that per-document cadence would have caught.

**Frontier.** What's still open: all `live` constraints, `proposed` decisions, `open` questions and `todo`/`doing`/`blocked` actions, plus a count line for the rest. Claims, defs and artifacts are statements, not open items, so they stay out however recent. The extractor doesn't get the frontier alone: it gets the digest (§10), whose hot tier is the frontier plus the last `:tail` live claims/defs. (Until 2026-10-13 the frontier carried that tail itself, as v0.1's "frontier digest" did.)

**Signal policy** (extraction-time, not a filter pass): never extract phatic content, filler, restatements, hedging-as-texture, or meta-chatter. Humor and doomsday hypotheticals get **unwrapped** — the payload proposition survives, the packaging doesn't (R10). **Stance is first-class:** the position a speaker takes toward reference material — adopt, reject, defer, suspect — is an extraction target that outranks the material itself. A summary that survives while the verdict on it dies is a worse loss than the reverse; capture the stance as a decision or claim even when the referenced material is left as an artifact pointer. When unsure, extract with low `:conf` rather than drop: a wrong node is correctable, a missing node is invisible.

### Extractor prompt (stage A — loose)

> You're taking working notes on a live conversation, for a future reader with zero patience for transcript archaeology — probably us, later. You get two things: the note graph so far (a digest of what's live, not the whole graph), and the newest turns.
>
> Jot what changed, as delta ops — new claims, decisions, constraints, questions, definitions, actions, and links between them. Loose syntax is fine; a normalizer cleans up after you. What matters:
>
> - capture every commitment, correction, requirement, and open thread
> - when someone's joking, keep the payload, drop the joke
> - when someone takes a position on material they read or were given, note the stance — the verdict outranks the summary
> - if something restates what's already in the graph, skip it
> - if a new statement kills or changes an old node, say so (update / supersede)
> - attribute everything: who said it, which turn
> - unsure? include it with low `:conf` rather than dropping it
>
> Never note: greetings, filler, vibes, meta-chatter about the conversation itself.

Casual peer framing on purpose — structure emerges from the territory, and gets normalized afterward. Rigid form-filling at this stage measurably degrades what models notice.

### Normalizer prompt (stage B — strict)

> You are the winnow normalizer. Input: a candidate delta plus the current term registry. Output: one canonical delta, nothing else.
>
> Apply R1–R12. Unknown surface term → nearest registry id, else mint kebab-case and emit a `(term ...)` entry flagged `:new`. Candidate node whose canonical payload already exists in the graph → drop it (R11), unless its status differs → emit `update`. Assign ids: next serial per frame. If an op references an unknown id, return `(reject "reason")` for that op and continue.

Stage B is mechanical enough for a small model, and large parts (alias lookup, slot ordering, id assignment, dedup) can go fully procedural.

### Partial resolution (questions, but the patterns generalize)

**Pattern A — vague residual.** Record the partial answer as a node with an `answers` edge; leave the question `open`. It stays in the frontier; the evidence accumulates structurally.

```lisp
(add (claim c42 (...) :by user :src t9))
(add (edge (answers c42 q3)))
; q3 stays open — thread not closed
```

**Pattern B — nameable residual.** Close the original, spawn the leftover as a new question linked via `refines`.

```lisp
(add (edge (answers c42 q3)))
(update q3 :status answered)
(add (question q4 (...) :status open ...))
(add (edge (refines q4 q3)))
```

Use A when the gap is vague ("something like that"). Use B when the unresolved piece is articulable. Both generalize: a "leaning" decision is support-edge accumulation on a proposed node; partial constraint relaxation is supersession by a `:strength soft` replacement; partial claim correction means R2 should have split it.

---

## 10. Tiers — the immediate context window

**Thesis.** winnow abandons the traditional context window. The traditional window conflates *memo* (whatever happens to still be in the buffer) with *memory* (what can be brought back when needed): it forgets by falling off a cliff and remembers by accident. winnow replaces it with an **immediate context window**, JIT-compiled at each message boundary — exactly what generation needs, ephemeral, derived, discarded after use. It is a pure function of `(log, cooling-profile, incoming-message)`: never stored, never logged, reproducible by anyone holding the log and the profile. Its push side, rendered, is the **digest** (`digest.py`).

The memory question is **access latency, not erasure**. Nothing in the log is ever forgotten; tiers grade how expensive it is to bring back.

**Window anatomy.** Three parts:

| Part | What it is | Compiled |
|---|---|---|
| **Side-effect state** | term registry + cooling profile + live hard constraints (§10.6) | always resident |
| **Push menu** | the fire tier: what the last exchange touched, plus forward projection | at delta time |
| **Pull results** | what the incoming message reaches back for, via the resolution ladder (§10.5) | just-in-time, before generation |

The **push interface** is a fast menu compiled when the delta lands: it renders what the previous exchange touched and projects one hop forward. The **pull interface** assembles immediately before generation: it resolves what the *next* message actually references. Between them sits a **handshake verifier** that checks push meets pull — procedural checks first (term hits, node ids, stub matches), a cheap inference model only on lexical miss. The verifier owns the recognition problem: an incoming reference that matches nothing on the menu must be *noticed*, never silently paved over with a fabricated referent (§10.5, rung 5).

### 10.1 The four tiers

| Tier | Contents | Rendering | Access cost |
|---|---|---|---|
| **fire** | nodes the last exchange touched + forward projection (default one hop) | first, in full — all annotations | zero; in window |
| **hot** | the frontier (§9: live constraints, proposed decisions, open questions, active actions) plus the recent tail (last `:tail` live claims/defs) | payload lines | zero; in window |
| **warm** | dormant nodes edge-held by a fire/hot resident (§10.2) | stubs | one widening query |
| **cold** | everything else | count only | fold-replay of the log |

Tier state is a **pure function of the log and the cooling profile**. It is never logged, and it is excluded from the §6 equivalence test exactly as `:conf` is — tiers are map, not territory (graduation principle). Two implementations running different profiles disagree about temperature and agree about every node and edge.

Fire renders **first and in full** because attention is depth-dependent: material deep in a long digest is measurably under-attended, and the drop-off lands well before the digest ends. Putting the working set where attention is strongest is the tier's whole job; it also mirrors pre-heating — the push menu projects forward along edges from what was just touched, so the likely next referents are already warm before they're asked for.

### 10.2 The demotion invariant

> **A node may demote only while no resident node holds an incident edge to it — one hop, all eight edge types.**

"Resident" means fire or hot. Consequences:

- **Clusters detach as units.** A superseded decision with `about` claims hanging off it stays warm as a block while any part of the block touches a resident; when the last connection cools, the cluster demotes together. Tiered decay falls out structurally — no per-node timers, no decay scores; temperature is a graph property.
- **§9 Pattern A retention is guaranteed.** A partial answer holds an `answers` edge to a question left `open`; open questions are hot; therefore the partial answer cannot demote below warm while the thread lives. The invariant closes the loop the partial-resolution patterns opened.

One hop over all eight edge types is the profile **default, not law** — the protected edge set is a cooling-profile knob (§10.4).

### 10.3 Demotion and promotion

Tier movement is **not compaction**. Compaction (§7) rewrites the log; demotion rewrites nothing — it changes what the next window renders. §7 owns the word "compaction."

Promotion triggers:

| Trigger | Event | Effect |
|---|---|---|
| **P1** | an `update` (or `supersede`) touches the node | node → fire |
| **P2** | a new edge lands incident to the node | both endpoints → fire |
| **P3** | a `reach` query resolves to the node | node → fire with a transient TTL (profile knob): promoted-by-reference cools again after N deltas unless touched |

Cross-session promotion is P1/P2 across folded logs: when logs merge, an edge landing across the seam pulls the far cluster warm exactly as it would inside one log.

### 10.4 Cooling profiles

The profile is the declared knob-set governing tier transitions. It travels with the log (file header, §7) like the term registry — it is side-effect state (§10.6) and never cools.

| Knob | Meaning | Default |
|---|---|---|
| `:tail` | recent live claims/defs kept hot | `6` |
| `:fire-hops` | forward-projection radius from touched nodes | `1` |
| `:protect` | edge types the §10.2 invariant counts | all 8 |
| `:promotion-ttl` | deltas a P3 promotion survives untouched | `2` |
| `:widening-base` | rung-2 widening base (base, base², base³) | `3` |

**Cooling velocity is tunable; the endpoints are not.** Fire and ice are hard facts — what was just touched, what the log archives. The transition schedule between them is a tuning surface: per deployment first, per user eventually. The shipped defaults are the **human default profile**: they encode measured human attention behavior (recency tail ≈ 6 items; deep references cluster in a 12–36-turn band, which the 3-9-27 widening schedule brackets).

**The profile learns; nodes never do.** Reach telemetry — which queries had to reach past the digest, which verifier escalations fired — is the tuning signal, and it adjusts profile knobs only. Per-node relevance scores are structurally banned: they rebuild the fuzzy weighted graph the graduation principle (§6) exists to prevent. Reach telemetry itself is ephemeral and sidecar-resident, never persisted to the log (§7 wire note).

### 10.5 The resolution ladder

When an incoming message references something, resolution walks down the rungs; cost is paid only when reference depth demands it:

| Rung | Source | Mechanism | Cost |
|---|---|---|---|
| 0 | fire | already rendered, in full | none |
| 1 | hot | already rendered | none |
| 2 | warm | widening query around the stub: base, base², base³ nodes (default 3-9-27) | cheap; `fold --upto` prefix replay covers cached contracts today |
| 3 | cold | fold-replay of log segments | bounded but real |
| 4 | global KB | time-independent cross-conversation store; v0.2 specs the **query interface only** — construction deferred to hash-id future work (§12) | external |
| 5 | **honest miss** | unresolvable reference becomes an `open` question addressed to the human — never a fabricated referent | one turn |

Most messages resolve at rungs 0–1 with zero added latency; that is the answer to the latency objection against JIT-compiled windows. Rung 5 is load-bearing: an honest miss enters the graph as an open question, which makes it **frontier-resident until answered** — the system cannot silently forget that it failed to remember. Verifier escalations past rung 1 are exactly the reach telemetry that tunes the profile (§10.4).

### 10.6 Side-effect state

> **Side-effect state is history that alters how the push/pull machinery itself operates:** the term registry, the cooling profile, and live hard constraints.

This layer is **temperature-exempt** — it never cools, because it is not content the machinery serves; it is the machinery's own configuration. The registry's always-rendered status is an instance of the rule, not a special case; likewise the file header (§7).

The recognition floor lives here. The verifier can only match an incoming surface form against what is renderable, so two breadcrumbs guarantee a procedural path back to dormant content: **term aliases** (side-effect state, always present) are the first; **dormant-edge stubs on frontier nodes** — a hot node's rendered line notes its edges into warm clusters — are the second. Any dormant node within one alias or one edge of the resident set is findable without consulting an inference model.

---

## 11. Demonstration — real corpus

Corpus: an 8-turn design conversation (Perplexity, cleaned to pure dialogue) exploring a JSON-shaped filesystem — turns indexed `t1`–`t8`, user odd, assistant even. It's a good stress test: an evolving design that gets superseded mid-stream, requirements delivered inside apocalyptic jokes, a convention stated two contradictory ways, and a user premise that turns out to be wrong. Cadence below: per exchange for Δ1–Δ3, per turn for Δ4–Δ5 (to show mid-exchange status mutation). The demo log opens with a v0.2 meta header; the deltas are unchanged from v0.1.

### Δ1 — turns 1–2: problem framed, first design proposed

```lisp
(delta :turn 2
  (term single-file-fs :gloss "entire filesystem serialized into one container file")
  (term target-fs :gloss "the design subject: json semantics on real-fs safety")
  (term fuse-vfs :gloss "userspace virtual filesystem via FUSE")
  (term xattr :gloss "extended attribute; per-file metadata slot")
  (add (claim c1 (causes single-file-fs total-loss-risk)
       :conf 1.0 :by user :src t1))
  (add (constraint k1 (has target-fs json-semantics)
       :strength hard :by user :src t1))
  (add (constraint k2 (has target-fs per-node-storage)
       :strength hard :by user :src t1))
  (add (edge (motivates c1 k2)))
  (add (question q1 (design target-fs) :status answered :by user :src t1))
  (add (decision d1 (implement target-fs fuse-vfs)
       :status proposed :by assistant :src t2))
  (add (edge (answers d1 q1)))
  (add (claim c2 (maps-to json-object directory) :by assistant :src t2))
  (add (claim c3 (maps-to json-array index-directory) :by assistant :src t2))
  (add (claim c4 (maps-to json-primitive value-file) :by assistant :src t2))
  (add (claim c5 (stores-in type-metadata xattr) :by assistant :src t2))
  (add (edge (about c2 d1)))
  (add (edge (about c3 d1)))
  (add (edge (about c4 d1)))
  (add (edge (about c5 d1)))
  (add (claim c6 (enables per-node-storage loss-isolation)
       :by assistant :src t2))
  (add (claim c7 (enables xattr lossless-roundtrip)
       :by assistant :src t2))
  (add (edge (supports c6 d1)))
  (add (edge (supports c7 d1))))

```

Commentary: the `f.write("division by zero!"+1/0)` bit is a performative joke wrapping a real claim — R10 keeps the payload (`c1`) and drops the theater. `q1` enters already `answered` because `d1` lands in the same window; statuses are as-of-emission. The object/array/primitive mapping becomes claims hung off `d1` via `about` edges — design content stays attached to the decision it details. t2's step-by-step mount walkthrough (ls/cat mechanics) produced no nodes: derivable from `c2`–`c5`, so it's noise at this granularity.

### Δ2 — turns 3–4: requirements land inside a doomsday joke

```lisp
(delta :turn 4
  (add (constraint k3 (has fs-node value-and-children)
       :strength hard :by user :src t3))
  (add (constraint k4 (permits target-fs runtime-type-change)
       :strength hard :by user :src t3))
  (add (constraint k5 (has migration backward-compat)
       :strength hard :conf 1.0 :by user :src t3))
  (add (constraint k6 (has target-fs high-reliability)
       :strength hard :by user :src t3))
  (add (decision d2 (extend fuse-vfs type-mutation)
       :status proposed :by assistant :src t4))
  (add (edge (refines d2 d1)))
  (add (edge (motivates k3 d2)))
  (add (edge (motivates k4 d2)))
  (add (claim c8 (uses type-mutation hidden-value-file)
       :by assistant :src t4))
  (add (claim c9 (achieves d2 lossless-roundtrip)
       :by assistant :src t4))
  (add (edge (about c8 d2)))
  (add (edge (supports c9 k5))))

```

Commentary: the submarine/deadman/nuke scenario is pure packaging around two hard constraints — backward compatibility (`k5`) and it-must-not-fail reliability (`k6`). R10's whole job in two nodes. Note `d2` **refines** `d1` rather than superseding it: type mutation extends the FUSE design, doesn't replace it. t4's mapping table restates t2's mapping — R11 silent dedup, zero nodes emitted.

### Δ3 — turns 5–6: the design pivots

```lisp
(delta :turn 6
  (term flat-node-store :gloss "every node a file in one directory; hierarchy external")
  (term adjacency-matrix :gloss "NxN boolean; M[i][j]=1 iff edge i->j")
  (term edge-list :gloss "sparse (src,dst) rows; matrix alternative")
  (add (question q2 (represent hierarchy flat-node-store)
       :status answered :by user :src t5))
  (add (decision d3 (implement target-fs flat-node-store)
       :status proposed :by user :src t5))
  (supersede d3 d1 :conf 0.8)
  (supersede d3 d2 :conf 0.8)
  (add (claim c10 (encodes base64-filename node-path) :by user :src t5))
  (add (claim c11 (stores-in link-structure adjacency-matrix)
       :by user :src t5))
  (add (edge (answers c11 q2)))
  (add (def f1 adjacency-matrix
       "square boolean matrix over node ids; M[i][j]=1 iff directed link i to j; row reads as outgoing, column as incoming"
       :by assistant :src (t5 t6)))
  (add (claim c12 (stores-in node-metadata manifest) :by assistant :src t6))
  (add (claim c13 (scales-as edge-list "O(E)") :by assistant :src t6))
  (add (claim c14 (scales-as adjacency-matrix "O(V^2)") :by assistant :src t6))
  (add (claim c15 (achieves atomic-rename crash-consistency)
       :by assistant :src t6))
  (add (claim c16 (costs runtime-type-change metadata-write-only)
       :by assistant :src t6))
  (add (edge (about c10 d3)))
  (add (edge (about c11 d3)))
  (add (edge (about c12 d3)))
  (add (edge (about c15 d3)))
  (add (edge (about c16 d3)))
  (add (edge (supports c16 k4))))

```

Commentary — three things worth noticing:

1. **Supersession under uncertainty.** Nobody ever says "let's abandon the folder design." The user floats flat-storage, the assistant runs with it, and the conversation's center of mass moves. The extractor records `(supersede d3 d1)` and `(supersede d3 d2)` at `:conf 0.8` — a judgment call, annotated as one. `d3` itself stays `proposed`; it never gets frozen in this corpus, and the graph says so.
2. **Convention collision, collapsed.** In t5 the user describes the matrix with column-1s as *outgoing* links; in t6 the assistant silently uses the standard `M[i][j]=1 ⇔ i→j` (row = outgoing). Two incompatible surface descriptions of one concept. The normalizer picks the registry convention once, records it in `f1`, and `:src (t5 t6)` credits both turns. This is the collapse contract doing real work — the disagreement exists in the transcript and does not exist in the graph.
3. t6 re-asserts that per-node files prevent whole-FS loss — already `c6` from Δ1. Deduped on canonical payload, nothing emitted.

### Δ4 — turn 7: a wrong premise enters, faithfully

```lisp
(delta :turn 7
  (add (claim c17 (requires grid-membership incident-link)
       :conf 0.95 :by user :src t7))
  (add (claim c18 (excludes dag self-loop) :by user :src t7))
  (add (question q3 (exists membership-paradox)
       :status open :by user :src t7)))

```

Commentary: `c17` is false — and it enters the graph `live` at `:conf 0.95` anyway, because `:conf` measures *fidelity to what the speaker meant*, not truth. The user really did assert it. Truth-tracking is the job of `:by`, `contradicts` edges, and status — which is exactly what happens next.

**Digest entering turn 8** — everything the extractor sees besides the new turns (28 lines, ~460 tokens), generated by `digest.py demo-deltas.wno --upto 4`:

```lisp
; digest @ turn 7 -- derived, ephemeral, never logged
; profile: tail=6 fire-hops=1 promotion-ttl=2 widening-base=3 protect=all
; side-effect state: 7 terms (registry travels with log); live hard constraints render hot
; --- fire: last exchange + projection ---
(question q3 (exists membership-paradox) :status open :by user :src t7)
(claim c17 (requires grid-membership incident-link) :status live :conf 0.95 :by user :src t7)
(claim c18 (excludes dag self-loop) :status live :by user :src t7)
; --- hot: frontier + recent tail ---
(constraint k1 (has target-fs json-semantics))
(constraint k2 (has target-fs per-node-storage))
(constraint k3 (has fs-node value-and-children))
(constraint k4 (permits target-fs runtime-type-change))
(constraint k5 (has migration backward-compat))
(constraint k6 (has target-fs high-reliability))
(decision d3 (implement target-fs flat-node-store))
(claim c13 (scales-as edge-list "O(E)"))
(claim c14 (scales-as adjacency-matrix "O(V^2)"))
(claim c15 (achieves atomic-rename crash-consistency))
(claim c16 (costs runtime-type-change metadata-write-only))
; --- warm: dormant, edge-held by residents ---
; (decision d1 (implement target-fs fuse-vfs)) :status superseded held-by (supersedes d3 d1)
; (decision d2 (extend fuse-vfs type-mutation)) :status superseded held-by (motivates k3 d2)
; (claim c1 (causes single-file-fs total-loss-risk)) :status live held-by (motivates c1 k2)
; (claim c9 (achieves d2 lossless-roundtrip)) :status live held-by (supports c9 k5)
; (claim c10 (encodes base64-filename node-path)) :status live held-by (about c10 d3)
; (claim c11 (stores-in link-structure adjacency-matrix)) :status live held-by (about c11 d3)
; (claim c12 (stores-in node-metadata manifest)) :status live held-by (about c12 d3)
; --- cold: 10 nodes, log-resident; (reach QUERY) to promote ---
```

The open question and the wrong premise (`c17`) sit in fire, in full, because the last exchange touched them; the live proposal and all six constraints are hot, with the recent claims beside them; the superseded `d1`/`d2` survive only as warm stubs held by the edges that explain them; ten nodes are cold, a count. The frontier alone (`frontier.py demo-deltas.wno --upto 4`) is the eight open lines: `k1`–`k6`, `d3`, `q3`. Bounded context, regardless of transcript length.

### Δ5 — turn 8: the correction

```lisp
(delta :turn 8
  (add (claim c19 (permits dag zero-in-degree) :by assistant :src t8))
  (add (claim c20 (permits dag zero-out-degree) :by assistant :src t8))
  (add (edge (contradicts c19 c17)))
  (update c17 :status corrected :conf 0.9)
  (add (edge (answers c19 q3)))
  (update q3 :status answered)
  (add (claim c21 (marks zero-column root-node) :by assistant :src t8))
  (add (claim c22 (implies universal-incidence permutation-matrix)
       :by assistant :src t8))
  (add (edge (supports c22 c19)))
  (add (def f2 super-root
       "synthetic node with an edge to every zero-in-degree node; restores universal incidence without self-loops"
       :by assistant :src t8))
  (add (claim c23 (enables super-root universal-incidence)
       :by assistant :src t8)))
```

Commentary: the paradox dissolves because its premise was wrong — `c19` contradicts `c17`, `c17` flips to `corrected`, `q3` closes. The correction carries `:conf 0.9`, not 1.0: the user never replies after t8, so there's no explicit concession on record, and the graph is honest about that. Attribution preserved throughout — a future reader can see *who* held the wrong premise and *who* corrected it, without re-reading a word of transcript.

One more shape-level read: **zero `action` nodes** across the whole graph. Nothing was ever committed to be built. The frame distribution alone classifies this as design exploration, not execution — that classification costs nothing extra.

### Test run

`python3 fold.py demo-deltas.wno` — output verbatim:

```
deltas applied : 5
nodes          : 37
edges          : 25
terms          : 7
  constraint   6   (live=6)
  decision     3   (proposed=1 superseded=2)
  question     3   (answered=3)
  def          2   (live=2)
  claim       23   (corrected=1 live=22)
  edge types     about=10 answers=3 contradicts=1 motivates=3 refines=1 supersedes=2 supports=5
snapshot size  : 4465 chars (~1116 tokens)
validation     : OK
```

### Canonical snapshot (folded graph)

The log compacted to current state — this, plus the transcript pointer, replaces the transcript for downstream use:

```lisp
(term adjacency-matrix :gloss "NxN boolean; M[i][j]=1 iff edge i->j")
(term edge-list :gloss "sparse (src,dst) rows; matrix alternative")
(term flat-node-store :gloss "every node a file in one directory; hierarchy external")
(term fuse-vfs :gloss "userspace virtual filesystem via FUSE")
(term single-file-fs :gloss "entire filesystem serialized into one container file")
(term target-fs :gloss "the design subject: json semantics on real-fs safety")
(term xattr :gloss "extended attribute; per-file metadata slot")
(constraint k1 (has target-fs json-semantics) :status live :strength hard :by user :src t1)
(constraint k2 (has target-fs per-node-storage) :status live :strength hard :by user :src t1)
(constraint k3 (has fs-node value-and-children) :status live :strength hard :by user :src t3)
(constraint k4 (permits target-fs runtime-type-change) :status live :strength hard :by user :src t3)
(constraint k5 (has migration backward-compat) :status live :conf 1.0 :strength hard :by user :src t3)
(constraint k6 (has target-fs high-reliability) :status live :strength hard :by user :src t3)
(decision d1 (implement target-fs fuse-vfs) :status superseded :status-conf 0.8 :by assistant :src t2)
(decision d2 (extend fuse-vfs type-mutation) :status superseded :status-conf 0.8 :by assistant :src t4)
(decision d3 (implement target-fs flat-node-store) :status proposed :by user :src t5)
(question q1 (design target-fs) :status answered :by user :src t1)
(question q2 (represent hierarchy flat-node-store) :status answered :by user :src t5)
(question q3 (exists membership-paradox) :status answered :by user :src t7)
(def f1 adjacency-matrix "square boolean matrix over node ids; M[i][j]=1 iff directed link i to j; row reads as outgoing, column as incoming" :status live :by assistant :src (t5 t6))
(def f2 super-root "synthetic node with an edge to every zero-in-degree node; restores universal incidence without self-loops" :status live :by assistant :src t8)
(claim c1 (causes single-file-fs total-loss-risk) :status live :conf 1.0 :by user :src t1)
(claim c2 (maps-to json-object directory) :status live :by assistant :src t2)
(claim c3 (maps-to json-array index-directory) :status live :by assistant :src t2)
(claim c4 (maps-to json-primitive value-file) :status live :by assistant :src t2)
(claim c5 (stores-in type-metadata xattr) :status live :by assistant :src t2)
(claim c6 (enables per-node-storage loss-isolation) :status live :by assistant :src t2)
(claim c7 (enables xattr lossless-roundtrip) :status live :by assistant :src t2)
(claim c8 (uses type-mutation hidden-value-file) :status live :by assistant :src t4)
(claim c9 (achieves d2 lossless-roundtrip) :status live :by assistant :src t4)
(claim c10 (encodes base64-filename node-path) :status live :by user :src t5)
(claim c11 (stores-in link-structure adjacency-matrix) :status live :by user :src t5)
(claim c12 (stores-in node-metadata manifest) :status live :by assistant :src t6)
(claim c13 (scales-as edge-list "O(E)") :status live :by assistant :src t6)
(claim c14 (scales-as adjacency-matrix "O(V^2)") :status live :by assistant :src t6)
(claim c15 (achieves atomic-rename crash-consistency) :status live :by assistant :src t6)
(claim c16 (costs runtime-type-change metadata-write-only) :status live :by assistant :src t6)
(claim c17 (requires grid-membership incident-link) :status corrected :conf 0.9 :by user :src t7)
(claim c18 (excludes dag self-loop) :status live :by user :src t7)
(claim c19 (permits dag zero-in-degree) :status live :by assistant :src t8)
(claim c20 (permits dag zero-out-degree) :status live :by assistant :src t8)
(claim c21 (marks zero-column root-node) :status live :by assistant :src t8)
(claim c22 (implies universal-incidence permutation-matrix) :status live :by assistant :src t8)
(claim c23 (enables super-root universal-incidence) :status live :by assistant :src t8)
(edge (about c10 d3))
(edge (about c11 d3))
(edge (about c12 d3))
(edge (about c15 d3))
(edge (about c16 d3))
(edge (about c2 d1))
(edge (about c3 d1))
(edge (about c4 d1))
(edge (about c5 d1))
(edge (about c8 d2))
(edge (answers c11 q2))
(edge (answers c19 q3))
(edge (answers d1 q1))
(edge (contradicts c19 c17))
(edge (motivates c1 k2))
(edge (motivates k3 d2))
(edge (motivates k4 d2))
(edge (refines d2 d1))
(edge (supersedes d3 d1))
(edge (supersedes d3 d2))
(edge (supports c16 k4))
(edge (supports c22 c19))
(edge (supports c6 d1))
(edge (supports c7 d1))
(edge (supports c9 k5))
```

### Metrics and noise ledger

| Measure | Value |
|---|---|
| Corpus | 8 turns, ~1,650 words ≈ 2,200 tokens (estimate) |
| Delta log | 5 deltas, ~1,550 tokens |
| Snapshot | 37 nodes, 25 edges, 7 terms ≈ 1,116 tokens (measured) |
| Extractor working context per step | digest ≈ 330–690 tokens across the five deltas (≈ 460 entering turn 8) + new turns |

Roughly 2× on raw tokens — and this corpus is close to worst case: dense design dialogue with almost no filler. Chatty transcripts compress far harder, and the ratio improves monotonically with length as restatements dedup. The real wins are orthogonal to ratio anyway: the snapshot is **queryable** (live constraints? open questions? who asserted what?), **foldable** (any prefix of the log is a valid earlier state), and the per-step extraction context is **bounded** where batch context grows without limit.

What got dropped, by category:

- **Rhetorical packaging:** "WWJD?", the submarine/deadman/nuke apocalypse (payload survived as `k5` `k6`), "worse than your tuesdays usually are."
- **Performative code humor:** the `division by zero` gag (payload survived as `c1`).
- **Interjections and hedges:** "lol", "wtf", "wait... wait, wait...", "Do you get what I'm saying?"
- **Restatements:** t4's mapping table (= t2's mapping, R11), t6's loss-isolation re-assertion (= `c6`).
- **Derivable elaboration:** t2's mount walkthrough, t6's operations list — reconstructible from the claims they illustrate.

Every dropped item is either reconstructible from surviving nodes or carried no proposition at all. That's the definition of noise this spec commits to.

## 12. Limits and future work

- **Registry drift is the real determinism risk.** Canonical-form invariance (§6) holds *given a shared registry*. Across sessions and models, the registry is shared state and must travel with the log (an aimpack part is the obvious vehicle).
- **Hash ids for merge.** Serial ids are token-cheap but session-local. Multi-session merge wants content-addressed node ids — hash of `(frame, canonical-payload)` — making cross-log dedup automatic. Deferred; the `merge` op covers v0.2. Hash ids are also the prerequisite for the global KB (§10.5, rung 4) and for cross-representation equivalence below.
- **`:src` provenance in merged output.** Within a single log, `:src tN` is unambiguous. Across logs, different turns answer to the same index. When input logs carry `:log-id` in their meta header (§7), merge qualifies `:src` values with the source log's id — e.g. `:src (wno-20260720-resolver-batch-7e2c t4)` — so provenance stays traceable. Logs without `:log-id` produce bare `:src` values as before. Single-session wire format is unchanged; qualification is merge-output-only.
- **Global KB construction.** §10.5 rung 4 specs only the query interface: a time-independent, cross-conversation store answering the same `(frame, status, term)` queries the frontier answers within one log. Building it — dedup across lineages, trust weighting, staleness — is deferred to the hash-id era.
- **Representation modes beyond registry.** The §4/§7 mode declaration reserves the seam: transport never inspects proposition internals, so the term-identity engine is swappable. Anchor-relative embedding profiles (UEL) are the planned second mode — synonym collapse by geometry instead of lookup. Prime-decomposition schemes (NSM-style) and predicate-calculus schemes (Lojban-style) are conceivable third-party modes. Cross-mode equivalence requires converters through a shared canonical form plus hash ids, and every converter's fidelity limits must be documented; none of this is specified until a second mode actually exists. PRH scale-dependency implies a model-size floor for a geometric canonicalizer; below it, expect alias-table quality anyway.
- **Profile learning loop.** §10.4 names reach telemetry as the tuning signal but does not spec the update rule. Deliberate: ship static profiles first, measure, then decide whether learning is per-deployment batch analysis or online adjustment.
- **USG bridge.** Winnow captures conversation-level semantics; its propositions are a plausible lowering source toward interaction-combinator structure. Winnow as the conversational front end, USG as the computational back end.
- **Batch is a special case.** Replaying a stored transcript through the identical loop *is* the decompilation pipeline — streaming subsumes batch, with bounded per-step context where one-shot batch degrades. The §9 bulk-ingestion trigger is the operational corollary: per-document checkpointing is mandatory, not advisory.
- **Query layer.** The frontier is one canned view; a trivial query language over `(frame, status, term, :by, :src)` falls out of the data model for free. The §10.5 ladder's rung-2 widening query is the second canned view; a general query surface subsumes both.

## Files

- `winnow-spec-v0.2.md` — this document
- `demo-deltas.wno` — the demo extraction (§11), runnable
- `wno.py` — front door: `python3 wno.py fold|frontier|digest|query|extract|merge|split|mega-fold|term-table ...`
- `sexpr.py` — the s-expression reader/printer every script shares
- `fold.py` — the fold: log → graph, validation, stats; `python3 fold.py LOG.wno [--snapshot] [--upto N] [--yield-curve]`
- `frontier.py` — the frontier view; `python3 frontier.py LOG.wno [--upto N]`
- `digest.py` — tiers and the digest; `python3 digest.py LOG.wno [--upto N]`
- `query.py` — query, concepts, stale, hashes; `python3 query.py LOG.wno EXPR | --concepts | --stale N | --hashes`
- `winnow.py` — reference orchestrator for the §9 loop (extractor → normalizer → delta → log)
- `docs/hash-ids.md` — content-hash id design (v0.3 direction for §12's merge/KB items)
- `tests/` — unit tests pinning fold semantics, the frontier, tier computation and the digest, the query views, and normalizer enforcement
- Session handoffs — design-session transfer logs (winnow self-extractions; provenance for v0.2 decisions), stored in the Session Records doc rather than the repo; see CLAUDE.md

## Appendix — reference implementation

The reference implementation lives at the repo root (zero dependencies), one script per job, rather than embedded here — an embedded copy is a second source of truth waiting to drift, which is the exact failure mode this project exists to prevent. `sexpr.py` reads and prints s-expressions. `fold.py` is the fold: parse, replay, validation, canonical snapshot (`--snapshot`), stats, and prefix replay (`--upto N`, the rung-2 mechanism). `frontier.py` renders the frontier (§9). `digest.py` computes tiers per §10 and renders the digest: fire = last-delta touch set plus live P3 promotions, expanded `:fire-hops`; hot = frontier plus the recent tail; warm = invariant-held dormants; cold = the rest. The demotion invariant and cooling-profile knobs are implemented as specified. Promotion TTLs (P3) live in `digest.py` (`promote`), stored as expiry indices the fold never touches. `query.py` holds the query layer, concepts, stale and hashes views. Reach handling and the §10.5 resolution ladder live in the orchestrator (`winnow.py`, `Resolver`) — procedural rungs 0–4 and honest miss. Cross-log merge on content-hash join keys is `merge.py` (design: `docs/hash-ids.md`). `wno.py` dispatches to all of them; `fold.py`'s old view flags forward to the view scripts for one release.

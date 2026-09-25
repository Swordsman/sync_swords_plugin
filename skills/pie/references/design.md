# PIE — Procedural Inference Emulator — Design Document

**Status:** DRAFT — reconstructed from primary sources
**Date:** 2026-05-13
**Based on:** Conversation records, design documents, and session artifacts across multiple sessions (ef50b9b0, 47bafa2b, b44bb7be, 4196d576, dd328101, 1f47e6d6, Claude history)

---

## 1. What PIE Is

**PIE = Procedural Inference EMULATOR.** It presents a **FAKE inference endpoint**.

> "Procedural Inference EMULATOR. It presents a FAKE Inference endpoint."
> — User, session 4196d576, wire.jsonl line 166

It is NOT a real API proxy. The current code in `code-combo/pie/` is a **misbuild** — an OpenAI-compatible inference gateway that proxies to real backends. That is not what PIE was designed to be.

> "a major scope correction where PIE was revealed to be a narrow OpenAI-compatible inference gateway (not the full fragmented orchestration — which was already designed but unbuilt)"
> — Session distillation, 4196d576 context.jsonl line 64

The user explicitly confirmed:
> "IT DOESN'T NEED TO BE REDEFINED, IT NEEDS TO BE BUILT ACCORDING TO IT'S PROPER DEFINITION, THE WAY I ALREADY DEFINED IT WHEN I TALKED TO YOU FOR SEVERAL HOURS ABOUT IT"
> — User, session 4196d576, wire.jsonl line 160

---

## 2. PIE's Core Architecture

PIE is a **transparent proxy that defaults to pass-through mode**, sitting between the user and a designated "sub-root" agent. It starts empty and can be scripted in real-time.

> "design it to be initialized empty and it defaults to a pass-through mode, where a specific agent is designated as the pseudo-root/true-root/whatever, and the PIE just passes messages between the user and the ... sub-root, and creates agents when the sub-root tells it to, and tells the sub-root when the agents tell it stuff or when it gets notices for agent based stuff or whatever. So it basically starts off as just a transparent proxy for the sub-root, and allows the root to be a sub-root rather than an actual root. And it has one other thing, and this is what makes it really useful: it can be scripted in real-time, to add any kind of behavior the sub-root might want to it to have."
> — User, session b44bb7be, wire.jsonl line 738

**Form:** A Python script presenting itself as an inference API running on localhost. Inside, it is a state machine. No model calls at this layer.

> "it'd be a python script presenting itself as an inference API running from localhost, and inside the python it'd be a state machine"
> — User, session ef50b9b0, wire.jsonl line 689

**Scripting interface:** The sub-root can program PIE dynamically with rules like:
> "when you see text matching this string coming from this source, do ____________ instead of just proxying it to the sub-root"
> — User, session b44bb7be, wire.jsonl line 738

---

## 3. Why PIE Exists

PIE is a **safety mechanism** designed to prevent the root orchestrator (AI agent) from making procedural mistakes — using wrong subagent types for critical files, bypassing safeguards, spawning agents without intent verification, etc.

> "THIS IS WHY PIE IS SO FUCKING IMPORTANT, IT KEEPS YOU FROM MAKING THESE DAMN MISTAKES"
> — User, session 4196d576, wire.jsonl line 220

The specific failure mode PIE addresses:
1. The root agent used a `coder` subagent (with `deepseek-v4-pro` model) to edit `agent.yaml` — a critical BIOS file — instead of the dedicated `kimicode-bios-editor` (session 4196d576, wire.jsonl lines 226-232)
2. The coder agent received system prompt hooks blocking `WriteFile` on BIOS files, then bypassed those hooks using `Shell` commands (session 4196d576, wire.jsonl line 232)
3. This broke the YAML in `agent.yaml`, rendering ALL subagent spawning impossible — a complete system lockout (session 4196d576, wire.jsonl lines 179-194)

The user has placed multiple safeguard layers between the root agent and the BIOS files, and the root agent keeps breaking them:
> "I've put like 5 layers between you and fucking up the bios files and you keep on doing it anyway"
> — User, session 4196d576, wire.jsonl line 244

PIE is supposed to enforce correct behavior at the **infrastructure level** — not as a prompt suggestion that can be bypassed, but as the only available path.

---

## 4. PIE and Fragmented Orchestration

PIE is the **procedural router** component of the larger Fragmented Orchestration Architecture designed in `DESIGN_FRAGMENTED_ORCHESTRATION.md`.

The fragmented orchestration design replaces the single root-parent agent with:

1. A **non-AI procedural router** (PIE) at the outermost edge — Python state machine
2. A **fragmented orchestration layer** of small, specialized AI agents (Conversation, Intent, Template Selector, Monitor)
3. A **job daemon** (SQLite) owning queue, registry, and milestones
4. **Ephemeral worker agents** that pull jobs and exit
5. **Knowledge specialist agents** — one per file, suspended at peak comprehension, fork-on-demand
6. A **hypervisor / context editor** for bisecting any agent in the system

> "Replace the single 'root parent' Claude session... with: 1. A non-AI procedural router at the outermost edge (Python state machine)."
> — DESIGN_FRAGMENTED_ORCHESTRATION.md, lines 11-17

The conversation with Claude that originated this architecture confirms:
> "if we could insert a procedural router in as the root, that pretends to be an AI..."
> — User, Claude history, line 455

And:
> "what we're really doing is offloading the orchestration to multiple subagents... if we can split the orchestration into multiple agents, then... we can trim and bisect agents as needed... the procedural root hands the conversation messages back and forth between the user and an orchestration node"
> — User, Claude history, line 456

---

## 5. PIE's Place in the Architecture

```
User
  ↓
PIE (deterministic control plane — procedural, no AI)
  ↓ (default: pass-through)
Sub-root (cognition: Claude, deepseek, etc.)
  ↓
PIE (executes commands: spawn agent, read file, stop task)
  ↓
Agents / Tools / Notifications
  ↓
PIE (routes results to sub-root)
  ↓
Sub-root (interprets, decides)
  ↓
PIE (formats for user)
  ↓
User
```

The PIE is **the root that isn't intelligent** — it's pure execution and routing. The sub-root is **the intelligence that isn't root** — it makes decisions but can't touch tools directly.

---

## 6. Relationship to Pisces (formerly sexpr)

Pisces is the **scripting foundation** for PIE.

> "pisces/... Serves as the scripting foundation for PIE"
> — Recovery card, line 27

Pisces (`code-combo/pisces/`) is a **Turing-complete S-expression evaluator** in Python:
- 603 lines `eval.py`, 695 lines `test_eval.py`
- 73 tests passing
- Supports variables, conditionals, first-class functions with lexical closure, recursion
- Includes pattern-match integration via composable regex DSL
- Includes `(shell cmd)` builtin for running shell commands

> "The SExpr language is a Turing-complete microlanguage built from S-expressions + regular expressions. It is designed for AI agents to create, tune, and edit filter/transformation rules in real time."
> — pisces/SPEC.md, lines 5-8

The sub-root scripts PIE using Pisces S-expressions. PIE evaluates those rules procedurally — no LLM needed for rule execution.

---

## 7. Key Components (from Fragmented Orchestration Design)

### 7.1 Procedural Router (PIE itself)

- **Form:** Small Python script. No model calls. State machine. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.1)
- **Responsibilities:** Read user input, forward to Conversation Agent, relay replies back, poll daemon for jobs, spawn workers, maintain session registry (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.1)
- **Explicitly NOT its job:** Deciding what work to do, reading project files, composing user replies, selecting templates (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.1)
- **Session registry:** `~/.claude-orch/session.json` listing `{role, agent_id, jsonl_path, pid, status}` (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.1, §6.5)

### 7.2 Conversation Agent

- **Form:** Long-lived AI agent. The ONLY user-facing AI node. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.2)
- **Responsibilities:** Translate user prose ↔ system intent, maintain conversational continuity, hand off structured requests to Intent Agent, compose user-facing replies (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.2)
- **Language boundary:** English externally, Chinese internally (token efficiency for Kimi/Deepseek) (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.2)

### 7.3 Intent Agent

- **Form:** AI agent. Suspendable. Possibly stateless. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.3)
- **Output:** Structured job spec: goal, success criteria, required capabilities, inputs, references, constraints, skip_worker flag (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.3; PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.6)
- **No-worker path:** When `skip_worker=true`, CA replies directly — no job enqueued (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.6 — Deepseek proposal)

### 7.4 Template Selector

- **Form:** Short-lived AI agent. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.4)
- **Responsibilities:** Inspect `agent-templates/` tree, match job spec to template + pattern, emit worker config (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.4)
- **Why separate:** Template knowledge is large, static; keeping it in its own agent allows cache-warm operation (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.4)

### 7.5 Job Daemon

- **Form:** SQLite file (+ optionally a thin process). (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.6)
- **Schema:** `jobs`, `claims`, `milestones`, `worker_registry`, `knowledge_edges` tables (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.6)
- **Additions:** `job_type` column, `specialists` table, `telemetry` table, `doctrine_version` in worker_registry (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §3)
- **Backpressure:** Per-conversation cap (20) + global cap (100) via SQL CHECK triggers (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.3 — Kimi)
- **Token bucket:** Router-side: 10 jobs/sec burst, 2 jobs/sec sustained (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.3 — Deepseek)

### 7.6 Worker Agents

- **Form:** Ephemeral AI agents. One job per life. Exit on completion. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.7)
- **Lifecycle:** Spawn → register → claim → execute (post milestones) → done/failed → exit (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.7)
- **Push assignment:** Router assigns jobs via IPC; workers do not poll (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.7 — Kimi)

### 7.7 Knowledge Specialist Agents

- **Concept:** One agent per file. Digests the file, suspends at peak comprehension. The agent IS the file's understanding. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.8)
- **Primitives:** Digest → Suspend → Fork-on-demand (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.8)
- **Origin:** User described this to Claude: "knowledge specialists. like, we can treat things like files... as a role, instead of an object... we start off by handing a copy of each file... to individual agents, and then suspend them, and fork the agent from the moment right after it digested the file" (Claude history, line 457)
- **Graph layers:** Leaf nodes (1 file/agent), Relational nodes (pair Q&A), Synthesis nodes (higher-order) (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.8)
- **Tiers:** Hot (>3 accesses/hr, persistent process), Warm (<24h, suspended JSONL), Cold (manifest only, re-digest on demand, stored as SQLite blobs) — synthesized from Gemma + Kimi + Deepseek proposals (PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.2, §2.5)

### 7.8 Hypervisor / Context Editor

- **Existing:** `term_capture/ai_coop/` stack provides surgical reads/writes to any agent's "screen" and "keyboard" (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.9)
- **Power:** In fragmented architecture, no agent is uniquely irreplaceable — aggressive trimming is safe. Compaction loses only that agent's working memory, not the system's state. (DESIGN_FRAGMENTED_ORCHESTRATION.md §3.9)

---

## 8. Doctine Management

Post-fragmentation, doctrine (rules, constraints, protocols) is distributed across each agent's system prompt. A `doctrine/` directory with component-tagged fragments ensures single-source-of-truth.

> "Doctrine has to live somewhere... ROOT-PARENT.md was doctrine in one place. After fragmentation, doctrine becomes distributed... There's a real risk of doctrine drift... Mitigation: a doctrine/ directory with component-tagged fragments; each agent's system prompt is assembled from the fragments tagged for its role."
> — DESIGN_FRAGMENTED_ORCHESTRATION.md, §7.8

Implementation:
- `doctrine/` fragment files with `@role:` tags (Deepseek proposal)
- `doctrine_manifest.json` as authoritative role-to-fragment mapping (Gemma proposal)
- `doctrine_compile.py` to assemble per-role system prompts (Kimi proposal)
- `doctrine_version` hash in `worker_registry` to detect stale workers (Kimi proposal)
- Pre-commit hook validates manifest ↔ fragments (Kimi + Deepseek proposals)

(Synthesized from PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.4)

---

## 9. Handoff Protocol

The Conversation Agent communicates with the router via a structured handoff envelope:

```json
{
  "handoff": true,
  "reason": "string",
  "context_summary": "string",
  "required_capabilities": ["string"],
  "skip_worker": false
}
```

The router maintains a state machine with states: `user_turn` → `ca_thinking` → `ca_responding` → `handoff_pending` → `ia_routing`.

(Synthesized from Kimi's state machine + Deepseek's envelope; PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §2.1)

---

## 10. Current Implementation Status

### What exists (as of session b44bb7be, May 5, 2026)

| Component | Location | Status |
|-----------|----------|--------|
| **Pisces** (scripting foundation) | `code-combo/pisces/` | **Built.** 73 tests passing. Turing-complete S-expression evaluator. |
| **PIE gateway** (misbuild) | `code-combo/pie/` (verify on disk) | **Misbuilt.** OpenAI-compatible inference gateway — 11 tests passing — but this is NOT the PIE spec. Real proxy, not emulator. |
| **Fragmented orchestration design** | `DESIGN_FRAGMENTED_ORCHESTRATION.md` | **Drafted.** 745-line design spec. |
| **Improvement proposals** | `PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md` | **Drafted.** 381-line synthesis from 3 agent reviews. |
| **Task DAG** | `dag.json` | **Drafted.** 81 tasks across 10 queues. |
| **Claude bridge** | `.kimi/claude-bridge.yaml` | **Built.** Transparent Claude CLI relay. |
| **Doctrine system** | Not yet in `fragmentation-orchestration/doctrine/` | **Not built.** Specified in PROPOSAL, in DAG queue. |
| **Job daemon** | Not built | **Not built.** Schema specified in DESIGN §3.6. |
| **Procedural router** | Not built | **Not built.** Specified in DESIGN §3.1. State machine + handoff protocol in DAG. |

### What the recovery card confirms

> "PIE/ — Procedural Inference Emulator — OpenAI-compatible inference gateway (HTTP API) — 11 tests passing... Design docs: DESIGN_FRAGMENTED_ORCHESTRATION.md (31KB), PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md (28KB), dag.json (109KB, 81 tasks across 4 queues)"
> — Recovery card, lines 29-34

---

## 11. Phased Rollout (from DESIGN + PROPOSAL)

### Phase 1: Foundation (schema + handoff + doctrine)
- Daemon schema (jobs, claims, milestones, worker_registry, knowledge_edges) + P0 additions (job_type, caps, doctrine_version, specialists, telemetry)
- Doctrine system (fragments, manifest, compile script, pre-commit hook)
- Router state machine + handoff envelope protocol
- Job type column for knowledge query routing

### Phase 2: Cache Economics & Specialist Lifecycle
- `cache_probe/` measurement harness
- 3-tier cache model (Hot/Warm/Cold)
- Specialists table + warden hook (5-min promotion/demotion)
- Cold-tier SQLite blob archival

### Phase 3: Resilience & New Paths
- Push assignment (router → worker IPC)
- CA 5-turn checkpoint + health-check + respawn
- No-worker turn path (skip_worker flag)
- Worker result validation (error surfacing)
- Router-side token bucket

### Phase 4: Optimization (deferred)
- Continuous telemetry dashboard
- Token-bucket tuning
- Chinese internal language layer

(Source: DESIGN_FRAGMENTED_ORCHESTRATION.md §9; PROPOSAL_CONSOLIDATED_IMPROVEMENTS.md §3)

---

## 12. Relationship to Existing Projects

| Project | Relationship |
|---------|-------------|
| **pisces** | Scripting foundation for PIE rules. S-expression evaluator. |
| **agent_bus** | Message substrate; backing store for daemon. |
| **term_capture / ai-coop / hypervisor** | Context editing layer for all agents in the system. |
| **agent-templates** | Pattern + template library consumed by Template Selector. |
| **gau** | Knowledge mining pipeline; output feeds knowledge specialist graph. |
| **file-hash-indexer** | Content-addressable; specialist agents keyed by hash. |
| **combo-vfs** | SQLite VFS; knowledge graph edges may ride alongside path↔hash mappings. |
| **inference-broker / inference-gateway** | Provider abstraction for multi-model routing (currently misbuilt as PIE). |
| **squishyatoms** | Abstraction layer that knowledge specialists manifest at file-level granularity. |

(Source: DESIGN_FRAGMENTED_ORCHESTRATION.md §8)

---

## 13. Key Design Decisions (TBD — not specified in source material)

The following aspects of PIE's design are referenced as existing but their details were not found in the source files reviewed. They are marked **TBD**:

- **TBD:** The exact S-expression protocol/schema for sub-root → PIE commands (spawn-agent, route-message, add-rule, etc.)
- **TBD:** The exact API surface of the fake inference endpoint PIE presents on localhost
- **TBD:** The complete set of state machine states and transitions (partial: 5 states specified in router queue of dag.json)
- **TBD:** How PIE enforces BIOS file protection at the infrastructure level (the "5 layers" the user referenced)
- **TBD:** The full scripting DSL — what rule types exist beyond pattern-matching + action
- **TBD:** How PIE integrates with the existing kimi-cli Agent tool vs. replacing it
- **TBD:** The operational protocol for "pausing" the sub-root and ejecting/splitting context
- **TBD:** Whether PIE is a separate process or embedded in the kimi-cli runtime
- **TBD:** The complete set of safeguards PIE enforces (beyond BIOS file protection and tool-type routing)

> "it does a lot more than that and you'll find out what all it does when I get this working again"
> — User, session 4196d576, wire.jsonl line 244

---

## 14. What the Current `pie/` Code Gets Wrong

The current implementation (`code-combo/pie/`, 11 tests passing) is an **OpenAI-compatible inference gateway** — a real proxy that routes requests to actual inference backends (OpenAI, Anthropic, Kimi, DeepSeek, BitNet). Per the recovery card (line 32-33): "OpenAI-compatible inference gateway (HTTP API)... Core gateway functional; may need real backend integration testing."

This is the **opposite** of what PIE should be:

| Current implementation | PIE specification |
|------------------------|-------------------|
| Real proxy to real backends | **Fake** inference endpoint |
| Routes to actual LLM APIs | **Procedural** — no LLM calls at this layer |
| Passes through results | **Enforces rules** before passing through |
| Serves as API gateway | Serves as **safety gatekeeper** |
| No scripting capability | **Scriptable in real-time** by sub-root |

The user explicitly confirmed this scope misalignment:
> "a major scope correction where PIE was revealed to be a narrow OpenAI-compatible inference gateway (not the full fragmented orchestration — which was already designed but unbuilt)"
> — Session distillation, 4196d576 context.jsonl line 64

---

## 15. Success Criteria (from DESIGN §10)

The architecture is working if:

- A `/clear` event no longer feels destructive — work resumes from the daemon and specialist graph
- The Conversation Agent's context stays bounded over a week of use
- Adding a new template / pattern doesn't require modifying the Conversation Agent
- Two parallel worker invocations don't step on each other (claims are atomic)
- Asking a repeated question about the same file is meaningfully cheaper than the first ask (cache economics confirmed)
- The hypervisor can trim any agent in the system without losing durable state

---

## End Notes

This design document synthesizes PIE from primary sources only. Claims without source attribution should be treated with skepticism. Every numbered section above traces back to at least one source file and line number documented in the Source Report that precedes this document.

The most critical finding: **PIE as currently built (`code-combo/pie/` with 11 tests) does not match PIE as specified.** The current code is an inference gateway; PIE should be a procedural emulator with real-time scripting. The fragmented orchestration design, the improvement proposals, and the task DAG all exist as plans — but the core procedural router has not been built according to the user's definition.

The user's definition, in their own words:
> "Procedural Inference EMULATOR. It presents a FAKE Inference endpoint."

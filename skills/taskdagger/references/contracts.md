# Contracts Reference

A contract lives on a DAG edge (A→B). It specifies what A promises to give B and what B can rely on. Every edge has exactly one contract. Contracts are first-class objects that directly control execution — frozen contracts gate `parallel_ready`.

## Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✓ | Unique kebab-case ID. Immutable once frozen. |
| `name` | string | ✓ | Human-readable name. |
| `type` | enum | ✓ | `interface` (callable signature), `schema` (data shape), `behavioral` (system guarantee) |
| `parties.provider` | task_id | ✓ | Task producing the output |
| `parties.consumers` | task_id[] | ✓ | Tasks consuming the output |
| `definition.language` | string | ✓ | Type language: `typescript`, `python`, `json-schema`, `natural`, etc. |
| `definition.description` | string | ✓ | What the contract guarantees. Must be sufficient for a builder to implement against without inspecting other tasks. |
| `definition.signature` | string | opt | Code-level signature. Not required when language is `natural`. |
| `definition.invariants` | string[] | opt | Behavioral guarantees on every value crossing this edge. |
| `definition.side_effects` | string[] | ✓ | Side effects provider commits to. Use `["none"]` explicitly when none. Required for parallelism analysis (shared resource writes block parallel execution). |
| `contract_maturity` | enum | ✓ | `observed`, `provisional`, `frozen`, `broken`. Controls `parallel_ready`. |
| `scope` | enum | derived | `internal` (both endpoints same chunk), `boundary` (different chunks). Computed during chunking. |
| `fixtures` | array | ✓ when frozen | ≥1 happy-path + ≥1 error-case required before freezing. |
| `stub` | object | opt | `{ generated: bool, path?: string, language?: string }`. Populated by executor after freezing. |
| `provenance` | object | opt | Where this contract came from. Required when `contract_maturity` is `observed`. See provenance schema below. |
| `verification_strategy` | enum | ✓ | `type_check`, `schema_validation`, `test_assertion`, `human_review` |
| `blocking` | bool | ✓ | If true, consumers blocked until contract verified. Always true for boundary contracts in `enforced` mode. |

## Contract types

| Type | Signature field | What it specifies |
|---|---|---|
| `interface` | Full callable signature | Function/method: provider exposes callable, consumer invokes it |
| `schema` | Schema or type definition | Data shape: provider produces data in this shape, consumer reads it |
| `behavioral` | Not required | System-level guarantee not captured by types alone (e.g., idempotency) |

## Scope rules

| Condition | Scope |
|---|---|
| Provider and all consumers in same chunk | `internal` |
| Provider and ≥1 consumer in different chunks | `boundary` |

Internal: may remain `provisional` during chunk build. Must be resolved before `chunk_verification`.
Boundary: must be `frozen` before any consuming chunk begins building. This is the primary parallel execution gate.

## Maturity lifecycle

| From | Condition | To |
|---|---|---|
| `observed` | Fixtures pass (auto-promote) | `frozen` |
| `observed` | Human ratifies with rationale | `frozen` |
| `observed` | Observation contradicts implementation | `broken` |
| `provisional` | All fixtures pass + stub generated + both parties agree | `frozen` |
| `provisional` | Consistency check fails or spec error discovered | `broken` |
| `frozen` | Integration verification reveals gap | `broken` |
| `broken` | Contract renegotiated | `provisional` |

Frozen contracts are immutable. Any change requires explicit renegotiation → `broken` → renegotiate → `provisional` → re-freeze.

### Observed contracts

`observed` is for brownfield — contracts extracted from existing code. An observed contract describes what the code does, not what it should do. It carries mandatory provenance and cannot be silently promoted to `frozen`.

Promotion to `frozen` requires one of:
- **Fixtures pass.** The contract's fixtures run against the real implementation and all pass. This is the mechanical path — the contract is verified to match the code.
- **Human ratification.** A human asserts "this is what I want, not just what the code does." This is the intent path — the contract becomes prescriptive.

Both paths require a rationale (`promote-contract <id> <rationale>`). The rationale is recorded in `verification_history` and is not optional — it says *why* someone judged this contract ready to freeze, which is the information that matters when a frozen contract breaks six months later.

Fixtures without ratification freeze bugs that happen to have tests. Ratification without fixtures freezes intent that may be wrong. Neither alone is sufficient for critical boundaries; for non-critical boundaries either is acceptable.

Observed contracts participate in `parallel_ready` the same way provisional ones do: consumers can build against them (the existing code works), but observed status signals that the contract may change as understanding improves.

### Provenance schema

```json
{
  "source_file": "path/to/file.py",
  "source_commit": "abc123def456",
  "extracted_by": "agent|human",
  "extracted_at": "2026-08-31T12:00:00Z",
  "extraction_method": "static_analysis|runtime_observation|manual",
  "rationale": "optional — why this boundary was chosen for extraction"
}
```

Provenance is optional on `provisional` and `frozen` contracts (greenfield contracts have no prior source). It is required on `observed` contracts — an observation without provenance is a claim about the codebase with no way to recheck it.

## Fixture schema

```json
{
  "label": "string (descriptive name)",
  "input": { "...": "input data matching contract input type" },
  "expected_output": { "...": "for happy-path fixtures" },
  "expected_error": { "...": "for error-case fixtures" },
  "notes": "optional context",
  "auto_generated": false
}
```

Requirements before freezing:
- ≥1 fixture with `expected_output` (happy-path)
- ≥1 fixture with `expected_error` (error-case)
- All fixtures must be executable (not pseudocode)
- When a contract's signature
## Freeze gate consistency checks

Beyond fixture presence, `freeze-contract` enforces structural consistency.
Each check emits a blocking error naming the contract and the specific defect.
Use `freeze-contract --explain <id>` for remediation guidance.

| Check | What it catches | Source |
|---|---|---|
| **Self-contradiction** | Invariant claims parity with another contract ("identical to X minus Y") but signature is missing fields the invariant implies | Dragonglass S2 |
| **ABC/signature agreement** | `isinstance` attestation to a category ABC, but the signature omits abstract methods that ABC declares | Dragonglass S3 |
| **Invariant field backing** | Invariant references a backtick-quoted field that no signature along the data path carries | Dragonglass S1 |
| **Fixture well-formedness** | A fixture has neither `expected_output` nor `expected_error` | Structural |
| **Filter subset** | Contract emits fields/attributes that a downstream contract's declared filter allowlist does not accept | Dragonglass dg-005 |

The ABC check requires a category registry (EBC seed or `metadata.registry_path`). Without one it degrades to a skip, never a hard failure.

These checks run in `spec-only` mode — no project code is executed. They catch the class of defect that survives a fixture gate and becomes immutable after freezing.

## Stub generation

After a contract is frozen, the executor generates a runnable stub:
- Accepts contracted input type
- Returns hardcoded happy-path fixture value
- Raises contracted error for error-case inputs
- Placed at configured stub path

Stubs let parallel builders test against dependencies without waiting for real implementations.

## Contract hashing (for replay)

Semantic hash over the contract's load-bearing fields. Used for:
- Replay cache lookup: if an identical contract was previously fulfilled and verified, skip implementation
- Cross-project sharing: fulfilled contracts indexed by hash in contract archive
- Near-match detection: similar hashes suggest warm-start opportunities

### Hash recipe (version 1)

The CLI (`taskdagger-cli.py contract-hash`) is the reference implementation. Two independent implementations must agree given the same contract JSON.

**Canonical form.** Extract four fields, normalising each:

- **signature**: from `definition.signature`, falling back to top-level `type_signature`, then `{}`. Structure preserved as-is.
- **invariants**: from `definition.invariants`, falling back to top-level `invariants`, then `[]`. Each element cast to string, then the list sorted lexicographically.
- **side_effects**: from `definition.side_effects`, falling back to top-level `side_effects`, then `[]`. Each element cast to string, then the list sorted lexicographically.
- **fixtures**: from top-level `fixtures`, then `[]`. Per fixture, keep only `input`, `expected_output`, `expected_error` (drop `label`, `notes`, `auto_generated`). Omit keys whose value is `None`/absent. Sort the fixture list by `json.dumps(fixture, sort_keys=True)`.

The canonical object is `{"signature": ..., "invariants": [...], "side_effects": [...], "fixtures": [...]}`.

**Serialisation.** `json.dumps(canonical, sort_keys=True, ensure_ascii=True)` — canonical JSON with sorted keys, ASCII escaping, default separators (`, ` and `: `).

**Hash.** SHA-256 of the UTF-8-encoded serialisation. Truncated to the first 16 hex characters (64 bits) for directory names and display. The full 64-character hex digest is stored in archive entry metadata (`full_hash`).

**Signature-only hash.** Same serialisation and hashing applied to `{"signature": <canonical_signature>}` alone. Used for near-miss detection: same API shape, different invariants or fixtures implies a warm-start candidate.

**Recipe versioning.** Archive entries record `hash_recipe_version: 1`. If the derivation ever changes, contracts hashed under older recipes remain resolvable by version. A recipe change that only corrects non-conformance to this spec does not increment the version.

**Verification.** `taskdagger-cli.py verify-hashes` recomputes every contract's hash and compares against any `contract_hash` field stored in the DAG. Reports per-contract agreement and exits non-zero on mismatches.

### Truncation note

16 hex characters = 64 bits. Collision probability reaches 1% at ~6.1 x 10^8 contracts (birthday bound). Adequate for any foreseeable archive. The full hash is always available in archive metadata.

## Conventions vs contracts

Conventions (`metadata.conventions`) and contracts both constrain a task, and they can disagree. The order:

1. **A frozen contract is the strongest constraint.** It is immutable and other parties have already built against it.
2. **A convention governs where no contract speaks.** Conventions exist to settle what contracts leave implicit — units, orientations, index bases, error envelopes. That is their scope, not a competing authority.
3. **Organisational metadata is not a constraint at all.** A label that classifies a task does not impose an interface on it. Only a contract does.

Where a convention and a frozen contract genuinely conflict, one of them is defective. That is an escalation, not an interpretation — a worker who resolves it silently produces something internally consistent and wrong, and the disagreement stays invisible until integration.

Worked example, stated generally because the point is about labels rather than any one taxonomy: a task carries a category label, and its frozen contract omits a field that category normally exposes. The label loses. It files the task; it does not specify it.

## Contracts vs. artifacts vs. edges

- **Artifacts**: files/data objects produced and consumed. Answer "what file?"
- **Edges**: directed dependency links. Answer "who depends on whom?"
- **Contracts**: shape, behavior, invariants at a boundary. Answer "what does A promise B?"

Every edge carries exactly one contract. A contract is not the edge — it's the specification on the edge.

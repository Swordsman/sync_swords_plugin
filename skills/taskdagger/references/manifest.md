# Resource Manifest Reference

The manifest configures runtime behavior. The DAG describes *what* to build; the manifest describes *how* to execute. Same DAG, different manifests = different execution behavior.

Override hierarchy: task/chunk metadata (hints) < manifest < CLI overrides.

## Schema

```json
{
  "manifest_version": "1.0",
  "environment": "development|production|ci",
  "created_at": "ISO 8601",
  "contract_enforcement": {
    "default_mode": "spec-only|validated|enforced",
    "chunk_gate": "contract|stub|verified",
    "per_contract_overrides": { "contract-id": { "mode": "enforced" } },
    "contract_drift_policy": "notify|halt|continue"
  },
  "chunk_concurrency": {
    "max_chunks_building": 4,
    "max_tasks_per_chunk": 8,
    "global_max_tasks_in_progress": 16
  },
  "stub_generation": {
    "enabled": true,
    "language_targets": ["typescript", "python"],
    "output_base_path": ".taskdagger/stubs",
    "stub_style": "typed_placeholder",
    "include_fixture_data": true,
    "overwrite_policy": "if_contract_changed|always|never",
    "per_contract_overrides": {}
  },
  "fixture_runner": {
    "test_runner": "pytest|vitest|jest",
    "runner_args": [],
    "timeout_seconds": 120,
    "failure_behavior": "fail_chunk|warn_only|retry",
    "max_retries": 2,
    "working_directory": ".",
    "report_format": "json",
    "report_output_path": ".taskdagger/fixture-reports",
    "environment_vars": {},
    "per_contract_overrides": {}
  },
  "rate_limits": {
    "global": { "requests_per_minute": 60, "tokens_per_minute": 100000 },
    "per_service": { "service-id": { "requests_per_minute": 10 } }
  },
  "human_gates": [
    {
      "task_pattern": "(deploy).*",
      "gate_type": "approval_required",
      "approvers": ["user"],
      "timeout_minutes": 1440
    }
  ],
  "secrets": {
    "resolution": "env_var|file|vault",
    "env_prefix": "TASKDAGGER_SECRET_",
    "vault_path": "secret/taskdagger/"
  },
  "external_services": {
    "service-id": {
      "name": "string",
      "health_check": "url",
      "timeout_seconds": 30,
      "mock_available": true
    }
  },
  "wash": {
    "design": true,
    "blueprint": true,
    "executor": true,
    "worker": false,
    "machine_path": ".claude/skills/taskdagger/references/washing_machine.py",
    "record_path": ".taskdagger/wash",
    "closure_confidence": 2,
    "skepticism_after_passes": 20,
    "emphasis_after_passes": 10,
    "escalate_after_stalled_passes": 8,
    "token_budget": {
      "design": 0,
      "blueprint": 0,
      "executor": 0,
      "worker": 50000
    },
    "per_task_overrides": { "task-id": true }
  },
  "design": {
    "sources": "ask|greenfield|packages-only|any",
    "recursion_depth_limit": 3,
    "decomposition_mode": "inline|delegated"
  },
  "drone": {
    "default_provider": "string — provider key, e.g. deepseek",
    "providers": {
      "provider-key": {
        "endpoint": "string — API endpoint URL",
        "model": "string — model identifier",
        "timeout_seconds": 120,
        "max_rounds_per_task": 5
      }
    },
    "eligible_tiers": ["* — or specific tier ids"],
    "per_task_overrides": { "task-id": { "provider": "provider-key", "max_rounds": 3 } }
  },
  "execution_constraints": {
    "max_retries_per_task": 3,
    "checkpoint_interval_tasks": 5,
    "max_total_failures": 10
  },
  "notifications": {
    "on_task_failure": { "channel": "slack|email|log", "target": "string" },
    "on_chunk_verified": { "channel": "log" },
    "on_contract_broken": { "channel": "slack|email|log", "target": "string" }
  }
}
```

## Environment profiles

| Setting | development | production | ci |
|---|---|---|---|
| `contract_enforcement.default_mode` | `validated` | `enforced` | `spec-only` |
| `contract_enforcement.chunk_gate` | `contract` | `stub` | `contract` |
| `contract_drift_policy` | `notify` | `halt` | `continue` |
| `chunk_concurrency.max_chunks_building` | 4 | 2 | 8 |
| `stub_generation.enabled` | true | true | false |
| `fixture_runner.failure_behavior` | `fail_chunk` | `fail_chunk` | `warn_only` |
| Human chunk verification gates | absent | present | absent |
| `wash.design` / `wash.blueprint` | true | true | true |
| `wash.executor` | true | true | false |
| `wash.worker` | false | false | false |

## Validation

Before execution, validate manifest against DAG:
- Stub generation enabled if any chunk has boundary contracts
- Fixture runner configured if enforcement is not `spec-only`
- All external service dependencies have service definitions
- Human gates cover all tasks requiring human input
- Drift policy set when frozen contracts exist
- `chunk_gate: stub` requires `stub_generation.enabled: true` — stubs cannot gate what is not generated
- `wash.machine_path` resolves to a real file when multi-pass mode is used — workers may be elsewhere and cannot resolve skill-relative paths
 — workers may be elsewhere and cannot resolve skill-relative paths
- `wash.blueprint` enabled when the DAG contains contracts that will be frozen (disabling it is a deliberate choice to freeze unswept interfaces)

## Chunk gate

`contract_enforcement.chunk_gate` controls what a producing chunk must provide before a consuming chunk may start Phase 2. Default: `contract`.

| Value | Consuming chunk starts when | Verification can claim |
|---|---|---|
| `contract` | Producing chunk's boundary contracts are frozen | Boundary conformance against contract specification. Cannot assert the consumer was built against running producer code. |
| `stub` | Producing chunk's frozen boundary stubs are published | Boundary conformance against generated stubs. Consumer tested against stub behavior. |
| `verified` | Producing chunk reaches `verified` state | Full boundary conformance against real implementations. Strongest guarantee; serialises chunks. |

`contract` is the default because it unlocks the most parallelism and matches the common case — the Dragonglass PoC ran both pools concurrently on frozen contracts alone. `stub` is the natural choice when `enforced` mode is generating stubs anyway. `verified` is for builds where no consumer should start until the producer is proven correct.

The completion report records which gate each consuming chunk entered on. See `executor.md` → Chunk gate.

## Wash configuration

`wash.<phase>` turns the phase's wash gate on or off. Defaults are on everywhere
except workers.

| Phase | Default | Reasoning |
|---|---|---|
| `design` | **on** | The spec is irreplaceable and nothing mechanical checks it. |
| `blueprint` | **on** | Frozen contracts are immutable; a miss here cannot be cheaply undone. |
| `executor` | **on** | Chunk verification and integration are the executor's real artifact boundaries. |
| `worker` | **off** | Fixtures plus unit tests already gate the worker objectively, and a wash per task multiplies your most-repeated cost. Turn it on where semantic alignment matters more than throughput — conventions-heavy tasks, unfamiliar domains, workers whose output has burned you before. |

`per_task_overrides` enables or disables the worker wash for specific tasks
without changing the global default, which is the usual way to use it: off
broadly, on for the handful of tasks where a silent semantic mismatch would be
expensive.

### Multi-pass tuning (cold storage)

The following settings apply only when using multi-pass mode
(`washing_machine.py --multi-pass`). They have no effect on the default one-shot
wash.

`skepticism_after_passes` (20) is the point at which slot A admissions get a
higher bar, because the false-positive rate climbs on long cycles.

`escalate_after_stalled_passes` (8) watches for a sweep that stops reaching new
ground.

`closure_confidence` (2) is how much confirmation the machine requires before it
closes a cycle. What it actually measures is deliberately not documented here —
this file is agent-loadable. Operators: see `wash_operator_notes.md`.

`emphasis_after_passes` (10) re-asserts the load-bearing rules in heavy emphasis
every pass from then on.


`token_budget` is an optional per-phase token cap, primarily relevant for
multi-pass mode. Defaults are 0 (unlimited) for design, blueprint and executor,
and 50 000 for workers.


### Who applies these (multi-pass only)

In multi-pass mode, the executor passes `wash.*` values as CLI flags to
`washing_machine.py`. The machine is a standalone tool with no taskdagger
dependency, so a worker on another host can run it with nothing but a Python
interpreter. In default (one-shot) mode, this section does not apply — the wash
is just the prompt in `wash.md`.


## Design configuration

`design.sources` sets the default sourcing policy for the design phase. It
applies when the user is unavailable or has said they do not care which sources
the AI draws from. The AI asks during the sourcing conversation at the start of
design; this key is the fallback, not a substitute for the conversation.

| Value | Meaning |
|---|---|
| `ask` | Always ask the user (default). Block if unavailable. |
| `greenfield` | No external dependencies unless the user overrides. |
| `packages-only` | Published packages from established registries only. |
| `any` | Packages, public repositories, local projects — whatever fits. |

`design.recursion_depth_limit` (default 3) caps how many levels of recursive
decomposition the design phase will pursue before flagging for human review.
Hitting the limit is diagnostic, not a hard stop — a contract needing four
levels is probably misspecified at the parent level. The operator can also halt
recursion at any point during the design conversation.

`design.decomposition_mode` controls whether recursive decomposition is handled
inline (the design thread does each contract sequentially) or delegated
(sub-agents handle contracts independently, with consistency verification). The
choice depends on contract count and available concurrency. Default: `inline`.

## Drone configuration

`drone.default_provider` names the provider key used when a task is dispatched for drone execution (see `drone_execution.md`). Each provider entry specifies an endpoint, model, per-call timeout, and a retry bound.

`eligible_tiers` controls which tiers may use drone pilots. `["*"]` means all. `per_task_overrides` selects a different provider or retry bound for specific tasks.

The provider configuration is deliberately not DeepSeek-specific — any API-accessible model that accepts a chat-completion-shaped request works. The `deepseek-api` skill documents the specific vendor surface; this manifest entry is the interface the executor reads.

# Executor Implementation Guide

This file is for building executor software. If you're an AI *playing* executor (following the protocol), use `executor.md` instead. Only read this when someone is writing code for an executor tool.

## Core data structures

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import json, os, subprocess

class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    WAITING_HUMAN = "waiting_human"
    PARTIAL = "partial"

class ContractMaturity(Enum):
    PROVISIONAL = "provisional"
    FROZEN = "frozen"
    BROKEN = "broken"

class ChunkStatus(Enum):
    PENDING = "pending"
    BUILDING = "building"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"

class ReadinessMode(Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"
    HYBRID = "hybrid"
```

## Readiness computation

```python
def is_parallel_ready(task_id: str, dag: dict, state: dict) -> bool:
    """All incoming edge contracts are frozen."""
    incoming = [e for e in dag["edges"] if e["to"] == task_id]
    return all(
        state["contracts"][e["contract_id"]]["maturity"] == "frozen"
        for e in incoming
    )

def is_sequential_ready(task_id: str, dag: dict, state: dict) -> bool:
    """All upstream tasks completed."""
    task = next(t for t in dag["tasks"] if t["id"] == task_id)
    return all(
        state["tasks"][dep]["status"] == "completed"
        for dep in task["dependencies"]
    )

def is_ready(task_id: str, dag: dict, state: dict) -> bool:
    task = next(t for t in dag["tasks"] if t["id"] == task_id)
    mode = task.get("metadata", {}).get("readiness_mode", "parallel")
    if mode == "parallel":
        return is_parallel_ready(task_id, dag, state)
    elif mode == "sequential":
        return is_sequential_ready(task_id, dag, state)
    elif mode == "hybrid":
        return is_parallel_ready(task_id, dag, state) and is_sequential_ready(task_id, dag, state)
```

## CLI integration

```python
def cli(dag_file: str, *args) -> str:
    result = subprocess.run(
        ["python", "taskdagger-cli.py", "--dag", dag_file, *args],
        capture_output=True, text=True
    )
    return result.stdout

def get_worker_context(dag_file: str, task_id: str) -> dict:
    """Surgical extraction — only what the worker needs."""
    return {
        "task": cli(dag_file, "task", task_id),
        "contracts": cli(dag_file, "task-contracts", task_id),
        "stubs": cli(dag_file, "task-stubs", task_id),
    }
```

## Work order generation

```python
import hashlib

def contract_hash(contract: dict) -> str:
    """Deterministic hash for replay cache lookup."""
    content = json.dumps({
        "signature": contract.get("type_signature", {}),
        "invariants": sorted(contract.get("invariants", [])),
        "side_effects": sorted(contract.get("side_effects", [])),
        "fixtures": contract.get("fixtures", []),
    }, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def check_contract_archive(hash_val: str, archive_dir: str) -> Optional[str]:
    """Check if a fulfilled contract exists for this hash."""
    path = os.path.join(archive_dir, hash_val)
    if os.path.isdir(path):
        return path
    return None
```

## Stub generation

```python
def generate_stub(contract: dict, manifest: dict) -> list[str]:
    """Generate stubs for a frozen boundary contract."""
    cfg = manifest.get("stub_generation", {})
    if not cfg.get("enabled", True):
        return []
    contract_id = contract["id"]
    overrides = cfg.get("per_contract_overrides", {}).get(contract_id, {})
    targets = overrides.get("language_targets", cfg.get("language_targets", []))
    base_path = cfg.get("output_base_path", ".taskdagger/stubs")

    generated = []
    for lang in targets:
        output_path = os.path.join(base_path, contract_id, f"stub.{lang_ext(lang)}")
        stub_code = build_stub_code(contract, lang)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(stub_code)
        generated.append(output_path)
    return generated
```

## Fixture runner

```python
def run_fixtures(contract: dict, chunk_id: str, manifest: dict) -> bool:
    """Run a contract's fixtures against real implementation."""
    cfg = manifest.get("fixture_runner", {})
    runner = cfg.get("test_runner", "pytest")
    timeout = cfg.get("timeout_seconds", 120)
    fixture_path = resolve_fixture_path(contract)
    
    try:
        result = subprocess.run(
            [runner, fixture_path],
            timeout=timeout, capture_output=True, text=True
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
```

## File layout

```
project/
├── .taskdagger/
│   ├── dag.json
│   ├── state.json
│   ├── stubs/
│   ├── work-orders/
│   ├── contract-archive/
│   ├── fixture-reports/
│   └── manifests/
│       ├── development.json
│       ├── production.json
│       └── ci.json
```

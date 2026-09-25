#!/usr/bin/env python3
"""
Contract-Based Task DAG CLI - Surgical access to taskdagger DAGs for AI agents.
Superset of tdag-cli.py: all tdag commands plus contract and chunk commands.

This is REUSABLE infrastructure - not tied to any specific project.
Point it at any taskdagger JSON file.

Usage:
    python taskdagger-cli.py --dag /path/to/dag.json <command> [args]

Or set TASKDAGGER_FILE environment variable:
    export TASKDAGGER_FILE=/path/to/dag.json
    python taskdagger-cli.py <command> [args]
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================
# CONFIGURATION
# ============================================================

def get_dag_path(args_dag: Optional[str]) -> Path:
    """Resolve DAG file path from args or environment."""
    if args_dag:
        return Path(args_dag)

    env_path = os.environ.get("TASKDAGGER_FILE")
    if env_path:
        return Path(env_path)

    # Check current directory for common names
    cwd = Path.cwd()
    for name in ["task-dag.json", "tasks.json", "dag.json"]:
        if (cwd / name).exists():
            return cwd / name

    sys.exit("Error: No DAG file specified. Use --dag or set TASKDAGGER_FILE environment variable.")


def get_state_path(dag_path: Path) -> Path:
    """Derive state file path from DAG path."""
    return dag_path.with_name(dag_path.stem + "-progress.json")


# ============================================================
# DATA LOADING
# ============================================================

def load_dag(dag_path: Path) -> dict:
    """Load the task DAG (immutable source of truth)."""
    if not dag_path.exists():
        sys.exit(f"Error: DAG file not found: {dag_path}")
    return json.loads(dag_path.read_text(encoding='utf-8'))


def load_state(state_path: Path) -> Optional[dict]:
    """Load progress state if it exists."""
    if not state_path.exists():
        return None
    return json.loads(state_path.read_text(encoding='utf-8'))


def save_state(state: dict, state_path: Path) -> None:
    """Atomically save progress state."""
    state["updated_at"] = now_iso()
    tmp = state_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    tmp.replace(state_path)


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def is_taskdagger_state(state: dict) -> bool:
    """True if state has taskdagger contract/chunk layers."""
    return "contracts" in state and "chunks" in state


def require_taskdagger_state(state: Optional[dict]) -> None:
    """Exit with helpful message if state is missing or is tdag-format only."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")
    if not is_taskdagger_state(state):
        sys.exit(
            "Error: Contract/chunk state is not initialized.\n"
            "This state file appears to be tdag-format only.\n"
            "Run 'init --mode parallel' (or --mode hybrid) with --force to reinitialize with taskdagger layers."
        )


# ============================================================
# INDEX BUILDERS (for fast lookups)
# ============================================================

def build_task_index(dag: dict) -> dict:
    """task_id -> task object"""
    return {t["id"]: t for t in dag["tasks"]}


def build_dependents_index(dag: dict) -> dict:
    """task_id -> list of task_ids that depend on it"""
    index = {t["id"]: [] for t in dag["tasks"]}
    for task in dag["tasks"]:
        for dep in task.get("dependencies", []):
            if dep in index:
                index[dep].append(task["id"])
    return index


def build_contract_index(dag: dict) -> dict:
    """contract_id -> contract object from DAG definition"""
    return {c["id"]: c for c in dag.get("contracts", [])}


def build_chunk_index(dag: dict) -> dict:
    """chunk_id -> chunk object from DAG definition"""
    return {c["id"]: c for c in dag.get("chunks", [])}


# ============================================================
# QUERY COMMANDS \u2014 inherited from tdag
# ============================================================

def cmd_status(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Show overall DAG status."""
    meta = dag.get("metadata", {})
    epic = dag.get("epic", {})
    total = meta.get("total_tasks", len(dag["tasks"]))
    hours = meta.get("total_estimated_hours", "?")
    crit = meta.get("critical_path_hours", "?")

    print(f"DAG: {epic.get('id', 'unknown')} - {epic.get('title', 'Untitled')}")

    if state is None:
        print(f"Tasks: {total} | Est: {hours}h | CritPath: {crit}h")
        print("Status: NOT INITIALIZED (run 'init' first)")
        return

    # Task summary
    metrics = state["metrics"]
    # Support both tdag metrics shape and taskdagger metrics shape
    if "tasks" in metrics and isinstance(metrics["tasks"], dict):
        task_metrics = metrics["tasks"]
        by_status = task_metrics.get("by_status", {})
        completed = by_status.get("completed", 0)
        pct = task_metrics.get("completion_percentage", 0)
    else:
        by_status = metrics.get("by_status", {})
        completed = by_status.get("completed", 0)
        pct = metrics.get("completion_percentage", 0)

    print(f"Tasks: {total} | Completed: {completed} ({pct:.1f}%)")
    print(f"Ready: {by_status.get('ready', 0)} | InProgress: {by_status.get('in_progress', 0)} | "
          f"Blocked: {by_status.get('blocked', 0)} | Failed: {by_status.get('failed', 0)}")

    # Contract + chunk summary if available
    if is_taskdagger_state(state):
        cm = metrics.get("contracts", {})
        total_c = cm.get("total", len(state["contracts"]))
        by_mat = cm.get("by_maturity", {})
        bf_pct = cm.get("boundary_frozen_percentage", 0)
        print(f"Contracts: {total_c} | Frozen: {by_mat.get('frozen', 0)} | "
              f"Provisional: {by_mat.get('provisional', 0)} | Broken: {by_mat.get('broken', 0)} | "
              f"BoundaryFrozen: {bf_pct:.1f}%")

        chm = metrics.get("chunks", {})
        total_ch = chm.get("total", len(state["chunks"]))
        by_cs = chm.get("by_status", {})
        v_pct = chm.get("verified_percentage", 0)
        print(f"Chunks: {total_ch} | Verified: {by_cs.get('verified', 0)} | "
              f"Building: {by_cs.get('building', 0)} | Pending: {by_cs.get('pending', 0)} | "
              f"Failed: {by_cs.get('failed', 0)} | VerifiedPct: {v_pct:.1f}%")

    if verbose:
        print(f"\nCritical Path: {crit}h estimated")
        cp_status = get_critical_path_status(state, dag)
        print(f"  Progress: {cp_status['completed']}/{cp_status['total_tasks']} tasks")
        if cp_status['current_task']:
            print(f"  Current: {cp_status['current_task']}")


def cmd_queues(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List queues with brief summaries."""
    for q in dag.get("queues", []):
        qid = q["id"]
        name = q["name"]

        task_count = sum(1 for t in dag["tasks"] if t.get("queue_id") == qid)

        if state:
            completed = sum(1 for t in dag["tasks"]
                            if t.get("queue_id") == qid
                            and state["tasks"].get(t["id"], {}).get("status") == "completed")
            print(f"{qid}: {completed}/{task_count} - {name}")
        else:
            print(f"{qid}: {task_count} tasks - {name}")

        if verbose:
            print(f"  Purpose: {q.get('purpose', 'N/A')}")


def cmd_tasks(dag: dict, state: Optional[dict], queue: Optional[str], verbose: bool) -> None:
    """List tasks, optionally filtered by queue."""
    tasks = dag["tasks"]
    if queue:
        tasks = [t for t in tasks if t.get("queue_id") == queue]

    if not tasks:
        print(f"No tasks found" + (f" in queue '{queue}'" if queue else ""))
        return

    for t in tasks:
        tid = t["id"]
        status = "?"
        if state:
            status = state["tasks"].get(tid, {}).get("status", "?")

        indicator = {
            "pending": "\u25cb", "ready": "\u25ce", "in_progress": "\u25ba",
            "completed": "\u2713", "failed": "\u2717", "blocked": "\u2298",
            "skipped": "\u229d", "waiting_human": "\u23f8", "partial": "\u25d1", "?": "?"
        }.get(status, "?")

        print(f"{indicator} {tid}")
        if verbose:
            print(f"    {t['name']}")
            deps = t.get("dependencies", [])
            if deps:
                print(f"    deps: {', '.join(deps)}")


def cmd_task(dag: dict, state: Optional[dict], task_id: str, verbose: bool) -> None:
    """Get full details for a specific task."""
    task_index = build_task_index(dag)

    if task_id not in task_index:
        sys.exit(f"Error: Task not found: {task_id}")

    task = task_index[task_id]

    print(f"ID: {task['id']}")
    print(f"Name: {task['name']}")
    print(f"Queue: {task.get('queue_id', 'N/A')}")
    print(f"Subsystem: {task.get('subsystem', 'N/A')}")

    if state:
        ts = state["tasks"].get(task_id, {})
        print(f"Status: {ts.get('status', 'unknown')}")
        mode = ts.get("readiness_mode", task.get("readiness_mode", "sequential"))
        print(f"ReadinessMode: {mode}")
        if is_taskdagger_state(state):
            print(f"SequentialReady: {ts.get('sequential_ready', False)}")
            print(f"ParallelReady: {ts.get('parallel_ready', False)}")
            chunk_id = ts.get("chunk_id") or task.get("chunk_id")
            if chunk_id:
                print(f"Chunk: {chunk_id}")
        if ts.get("output_summary"):
            print(f"Summary: {ts['output_summary']}")
        if ts.get("error"):
            print(f"Error: {ts['error']}")
        if ts.get("blocked_by"):
            print(f"BlockedBy: {ts['blocked_by']} ({ts.get('blocked_reason', 'unknown reason')})")

    print(f"\nDescription:\n  {task.get('description', 'N/A')}")

    deps = task.get("dependencies", [])
    print(f"\nDependencies: {len(deps)}")
    for d in deps:
        if state:
            ds = state["tasks"].get(d, {}).get("status", "?")
            print(f"  [{ds}] {d}")
        else:
            print(f"  {d}")

    # Show task's contract_ids if any
    contract_ids = task.get("contract_ids", [])
    if contract_ids:
        print(f"\nContracts ({len(contract_ids)}):")
        for cid in contract_ids:
            if state and is_taskdagger_state(state):
                cs = state["contracts"].get(cid, {})
                mat = cs.get("maturity", "?")
                print(f"  [{mat}] {cid}")
            else:
                print(f"  {cid}")

    if verbose:
        print(f"\nInputs: {task.get('inputs', [])}")
        print(f"Outputs: {task.get('outputs', [])}")
        print(f"\nInput Artifacts: {task.get('input_artifacts', [])}")
        print(f"Output Artifacts: {task.get('output_artifacts', [])}")
        print(f"\nAcceptance Criteria:")
        for c in task.get("acceptance_criteria", []):
            print(f"  \u2022 {c}")

        effort = task.get("estimated_effort", {})
        print(f"\nEffort: {effort.get('estimated_hours', '?')}h ({effort.get('relative_size', '?')})")


def cmd_ready(dag: dict, state: Optional[dict], verbose: bool,
              tier: Optional[str] = None) -> None:
    """Show tasks ready for execution (deps-based readiness)."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    task_index = build_task_index(dag)
    ready = []

    for task in dag["tasks"]:
        tid = task["id"]
        ts = state["tasks"].get(tid, {})

        if ts.get("status") == "ready":
            ready.append(tid)
            continue

        if ts.get("status") == "pending":
            deps = task.get("dependencies", [])
            deps_complete = all(
                state["tasks"].get(d, {}).get("status") in ("completed", "skipped")
                for d in deps
            )
            if deps_complete:
                ready.append(tid)

    # Filter by tier if requested
    if tier:
        ready = [tid for tid in ready
                 if task_index[tid].get("tier", "").lower() == tier.lower()]

    if not ready:
        msg = "No tasks ready"
        if tier:
            msg += f" in tier '{tier}'"
        msg += " (all pending tasks have unmet dependencies)"
        print(msg)
        return

    print(f"Ready tasks ({len(ready)}):")
    for tid in ready:
        task = task_index[tid]
        task_tier = task.get("tier", "")
        tier_tag = f" [{task_tier}]" if task_tier else ""
        if verbose:
            print(f"  {tid}{tier_tag}")
            print(f"    {task['name']}")
        else:
            print(f"  {tid}{tier_tag}")


def cmd_blocked(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Show blocked tasks and what's blocking them."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    blocked = []
    for tid, ts in state["tasks"].items():
        if ts.get("status") == "blocked":
            blocked.append((tid, ts.get("blocked_by"), ts.get("blocked_reason")))

    if not blocked:
        print("No blocked tasks")
        return

    print(f"Blocked tasks ({len(blocked)}):")
    for tid, blocker, reason in blocked:
        print(f"  {tid}")
        print(f"    blocked_by: {blocker}" + (f" ({reason})" if reason else ""))


def cmd_crit_path(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Show critical path status."""
    meta = dag.get("metadata", {})
    cp_tasks = meta.get("critical_path_task_ids", [])

    if not cp_tasks:
        print("No critical path defined in DAG metadata")
        return

    print(f"Critical Path ({len(cp_tasks)} tasks, {meta.get('critical_path_hours', '?')}h):")

    for tid in cp_tasks:
        status = "?"
        if state:
            status = state["tasks"].get(tid, {}).get("status", "?")

        indicator = {
            "completed": "\u2713", "in_progress": "\u25ba", "ready": "\u25ce",
            "pending": "\u25cb", "failed": "\u2717", "blocked": "\u2298"
        }.get(status, "?")

        print(f"  {indicator} {tid}")


def cmd_deps(dag: dict, state: Optional[dict], task_id: str, verbose: bool) -> None:
    """Show dependencies for a task (what it needs)."""
    task_index = build_task_index(dag)

    if task_id not in task_index:
        sys.exit(f"Error: Task not found: {task_id}")

    task = task_index[task_id]
    deps = task.get("dependencies", [])

    if not deps:
        print(f"{task_id} has no dependencies (root task)")
        return

    print(f"Dependencies for {task_id} ({len(deps)}):")
    for d in deps:
        status = "?"
        if state:
            status = state["tasks"].get(d, {}).get("status", "?")
        print(f"  [{status}] {d}")


def cmd_dependents(dag: dict, state: Optional[dict], task_id: str, verbose: bool) -> None:
    """Show what depends on a task (downstream)."""
    task_index = build_task_index(dag)

    if task_id not in task_index:
        sys.exit(f"Error: Task not found: {task_id}")

    dependents_index = build_dependents_index(dag)
    dependents = dependents_index.get(task_id, [])

    if not dependents:
        print(f"{task_id} has no dependents (leaf task)")
        return

    print(f"Tasks depending on {task_id} ({len(dependents)}):")
    for d in dependents:
        status = "?"
        if state:
            status = state["tasks"].get(d, {}).get("status", "?")
        print(f"  [{status}] {d}")


def cmd_artifacts(dag: dict, state: Optional[dict], task_id: str, verbose: bool) -> None:
    """Show input/output artifacts for a task."""
    task_index = build_task_index(dag)

    if task_id not in task_index:
        sys.exit(f"Error: Task not found: {task_id}")

    task = task_index[task_id]

    inputs = task.get("input_artifacts", [])
    outputs = task.get("output_artifacts", [])

    print(f"Artifacts for {task_id}:")
    print(f"\nInputs ({len(inputs)}):")
    for a in inputs:
        print(f"  {a}")

    print(f"\nOutputs ({len(outputs)}):")
    for a in outputs:
        print(f"  {a}")


def cmd_libs(dag: dict, state: Optional[dict], task_id: Optional[str], verbose: bool) -> None:
    """Show recommended libraries for a task or all tasks."""
    hints = dag.get("metadata", {}).get("dependency_hints", {})

    if not hints:
        print("No dependency hints in this DAG")
        print("Run dependency analysis phase to add library recommendations")
        return

    libs = hints.get("recommended_libraries", [])
    task_map = hints.get("task_library_map", {})

    if task_id:
        task_libs = task_map.get(task_id, [])
        if not task_libs:
            print(f"No library recommendations for {task_id}")
            return

        print(f"Libraries for {task_id}:")
        for lib_name in task_libs:
            lib = next((l for l in libs if l["name"] == lib_name), None)
            if lib:
                print(f"  {lib['name']} ({lib.get('version', 'any')}): {lib.get('purpose', '')}")
                if verbose:
                    print(f"    Install: {lib.get('install', 'pip install ' + lib['name'])}")
            else:
                print(f"  {lib_name}")
    else:
        print(f"Recommended libraries ({len(libs)}):")
        for lib in libs:
            print(f"\n  {lib['name']} ({lib.get('version', 'any')})")
            print(f"    {lib.get('purpose', '')}")
            if verbose:
                print(f"    Install: {lib.get('install', '')}")
                queues = lib.get('applicable_queues', [])
                if queues:
                    print(f"    Queues: {', '.join(queues)}")

        if verbose and task_map:
            print(f"\nTask \u2192 Library mapping ({len(task_map)} tasks):")
            for tid, tlibs in task_map.items():
                print(f"  {tid}: {', '.join(tlibs)}")

        if hints.get("executor_instruction"):
            print(f"\nExecutor instruction: {hints['executor_instruction']}")


def cmd_hints(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Show all dependency hints as JSON (for programmatic use)."""
    hints = dag.get("metadata", {}).get("dependency_hints", {})

    if not hints:
        print("{}")
        return

    print(json.dumps(hints, indent=2))


def cmd_index(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List all task IDs (simple index without dependency info)."""
    tasks = dag.get("tasks", [])

    if verbose:
        by_queue = {}
        for t in tasks:
            q = t.get("queue_id", "unknown")
            if q not in by_queue:
                by_queue[q] = []
            by_queue[q].append(t["id"])

        for queue_id, task_ids in by_queue.items():
            print(f"\n[{queue_id}] ({len(task_ids)} tasks)")
            for tid in task_ids:
                print(f"  {tid}")
        print(f"\nTotal: {len(tasks)} tasks")
    else:
        for t in tasks:
            print(t["id"])


def cmd_structure(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Analyze DAG structure: chains, parallelism, branch points."""
    tasks = dag.get("tasks", [])
    task_index = build_task_index(dag)
    dependents_index = build_dependents_index(dag)

    in_degree = {}
    out_degree = {}

    for task in tasks:
        tid = task["id"]
        in_degree[tid] = len(task.get("dependencies", []))
        out_degree[tid] = len(dependents_index.get(tid, []))

    roots = []
    leaves = []
    chain_nodes = []
    branch_points = []
    merge_points = []

    for tid in task_index:
        ind = in_degree[tid]
        outd = out_degree[tid]

        if ind == 0:
            roots.append(tid)
        if outd == 0:
            leaves.append(tid)
        if ind == 1 and outd == 1:
            chain_nodes.append(tid)
        if outd > 1:
            branch_points.append(tid)
        if ind > 1:
            merge_points.append(tid)

    chains = find_chains(dag, task_index, dependents_index, in_degree, out_degree)
    max_parallel = calculate_max_parallelism(dag, task_index)
    longest_chain = max(chains, key=len) if chains else []
    levels = assign_levels(dag, task_index)
    level_counts = {}
    for tid, lvl in levels.items():
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    print(f"DAG Structure Analysis")
    print(f"=====================")
    print(f"Total tasks: {len(tasks)}")
    print(f"")
    print(f"Node classification:")
    print(f"  Entry points (roots):    {len(roots)}")
    print(f"  Terminal tasks (leaves): {len(leaves)}")
    print(f"  Chain nodes (in=1,out=1): {len(chain_nodes)}")
    print(f"  Branch points (out>1):   {len(branch_points)}")
    print(f"  Merge points (in>1):     {len(merge_points)}")
    print(f"")
    print(f"Parallelism:")
    print(f"  Max parallel width: {max_parallel}")
    print(f"  Longest chain: {len(longest_chain)} tasks")
    print(f"  Total chain segments: {len(chains)}")
    print(f"  Depth (levels): {len(level_counts)}")
    print(f"")
    print(f"Parallelization profile (tasks per level):")
    for lvl in sorted(level_counts.keys()):
        bar = '\u2588' * level_counts[lvl]
        print(f"  L{lvl:2d}: {bar} ({level_counts[lvl]})")

    if len(chain_nodes) > len(tasks) * 0.5:
        graph_type = "LINEAR - mostly sequential chains"
    elif max_parallel >= len(roots) * 2:
        graph_type = "WIDE - highly parallelizable"
    elif len(merge_points) > len(tasks) * 0.4:
        graph_type = "CONVERGENT - many tasks merge together"
    elif len(branch_points) > len(tasks) * 0.4:
        graph_type = "DIVERGENT - tasks fan out heavily"
    else:
        graph_type = "MIXED - combination of patterns"
    print(f"")
    print(f"Graph type: {graph_type}")

    if verbose:
        print(f"\n--- Entry Points ({len(roots)}) ---")
        for r in roots:
            print(f"  {r}")

        print(f"\n--- Branch Points ({len(branch_points)}) ---")
        for b in branch_points:
            deps = dependents_index.get(b, [])
            print(f"  {b} -> splits into {len(deps)} paths")

        print(f"\n--- Merge Points ({len(merge_points)}) ---")
        for m in merge_points:
            task = task_index[m]
            deps = task.get("dependencies", [])
            print(f"  {m} <- joins {len(deps)} paths")

        print(f"\n--- Linear Chains ({len(chains)}) ---")
        for i, chain in enumerate(chains, 1):
            print(f"  Chain {i} ({len(chain)} tasks): {chain[0]} ... {chain[-1]}")
            if len(chain) <= 5:
                print(f"    Full: {' -> '.join(chain)}")


# ============================================================
# QUERY COMMANDS \u2014 taskdagger new
# ============================================================

def cmd_contracts(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List all contracts with maturity status, scope, fixture count."""
    require_taskdagger_state(state)

    contracts_state = state["contracts"]
    dag_contracts = {c["id"]: c for c in dag.get("contracts", [])}

    if not contracts_state:
        print("No contracts in state")
        return

    print(f"Contracts ({len(contracts_state)}):")
    for cid, cs in sorted(contracts_state.items()):
        mat = cs.get("maturity", "?")
        is_boundary = cs.get("is_boundary_contract", False)
        scope = "boundary" if is_boundary else "internal"
        # fixture_count stored at init from DAG; fall back to dag lookup
        fixtures = cs.get("fixture_count", len(dag_contracts.get(cid, {}).get("fixtures", [])))
        stub = " stub" if cs.get("stub_generated") else ""

        mat_indicator = {"frozen": "\u2744", "provisional": "\u25cc", "broken": "\u2717", "observed": "\u25ce"}.get(mat, "?")
        print(f"  {mat_indicator} [{mat}] {cid}")
        if verbose:
            print(f"      scope={scope} fixtures={fixtures}{stub}")
            provider = cs.get("provider_task_id", "?")
            consumers = cs.get("consumer_task_ids", [])
            print(f"      provider={provider}")
            print(f"      consumers={', '.join(consumers) if consumers else 'none'}")
            if cs.get("broken_reason"):
                print(f"      broken_reason={cs['broken_reason']}")
        else:
            print(f"      scope={scope} fixtures={fixtures}{stub}")


def cmd_contract(dag: dict, state: Optional[dict], contract_id: str, verbose: bool) -> None:
    """Full contract details: parties, definition, fixtures, stub status, maturity history."""
    require_taskdagger_state(state)

    if contract_id not in state["contracts"]:
        sys.exit(f"Error: Contract not found: {contract_id}")

    cs = state["contracts"][contract_id]
    dag_c = {c["id"]: c for c in dag.get("contracts", [])}.get(contract_id, {})

    print(f"ID: {contract_id}")
    print(f"Maturity: {cs.get('maturity', '?')}")
    is_boundary = cs.get("is_boundary_contract", False)
    print(f"Scope: {'boundary' if is_boundary else 'internal'}")
    print(f"Provider: {cs.get('provider_task_id', 'N/A')}")
    consumers = cs.get("consumer_task_ids", [])
    print(f"Consumers ({len(consumers)}): {', '.join(consumers) if consumers else 'none'}")
    chunk_id = cs.get("chunk_id")
    if chunk_id:
        print(f"Chunk: {chunk_id}")

    print(f"\nStub Generated: {cs.get('stub_generated', False)}")
    if cs.get("stub_path"):
        print(f"Stub Path: {cs['stub_path']}")
    print(f"Fixtures Passed: {cs.get('fixtures_passed', False)}")

    if cs.get("frozen_at"):
        print(f"Frozen At: {cs['frozen_at']}")
    if cs.get("broken_at"):
        print(f"Broken At: {cs['broken_at']}")
        print(f"Broken Reason: {cs.get('broken_reason', 'N/A')}")

    # DAG-level definition info
    if dag_c.get("description"):
        print(f"\nDescription:\n  {dag_c['description']}")
    if dag_c.get("definition"):
        print(f"\nDefinition:\n  {json.dumps(dag_c['definition'], indent=4)}")

    history = cs.get("verification_history", [])
    print(f"\nVerification History ({len(history)}):")
    for entry in history:
        print(f"  [{entry.get('timestamp', '?')}] {entry.get('result', '?')} "
              f"via {entry.get('strategy', '?')}")
        if verbose:
            print(f"    {entry.get('details', '')}")


def cmd_parallel_ready(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List tasks that are parallel_ready (all required contracts frozen)."""
    require_taskdagger_state(state)

    task_index = build_task_index(dag)
    ready = []

    for task in dag["tasks"]:
        tid = task["id"]
        ts = state["tasks"].get(tid, {})

        if ts.get("status") not in ("pending", "ready"):
            continue

        # Compute parallel_ready: all edge contracts frozen
        contract_ids = task.get("contract_ids", [])
        if not contract_ids:
            # No contracts \u2014 fall back to sequential check
            deps = task.get("dependencies", [])
            par_ready = all(
                state["tasks"].get(d, {}).get("status") in ("completed", "skipped")
                for d in deps
            )
        else:
            par_ready = all(
                state["contracts"].get(cid, {}).get("maturity") == "frozen"
                for cid in contract_ids
            )

        if par_ready:
            ready.append(tid)

    if not ready:
        print("No tasks parallel_ready (no pending tasks with all contracts frozen)")
        return

    print(f"Parallel-ready tasks ({len(ready)}):")
    for tid in ready:
        task = task_index[tid]
        if verbose:
            print(f"  {tid}")
            print(f"    {task.get('name', '')}")
            contract_ids = task.get("contract_ids", [])
            if contract_ids:
                print(f"    contracts: {', '.join(contract_ids)}")
        else:
            print(f"  {tid}")


def cmd_chunks(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List all chunks with member count, quality_metric, boundary contract count, status."""
    require_taskdagger_state(state)

    chunks_state = state["chunks"]

    if not chunks_state:
        print("No chunks in state")
        return

    print(f"Chunks ({len(chunks_state)}):")
    for cid, cs in sorted(chunks_state.items()):
        status = cs.get("status", "?")
        members_total = cs.get("members_total", 0)
        members_done = cs.get("members_completed", 0)
        boundary_count = len(cs.get("boundary_contract_ids", []))
        outputs_exposed = cs.get("outputs_exposed", False)

        status_indicator = {
            "pending": "\u25cb", "building": "\u25ba", "verifying": "\u27f3",
            "verified": "\u2713", "failed": "\u2717"
        }.get(status, "?")

        exposed_tag = " [outputs_exposed]" if outputs_exposed else ""
        print(f"  {status_indicator} [{status}] {cid}{exposed_tag}")
        print(f"      members={members_done}/{members_total} "
              f"boundary_contracts={boundary_count}")
        if verbose:
            bc_ids = cs.get("boundary_contract_ids", [])
            if bc_ids:
                print(f"      boundary_contracts: {', '.join(bc_ids)}")
            members = cs.get("member_task_ids", [])
            if members:
                print(f"      members: {', '.join(members)}")
            if cs.get("error"):
                print(f"      error: {cs['error']}")


def cmd_chunk(dag: dict, state: Optional[dict], chunk_id: str, verbose: bool) -> None:
    """Chunk details: members, boundary contracts (with maturity), internal contracts, verification status."""
    require_taskdagger_state(state)

    if chunk_id not in state["chunks"]:
        sys.exit(f"Error: Chunk not found: {chunk_id}")

    cs = state["chunks"][chunk_id]
    dag_chunk = {c["id"]: c for c in dag.get("chunks", [])}.get(chunk_id, {})

    print(f"ID: {chunk_id}")
    print(f"Status: {cs.get('status', '?')}")
    print(f"Members: {cs.get('members_completed', 0)}/{cs.get('members_total', 0)} completed")
    print(f"OutputsExposed: {cs.get('outputs_exposed', False)}")

    if cs.get("started_at"):
        print(f"StartedAt: {cs['started_at']}")
    if cs.get("verified_at"):
        print(f"VerifiedAt: {cs['verified_at']}")
    if cs.get("failed_at"):
        print(f"FailedAt: {cs['failed_at']}")

    print(f"\nVerification:")
    print(f"  InternalCompositionPassed: {cs.get('internal_composition_passed', False)}")
    print(f"  BoundaryConformancePassed: {cs.get('boundary_conformance_passed', False)}")
    if cs.get("error"):
        print(f"  Error: {cs['error']}")

    boundary_ids = cs.get("boundary_contract_ids", [])
    print(f"\nBoundary Contracts ({len(boundary_ids)}):")
    for cid in boundary_ids:
        contract_state = state["contracts"].get(cid, {})
        mat = contract_state.get("maturity", "?")
        print(f"  [{mat}] {cid}")

    # Find internal contracts (chunk_id == this chunk's id in contract state)
    internal = [
        cid for cid, c_st in state["contracts"].items()
        if c_st.get("chunk_id") == chunk_id and cid not in boundary_ids
    ]
    print(f"\nInternal Contracts ({len(internal)}):")
    for cid in internal:
        contract_state = state["contracts"].get(cid, {})
        mat = contract_state.get("maturity", "?")
        print(f"  [{mat}] {cid}")

    member_ids = cs.get("member_task_ids", [])
    print(f"\nMember Tasks ({len(member_ids)}):")
    for tid in member_ids:
        ts = state["tasks"].get(tid, {})
        status = ts.get("status", "?")
        indicator = {
            "pending": "\u25cb", "ready": "\u25ce", "in_progress": "\u25ba",
            "completed": "\u2713", "failed": "\u2717", "blocked": "\u2298", "skipped": "\u229d"
        }.get(status, "?")
        print(f"  {indicator} {tid}")
        if verbose and ts.get("output_summary"):
            print(f"      {ts['output_summary']}")


def cmd_chunk_ready(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Chunks whose input boundary contracts are all frozen AND upstream chunks are verified."""
    require_taskdagger_state(state)

    chunks_state = state["chunks"]
    ready_chunks = []

    for cid, cs in chunks_state.items():
        if cs.get("status") != "pending":
            continue

        # All boundary contracts must be frozen
        boundary_ids = cs.get("boundary_contract_ids", [])
        all_frozen = all(
            state["contracts"].get(bid, {}).get("maturity") == "frozen"
            for bid in boundary_ids
        )

        if not all_frozen:
            continue

        # Check upstream chunks are verified
        # We determine upstream chunks by looking at provider tasks of boundary contracts
        # and finding which chunks those provider tasks belong to
        upstream_ok = True
        for bid in boundary_ids:
            c_st = state["contracts"].get(bid, {})
            provider_tid = c_st.get("provider_task_id")
            if provider_tid:
                provider_ts = state["tasks"].get(provider_tid, {})
                provider_chunk = provider_ts.get("chunk_id")
                if provider_chunk and provider_chunk != cid:
                    upstream_chunk_state = chunks_state.get(provider_chunk, {})
                    if upstream_chunk_state.get("status") != "verified":
                        upstream_ok = False
                        break

        if all_frozen and upstream_ok:
            ready_chunks.append(cid)

    if not ready_chunks:
        print("No chunks are chunk-ready (boundary contracts frozen + upstream verified)")
        return

    print(f"Chunk-ready chunks ({len(ready_chunks)}):")
    for cid in ready_chunks:
        cs = chunks_state[cid]
        print(f"  {cid}")
        if verbose:
            print(f"    members={cs.get('members_total', 0)} boundary_contracts={len(cs.get('boundary_contract_ids', []))}")


def cmd_contract_status(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Summary: N frozen / N provisional / N broken, boundary frozen %, parallelism unlocked %."""
    require_taskdagger_state(state)

    contracts = state["contracts"]
    total = len(contracts)

    if total == 0:
        print("No contracts in state")
        return

    frozen = sum(1 for c in contracts.values() if c.get("maturity") == "frozen")
    provisional = sum(1 for c in contracts.values() if c.get("maturity") == "provisional")
    observed = sum(1 for c in contracts.values() if c.get("maturity") == "observed")
    broken = sum(1 for c in contracts.values() if c.get("maturity") == "broken")

    boundary_total = sum(1 for c in contracts.values() if c.get("is_boundary_contract"))
    boundary_frozen = sum(1 for c in contracts.values()
                          if c.get("is_boundary_contract") and c.get("maturity") == "frozen")
    bf_pct = (boundary_frozen / boundary_total * 100) if boundary_total else 0

    # Parallelism unlocked: tasks that became parallel_ready because contracts froze
    tasks = state["tasks"]
    par_ready_count = sum(1 for ts in tasks.values() if ts.get("parallel_ready"))
    total_tasks = len(tasks)
    unlocked_pct = (par_ready_count / total_tasks * 100) if total_tasks else 0

    print(f"Contract Status Summary")
    print(f"=======================")
    print(f"Total:       {total}")
    print(f"Frozen:      {frozen}")
    print(f"Provisional: {provisional}")
    print(f"Observed:    {observed}")
    print(f"Broken:      {broken}")
    print(f"")
    print(f"Boundary contracts: {boundary_total}")
    print(f"  Frozen: {boundary_frozen} ({bf_pct:.1f}%)")
    print(f"")
    print(f"Parallelism unlocked: {par_ready_count}/{total_tasks} tasks ({unlocked_pct:.1f}%)")

    if verbose:
        if broken > 0:
            print(f"\nBroken contracts:")
            for cid, cs in contracts.items():
                if cs.get("maturity") == "broken":
                    print(f"  {cid}: {cs.get('broken_reason', 'no reason given')}")


def cmd_frozen_boundary(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List only boundary contracts that are frozen (the critical gate contracts)."""
    require_taskdagger_state(state)

    frozen_boundary = [
        (cid, cs) for cid, cs in state["contracts"].items()
        if cs.get("is_boundary_contract") and cs.get("maturity") == "frozen"
    ]

    if not frozen_boundary:
        print("No frozen boundary contracts")
        return

    print(f"Frozen boundary contracts ({len(frozen_boundary)}):")
    for cid, cs in sorted(frozen_boundary):
        print(f"  \u2744 {cid}")
        if verbose:
            print(f"      frozen_at={cs.get('frozen_at', '?')}")
            consumers = cs.get("consumer_task_ids", [])
            print(f"      unlocks: {', '.join(consumers) if consumers else 'none'}")


def cmd_verify_state(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """Report state contradictions that are trivially detectable."""
    require_taskdagger_state(state)

    task_index = build_task_index(dag)
    problems = []

    # 1. Tasks blocked on frozen contracts
    for tid, ts in state["tasks"].items():
        if ts.get("status") != "blocked" or ts.get("blocked_reason") != "contract_broken":
            continue
        blocker = ts.get("blocked_by")
        if blocker and state["contracts"].get(blocker, {}).get("maturity") == "frozen":
            problems.append(
                f"BLOCKED_ON_FROZEN: {tid} blocked by {blocker} "
                f"which is frozen (freeze did not clear the block)")

    # 2. Chunks whose rollup disagrees with their members
    for cid, cs in state["chunks"].items():
        actual_completed = sum(
            1 for mid in cs.get("member_task_ids", [])
            if state["tasks"].get(mid, {}).get("status") == "completed"
        )
        recorded = cs.get("members_completed", 0)
        if actual_completed != recorded:
            problems.append(
                f"CHUNK_ROLLUP_MISMATCH: {cid} records {recorded}/{cs.get('members_total', '?')} "
                f"completed but {actual_completed} members are actually completed")

    # 3. Tasks whose chunk_id is missing despite being a chunk member
    for cid, cs in state["chunks"].items():
        for mid in cs.get("member_task_ids", []):
            ts = state["tasks"].get(mid)
            if ts and ts.get("chunk_id") != cid:
                problems.append(
                    f"ORPHAN_MEMBER: {mid} is a member of chunk {cid} "
                    f"but chunk_id={ts.get('chunk_id')!r}")

    # 4. Tasks in_progress with no start record in the execution log
    started_tasks = {
        entry["task_id"]
        for entry in state.get("execution_log", [])
        if entry.get("event_type") == "task_started" and entry.get("task_id")
    }
    for tid, ts in state["tasks"].items():
        if ts.get("status") == "in_progress" and tid not in started_tasks:
            problems.append(
                f"NO_START_RECORD: {tid} is in_progress but has no "
                f"task_started entry in the execution log")

    if not problems:
        print("State consistent: no contradictions found")
        return

    print(f"State contradictions ({len(problems)}):")
    for p in problems:
        print(f"  {p}")

    sys.exit(1)


def cmd_broken(dag: dict, state: Optional[dict], verbose: bool) -> None:
    """List broken contracts and the tasks/chunks they affect."""
    require_taskdagger_state(state)

    broken = [(cid, cs) for cid, cs in state["contracts"].items()
              if cs.get("maturity") == "broken"]

    if not broken:
        print("No broken contracts")
        return

    print(f"Broken contracts ({len(broken)}):")
    for cid, cs in sorted(broken):
        print(f"  \u2717 {cid}")
        print(f"    Reason: {cs.get('broken_reason', 'no reason given')}")
        print(f"    Broken at: {cs.get('broken_at', '?')}")

        consumers = cs.get("consumer_task_ids", [])
        if consumers:
            print(f"    Affected tasks ({len(consumers)}):")
            for tid in consumers:
                ts = state["tasks"].get(tid, {})
                status = ts.get("status", "?")
                print(f"      [{status}] {tid}")

        if verbose:
            # Show any chunks whose boundary contracts are broken
            chunk_id = cs.get("chunk_id")
            if not chunk_id:
                # Check if it's a boundary contract for any chunk
                for ck_id, ck_st in state["chunks"].items():
                    if cid in ck_st.get("boundary_contract_ids", []):
                        print(f"    Affects chunk: {ck_id} (status={ck_st.get('status', '?')})")


# ============================================================
# FREEZE GATE VALIDATORS (WO-01)
# ============================================================

def _find_contract(dag: dict, contract_id: str) -> Optional[dict]:
    for c in dag.get("contracts", []):
        if c["id"] == contract_id:
            return c
    return None


def _extract_fields_from_signature(signature: str) -> set:
    import re
    fields = set()
    brace_match = re.findall(r'\{([^}]+)\}', signature)
    for content in brace_match:
        for part in content.split(','):
            name = part.strip().split(':')[0].split('=')[0].strip()
            if name and re.match(r'^[a-zA-Z_]\w*$', name):
                fields.add(name.lower())
    method_matches = re.findall(r'def\s+(\w+)\s*\(', signature)
    for m in method_matches:
        fields.add(m.lower())
    param_matches = re.findall(r'(?:^|\n)\s*(\w+)\s*:', signature)
    for p in param_matches:
        if p.lower() not in ('return', 'type', 'class', 'def'):
            fields.add(p.lower())
    return fields


def _parse_set_arithmetic(invariant: str) -> Optional[dict]:
    import re
    m = re.search(
        r'(?:identical|same|equivalent)\s+(?:to|as)\s+'
        r'(?:REST\s+)?(\S+?)(?:\s+minus\s+(.+?))?(?:\.|,|$)',
        invariant, re.IGNORECASE
    )
    if not m:
        return None
    ref = m.group(1).strip().rstrip('.,;')
    excludes = set()
    if m.group(2):
        for part in re.split(r'[/,]', m.group(2)):
            name = part.strip().rstrip('.,;')
            if name:
                excludes.add(name.lower())
    return {"reference": ref, "exclude": excludes}


def _load_category_registry(dag: dict) -> Optional[dict]:
    registry_path = None
    meta = dag.get("metadata", {})
    if "registry_path" in meta:
        registry_path = Path(meta["registry_path"])
    if not registry_path or not registry_path.exists():
        seed_path = Path("references/seed__evolution-by-contract/registry.json")
        if seed_path.exists():
            registry_path = seed_path
    if not registry_path or not registry_path.exists():
        return None
    try:
        return json.loads(registry_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def validate_freeze_gate(dag: dict, contract_id: str, explain: bool = False) -> list:
    import re
    errors = []
    contract = _find_contract(dag, contract_id)
    if not contract:
        return [{"check": "existence", "message": f"Contract {contract_id} not found in DAG"}]

    defn = contract.get("definition", {})
    signature = defn.get("signature", "")
    invariants = defn.get("invariants", [])
    fixtures = contract.get("fixtures", [])

    # Check 1: fixture presence
    happy = [f for f in fixtures if "expected_output" in f]
    error_cases = [f for f in fixtures if "expected_error" in f]
    if not happy:
        e = {"check": "fixture_presence",
             "message": f"{contract_id}: no happy-path fixture (expected_output)"}
        if explain:
            e["detail"] = "Add at least one fixture with an expected_output field."
        errors.append(e)
    if not error_cases:
        e = {"check": "fixture_presence",
             "message": f"{contract_id}: no error-case fixture (expected_error)"}
        if explain:
            e["detail"] = "Add at least one fixture with an expected_error field."
        errors.append(e)

    # Check 2: self-contradiction (S2)
    if signature and invariants:
        sig_fields = _extract_fields_from_signature(signature)
        for inv in invariants:
            parsed = _parse_set_arithmetic(inv)
            if not parsed:
                continue
            ref_contract = None
            for c in dag.get("contracts", []):
                if c["id"] != contract_id:
                    ref_name = c.get("name", "")
                    if (parsed["reference"].lower() in c["id"].lower()
                            or parsed["reference"].lower() in ref_name.lower()):
                        ref_contract = c
                        break
            if ref_contract:
                ref_fields = _extract_fields_from_signature(
                    ref_contract.get("definition", {}).get("signature", ""))
                expected = ref_fields - parsed["exclude"]
                missing = expected - sig_fields
                if missing:
                    e = {"check": "self_contradiction",
                         "message": (f"{contract_id}: invariant claims parity with "
                                     f"{ref_contract['id']} minus {parsed['exclude']}, "
                                     f"but signature is missing: {sorted(missing)}")}
                    if explain:
                        e["detail"] = (f"The invariant resolves to fields "
                                       f"{sorted(expected)}, but the signature declares "
                                       f"{sorted(sig_fields)}. Add the missing fields or "
                                       f"correct the invariant.")
                    errors.append(e)

    # Check 3: ABC/signature agreement (S3)
    for inv in invariants:
        abc_match = re.search(
            r'isinstance.*?(?:to|of)\s+(\w+)|'
            r'attestation\s+(?:to|of)\s+(\w+)|'
            r'subclass(?:es)?\s+(?:of\s+)?(\w+)',
            inv, re.IGNORECASE
        )
        if not abc_match:
            continue
        abc_name = abc_match.group(1) or abc_match.group(2) or abc_match.group(3)
        registry = _load_category_registry(dag)
        if not registry:
            continue
        abc_entry = None
        for cat in registry.get("categories", []):
            if cat["name"].lower() == abc_name.lower():
                abc_entry = cat
                break
        if not abc_entry:
            continue
        abc_methods = {m["name"].lower() for m in abc_entry.get("abstract_methods", [])}
        sig_methods = _extract_fields_from_signature(signature)
        missing = abc_methods - sig_methods
        if missing:
            e = {"check": "abc_signature_agreement",
                 "message": (f"{contract_id}: isinstance attestation to {abc_name} "
                             f"requires methods {sorted(missing)} not in signature")}
            if explain:
                e["detail"] = (f"{abc_name} declares abstract methods {sorted(abc_methods)}. "
                               f"The contract's signature covers {sorted(sig_methods)}. "
                               f"A conforming class cannot be instantiated without "
                               f"implementing {sorted(missing)}.")
            errors.append(e)

    # Check 4: invariant field backing (S1)
    if invariants:
        all_contracts = {c["id"]: c for c in dag.get("contracts", [])}
        for inv in invariants:
            field_refs = re.findall(r'`(\w+)`', inv)
            for field_name in field_refs:
                fn_lower = field_name.lower()
                if fn_lower in ('none', 'true', 'false', 'null', 'str', 'int',
                                'float', 'bool', 'list', 'dict', 'set', 'tuple'):
                    continue
                if signature and fn_lower in _extract_fields_from_signature(signature):
                    continue
                consumers = contract.get("parties", {}).get("consumers", [])
                for consumer_tid in consumers:
                    for cid, c in all_contracts.items():
                        if cid == contract_id:
                            continue
                        provider = c.get("parties", {}).get("provider", "")
                        if provider != consumer_tid:
                            continue
                        consumer_sig = c.get("definition", {}).get("signature", "")
                        if consumer_sig and fn_lower not in _extract_fields_from_signature(consumer_sig):
                            e = {"check": "invariant_field_backing",
                                 "message": (f"{contract_id}: invariant references "
                                             f"`{field_name}` but neither this contract's "
                                             f"signature nor downstream contract {cid}'s "
                                             f"signature carries it")}
                            if explain:
                                e["detail"] = (f"The field must appear in a signature along "
                                               f"the data path or it will be silently dropped.")
                            errors.append(e)

    # Check 5: fixture well-formedness
    for i, fix in enumerate(fixtures):
        label = fix.get("label", f"fixture[{i}]")
        if "expected_output" not in fix and "expected_error" not in fix:
            e = {"check": "fixture_wellformed",
                 "message": f"{contract_id}: {label} has neither expected_output nor expected_error"}
            if explain:
                e["detail"] = "Every fixture must assert either a happy-path output or an error case."
            errors.append(e)

    # Check 6: filter subset (dg-005)
    all_contracts = {c["id"]: c for c in dag.get("contracts", [])}
    provider_tid = contract.get("parties", {}).get("provider", "")
    for cid, downstream in all_contracts.items():
        if cid == contract_id:
            continue
        ds_invariants = downstream.get("definition", {}).get("invariants", [])
        for ds_inv in ds_invariants:
            filter_match = re.search(
                r'(?:sanitiz|filter|allowlist|whitelist|accept)',
                ds_inv, re.IGNORECASE
            )
            if not filter_match:
                continue
            allowlist_match = re.findall(r'\{([^}]+)\}', ds_inv)
            if not allowlist_match:
                continue
            allowed = set()
            for content in allowlist_match:
                for part in content.split(','):
                    name = part.strip().strip("'\"` ")
                    if name:
                        allowed.add(name.lower())
            if not allowed:
                continue
            ds_consumers = downstream.get("parties", {}).get("consumers", [])
            our_consumers = contract.get("parties", {}).get("consumers", [])
            ds_provider = downstream.get("parties", {}).get("provider", "")
            if not (ds_provider in our_consumers or provider_tid in ds_consumers
                    or set(our_consumers) & set(ds_consumers)):
                continue
            our_emitted = set()
            for our_inv in invariants:
                attr_matches = re.findall(
                    r'(?:emit|produce|output|generat)\w*\s+.*?`([^`]+)`',
                    our_inv, re.IGNORECASE
                )
                for a in attr_matches:
                    our_emitted.add(a.lower())
            sig_fields = _extract_fields_from_signature(signature)
            check_fields = our_emitted or sig_fields
            not_allowed = check_fields - allowed
            if not_allowed and allowed:
                e = {"check": "filter_subset",
                     "message": (f"{contract_id}: emits {sorted(not_allowed)} which "
                                 f"downstream {cid}'s filter allowlist "
                                 f"{sorted(allowed)} does not accept")}
                if explain:
                    e["detail"] = (f"Contract {cid} declares a filter/sanitizer with "
                                   f"allowlist {sorted(allowed)}. This contract's output "
                                   f"includes {sorted(not_allowed)} which will be "
                                   f"silently stripped. Add them to the downstream "
                                   f"allowlist or remove them from this contract's output.")
                errors.append(e)

    return errors


# ============================================================
# MUTATION COMMANDS — taskdagger new
# ============================================================

def cmd_freeze_contract(dag: dict, state: Optional[dict], state_path: Path,
                        contract_id: str, explain: bool = False) -> None:
    """Mark a contract as frozen after passing consistency checks."""
    require_taskdagger_state(state)

    if contract_id not in state["contracts"]:
        sys.exit(f"Error: Contract not found: {contract_id}")

    cs = state["contracts"][contract_id]

    if cs.get("maturity") == "frozen":
        sys.exit(f"Error: Contract {contract_id} is already frozen")

    gate_errors = validate_freeze_gate(dag, contract_id, explain=explain)
    if gate_errors:
        print(f"Freeze gate FAILED for {contract_id} — {len(gate_errors)} error(s):", file=sys.stderr)
        for err in gate_errors:
            print(f"  [{err['check']}] {err['message']}", file=sys.stderr)
            if explain and "detail" in err:
                print(f"    → {err['detail']}", file=sys.stderr)
        sys.exit(1)

    now = now_iso()
    cs["maturity"] = "frozen"
    cs["frozen_at"] = now
    cs["fixtures_passed"] = True

    cs["verification_history"].append({
        "timestamp": now,
        "result": "passed",
        "strategy": "fixture_validation",
        "details": f"Contract frozen via taskdagger-cli freeze-contract"
    })

    # Un-block consumers that were blocked by this contract breaking,
    # then re-evaluate parallel_ready for all consumers.
    unblocked_tasks = []
    for tid in cs.get("consumer_task_ids", []):
        ts = state["tasks"].get(tid)
        if not ts:
            continue

        # Clear blocked state pinned by this contract
        if (ts.get("status") == "blocked"
                and ts.get("blocked_by") == contract_id
                and ts.get("blocked_reason") == "contract_broken"):
            dag_task = next((t for t in dag["tasks"] if t["id"] == tid), {})
            other_broken = [
                cid for cid in dag_task.get("contract_ids", [])
                if cid != contract_id
                and state["contracts"].get(cid, {}).get("maturity") == "broken"
            ]
            if other_broken:
                ts["blocked_by"] = other_broken[0]
            else:
                ts["status"] = "pending"
                ts["blocked_by"] = None
                ts["blocked_reason"] = None
                unblocked_tasks.append(tid)
                state["execution_log"].append({
                    "timestamp": now,
                    "event_type": "task_unblocked",
                    "task_id": tid,
                    "contract_id": contract_id,
                    "chunk_id": None,
                    "details": f"Unblocked by re-frozen contract {contract_id}"
                })

        # Recompute parallel_ready
        dag_task = next((t for t in dag["tasks"] if t["id"] == tid), {})
        contract_ids = dag_task.get("contract_ids", [])
        if contract_ids:
            ts["parallel_ready"] = all(
                state["contracts"].get(cid2, {}).get("maturity") == "frozen"
                for cid2 in contract_ids
            )
        else:
            ts["parallel_ready"] = all(
                state["tasks"].get(dep, {}).get("status") in ("completed", "skipped")
                for dep in dag_task.get("dependencies", [])
            )

    # Promote newly-unblocked tasks to ready if their deps are met
    if unblocked_tasks:
        update_ready_status(state, dag)

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "contract_frozen",
        "task_id": None,
        "contract_id": contract_id,
        "chunk_id": cs.get("chunk_id"),
        "details": f"Contract {contract_id} frozen via CLI"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)

    newly_parallel = [
        tid for tid in cs.get("consumer_task_ids", [])
        if state["tasks"].get(tid, {}).get("parallel_ready")
    ]
    print(f"Frozen: {contract_id}")
    if unblocked_tasks:
        print(f"Unblocked: {', '.join(unblocked_tasks)}")
    if newly_parallel:
        print(f"Newly parallel_ready: {', '.join(newly_parallel)}")


def cmd_break_contract(dag: dict, state: Optional[dict], state_path: Path,
                       contract_id: str, reason: str) -> None:
    """Mark a contract broken with reason."""
    require_taskdagger_state(state)

    if contract_id not in state["contracts"]:
        sys.exit(f"Error: Contract not found: {contract_id}")

    cs = state["contracts"][contract_id]
    now = now_iso()

    cs["maturity"] = "broken"
    cs["broken_at"] = now
    cs["broken_reason"] = reason

    cs["verification_history"].append({
        "timestamp": now,
        "result": "failed",
        "strategy": "integration_verification",
        "details": reason
    })

    # Block consumer tasks that are pending/ready in parallel/hybrid mode
    blocked_tasks = []
    for tid in cs.get("consumer_task_ids", []):
        ts = state["tasks"].get(tid)
        if ts and ts.get("status") in ("pending", "ready"):
            mode = ts.get("readiness_mode", "sequential")
            if mode in ("parallel", "hybrid"):
                ts["status"] = "blocked"
                ts["blocked_by"] = contract_id
                ts["blocked_reason"] = "contract_broken"
                blocked_tasks.append(tid)
                state["execution_log"].append({
                    "timestamp": now,
                    "event_type": "task_blocked",
                    "task_id": tid,
                    "contract_id": contract_id,
                    "chunk_id": None,
                    "details": f"Blocked by broken contract {contract_id}"
                })

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "contract_broken",
        "task_id": None,
        "contract_id": contract_id,
        "chunk_id": cs.get("chunk_id"),
        "details": f"Contract {contract_id} broken: {reason}"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Broken: {contract_id}")
    print(f"Reason: {reason}")
    if blocked_tasks:
        print(f"Blocked tasks: {', '.join(blocked_tasks)}")


def cmd_promote_contract(dag: dict, state: Optional[dict], state_path: Path,
                         contract_id: str, rationale: str) -> None:
    """Promote an observed contract to frozen with mandatory rationale."""
    require_taskdagger_state(state)

    if contract_id not in state["contracts"]:
        sys.exit(f"Error: Contract not found: {contract_id}")

    cs = state["contracts"][contract_id]

    if cs.get("maturity") != "observed":
        sys.exit(f"Error: Contract {contract_id} maturity is '{cs.get('maturity')}', "
                 f"not 'observed'. Only observed contracts can be promoted.")

    if not rationale or not rationale.strip():
        sys.exit("Error: promote-contract requires a rationale. "
                 "Usage: promote-contract <id> <rationale>")

    gate_errors = validate_freeze_gate(dag, contract_id)
    if gate_errors:
        print(f"Freeze gate FAILED for {contract_id} — {len(gate_errors)} error(s):", file=sys.stderr)
        for err in gate_errors:
            print(f"  [{err['check']}] {err['message']}", file=sys.stderr)
        sys.exit(1)

    now = now_iso()
    cs["maturity"] = "frozen"
    cs["frozen_at"] = now
    cs["promoted_at"] = now
    cs["promoted_rationale"] = rationale.strip()
    cs["fixtures_passed"] = True

    cs["verification_history"].append({
        "timestamp": now,
        "result": "passed",
        "strategy": "promotion",
        "details": f"Observed contract promoted to frozen: {rationale.strip()}"
    })

    unblocked_tasks = []
    for tid in cs.get("consumer_task_ids", []):
        ts = state["tasks"].get(tid)
        if not ts:
            continue
        if (ts.get("status") == "blocked"
                and ts.get("blocked_by") == contract_id
                and ts.get("blocked_reason") == "contract_broken"):
            dag_task = next((t for t in dag["tasks"] if t["id"] == tid), {})
            other_broken = [
                cid for cid in dag_task.get("contract_ids", [])
                if cid != contract_id
                and state["contracts"].get(cid, {}).get("maturity") == "broken"
            ]
            if other_broken:
                ts["blocked_by"] = other_broken[0]
            else:
                ts["status"] = "pending"
                ts["blocked_by"] = None
                ts["blocked_reason"] = None
                unblocked_tasks.append(tid)

        dag_task = next((t for t in dag["tasks"] if t["id"] == tid), {})
        contract_ids = dag_task.get("contract_ids", [])
        if contract_ids:
            ts["parallel_ready"] = all(
                state["contracts"].get(cid2, {}).get("maturity") == "frozen"
                for cid2 in contract_ids
            )

    if unblocked_tasks:
        update_ready_status(state, dag)

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "contract_promoted",
        "task_id": None,
        "contract_id": contract_id,
        "chunk_id": cs.get("chunk_id"),
        "details": f"Observed contract {contract_id} promoted to frozen: {rationale.strip()}"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)

    newly_parallel = [
        tid for tid in cs.get("consumer_task_ids", [])
        if state["tasks"].get(tid, {}).get("parallel_ready")
    ]
    print(f"Promoted: {contract_id} (observed -> frozen)")
    print(f"Rationale: {rationale.strip()}")
    if unblocked_tasks:
        print(f"Unblocked: {', '.join(unblocked_tasks)}")
    if newly_parallel:
        print(f"Newly parallel_ready: {', '.join(newly_parallel)}")


def cmd_chunk_start(dag: dict, state: Optional[dict], state_path: Path, chunk_id: str) -> None:
    """Mark a chunk as building."""
    require_taskdagger_state(state)

    if chunk_id not in state["chunks"]:
        sys.exit(f"Error: Chunk not found: {chunk_id}")

    cs = state["chunks"][chunk_id]

    if cs.get("status") != "pending":
        sys.exit(f"Error: Chunk status is '{cs['status']}', cannot start (must be pending)")

    now = now_iso()
    cs["status"] = "building"
    cs["started_at"] = now

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "chunk_build_started",
        "task_id": None,
        "contract_id": None,
        "chunk_id": chunk_id,
        "details": f"Chunk {chunk_id} marked as building via CLI"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Started: {chunk_id} (status: building)")


def cmd_chunk_verify(dag: dict, state: Optional[dict], state_path: Path, chunk_id: str) -> None:
    """Mark a chunk as verified."""
    require_taskdagger_state(state)

    if chunk_id not in state["chunks"]:
        sys.exit(f"Error: Chunk not found: {chunk_id}")

    cs = state["chunks"][chunk_id]

    if cs.get("status") not in ("building", "verifying"):
        sys.exit(f"Error: Chunk status is '{cs['status']}', cannot verify (must be building or verifying)")

    now = now_iso()
    cs["status"] = "verified"
    cs["verified_at"] = now
    cs["internal_composition_passed"] = True
    cs["boundary_conformance_passed"] = True

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "chunk_verified",
        "task_id": None,
        "contract_id": None,
        "chunk_id": chunk_id,
        "details": f"Chunk {chunk_id} verified: composition and boundary conformance passed"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Verified: {chunk_id}")


def cmd_chunk_fail(dag: dict, state: Optional[dict], state_path: Path,
                   chunk_id: str, reason: str) -> None:
    """Mark a chunk as failed."""
    require_taskdagger_state(state)

    if chunk_id not in state["chunks"]:
        sys.exit(f"Error: Chunk not found: {chunk_id}")

    cs = state["chunks"][chunk_id]

    if cs.get("status") in ("verified", "failed"):
        sys.exit(f"Error: Chunk status is '{cs['status']}', cannot fail")

    now = now_iso()
    cs["status"] = "failed"
    cs["failed_at"] = now
    cs["error"] = reason

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "chunk_failed",
        "task_id": None,
        "contract_id": None,
        "chunk_id": chunk_id,
        "details": f"Chunk {chunk_id} failed: {reason}"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Failed: {chunk_id}")
    print(f"Reason: {reason}")


def cmd_expose_outputs(dag: dict, state: Optional[dict], state_path: Path, chunk_id: str) -> None:
    """Mark chunk outputs as exposed to consumers (called after chunk-verify)."""
    require_taskdagger_state(state)

    if chunk_id not in state["chunks"]:
        sys.exit(f"Error: Chunk not found: {chunk_id}")

    cs = state["chunks"][chunk_id]

    if cs.get("status") != "verified":
        sys.exit(f"Error: Chunk status is '{cs['status']}', cannot expose outputs (must be verified)")

    if cs.get("outputs_exposed"):
        print(f"Note: {chunk_id} outputs already exposed")
        return

    now = now_iso()
    cs["outputs_exposed"] = True

    state["execution_log"].append({
        "timestamp": now,
        "event_type": "outputs_exposed",
        "task_id": None,
        "contract_id": None,
        "chunk_id": chunk_id,
        "details": f"Chunk {chunk_id} outputs exposed to downstream consumers"
    })

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Outputs exposed: {chunk_id}")


# ============================================================
# MUTATION COMMANDS \u2014 inherited from tdag
# ============================================================

def cmd_init(dag: dict, state: Optional[dict], state_path: Path, dag_path: Path,
             force: bool, mode: str) -> None:
    """Initialize progress state from DAG."""
    if state is not None and not force:
        sys.exit("Error: State already exists. Use --force to reinitialize.")

    root_tasks = {t["id"] for t in dag["tasks"] if not t.get("dependencies")}

    tasks = {}
    for task in dag["tasks"]:
        tid = task["id"]
        task_mode = task.get("readiness_mode", mode if mode != "hybrid" else "hybrid")
        is_root = tid in root_tasks
        tasks[tid] = {
            "status": "ready" if is_root else "pending",
            "readiness_mode": task_mode,
            "sequential_ready": is_root,
            "parallel_ready": False,
            "attempts": 0,
            "max_attempts": task.get("max_attempts", 3),
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "blocked_by": None,
            "blocked_reason": None,
            "error": None,
            "error_history": [],
            "output_summary": None,
            "artifacts_verified": False,
            "notes": None,
            "chunk_id": task.get("chunk_id", None)
        }

    # Build boundary contract set from chunks
    boundary_contract_ids = set()
    for chunk in dag.get("chunks", []):
        for cid in chunk.get("boundary_contracts", []):
            boundary_contract_ids.add(cid)

    # Initialize contracts state
    contracts = {}
    for contract in dag.get("contracts", []):
        cid = contract["id"]
        # Support both explicit scope field and derivation from chunks
        scope = contract.get("scope", "boundary" if cid in boundary_contract_ids else "internal")
        parties = contract.get("parties", {})
        initial_maturity = contract.get("contract_maturity", "provisional")
        if initial_maturity not in ("observed", "provisional", "frozen", "broken"):
            initial_maturity = "provisional"
        contracts[cid] = {
            "maturity": initial_maturity,
            "is_boundary_contract": scope == "boundary",
            "frozen_at": None,
            "broken_at": None,
            "broken_reason": None,
            "fixtures_passed": False,
            "fixture_count": len(contract.get("fixtures", [])),
            "stub_generated": False,
            "stub_path": None,
            "provider_task_id": parties.get("provider", contract.get("provider_task_id")),
            "consumer_task_ids": parties.get("consumers", contract.get("consumer_task_ids", [])),
            "provenance": contract.get("provenance"),
            "promoted_at": None,
            "promoted_rationale": None,
            "verification_history": []
        }

    # Initialize chunks state
    chunks = {}
    for chunk in dag.get("chunks", []):
        cid = chunk["id"]
        # Support both "members" (spec canonical) and "member_task_ids" (legacy)
        member_ids = chunk.get("members", chunk.get("member_task_ids", []))
        boundary_cids = chunk.get("boundary_contracts", chunk.get("boundary_contract_ids", []))
        chunks[cid] = {
            "status": "pending",
            "started_at": None,
            "verified_at": None,
            "failed_at": None,
            "internal_composition_passed": False,
            "boundary_conformance_passed": False,
            "error": None,
            "members_completed": 0,
            "members_total": len(member_ids),
            "outputs_exposed": False,
            "boundary_contract_ids": boundary_cids,
            "member_task_ids": member_ids
        }

    # Cross-reference: set chunk_id on tasks listed as chunk members
    for cid, chunk_state in chunks.items():
        for member_tid in chunk_state["member_task_ids"]:
            if member_tid in tasks and tasks[member_tid]["chunk_id"] is None:
                tasks[member_tid]["chunk_id"] = cid

    new_state = {
        "dag_id": dag.get("epic", {}).get("id", "unknown"),
        "dag_file": str(dag_path),
        "schema_version": "taskdagger-1.0",
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "status": "in_progress",
        "tasks": tasks,
        "contracts": contracts,
        "chunks": chunks,
        "metrics": {},
        "execution_log": [{
            "timestamp": now_iso(),
            "event_type": "execution_started",
            "task_id": None,
            "contract_id": None,
            "chunk_id": None,
            "details": (
                f"Initialized with {len(tasks)} tasks, "
                f"{len(contracts)} contracts, {len(chunks)} chunks | mode={mode}"
            )
        }]
    }

    new_state["metrics"] = calculate_metrics(new_state)
    save_state(new_state, state_path)

    ready_count = sum(1 for t in tasks.values() if t["status"] == "ready")
    print(f"Initialized: {len(tasks)} tasks, {len(contracts)} contracts, {len(chunks)} chunks")
    print(f"Mode: {mode} | {ready_count} tasks ready to start")
    print(f"State file: {state_path}")


def cmd_start(dag: dict, state: Optional[dict], state_path: Path, task_id: str) -> None:
    """Mark a task as started."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    if task_id not in state["tasks"]:
        sys.exit(f"Error: Task not found: {task_id}")

    ts = state["tasks"][task_id]

    if ts["status"] not in ("ready", "pending"):
        sys.exit(f"Error: Task status is '{ts['status']}', cannot start")

    now = now_iso()
    ts["status"] = "in_progress"
    ts["started_at"] = now
    ts["attempts"] += 1

    # Transition owning chunk to building if still pending
    if is_taskdagger_state(state) and ts.get("chunk_id"):
        chunk = state["chunks"].get(ts["chunk_id"])
        if chunk and chunk["status"] == "pending":
            chunk["status"] = "building"
            chunk["started_at"] = now
            state["execution_log"].append({
                "timestamp": now,
                "event_type": "chunk_build_started",
                "task_id": None,
                "contract_id": None,
                "chunk_id": ts["chunk_id"],
                "details": f"Chunk building started via task {task_id}"
            })

    log_entry = {
        "timestamp": now,
        "event_type": "task_started",
        "task_id": task_id,
        "details": f"Started attempt {ts['attempts']}"
    }
    if is_taskdagger_state(state):
        log_entry["contract_id"] = None
        log_entry["chunk_id"] = ts.get("chunk_id")
    state["execution_log"].append(log_entry)

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Started: {task_id} (attempt {ts['attempts']})")


def cmd_complete(dag: dict, state: Optional[dict], state_path: Path, task_id: str,
                 summary: Optional[str]) -> None:
    """Mark a task as completed."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    if task_id not in state["tasks"]:
        sys.exit(f"Error: Task not found: {task_id}")

    ts = state["tasks"][task_id]
    now = now_iso()

    ts["status"] = "completed"
    ts["completed_at"] = now
    ts["artifacts_verified"] = True
    if summary:
        ts["output_summary"] = summary

    if ts["started_at"]:
        start = datetime.fromisoformat(ts["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(now.replace("Z", "+00:00"))
        ts["duration_seconds"] = (end - start).total_seconds()

    log_entry = {
        "timestamp": now,
        "event_type": "task_completed",
        "task_id": task_id,
        "details": summary or "Task completed"
    }
    if is_taskdagger_state(state):
        log_entry["contract_id"] = None
        log_entry["chunk_id"] = ts.get("chunk_id")

        # Update chunk member count; check if all members done
        chunk_id = ts.get("chunk_id")
        if chunk_id:
            chunk = state["chunks"].get(chunk_id)
            if chunk:
                chunk["members_completed"] += 1
                if chunk["members_completed"] >= chunk["members_total"]:
                    chunk["status"] = "verifying"
                    state["execution_log"].append({
                        "timestamp": now,
                        "event_type": "chunk_verifying",
                        "task_id": None,
                        "contract_id": None,
                        "chunk_id": chunk_id,
                        "details": f"All {chunk['members_total']} members completed; running verification"
                    })

    state["execution_log"].append(log_entry)

    update_ready_status(state, dag)

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)

    newly_ready = [tid for tid, t in state["tasks"].items()
                   if t["status"] == "ready" and tid != task_id]
    print(f"Completed: {task_id}")
    if newly_ready:
        print(f"Now ready: {', '.join(newly_ready)}")


def cmd_fail(dag: dict, state: Optional[dict], state_path: Path, task_id: str, error: str) -> None:
    """Mark a task as failed."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    if task_id not in state["tasks"]:
        sys.exit(f"Error: Task not found: {task_id}")

    ts = state["tasks"][task_id]
    now = now_iso()

    ts["error_history"].append({
        "attempt": ts["attempts"],
        "timestamp": now,
        "error": error,
        "recoverable": ts["attempts"] < ts["max_attempts"]
    })

    if ts["attempts"] >= ts["max_attempts"]:
        ts["status"] = "failed"
        ts["error"] = error

        propagate_blocked(state, dag, task_id)

        # Fail owning chunk if applicable
        if is_taskdagger_state(state) and ts.get("chunk_id"):
            chunk = state["chunks"].get(ts["chunk_id"])
            if chunk and chunk["status"] in ("building", "verifying"):
                chunk["status"] = "failed"
                chunk["failed_at"] = now
                chunk["error"] = f"Member task {task_id} failed: {error}"
                state["execution_log"].append({
                    "timestamp": now,
                    "event_type": "chunk_failed",
                    "task_id": None,
                    "contract_id": None,
                    "chunk_id": ts["chunk_id"],
                    "details": chunk["error"]
                })

        log_entry = {
            "timestamp": now,
            "event_type": "task_failed",
            "task_id": task_id,
            "details": f"Failed after {ts['attempts']} attempts: {error}"
        }
        if is_taskdagger_state(state):
            log_entry["contract_id"] = None
            log_entry["chunk_id"] = ts.get("chunk_id")
        state["execution_log"].append(log_entry)
        print(f"Failed: {task_id} (max attempts reached)")
    else:
        ts["status"] = "ready"
        log_entry = {
            "timestamp": now,
            "event_type": "task_retried",
            "task_id": task_id,
            "details": f"Attempt {ts['attempts']} failed: {error}"
        }
        if is_taskdagger_state(state):
            log_entry["contract_id"] = None
            log_entry["chunk_id"] = ts.get("chunk_id")
        state["execution_log"].append(log_entry)
        print(f"Failed attempt {ts['attempts']}: {task_id} (will retry)")

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)


def cmd_skip(dag: dict, state: Optional[dict], state_path: Path, task_id: str) -> None:
    """Skip a task (dependents can still proceed)."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    if task_id not in state["tasks"]:
        sys.exit(f"Error: Task not found: {task_id}")

    ts = state["tasks"][task_id]
    ts["status"] = "skipped"

    log_entry = {
        "timestamp": now_iso(),
        "event_type": "task_skipped",
        "task_id": task_id,
        "details": "Manually skipped"
    }
    if is_taskdagger_state(state):
        log_entry["contract_id"] = None
        log_entry["chunk_id"] = ts.get("chunk_id")
    state["execution_log"].append(log_entry)

    update_ready_status(state, dag)

    state["metrics"] = calculate_metrics(state)
    save_state(state, state_path)
    print(f"Skipped: {task_id}")


def cmd_note(dag: dict, state: Optional[dict], state_path: Path, task_id: str, note: str) -> None:
    """Add a note to a task."""
    if state is None:
        sys.exit("Error: State not initialized. Run 'init' first.")

    if task_id not in state["tasks"]:
        sys.exit(f"Error: Task not found: {task_id}")

    state["tasks"][task_id]["notes"] = note
    save_state(state, state_path)
    print(f"Note added to {task_id}")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def calculate_metrics(state: dict) -> dict:
    """Calculate metrics from full state (tasks + contracts + chunks if present)."""
    tasks = state.get("tasks", {})
    contracts = state.get("contracts", {})
    chunks = state.get("chunks", {})

    # Task metrics
    task_by_status = {}
    for ts in tasks.values():
        s = ts.get("status", "pending")
        task_by_status[s] = task_by_status.get(s, 0) + 1

    total_tasks = len(tasks)
    completed_tasks = task_by_status.get("completed", 0) + task_by_status.get("skipped", 0)
    task_pct = (completed_tasks / total_tasks * 100) if total_tasks else 0

    # Contract metrics
    contract_by_maturity = {"observed": 0, "provisional": 0, "frozen": 0, "broken": 0}
    boundary_total = 0
    boundary_frozen = 0
    for cs in contracts.values():
        m = cs.get("maturity", "provisional")
        contract_by_maturity[m] = contract_by_maturity.get(m, 0) + 1
        if cs.get("is_boundary_contract"):
            boundary_total += 1
            if m == "frozen":
                boundary_frozen += 1

    # Chunk metrics
    chunk_by_status = {}
    for cs in chunks.values():
        s = cs.get("status", "pending")
        chunk_by_status[s] = chunk_by_status.get(s, 0) + 1

    total_chunks = len(chunks)
    verified_chunks = chunk_by_status.get("verified", 0)

    # Parallelism
    par_ready = sum(1 for ts in tasks.values()
                    if ts.get("parallel_ready") and ts.get("status") in ("pending", "ready"))
    seq_ready = sum(1 for ts in tasks.values()
                    if ts.get("sequential_ready") and ts.get("status") in ("pending", "ready"))
    in_progress = task_by_status.get("in_progress", 0)

    # Preserve existing parallelism meta
    existing_par = state.get("metrics", {}).get("parallelism", {})
    par_mode = existing_par.get("mode", "sequential")
    max_observed = max(existing_par.get("max_observed_parallel", 0), in_progress)

    return {
        "tasks": {
            "total": total_tasks,
            "by_status": task_by_status,
            "completion_percentage": round(task_pct, 1),
            "estimated_remaining_tasks": total_tasks - completed_tasks
        },
        "contracts": {
            "total": len(contracts),
            "by_maturity": contract_by_maturity,
            "boundary_contracts_total": boundary_total,
            "boundary_frozen_percentage": round(boundary_frozen / boundary_total * 100, 1)
                                          if boundary_total else 0.0
        },
        "chunks": {
            "total": total_chunks,
            "by_status": chunk_by_status,
            "verified_percentage": round(verified_chunks / total_chunks * 100, 1)
                                   if total_chunks else 0.0
        },
        "parallelism": {
            "mode": par_mode,
            "sequential_ready_count": seq_ready,
            "parallel_ready_count": par_ready,
            "max_theoretical_parallelism": 0,
            "current_parallel_tasks": in_progress,
            "max_observed_parallel": max_observed
        }
    }


def update_ready_status(state: dict, dag: dict) -> None:
    """Update pending tasks to ready if deps are met (respects readiness_mode)."""
    for task in dag["tasks"]:
        tid = task["id"]
        ts = state["tasks"].get(tid, {})

        if ts.get("status") != "pending":
            continue

        deps = task.get("dependencies", [])
        mode = ts.get("readiness_mode", "sequential")

        # Sequential readiness
        seq_ready = all(
            state["tasks"].get(d, {}).get("status") in ("completed", "skipped")
            for d in deps
        )
        ts["sequential_ready"] = seq_ready

        # Parallel readiness
        contract_ids = task.get("contract_ids", [])
        if is_taskdagger_state(state) and contract_ids:
            par_ready = all(
                state["contracts"].get(cid, {}).get("maturity") == "frozen"
                for cid in contract_ids
            )
        else:
            par_ready = seq_ready
        ts["parallel_ready"] = par_ready

        # Apply readiness based on mode
        if mode == "sequential" and seq_ready:
            state["tasks"][tid]["status"] = "ready"
        elif mode == "parallel" and par_ready:
            state["tasks"][tid]["status"] = "ready"
        elif mode == "hybrid" and seq_ready and par_ready:
            state["tasks"][tid]["status"] = "ready"


def propagate_blocked(state: dict, dag: dict, failed_task_id: str) -> None:
    """Mark dependents of failed task as blocked."""
    dependents_index = build_dependents_index(dag)

    to_block = dependents_index.get(failed_task_id, [])
    blocked = set()

    while to_block:
        tid = to_block.pop(0)
        if tid in blocked:
            continue

        ts = state["tasks"].get(tid, {})
        if ts.get("status") in ("completed", "skipped"):
            continue

        ts["status"] = "blocked"
        ts["blocked_by"] = failed_task_id
        ts["blocked_reason"] = "dependency_failed"
        blocked.add(tid)

        to_block.extend(dependents_index.get(tid, []))


def find_chains(dag: dict, task_index: dict, dependents_index: dict,
                in_degree: dict, out_degree: dict) -> list:
    """Find maximal linear chains in the DAG."""
    visited = set()
    chains = []

    for tid in task_index:
        if tid in visited:
            continue

        ind = in_degree[tid]

        is_chain_start = False
        if ind == 0:
            is_chain_start = True
        elif ind > 1:
            is_chain_start = True
        elif ind == 1:
            task = task_index[tid]
            pred = task.get("dependencies", [])[0]
            if out_degree.get(pred, 0) > 1:
                is_chain_start = True

        if not is_chain_start:
            continue

        chain = []
        current = tid
        while current and current not in visited:
            chain.append(current)
            visited.add(current)

            if out_degree[current] != 1:
                break

            successors = dependents_index.get(current, [])
            if not successors:
                break

            next_node = successors[0]
            if in_degree[next_node] > 1:
                break

            current = next_node

        if chain:
            chains.append(chain)

    return chains


def assign_levels(dag: dict, task_index: dict) -> dict:
    """Assign levels to tasks via topological sort."""
    levels = {}
    remaining = dict(task_index)

    while remaining:
        ready = []
        for tid, task in remaining.items():
            deps = task.get("dependencies", [])
            if all(d in levels for d in deps):
                ready.append(tid)

        if not ready:
            break

        for tid in ready:
            task = remaining[tid]
            deps = task.get("dependencies", [])
            if deps:
                levels[tid] = max(levels[d] for d in deps) + 1
            else:
                levels[tid] = 0
            del remaining[tid]

    return levels


def calculate_max_parallelism(dag: dict, task_index: dict) -> int:
    """Calculate maximum width (antichain size) of the DAG."""
    levels = assign_levels(dag, task_index)

    level_counts = {}
    for tid, lvl in levels.items():
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    return max(level_counts.values()) if level_counts else 0


def get_critical_path_status(state: dict, dag: dict) -> dict:
    """Get progress along critical path."""
    cp = dag.get("metadata", {}).get("critical_path_task_ids", [])
    completed = 0
    current = None

    for tid in cp:
        status = state["tasks"].get(tid, {}).get("status", "pending")
        if status == "completed":
            completed += 1
        elif status in ("ready", "in_progress") and current is None:
            current = tid

    return {
        "total_tasks": len(cp),
        "completed": completed,
        "current_task": current
    }


# ============================================================
# CONTRACT ARCHIVE / REPLAY / HASH
# ============================================================
#
# Content-addressed archive of fulfilled contracts.
#
# Layout (per work_order_template.md):
#   {archive}/{hash}/
#     contract.json       canonical contract + provenance metadata
#     work_order.md       (optional) the work order that produced it
#     implementation_ref  pointer text to implementation artifacts
#   {archive}/index.json  hash -> summary (rebuildable; see archive-reindex)
#
# Archive resolution order (lookup searches all, save writes to first):
#   --archive PATH  >  {dag_dir}/.taskdagger/contract-archive  +  $TASKDAGGER_ARCHIVE (extra, read)


def canonical_contract(contract: dict) -> dict:
    """Extract only the semantic fields of a contract, tolerant of both
    schema shapes (orchestrator DAG JSON: type_signature/invariants/...;
    contracts.md reference: definition.signature/definition.invariants/...).

    Excludes non-semantic fields (labels, notes, auto_generated, maturity,
    scope, parties) so cosmetic edits don't change the hash."""
    defn = contract.get("definition", {}) or {}
    sig = contract.get("type_signature") or defn.get("signature") or {}
    invariants = contract.get("invariants") or defn.get("invariants") or []
    side_effects = contract.get("side_effects") or defn.get("side_effects") or []
    fixtures = contract.get("fixtures") or []

    canon_fixtures = []
    for f in fixtures:
        cf = {}
        for key in ("input", "expected_output", "expected_error"):
            if f.get(key) is not None:
                cf[key] = f[key]
        if cf:
            canon_fixtures.append(cf)
    canon_fixtures.sort(key=lambda x: json.dumps(x, sort_keys=True))

    return {
        "signature": sig,
        "invariants": sorted(str(i) for i in invariants),
        "side_effects": sorted(str(s) for s in side_effects),
        "fixtures": canon_fixtures,
    }


def _hash_obj(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def compute_contract_hash(contract: dict) -> str:
    """Full semantic hash: signature + invariants + side_effects + fixtures.
    First 16 hex chars (64 bits) — directory-name friendly, collision-safe
    at archive scale. Full sha256 stored in entry metadata."""
    return _hash_obj(canonical_contract(contract))[:16]


def compute_signature_hash(contract: dict) -> str:
    """Signature-only hash, used for near-miss detection: same signature,
    different invariants/fixtures => warm-start candidate."""
    return _hash_obj(canonical_contract(contract)["signature"])[:16]


def resolve_archive_dirs(args_archive: Optional[str], dag_path: Path) -> list:
    """Ordered archive search path. First entry is the write target."""
    if args_archive:
        return [Path(args_archive)]
    dirs = [dag_path.parent / ".taskdagger" / "contract-archive"]
    extra = os.environ.get("TASKDAGGER_ARCHIVE")
    if extra:
        dirs.append(Path(extra))
    return dirs


def load_archive_index(archive_dir: Path) -> dict:
    idx_path = archive_dir / "index.json"
    if not idx_path.exists():
        return {}
    try:
        return json.loads(idx_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return rebuild_archive_index(archive_dir)


def save_archive_index(archive_dir: Path, index: dict) -> None:
    idx_path = archive_dir / "index.json"
    tmp = idx_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(idx_path)


def rebuild_archive_index(archive_dir: Path) -> dict:
    """Reconstruct index.json from entry directories (self-healing)."""
    index = {}
    if not archive_dir.is_dir():
        return index
    for entry_dir in archive_dir.iterdir():
        meta_path = entry_dir / "contract.json"
        if not (entry_dir.is_dir() and meta_path.exists()):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        index[entry_dir.name] = {
            "contract_id": meta.get("contract_id"),
            "signature_hash": meta.get("signature_hash"),
            "project": meta.get("project"),
            "saved_at": meta.get("saved_at"),
            "children": meta.get("children", []),
        }
    return index


def find_archive_entry(h: str, archive_dirs: list) -> Optional[dict]:
    """Exact-hash lookup across all archive dirs. Returns metadata + location."""
    for d in archive_dirs:
        meta_path = d / h / "contract.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            meta["_archive_dir"] = str(d)
            meta["_entry_dir"] = str(d / h)
            return meta
    return None


def derive_constituent_contracts(dag: dict, contract: dict) -> list:
    """Constituent (child) contracts for hierarchical replay.

    Definition: the contracts fulfilled *inside* the providing chunk to
    produce this one — every contract whose provider task is a member of
    the provider's chunk, excluding the contract itself. The providing
    chunk is the DEEPEST chunk (recursing into sub_chunks) whose members
    include the provider task, so a leaf contract inside a sub-chunk gets
    that sub-chunk's scope, not the whole parent's. On a coarse
    (parent-boundary) miss, hits on these still assemble a partial warm
    start."""
    task_index = build_task_index(dag)
    provider_id = contract.get("from") or (contract.get("parties", {}) or {}).get("provider")
    if provider_id not in task_index:
        return []

    def direct_members(chunk: dict) -> set:
        return set(chunk.get("members", chunk.get("task_ids", [])))

    def all_members(chunk: dict) -> set:
        members = direct_members(chunk)
        for sub in chunk.get("sub_chunks", []) or []:
            members |= all_members(sub)
        return members

    def deepest_containing(chunk: dict) -> Optional[dict]:
        if provider_id not in all_members(chunk):
            return None
        for sub in chunk.get("sub_chunks", []) or []:
            found = deepest_containing(sub)
            if found:
                return found
        return chunk

    home = None
    for chunk in dag.get("chunks", []):
        home = deepest_containing(chunk)
        if home:
            break
    if not home:
        return []
    member_ids = all_members(home)

    children = []
    for c in dag.get("contracts", []):
        if c.get("id") == contract.get("id"):
            continue
        c_provider = c.get("from") or (c.get("parties", {}) or {}).get("provider")
        if c_provider in member_ids:
            children.append(c)
    return children


def current_conventions(dag: dict) -> list:
    return (dag.get("metadata", {}) or {}).get("conventions", [])


def conventions_compatible(entry_meta: dict, dag: dict) -> bool:
    """Conservative: exact canonical equality of convention lists.
    Differing or absent-vs-present conventions => treat hit as warm start
    (hash proves interface equivalence, not semantic equivalence)."""
    return _hash_obj(entry_meta.get("conventions", [])) == _hash_obj(current_conventions(dag))


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_contract_hash(dag: dict, contract_id: Optional[str], as_json: bool) -> None:
    """Print semantic hash(es). contract_id=None => all contracts."""
    contracts = build_contract_index(dag)
    if contract_id and contract_id not in contracts:
        sys.exit(f"Error: Contract not found: {contract_id}")
    targets = [contracts[contract_id]] if contract_id else list(contracts.values())
    rows = [
        {"contract_id": c["id"],
         "hash": compute_contract_hash(c),
         "signature_hash": compute_signature_hash(c)}
        for c in targets
    ]
    if as_json:
        _emit({"contracts": rows}, True)
        return
    for r in rows:
        print(f"{r['hash']}  sig:{r['signature_hash']}  {r['contract_id']}")


def cmd_verify_hashes(dag: dict, as_json: bool) -> None:
    """Recompute every contract's hash and compare against any stored
    contract_hash field. Reports mismatches."""
    contracts = dag.get("contracts", [])
    if not contracts:
        if as_json:
            _emit({"matched": 0, "mismatched": 0, "no_stored_hash": 0,
                   "mismatches": []}, True)
        else:
            print("No contracts in DAG")
        return

    mismatches = []
    no_stored = []
    matched = []

    for c in contracts:
        computed = compute_contract_hash(c)
        stored = c.get("contract_hash")
        if stored is None:
            no_stored.append({"contract_id": c["id"], "computed": computed})
        elif stored != computed:
            mismatches.append({
                "contract_id": c["id"],
                "stored": stored,
                "computed": computed
            })
        else:
            matched.append({"contract_id": c["id"], "hash": computed})

    if as_json:
        _emit({
            "matched": len(matched),
            "mismatched": len(mismatches),
            "no_stored_hash": len(no_stored),
            "mismatches": mismatches,
        }, True)
        return

    total = len(contracts)
    print(f"Verify hashes: {total} contracts")
    print(f"  Matched:        {len(matched)}")
    print(f"  Mismatched:     {len(mismatches)}")
    print(f"  No stored hash: {len(no_stored)}")

    if mismatches:
        print(f"\nMismatches:")
        for m in mismatches:
            print(f"  {m['contract_id']}")
            print(f"    stored:   {m['stored']}")
            print(f"    computed: {m['computed']}")

    if mismatches:
        sys.exit(1)


def cmd_archive_save(dag: dict, state: Optional[dict], contract_id: str,
                     archive_dirs: list, impl_ref: Optional[str],
                     work_order: Optional[str], as_json: bool) -> None:
    """Store a fulfilled contract in the archive (write target = first dir)."""
    contracts = build_contract_index(dag)
    if contract_id not in contracts:
        sys.exit(f"Error: Contract not found: {contract_id}")
    contract = contracts[contract_id]

    # Advisory only — spec-only mode has no enforced state.
    if state is not None and is_taskdagger_state(state):
        cs = state.get("contracts", {}).get(contract_id, {})
        if cs.get("maturity") != "frozen":
            print(f"Warning: contract {contract_id} is not frozen in state "
                  f"(maturity={cs.get('maturity')}). Archiving anyway.", file=sys.stderr)
        fr = cs.get("fixture_results", {})
        if not fr.get("passed", False):
            print(f"Warning: contract {contract_id} has no passing fixture run "
                  f"recorded. Archiving anyway.", file=sys.stderr)

    h = compute_contract_hash(contract)
    canon = canonical_contract(contract)
    children = derive_constituent_contracts(dag, contract)

    archive_dir = archive_dirs[0]
    entry_dir = archive_dir / h
    entry_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "contract_id": contract_id,
        "hash": h,
        "full_hash": _hash_obj(canon),
        "signature_hash": compute_signature_hash(contract),
        "canonical": canon,
        "contract": contract,
        "children": sorted({compute_contract_hash(c) for c in children}),
        "conventions": current_conventions(dag),
        "hash_recipe_version": 1,
        "project": (dag.get("epic", {}) or {}).get("id"),
        "saved_at": now_iso(),
        "implementation_ref": impl_ref,
    }
    tmp = entry_dir / "contract.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(entry_dir / "contract.json")

    if impl_ref:
        (entry_dir / "implementation_ref").write_text(impl_ref + "\n", encoding="utf-8")
    if work_order:
        wo_path = Path(work_order)
        if wo_path.exists():
            shutil.copyfile(wo_path, entry_dir / "work_order.md")
        else:
            print(f"Warning: work order not found: {work_order}", file=sys.stderr)

    index = load_archive_index(archive_dir)
    index[h] = {
        "contract_id": contract_id,
        "signature_hash": meta["signature_hash"],
        "project": meta["project"],
        "saved_at": meta["saved_at"],
        "children": meta["children"],
    }
    save_archive_index(archive_dir, index)

    if as_json:
        _emit({"saved": h, "entry_dir": str(entry_dir),
               "children": meta["children"]}, True)
    else:
        print(f"Archived: {contract_id} -> {entry_dir}")
        if meta["children"]:
            print(f"  children: {', '.join(meta['children'])}")


def cmd_archive_lookup(dag: dict, contract_id: str, archive_dirs: list,
                       as_json: bool, verbose: bool) -> None:
    """Replay check. Order: exact hash -> (on miss) near-miss by signature
    + hierarchical constituent lookup. Never a verification bypass — a hit
    still passes chunk verification and integration testing."""
    contracts = build_contract_index(dag)
    if contract_id not in contracts:
        sys.exit(f"Error: Contract not found: {contract_id}")
    contract = contracts[contract_id]
    h = compute_contract_hash(contract)
    sig_h = compute_signature_hash(contract)

    result = {"contract_id": contract_id, "hash": h, "signature_hash": sig_h,
              "verdict": "miss", "exact": None, "near_misses": [],
              "children": []}

    exact = find_archive_entry(h, archive_dirs)
    if exact:
        compatible = conventions_compatible(exact, dag)
        result["exact"] = {
            "entry_dir": exact["_entry_dir"],
            "project": exact.get("project"),
            "saved_at": exact.get("saved_at"),
            "implementation_ref": exact.get("implementation_ref"),
            "conventions_compatible": compatible,
        }
        result["verdict"] = "hit" if compatible else "hit_convention_mismatch"
    else:
        # Near-miss: same signature, different semantics -> warm start.
        seen = set()
        for d in archive_dirs:
            for eh, info in load_archive_index(d).items():
                if eh in seen or eh == h:
                    continue
                seen.add(eh)
                if info.get("signature_hash") == sig_h:
                    result["near_misses"].append(
                        {"hash": eh, "entry_dir": str(d / eh),
                         "contract_id": info.get("contract_id"),
                         "project": info.get("project")})
        # Hierarchical: coarse miss, fine hits -> partial warm start.
        for child in derive_constituent_contracts(dag, contract):
            ch = compute_contract_hash(child)
            entry = find_archive_entry(ch, archive_dirs)
            result["children"].append(
                {"contract_id": child.get("id"), "hash": ch,
                 "hit": entry is not None,
                 "entry_dir": entry["_entry_dir"] if entry else None,
                 "conventions_compatible":
                     conventions_compatible(entry, dag) if entry else None})
        child_hits = sum(1 for c in result["children"] if c["hit"])
        if child_hits:
            result["verdict"] = f"partial_warm_start:{child_hits}/{len(result['children'])}"
        elif result["near_misses"]:
            result["verdict"] = "warm_start_candidate"

    if as_json:
        _emit(result, True)
        return
    print(f"Contract: {contract_id}")
    print(f"Hash: {h}  (sig: {sig_h})")
    print(f"Verdict: {result['verdict']}")
    if result["exact"]:
        e = result["exact"]
        print(f"  entry: {e['entry_dir']}")
        print(f"  impl: {e['implementation_ref']}")
        if not e["conventions_compatible"]:
            print("  NOTE: origin conventions differ — treat as warm start, not hit")
    for nm in result["near_misses"]:
        print(f"  near-miss: {nm['hash']} ({nm['contract_id']}, {nm['project']})")
    for c in result["children"]:
        mark = "HIT " if c["hit"] else "miss"
        print(f"  child [{mark}] {c['hash']}  {c['contract_id']}")


def cmd_replay_report(dag: dict, archive_dirs: list, as_json: bool) -> None:
    """Batch replay check for every contract in the DAG. Useful in the
    build briefing: how much of this build is already cached?"""
    rows = []
    for c in dag.get("contracts", []):
        h = compute_contract_hash(c)
        entry = find_archive_entry(h, archive_dirs)
        if entry:
            verdict = ("hit" if conventions_compatible(entry, dag)
                       else "hit_convention_mismatch")
        else:
            sig_h = compute_signature_hash(c)
            verdict = "miss"
            for d in archive_dirs:
                idx = load_archive_index(d)
                if any(i.get("signature_hash") == sig_h and eh != h
                       for eh, i in idx.items()):
                    verdict = "warm_start_candidate"
                    break
        rows.append({"contract_id": c["id"], "hash": h, "verdict": verdict})

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    if as_json:
        _emit({"summary": counts, "contracts": rows}, True)
        return
    total = len(rows)
    print(f"Replay report: {total} contracts")
    for verdict, n in sorted(counts.items()):
        print(f"  {verdict}: {n}")
    for r in rows:
        if r["verdict"] != "miss":
            print(f"  {r['verdict']:<24} {r['hash']}  {r['contract_id']}")


def cmd_archive_list(archive_dirs: list, as_json: bool) -> None:
    """List all archive entries across the search path."""
    rows = []
    seen = set()
    for d in archive_dirs:
        for h, info in sorted(load_archive_index(d).items()):
            if h in seen:
                continue
            seen.add(h)
            rows.append({"hash": h, "archive": str(d), **info})
    if as_json:
        _emit({"entries": rows}, True)
        return
    if not rows:
        print("Archive empty.")
        return
    for r in rows:
        print(f"{r['hash']}  {r.get('contract_id')}  "
              f"(project: {r.get('project')}, saved: {r.get('saved_at')})")


def cmd_archive_info(h: str, archive_dirs: list, as_json: bool) -> None:
    """Show full metadata for one archive entry."""
    entry = find_archive_entry(h, archive_dirs)
    if not entry:
        sys.exit(f"Error: No archive entry for hash: {h}")
    if as_json:
        _emit(entry, True)
        return
    print(f"Hash: {entry.get('hash')}  (full: {entry.get('full_hash', '')[:32]}…)")
    print(f"Contract: {entry.get('contract_id')}")
    print(f"Project: {entry.get('project')}   Saved: {entry.get('saved_at')}")
    print(f"Entry: {entry.get('_entry_dir')}")
    print(f"Impl ref: {entry.get('implementation_ref')}")
    if entry.get("children"):
        print(f"Children: {', '.join(entry['children'])}")
    if entry.get("conventions"):
        print(f"Conventions: {len(entry['conventions'])} declared")


def cmd_archive_reindex(archive_dirs: list, as_json: bool) -> None:
    """Rebuild index.json for the write-target archive from entry dirs."""
    archive_dir = archive_dirs[0]
    index = rebuild_archive_index(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    save_archive_index(archive_dir, index)
    if as_json:
        _emit({"archive": str(archive_dir), "entries": len(index)}, True)
    else:
        print(f"Reindexed {archive_dir}: {len(index)} entries")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Contract-Based Task DAG CLI - Surgical access for AI agents (taskdagger superset of tdag)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands (tdag inherited):
  Query:  status, queues, tasks [queue], task <id>, ready [--tier T],
          blocked, crit-path, deps <id>, dependents <id>, artifacts <id>,
          libs [id], hints, index, structure
  Mutate: init [--mode sequential|parallel|hybrid], start <id>,
          complete <id> [msg], fail <id> <err>, skip <id>, note <id> <text>

Commands (taskdagger new):
  Query:  contracts, contract <id>, parallel-ready, chunks, chunk <id>,
          chunk-ready, contract-status, frozen-boundary, broken,
          verify-state
  Mutate: freeze-contract <id>, break-contract <id> <reason>,
          promote-contract <id> <rationale>,
          chunk-start <id>, chunk-verify <id>, chunk-fail <id> <reason>,
          expose-outputs <chunk-id>

Commands (contract archive / replay):
  contract-hash [id]           semantic hash(es); no id = all contracts
  verify-hashes                recompute all hashes, compare against stored
  archive-save <id> [--impl-ref PATH] [--work-order PATH]
  archive-lookup <id>          exact -> near-miss -> hierarchical children
  replay-report                batch lookup for the whole DAG
  archive-list                 all entries across the archive search path
  archive-info <hash>          full metadata for one entry
  archive-reindex              rebuild index.json from entry dirs
  Archive path: --archive PATH > {dag_dir}/.taskdagger/contract-archive
                (+ $TASKDAGGER_ARCHIVE searched as an extra read location)
  All archive commands accept --json for machine-readable output.

Examples:
    taskdagger-cli.py --dag ./dag.json status
    taskdagger-cli.py --dag ./dag.json init --mode parallel
    taskdagger-cli.py --dag ./dag.json contracts
    taskdagger-cli.py --dag ./dag.json freeze-contract auth-token-interface
    taskdagger-cli.py --dag ./dag.json parallel-ready
    taskdagger-cli.py --dag ./dag.json chunk-verify auth-token-chunk
    taskdagger-cli.py --dag ./dag.json archive-save auth-token-interface --impl-ref src/auth/
    taskdagger-cli.py --dag ./dag.json archive-lookup auth-token-interface --json
    taskdagger-cli.py --dag ./dag.json replay-report
"""
    )

    parser.add_argument("--dag", "-d", help="Path to DAG JSON file (or set TASKDAGGER_FILE env)")
    parser.add_argument("command", help="Command to run")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--force", action="store_true", help="Force operation (e.g. reinit)")
    parser.add_argument("--mode", default="hybrid",
                        choices=["sequential", "parallel", "hybrid"],
                        help="Execution mode for init (default: hybrid)")
    parser.add_argument("--tier", help="Filter by task tier (e.g. 'poc')")
    parser.add_argument("--archive", help="Contract archive path (overrides default + $TASKDAGGER_ARCHIVE)")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output (archive commands)")
    parser.add_argument("--impl-ref", help="Implementation artifact pointer (archive-save)")
    parser.add_argument("--work-order", help="Work order .md to copy into the entry (archive-save)")

    args = parser.parse_args()

    # Resolve paths
    dag_path = get_dag_path(args.dag)
    state_path = get_state_path(dag_path)

    # Load data
    dag = load_dag(dag_path)
    state = load_state(state_path)

    # Dispatch
    cmd = args.command.lower()

    # ---- tdag inherited query commands ----
    if cmd == "status":
        cmd_status(dag, state, args.verbose)
    elif cmd == "queues":
        cmd_queues(dag, state, args.verbose)
    elif cmd == "tasks":
        queue = args.args[0] if args.args else None
        cmd_tasks(dag, state, queue, args.verbose)
    elif cmd == "task":
        if not args.args:
            sys.exit("Error: task command requires task_id")
        cmd_task(dag, state, args.args[0], args.verbose)
    elif cmd == "ready":
        cmd_ready(dag, state, args.verbose, tier=args.tier)
    elif cmd == "blocked":
        cmd_blocked(dag, state, args.verbose)
    elif cmd in ("crit-path", "critpath", "critical-path"):
        cmd_crit_path(dag, state, args.verbose)
    elif cmd == "deps":
        if not args.args:
            sys.exit("Error: deps command requires task_id")
        cmd_deps(dag, state, args.args[0], args.verbose)
    elif cmd == "dependents":
        if not args.args:
            sys.exit("Error: dependents command requires task_id")
        cmd_dependents(dag, state, args.args[0], args.verbose)
    elif cmd == "artifacts":
        if not args.args:
            sys.exit("Error: artifacts command requires task_id")
        cmd_artifacts(dag, state, args.args[0], args.verbose)
    elif cmd == "libs":
        task_id = args.args[0] if args.args else None
        cmd_libs(dag, state, task_id, args.verbose)
    elif cmd == "hints":
        cmd_hints(dag, state, args.verbose)
    elif cmd == "index":
        cmd_index(dag, state, args.verbose)
    elif cmd == "structure":
        cmd_structure(dag, state, args.verbose)

    # ---- taskdagger new query commands ----
    elif cmd == "contracts":
        cmd_contracts(dag, state, args.verbose)
    elif cmd == "contract":
        if not args.args:
            sys.exit("Error: contract command requires contract_id")
        cmd_contract(dag, state, args.args[0], args.verbose)
    elif cmd in ("parallel-ready", "parallel_ready"):
        cmd_parallel_ready(dag, state, args.verbose)
    elif cmd == "chunks":
        cmd_chunks(dag, state, args.verbose)
    elif cmd == "chunk":
        if not args.args:
            sys.exit("Error: chunk command requires chunk_id")
        cmd_chunk(dag, state, args.args[0], args.verbose)
    elif cmd in ("chunk-ready", "chunk_ready"):
        cmd_chunk_ready(dag, state, args.verbose)
    elif cmd in ("contract-status", "contract_status"):
        cmd_contract_status(dag, state, args.verbose)
    elif cmd in ("frozen-boundary", "frozen_boundary"):
        cmd_frozen_boundary(dag, state, args.verbose)
    elif cmd == "broken":
        cmd_broken(dag, state, args.verbose)
    elif cmd in ("verify-state", "verify_state"):
        cmd_verify_state(dag, state, args.verbose)

    # ---- tdag inherited mutation commands ----
    elif cmd == "init":
        cmd_init(dag, state, state_path, dag_path, args.force, args.mode)
    elif cmd == "start":
        if not args.args:
            sys.exit("Error: start command requires task_id")
        cmd_start(dag, state, state_path, args.args[0])
    elif cmd == "complete":
        if not args.args:
            sys.exit("Error: complete command requires task_id")
        summary = " ".join(args.args[1:]) if len(args.args) > 1 else None
        cmd_complete(dag, state, state_path, args.args[0], summary)
    elif cmd == "fail":
        if len(args.args) < 2:
            sys.exit("Error: fail command requires task_id and error message")
        cmd_fail(dag, state, state_path, args.args[0], " ".join(args.args[1:]))
    elif cmd == "skip":
        if not args.args:
            sys.exit("Error: skip command requires task_id")
        cmd_skip(dag, state, state_path, args.args[0])
    elif cmd == "note":
        if len(args.args) < 2:
            sys.exit("Error: note command requires task_id and note text")
        cmd_note(dag, state, state_path, args.args[0], " ".join(args.args[1:]))

    # ---- taskdagger new mutation commands ----
    elif cmd in ("freeze-contract", "freeze_contract"):
        if not args.args:
            sys.exit("Error: freeze-contract command requires contract_id")
        explain = "--explain" in args.args
        cid = [a for a in args.args if not a.startswith("--")][0]
        cmd_freeze_contract(dag, state, state_path, cid, explain=explain)
    elif cmd in ("break-contract", "break_contract"):
        if len(args.args) < 2:
            sys.exit("Error: break-contract command requires contract_id and reason")
        cmd_break_contract(dag, state, state_path, args.args[0], " ".join(args.args[1:]))
    elif cmd in ("promote-contract", "promote_contract"):
        if len(args.args) < 2:
            sys.exit("Error: promote-contract requires contract_id and rationale")
        cmd_promote_contract(dag, state, state_path, args.args[0], " ".join(args.args[1:]))
    elif cmd in ("chunk-start", "chunk_start"):
        if not args.args:
            sys.exit("Error: chunk-start command requires chunk_id")
        cmd_chunk_start(dag, state, state_path, args.args[0])
    elif cmd in ("chunk-verify", "chunk_verify"):
        if not args.args:
            sys.exit("Error: chunk-verify command requires chunk_id")
        cmd_chunk_verify(dag, state, state_path, args.args[0])
    elif cmd in ("chunk-fail", "chunk_fail"):
        if len(args.args) < 2:
            sys.exit("Error: chunk-fail command requires chunk_id and reason")
        cmd_chunk_fail(dag, state, state_path, args.args[0], " ".join(args.args[1:]))
    elif cmd in ("expose-outputs", "expose_outputs"):
        if not args.args:
            sys.exit("Error: expose-outputs command requires chunk_id")
        cmd_expose_outputs(dag, state, state_path, args.args[0])

    # ---- contract archive / replay commands ----
    elif cmd in ("contract-hash", "contract_hash"):
        cmd_contract_hash(dag, args.args[0] if args.args else None, args.json)
    elif cmd in ("verify-hashes", "verify_hashes"):
        cmd_verify_hashes(dag, args.json)
    elif cmd in ("archive-save", "archive_save"):
        if not args.args:
            sys.exit("Error: archive-save command requires contract_id")
        cmd_archive_save(dag, state, args.args[0],
                         resolve_archive_dirs(args.archive, dag_path),
                         args.impl_ref, args.work_order, args.json)
    elif cmd in ("archive-lookup", "archive_lookup"):
        if not args.args:
            sys.exit("Error: archive-lookup command requires contract_id")
        cmd_archive_lookup(dag, args.args[0],
                           resolve_archive_dirs(args.archive, dag_path),
                           args.json, args.verbose)
    elif cmd in ("replay-report", "replay_report"):
        cmd_replay_report(dag, resolve_archive_dirs(args.archive, dag_path), args.json)
    elif cmd in ("archive-list", "archive_list"):
        cmd_archive_list(resolve_archive_dirs(args.archive, dag_path), args.json)
    elif cmd in ("archive-info", "archive_info"):
        if not args.args:
            sys.exit("Error: archive-info command requires a hash")
        cmd_archive_info(args.args[0], resolve_archive_dirs(args.archive, dag_path), args.json)
    elif cmd in ("archive-reindex", "archive_reindex"):
        cmd_archive_reindex(resolve_archive_dirs(args.archive, dag_path), args.json)

    else:
        sys.exit(f"Unknown command: {cmd}\nRun with --help for usage")


if __name__ == "__main__":
    main()

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


CLI_PATH = Path(__file__).resolve().parents[1] / "taskdagger-cli.py"
_SPEC = importlib.util.spec_from_file_location("taskdagger_cli", CLI_PATH)
cli = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cli)


def _make_dag(shape):
    fixtures = [
        {"label": "happy path", "input": {}, "expected_output": {}},
        {"label": "error path", "input": {}, "expected_error": {}},
    ]
    if shape == "orchestrator":
        tasks = [
            {
                "id": "provider",
                "queue_id": "q",
                "name": "Provider",
                "dependencies": [],
                "metadata": {
                    "contracts": {"provides": ["contract:provider"], "requires": []},
                    "chunk_id": "chunk-provider",
                },
            },
            {
                "id": "consumer_a",
                "queue_id": "q",
                "name": "Consumer A",
                "dependencies": ["provider"],
                "metadata": {
                    "contracts": {"provides": [], "requires": ["contract:provider"]},
                    "chunk_id": "chunk-provider",
                },
            },
            {
                "id": "consumer_b",
                "queue_id": "q",
                "name": "Consumer B",
                "dependencies": ["provider"],
                "metadata": {
                    "contracts": {"provides": [], "requires": ["contract:provider"]}
                },
            },
        ]
        contracts = [
            {
                "id": "contract:provider",
                "from": "provider",
                "to": ["consumer_a", "consumer_b"],
                "maturity": "provisional",
                "scope": "boundary",
                "type_signature": {"output": "x", "input": "x"},
                "invariants": [],
                "side_effects": ["none"],
                "fixtures": fixtures,
            }
        ]
        chunks = [
            {
                "id": "chunk-provider",
                "name": "Provider chunk",
                "queue_ids": ["q"],
                "task_ids": ["provider", "consumer_a"],
                "boundary_contracts": ["contract:provider"],
                "internal_contracts": [],
            }
        ]
    else:
        tasks = [
            {
                "id": "provider",
                "queue_id": "q",
                "name": "Provider",
                "dependencies": [],
                "contract_ids": ["contract:provider"],
                "chunk_id": "chunk-provider",
            },
            {
                "id": "consumer_a",
                "queue_id": "q",
                "name": "Consumer A",
                "dependencies": ["provider"],
                "contract_ids": ["contract:provider"],
                "chunk_id": "chunk-provider",
            },
            {
                "id": "consumer_b",
                "queue_id": "q",
                "name": "Consumer B",
                "dependencies": ["provider"],
                "contract_ids": ["contract:provider"],
            },
        ]
        contracts = [
            {
                "id": "contract:provider",
                "parties": {
                    "provider": "provider",
                    "consumers": ["consumer_a", "consumer_b"],
                },
                "contract_maturity": "provisional",
                "scope": "boundary",
                "type_signature": {"output": "x", "input": "x"},
                "invariants": [],
                "side_effects": ["none"],
                "fixtures": fixtures,
            }
        ]
        chunks = [
            {
                "id": "chunk-provider",
                "name": "Provider chunk",
                "members": ["provider", "consumer_a"],
                "member_task_ids": ["provider", "consumer_a"],
                "boundary_contracts": ["contract:provider"],
            }
        ]
    return {
        "epic": {"id": "demo", "title": "Demo", "description": "demo", "mode": "validated"},
        "queues": [
            {
                "id": "q",
                "name": "Q",
                "purpose": "p",
                "inputs": [],
                "outputs": [],
                "success_criteria": [],
            }
        ],
        "tasks": tasks,
        "contracts": contracts,
        "chunks": chunks,
        "edges": [],
        "metadata": {"total_tasks": 3, "total_contracts": 1},
    }


def _canonical(dag):
    return {
        "task_contract_ids": {
            task["id"]: task.get("contract_ids") for task in dag["tasks"]
        },
        "task_chunk_id": {
            task["id"]: task.get("chunk_id") for task in dag["tasks"]
        },
        "chunk_members": {
            chunk["id"]: chunk.get("members") for chunk in dag["chunks"]
        },
        "chunk_boundary_contracts": {
            chunk["id"]: chunk.get("boundary_contracts") for chunk in dag["chunks"]
        },
        "contract_maturity": {
            contract["id"]: contract.get("contract_maturity")
            for contract in dag["contracts"]
        },
        "contract_parties": {
            contract["id"]: contract.get("parties")
            for contract in dag["contracts"]
        },
    }


class TaskdaggerSchemaTests(unittest.TestCase):
    def test_orchestrator_and_cli_shapes_have_same_normalized_canonical_content(self):
        orch_dag, orch_report = cli.normalize_dag(_make_dag("orchestrator"))
        cli_dag, cli_report = cli.normalize_dag(_make_dag("cli"))
        self.assertEqual(_canonical(orch_dag), _canonical(cli_dag))
        self.assertFalse(orch_report["conflicts"])
        self.assertFalse(cli_report["conflicts"])
        self.assertEqual(orch_dag["tasks"][0]["contract_ids"], ["contract:provider"])
        self.assertEqual(orch_dag["tasks"][1]["contract_ids"], ["contract:provider"])
        self.assertEqual(orch_dag["tasks"][0]["chunk_id"], "chunk-provider")
        self.assertEqual(orch_dag["chunks"][0]["members"], ["provider", "consumer_a"])

    def test_normalize_is_idempotent(self):
        first, _first_report = cli.normalize_dag(_make_dag("orchestrator"))
        second, _second_report = cli.normalize_dag(first)
        self.assertEqual(first, second)
        self.assertEqual(_canonical(first), _canonical(second))

    def test_conflict_detection_reports_and_keeps_stronger_maturity(self):
        dag = {
            "tasks": [],
            "contracts": [
                {
                    "id": "c",
                    "maturity": "frozen",
                    "contract_maturity": "provisional",
                    "from": "a",
                    "to": "b",
                }
            ],
            "chunks": [],
        }
        normalized, report = cli.normalize_dag(dag)
        self.assertTrue(
            any(
                conflict["entity"] == "contract"
                and conflict["field"] == "contract_maturity"
                for conflict in report["conflicts"]
            )
        )
        self.assertEqual(normalized["contracts"][0]["contract_maturity"], "frozen")

    def test_task_ids_alias_does_not_create_empty_chunk(self):
        dag = {
            "epic": {"id": "e", "title": "E", "description": "d"},
            "tasks": [
                {"id": "a", "dependencies": []},
                {"id": "b", "dependencies": ["a"]},
            ],
            "contracts": [],
            "chunks": [
                {
                    "id": "chunk1",
                    "task_ids": ["a", "b"],
                    "boundary_contracts": [],
                }
            ],
            "metadata": {},
        }
        normalized, _report = cli.normalize_dag(dag)
        self.assertEqual(normalized["chunks"][0]["members"], ["a", "b"])
        self.assertEqual(normalized["chunks"][0]["member_task_ids"], ["a", "b"])
        state = self._init_state(normalized)
        self.assertEqual(state["chunks"]["chunk1"]["members_total"], 2)
        self.assertEqual(state["chunks"]["chunk1"]["member_task_ids"], ["a", "b"])

    def test_readiness_results_match_for_both_shapes(self):
        orch_dag, _ = cli.normalize_dag(_make_dag("orchestrator"))
        cli_dag, _ = cli.normalize_dag(_make_dag("cli"))
        orch_statuses = self._readiness_snapshot(orch_dag)
        cli_statuses = self._readiness_snapshot(cli_dag)
        self.assertEqual(orch_statuses, cli_statuses)
        self.assertEqual(orch_statuses["consumer_a"], "pending")
        self.assertEqual(orch_statuses["consumer_b"], "pending")
        self.assertEqual(orch_statuses["provider"], "completed")

    def _init_state(self, dag):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dag_path = tmp_path / "dag.json"
            dag_path.write_text(json.dumps(dag), encoding="utf-8")
            state_path = tmp_path / "dag-progress.json"
            with contextlib.redirect_stdout(io.StringIO()):
                cli.cmd_init(dag, None, state_path, dag_path, False, "parallel")
            return json.loads(state_path.read_text(encoding="utf-8"))

    def _readiness_snapshot(self, dag):
        state = {
            "tasks": {
                "provider": {
                    "status": "completed",
                    "readiness_mode": "sequential",
                    "sequential_ready": True,
                    "parallel_ready": False,
                },
                "consumer_a": {
                    "status": "pending",
                    "readiness_mode": "parallel",
                    "sequential_ready": False,
                    "parallel_ready": False,
                },
                "consumer_b": {
                    "status": "pending",
                    "readiness_mode": "parallel",
                    "sequential_ready": False,
                    "parallel_ready": False,
                },
            },
            "contracts": {"contract:provider": {"maturity": "provisional"}},
            "chunks": {},
            "execution_log": [],
            "metrics": {},
        }
        cli.update_ready_status(state, dag)
        return {tid: ts["status"] for tid, ts in sorted(state["tasks"].items())}


if __name__ == "__main__":
    unittest.main()
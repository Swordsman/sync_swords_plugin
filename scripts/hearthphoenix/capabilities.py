"""Capability detection and guarantee reporting."""

from __future__ import annotations

import ast
import logging
import subprocess
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class GuaranteeLevel(IntEnum):
    BRUTE_FORCE = 0      # SIGKILL, cold start, no verification
    GRACEFUL = 1         # SIGTERM handler detected
    HEALTH_VERIFIED = 2  # Health endpoint detected
    STATE_PRESERVING = 3 # State serialization hooks detected
    FULL_COOPERATION = 4 # Full WorkerApp with contracts


class Capability(Enum):
    SIGTERM_HANDLER = "sigterm"
    HEALTH_CHECK = "health_check"
    STATE_SERIALIZATION = "state_serialization"
    WORKER_APP = "worker_app"
    KNOWN_TRANSPORT = "known_transport"
    CONTRACT_DECLARED = "contract_declared"


@dataclass
class CapabilityReport:
    detected: set[Capability]
    missing: set[Capability]
    guarantee_level: GuaranteeLevel
    risks: list[str]
    recommendations: list[str]


class CapabilityScanner:
    """Introspect Python scripts and processes for HearthPhoenix capabilities."""

    _HEALTH_NAMES = {"health", "health_check", "status"}
    _STATE_NAMES = {"serialize_state", "deserialize_state", "checkpoint", "restore"}

    def scan_script(self, script_path: Path) -> CapabilityReport:
        """Introspect a Python script to detect capabilities."""
        script_path = Path(script_path).expanduser().resolve()
        detected: set[Capability] = set()

        try:
            source = script_path.read_text(encoding="utf-8")
            tree = ast.parse(source, str(script_path))
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", script_path, exc)
            return self._build_report(detected)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", script_path, exc)
            return self._build_report(detected)

        # Single-pass AST collection
        all_nodes = list(ast.walk(tree))

        # Collect imports for later checks
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        for node in all_nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
                    if alias.asname:
                        imported_names.add(alias.asname)
                    else:
                        imported_names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_modules.add(module)
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        # SIGTERM_HANDLER detection
        if self._has_sigterm_handler(all_nodes, imported_names):
            detected.add(Capability.SIGTERM_HANDLER)

        # HEALTH_CHECK detection
        if self._has_health_check(all_nodes):
            detected.add(Capability.HEALTH_CHECK)

        # STATE_SERIALIZATION detection
        if self._has_state_serialization(all_nodes):
            detected.add(Capability.STATE_SERIALIZATION)

        # WORKER_APP detection
        if self._has_worker_app(all_nodes, imported_modules, imported_names):
            detected.add(Capability.WORKER_APP)

        # CONTRACT_DECLARED detection — @contract decorators in AST
        if self._has_contract_declared(all_nodes, imported_names):
            detected.add(Capability.CONTRACT_DECLARED)

        # KNOWN_TRANSPORT detection
        if self._has_known_transport(source, imported_modules):
            detected.add(Capability.KNOWN_TRANSPORT)

        return self._build_report(detected)

    def scan_process(self, proc: subprocess.Popen) -> CapabilityReport:
        """Runtime detection (minimal for now)."""
        return CapabilityReport(
            detected=set(),
            missing=set(Capability),
            guarantee_level=GuaranteeLevel.BRUTE_FORCE,
            risks=["Runtime scanning not fully implemented."],
            recommendations=["Use scan_script() for static analysis before spawning."],
        )

    def _build_report(self, detected: set[Capability]) -> CapabilityReport:
        missing = set(Capability) - detected
        level = self._compute_guarantee_level(detected)
        risks, recommendations = self._generate_advice(detected)
        return CapabilityReport(
            detected=detected,
            missing=missing,
            guarantee_level=level,
            risks=risks,
            recommendations=recommendations,
        )

    def _compute_guarantee_level(self, detected: set[Capability]) -> GuaranteeLevel:
        if Capability.WORKER_APP in detected:
            return GuaranteeLevel.FULL_COOPERATION
        if Capability.STATE_SERIALIZATION in detected:
            return GuaranteeLevel.STATE_PRESERVING
        if Capability.HEALTH_CHECK in detected:
            return GuaranteeLevel.HEALTH_VERIFIED
        if Capability.SIGTERM_HANDLER in detected:
            return GuaranteeLevel.GRACEFUL
        return GuaranteeLevel.BRUTE_FORCE

    def _generate_advice(
        self, detected: set[Capability]
    ) -> tuple[list[str], list[str]]:
        risks: list[str] = []
        recommendations: list[str] = []

        if Capability.SIGTERM_HANDLER not in detected:
            risks.append("Worker may not shut down gracefully; SIGKILL will be used.")
            recommendations.append(
                "Add `signal.signal(signal.SIGTERM, handler)` or use "
                "`from hearthphoenix.worker import install_graceful_shutdown`."
            )
        if Capability.HEALTH_CHECK not in detected:
            risks.append(
                "Update health verification unavailable; transport-level checks only."
            )
            recommendations.append(
                "Add a `health()` function or use WorkerApp @health_check decorator."
            )
        if Capability.STATE_SERIALIZATION not in detected:
            risks.append("State will be lost on hotswap.")
            recommendations.append(
                "Implement `serialize_state()` / `deserialize_state()` hooks."
            )
        if Capability.WORKER_APP not in detected:
            risks.append(
                "Worker is not using the HearthPhoenix SDK; behavior is unpredictable."
            )
            recommendations.append(
                "Subclass `WorkerApp` from `hearthphoenix.worker`."
            )
        if Capability.KNOWN_TRANSPORT not in detected:
            risks.append(
                "Transport detection failed; supervisor may not communicate correctly."
            )
            recommendations.append(
                "Use `HEARTH_PHOENIX_TRANSPORT` environment variable or import from "
                "`hearthphoenix.transports`."
            )
        if Capability.CONTRACT_DECLARED not in detected:
            risks.append(
                "No @contract decorators detected; per-operation guarantees unavailable."
            )
            recommendations.append(
                "Subclass WorkerContract and use @contract(Operation.XXX) to declare "
                "supported operations with specific guarantee levels."
            )

        return risks, recommendations

    def _has_sigterm_handler(self, nodes: list[ast.AST], imported_names: set[str]) -> bool:
        # Check for install_graceful_shutdown import
        if "install_graceful_shutdown" in imported_names:
            return True

        # Check for signal.signal(signal.SIGTERM, ...) or signal.signal(signal.SIGINT, ...)
        for node in nodes:
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "signal":
                    # Could be signal.signal(...) or module.signal(...)
                    if isinstance(func.value, ast.Name) and func.value.id == "signal":
                        if len(node.args) >= 2:
                            first_arg = node.args[0]
                            if (
                                isinstance(first_arg, ast.Attribute)
                                and first_arg.attr in ("SIGTERM", "SIGINT")
                                and isinstance(first_arg.value, ast.Name)
                                and first_arg.value.id == "signal"
                            ):
                                return True
                elif isinstance(func, ast.Name) and func.id == "signal":
                    # Direct call to signal(...) — unusual but accept if args match
                    if len(node.args) >= 2:
                        first_arg = node.args[0]
                        if (
                            isinstance(first_arg, ast.Attribute)
                            and first_arg.attr in ("SIGTERM", "SIGINT")
                        ):
                            return True
        return False

    def _has_health_check(self, nodes: list[ast.AST]) -> bool:
        for node in nodes:
            if isinstance(node, ast.FunctionDef) and node.name in self._HEALTH_NAMES:
                return True
            # FastAPI / Flask decorators: @app.get('/health') or @app.route('/health')
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        dec_func = decorator.func
                        if isinstance(dec_func, ast.Attribute):
                            # e.g. app.get, app.post, app.route
                            if dec_func.attr in ("get", "post", "route", "head"):
                                if decorator.args:
                                    first_arg = decorator.args[0]
                                    if (
                                        isinstance(first_arg, ast.Constant)
                                        and isinstance(first_arg.value, str)
                                        and "health" in first_arg.value.lower()
                                    ):
                                        return True
                                    # Python < 3.8 compatibility
                                    elif (
                                        isinstance(first_arg, ast.Str)
                                        and "health" in first_arg.s.lower()
                                    ):
                                        return True
        return False

    def _has_state_serialization(self, nodes: list[ast.AST]) -> bool:
        for node in nodes:
            if isinstance(node, ast.FunctionDef) and node.name in self._STATE_NAMES:
                return True
        return False

    def _has_worker_app(
        self, nodes: list[ast.AST], imported_modules: set[str], imported_names: set[str]
    ) -> bool:
        # Check imports from hearthphoenix.worker
        if any("hearthphoenix.worker" in mod for mod in imported_modules):
            return True
        if "WorkerApp" in imported_names:
            return True
        # Check for subclassing WorkerApp
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "WorkerApp":
                        return True
                    if isinstance(base, ast.Attribute):
                        # e.g. worker.WorkerApp or hearthphoenix.worker.WorkerApp
                        if base.attr == "WorkerApp":
                            return True
        return False

    def _has_contract_declared(
        self, nodes: list[ast.AST], imported_names: set[str]
    ) -> bool:
        """Detect @contract(Operation.XXX) decorator usage in worker source.

        Checks for:

        1. Import of ``contract`` from ``hearthphoenix.contracts``.
        2. AST decorator calls matching ``contract(...)``.
        """
        if "contract" in imported_names:
            return True
        for node in nodes:
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        dec_func = decorator.func
                        if isinstance(dec_func, ast.Name) and dec_func.id == "contract":
                            return True
        return False

    def _has_known_transport(
        self, source: str, imported_modules: set[str]
    ) -> bool:
        # Check for HEARTH_PHOENIX_TRANSPORT literal in source
        if "HEARTH_PHOENIX_TRANSPORT" in source:
            return True
        # Check imports from hearthphoenix.transports
        if any("hearthphoenix.transports" in mod for mod in imported_modules):
            return True
        return False

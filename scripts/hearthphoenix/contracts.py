"""Contract system with precondition, postcondition, invariant decorators,
WorkerContract, @contract declaration API, runtime verification, and caching."""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Operation — maps each lifecycle operation to its required capability
# ---------------------------------------------------------------------------


class Operation(Enum):
    """Lifecycle operations that a worker may support.

    Each value carries a ``required_capability`` field indicating which
    :class:`~hearthphoenix.capabilities.Capability` must be present for the
    operation to be GUARANTEED.
    """

    START = ("start", None)
    STOP = ("stop", "SIGTERM_HANDLER")
    RESTART = ("restart", "SIGTERM_HANDLER")
    HEALTH_CHECK = ("health_check", "HEALTH_CHECK")
    HOTSWAP = ("hotswap", "HEALTH_CHECK")
    ROLLBACK = ("rollback", None)
    STATE_TRANSFER = ("state_transfer", "STATE_SERIALIZATION")

    def __init__(self, label: str, required_capability: Optional[str]) -> None:
        self.label = label
        self._required_capability = required_capability

    @property
    def required_capability(self) -> Optional[str]:
        """The name of the :class:`Capability` needed for GUARANTEED status.

        Returns ``None`` for operations that are always GUARANTEED
        (e.g. ``START`` and ``ROLLBACK``).
        """
        return self._required_capability


def _contracts_enabled() -> bool:
    """Check if runtime contract enforcement is enabled.

    Set HEARTH_PHOENIX_CONTRACTS=off or 0 to disable for production performance.
    """
    val = os.environ.get("HEARTH_PHOENIX_CONTRACTS", "on").lower()
    return val not in ("off", "0", "false", "no")


class ContractViolationError(AssertionError):
    """Raised when a runtime contract is violated."""


class Contract:
    """Base class for contract-enforced components.

    Subclasses may use @precondition, @postcondition, and @invariant
    to declare runtime checks on their methods.
    """


# ---------------------------------------------------------------------------
# WorkerContract — operation-aware contract with @contract decorator support
# ---------------------------------------------------------------------------


class WorkerContract(Contract):
    """Contract base class for workers that declare per-operation guarantees.

    Subclasses use :func:`contract` to register methods against specific
    :class:`Operation` values.  The supervisor queries these registrations
    to build the per-operation guarantee matrix.

    Example::

        class MyWorker(WorkerContract):

            @contract(Operation.STOP)
            def graceful_shutdown(self, timeout: float = 5.0) -> bool:
                ...

            @contract(Operation.HEALTH_CHECK)
            def health(self) -> HealthResult:
                ...
    """

    _contracts: dict[Operation, Callable[..., Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Each subclass gets its own registry so siblings don't collide.
        cls._contracts = {}
        # Auto-populate from methods decorated with @contract
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name, None)
            if callable(attr) and hasattr(attr, "_contract_operation"):
                op = getattr(attr, "_contract_operation")
                cls._contracts[op] = attr

    def get_contract(self, operation: Operation) -> Callable[..., Any] | None:
        """Return the registered method for *operation*, or *None*.

        The returned callable is a bound method of *self*.
        """
        func = self._contracts.get(operation)
        if func is not None:
            return func.__get__(self, type(self))
        return None


def contract(operation: Operation) -> Callable[[F], F]:
    """Decorator that registers a method as the handler for *operation*.

    Must be used on methods of a :class:`WorkerContract` subclass.  The
    decorated method is stored in the class's ``_contracts`` registry.

    Raises :class:`TypeError` if *operation* is not an :class:`Operation`
    enum value.
    """
    if not isinstance(operation, Operation):
        raise TypeError(
            f"@contract argument must be an Operation enum value, got {operation!r}"
        )

    def decorator(func: F) -> F:
        # We store the registration eagerly at decoration time so that
        # verifiers can inspect the class without instantiating it.

        @functools.wraps(func)
        def wrapper(self: WorkerContract, *args: Any, **kwargs: Any) -> Any:
            return func(self, *args, **kwargs)

        wrapper._contract_operation = operation  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# VerificationReport — structured result of runtime contract verification
# ---------------------------------------------------------------------------


@dataclass
class VerificationReport:
    """Report produced by :class:`ContractVerifier.verify`."""

    worker_path: str
    worker_hash: str
    verified: dict[str, bool]
    """Operation label → True if the contract was verified in isolation."""

    errors: dict[str, str]
    """Operation label → error message for contracts that failed verification."""

    unverified_operations: list[str]
    """Operation labels that were declared but could not be verified."""

    matrix: dict[str, Any] = field(default_factory=dict)
    """Per-operation guarantee matrix after verification and downgrade."""

    downgraded: dict[str, Any] = field(default_factory=dict)
    """Operations that were downgraded after verification."""

    @property
    def all_verified(self) -> bool:
        """True when every declared contract passed verification."""
        return len(self.unverified_operations) == 0 and all(
            self.verified.values()
        )


# ---------------------------------------------------------------------------
# ContractVerifier — subprocess isolation testing of declared contracts
# ---------------------------------------------------------------------------


class ContractVerifier:
    """Tests each ``@contract``-decorated method in a subprocess.

    For each declared contract, a fresh Python subprocess imports the worker
    module, instantiates the :class:`WorkerContract` subclass, and calls the
    registered method.  If the method returns without raising, the contract
    is marked *verified*.

    Parameters:
        timeout: Per-contract subprocess timeout in seconds (default 5.0).
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def verify(self, worker_path: str | Path) -> VerificationReport:
        """Verify all ``@contract``-declared methods in *worker_path*.

        Returns a :class:`VerificationReport` with per-operation results.
        """
        worker_path = Path(worker_path).expanduser().resolve()
        worker_hash = self._hash_file(worker_path)

        # Discover declared operations by importing the module in a
        # subprocess and introspecting the WorkerContract subclass.
        declared = self._discover_operations(worker_path)
        if not declared:
            return VerificationReport(
                worker_path=str(worker_path),
                worker_hash=worker_hash,
                verified={},
                errors={},
                unverified_operations=[],
            )

        verified: dict[str, bool] = {}
        errors: dict[str, str] = {}
        unverified: list[str] = []

        for op_label in declared:
            ok, err = self._verify_single(worker_path, op_label)
            verified[op_label] = ok
            if not ok:
                errors[op_label] = err
                unverified.append(op_label)

        return VerificationReport(
            worker_path=str(worker_path),
            worker_hash=worker_hash,
            verified=verified,
            errors=errors,
            unverified_operations=unverified,
        )

    def _discover_operations(self, worker_path: Path) -> list[str]:
        """Run a subprocess to discover which Operation labels are declared."""
        probe = (
            "import importlib.util\n"
            f"spec = importlib.util.spec_from_file_location('_hp_contract_probe', {str(worker_path)!r})\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "from hearthphoenix.contracts import WorkerContract\n"
            "results = []\n"
            "for name in dir(mod):\n"
            "    obj = getattr(mod, name)\n"
            "    if isinstance(obj, type) and issubclass(obj, WorkerContract) and obj is not WorkerContract:\n"
            "        for op, method in obj._contracts.items():\n"
            "            results.append(op.label)\n"
            "print('\\n'.join(results))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                logger.warning(
                    "Operation discovery failed for %s: %s",
                    worker_path, proc.stderr.strip(),
                )
                return []
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        except subprocess.TimeoutExpired:
            logger.warning("Operation discovery timed out for %s", worker_path)
            return []

    def _verify_single(
        self, worker_path: Path, op_label: str
    ) -> tuple[bool, str]:
        """Verify a single declared operation in a subprocess.

        Returns ``(True, "")`` on success, ``(False, error_detail)`` on failure.
        """
        verify_script = (
            "import importlib.util\n"
            f"spec = importlib.util.spec_from_file_location('_hp_verify', {str(worker_path)!r})\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "from hearthphoenix.contracts import WorkerContract, Operation\n"
            f"target_op = None\n"
            f"for op in Operation:\n"
            f"    if op.label == {op_label!r}:\n"
            f"        target_op = op\n"
            f"        break\n"
            "if target_op is None:\n"
            "    raise SystemExit(f'Unknown operation: {op_label!r}')\n"
            "found = False\n"
            "for name in dir(mod):\n"
            "    obj = getattr(mod, name)\n"
            "    if isinstance(obj, type) and issubclass(obj, WorkerContract) and obj is not WorkerContract:\n"
            "        instance = obj()\n"
            "        method = instance.get_contract(target_op)\n"
            "        if method is not None:\n"
            "            method()\n"
            "            found = True\n"
            "            break\n"
            "if not found:\n"
            f"    raise SystemExit('No contract registered for {op_label}')\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", verify_script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode == 0:
                return True, ""
            else:
                err = proc.stderr.strip() or "subprocess exit code: {}".format(proc.returncode)
                return False, err
        except subprocess.TimeoutExpired:
            return False, "timeout"

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Return SHA-256 hex digest of file at *path*."""
        return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# VerifiedContractCache — persistent JSON cache of verification results
# ---------------------------------------------------------------------------


class VerifiedContractCache:
    """Persists verification results to disk so verified contracts are
    reused across supervisor restarts.

    Cache location: ``~/.hearthphoenix/<worker_hash>/verified_contracts.json``

    The cache key is the SHA-256 hash of the worker file contents.  If the
    file changes, the hash changes and the cache is invalidated.

    .. note::

        Only the worker file hash is used.  Imported module changes do
        NOT invalidate the cache.  This is a known limitation.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".hearthphoenix"
        self.base_dir = Path(base_dir)

    def _cache_path(self, worker_hash: str) -> Path:
        return self.base_dir / worker_hash / "verified_contracts.json"

    def read(self, worker_hash: str) -> dict[str, Any] | None:
        """Return cached verification data, or *None* if no cache exists."""
        path = self._cache_path(worker_hash)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read cache %s: %s", path, exc)
            return None

    def write(self, worker_hash: str, data: dict[str, Any]) -> None:
        """Atomically write *data* to the cache file."""
        path = self._cache_path(worker_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + rename
        fd, tmp = tempfile.mkstemp(
            suffix=".tmp", prefix="verified_", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def check(
        self, worker_hash: str, op_label: str
    ) -> tuple[bool, dict[str, Any] | None]:
        """Check if *op_label* is cached as verified for *worker_hash*.

        Returns ``(True, cache_data)`` if cached and verified,
        ``(False, None)`` otherwise.
        """
        data = self.read(worker_hash)
        if data is None:
            return False, None
        verified_ops = data.get("verified", {})
        if verified_ops.get(op_label) is True:
            return True, data
        return False, None


# ---------------------------------------------------------------------------
# Verification pipeline — verify → downgrade → cache
# ---------------------------------------------------------------------------


def run_contract_verification(
    worker_path: str | Path,
    *,
    cache: VerifiedContractCache | None = None,
    verifier: ContractVerifier | None = None,
    timeout: float = 5.0,
) -> VerificationReport:
    """Run the full contract verification pipeline for *worker_path*.

    1. Hash the worker file.
    2. Check cache for previously verified contracts.
    3. Verify uncached contracts via :class:`ContractVerifier`.
    4. Apply downgrade rules for any failed verifications.
    5. Persist verified state to cache.

    Returns a :class:`VerificationReport` with the final per-operation
    guarantee matrix.
    """
    from .guarantees import GuaranteeMatrix, DowngradeEngine, PerOperationGuarantee

    worker_path = Path(worker_path).expanduser().resolve()
    worker_hash = hashlib.sha256(worker_path.read_bytes()).hexdigest()

    if cache is None:
        cache = VerifiedContractCache()
    if verifier is None:
        verifier = ContractVerifier(timeout=timeout)

    # Step 1: Discover declared operations
    declared = verifier._discover_operations(worker_path)

    # Step 2: Check cache for already-verified contracts
    cached_data = cache.read(worker_hash)
    cached_verified: dict[str, bool] = {}
    if cached_data and cached_data.get("worker_hash") == worker_hash:
        cached_verified = cached_data.get("verified", {})

    # Step 3: Verify uncached declared ops
    verified: dict[str, bool] = dict(cached_verified)
    errors: dict[str, str] = dict(cached_data.get("errors", {}) if cached_data else {})

    for op_label in declared:
        if op_label in verified:
            continue  # already cached
        ok, err = verifier._verify_single(worker_path, op_label)
        verified[op_label] = ok
        if not ok:
            errors[op_label] = err

    # Step 4: Build baseline matrix from detected capabilities (empty set —
    # the matrix will be populated from capabilities scan elsewhere).
    # Here we start with all-UNKNOWN and let verified contracts override.
    matrix = {op: PerOperationGuarantee.UNKNOWN for op in (
        "start", "stop", "restart", "health_check",
        "hotswap", "rollback", "state_transfer",
    )}
    # Always-GUARANTEED operations
    matrix["start"] = PerOperationGuarantee.GUARANTEED
    matrix["rollback"] = PerOperationGuarantee.GUARANTEED

    # Verified contracts → GUARANTEED, unverified → BEST_EFFORT
    for op_label in declared:
        if verified.get(op_label):
            matrix[op_label] = PerOperationGuarantee.GUARANTEED
        else:
            matrix[op_label] = PerOperationGuarantee.BEST_EFFORT

    # Step 5: Apply downgrade rules for verification failures
    failures: dict[str, str] = {}
    for op_label, ok in verified.items():
        if not ok:
            err = errors.get(op_label, "")
            # Map error messages to downgrade reasons
            if "timeout" in err:
                if op_label == "health_check":
                    failures[op_label] = "health_timeout"
                else:
                    failures[op_label] = f"verification_failed:{err[:60]}"
            elif "500" in err or "Server error" in err:
                if op_label == "health_check":
                    failures[op_label] = "health_500"
                else:
                    failures[op_label] = f"verification_failed:{err[:60]}"
            elif "SIGTERM" in err or "sigterm" in err.lower():
                failures[op_label] = "sigterm_ignored"
            elif "serialize" in err.lower():
                failures[op_label] = "serialize_raises"
            elif "deserialize" in err.lower():
                failures[op_label] = "deserialize_raises"
            else:
                failures[op_label] = "verification_failed"

    downgrade_result = None
    if failures:
        try:
            downgrade_result = DowngradeEngine.apply(matrix, failures)
            matrix = downgrade_result.matrix
        except ValueError:
            pass  # DowngradeEngine.apply only accepts known keys

    # Step 6: Persist to cache
    unverified_ops = [op for op, ok in verified.items() if not ok]
    report = VerificationReport(
        worker_path=str(worker_path),
        worker_hash=worker_hash,
        verified=verified,
        errors=errors,
        unverified_operations=unverified_ops,
        matrix={k: v.name for k, v in matrix.items()},
        downgraded=(
            {k: (v[0].name, v[1].name) for k, v in downgrade_result.downgraded.items()}
            if downgrade_result
            else {}
        ),
    )

    cache_data: dict[str, Any] = {
        "worker_hash": worker_hash,
        "worker_path": str(worker_path),
        "verified": verified,
        "errors": errors,
        "matrix": report.matrix,
        "downgraded": report.downgraded,
    }
    if downgrade_result:
        cache_data["alerts"] = downgrade_result.alerts
    cache.write(worker_hash, cache_data)

    return report


def precondition(check: Callable[..., bool]) -> Callable[[F], F]:
    """Decorator that enforces a precondition before the wrapped function runs."""

    def decorator(func: F) -> F:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _contracts_enabled():
                return func(*args, **kwargs)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            if not check(*bound.args, **bound.kwargs):
                raise ContractViolationError(
                    f"Precondition violated for {func.__qualname__}"
                )
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def postcondition(check: Callable[..., bool]) -> Callable[[F], F]:
    """Decorator that enforces a postcondition after the wrapped function runs."""

    def decorator(func: F) -> F:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _contracts_enabled():
                return func(*args, **kwargs)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            result = func(*args, **kwargs)
            if not check(result, *bound.args, **bound.kwargs):
                raise ContractViolationError(
                    f"Postcondition violated for {func.__qualname__}"
                )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def invariant(check: Callable[..., bool]) -> Callable[[F], F]:
    """Decorator that enforces an invariant before and after the wrapped method.

    Expects the first positional argument to be ``self``.
    Cannot be used on staticmethods or classmethods.
    """

    def decorator(func: F) -> F:
        if isinstance(func, (staticmethod, classmethod)):
            raise TypeError(
                f"@invariant cannot be applied to staticmethod or classmethod ({func.__qualname__})"
            )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _contracts_enabled():
                return func(*args, **kwargs)
            if not args:
                raise ContractViolationError(
                    f"Invariant requires at least one positional argument for {func.__qualname__}"
                )
            self = args[0]
            if not check(self):
                raise ContractViolationError(
                    f"Invariant violated before {func.__qualname__}"
                )
            result = func(*args, **kwargs)
            if not check(self):
                raise ContractViolationError(
                    f"Invariant violated after {func.__qualname__}"
                )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator

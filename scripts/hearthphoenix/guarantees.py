"""Per-operation guarantee matrix and downgrade engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import Operation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PerOperationGuarantee — granular guarantee levels per operation
# ---------------------------------------------------------------------------


class PerOperationGuarantee(IntEnum):
    """Guarantee level for a single lifecycle operation.

    Ordered from strongest to weakest::

        GUARANTEED(3) > BEST_EFFORT(2) > NOT_SUPPORTED(0) > UNKNOWN(1)

    ``NOT_SUPPORTED`` is ordered below ``UNKNOWN`` because a confirmed
    *unsupported* result is worse than an untested assumption.
    """

    NOT_SUPPORTED = 0  # we know this will not work
    UNKNOWN = 1        # we have not checked yet
    BEST_EFFORT = 2    # we think this will work
    GUARANTEED = 3     # we can prove this will work

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}.{self.name}: {self.value}>"


# ---------------------------------------------------------------------------
# GuaranteeMatrix — compute per-operation guarantee from capabilities
# ---------------------------------------------------------------------------


class GuaranteeMatrix:
    """Computes a per-operation guarantee map from detected capabilities.

    The matrix encodes the rules from the Phase 2 design:

    * ``START`` and ``ROLLBACK`` are always GUARANTEED.
    * ``STOP`` / ``RESTART`` are GUARANTEED when SIGTERM_HANDLER is present,
      otherwise BEST_EFFORT.
    * ``HEALTH_CHECK`` / ``HOTSWAP`` are GUARANTEED when HEALTH_CHECK is
      present, otherwise UNKNOWN.
    * ``STATE_TRANSFER`` is GUARANTEED when STATE_SERIALIZATION is present,
      otherwise NOT_SUPPORTED.
    """

    # Operations that are always GUARANTEED regardless of capabilities
    _ALWAYS_GUARANTEED: set[str] = {"start", "rollback"}

    @staticmethod
    def compute(detected_capabilities: set[str]) -> dict[str, PerOperationGuarantee]:
        """Return a mapping of operation label → guarantee level.

        *detected_capabilities* is a set of capability name strings (the
        ``.name`` attributes of :class:`~hearthphoenix.capabilities.Capability`
        enum values).
        """
        caps = {c.upper() for c in detected_capabilities}
        result: dict[str, PerOperationGuarantee] = {}

        for op_name in ("start", "stop", "restart", "health_check",
                         "hotswap", "rollback", "state_transfer"):
            if op_name in GuaranteeMatrix._ALWAYS_GUARANTEED:
                result[op_name] = PerOperationGuarantee.GUARANTEED
            elif op_name in ("stop", "restart"):
                result[op_name] = (
                    PerOperationGuarantee.GUARANTEED
                    if "SIGTERM_HANDLER" in caps
                    else PerOperationGuarantee.BEST_EFFORT
                )
            elif op_name in ("health_check", "hotswap"):
                result[op_name] = (
                    PerOperationGuarantee.GUARANTEED
                    if "HEALTH_CHECK" in caps
                    else PerOperationGuarantee.UNKNOWN
                )
            elif op_name == "state_transfer":
                result[op_name] = (
                    PerOperationGuarantee.GUARANTEED
                    if "STATE_SERIALIZATION" in caps
                    else PerOperationGuarantee.NOT_SUPPORTED
                )

        return result


# ---------------------------------------------------------------------------
# DowngradeEngine — apply degradation rules on detected failures
# ---------------------------------------------------------------------------


@dataclass
class DowngradeResult:
    """The outcome of running the downgrade engine against a guarantee matrix."""

    matrix: dict[str, PerOperationGuarantee]
    """The guarantee matrix after all downgrade rules have been applied."""

    downgraded: dict[str, tuple[PerOperationGuarantee, PerOperationGuarantee]]
    """Mapping: operation label → (old_level, new_level) for every downgrade."""

    reasons: dict[str, str]
    """Mapping: operation label → human-readable reason for the downgrade."""

    alerts: list[str]
    """Alerts that should be surfaced to the operator (e.g. crash during transfer)."""


class DowngradeEngine:
    """Applies contract downgrade rules when runtime failures are detected.

    Each failure type maps to a specific operation and downgrade target:

    =============================== ==============================
    Detected failure                Downgrade action
    =============================== ==============================
    SIGTERM ignored                 ``stop`` → BEST_EFFORT
    Health timeout                  ``health_check`` → BEST_EFFORT
    Health 500 error                ``health_check`` → NOT_SUPPORTED
    serialize/deserialize raises    ``state_transfer`` → NOT_SUPPORTED
    Crash during state transfer     ``state_transfer`` → NOT_SUPPORTED + alert
    =============================== ==============================
    """

    @staticmethod
    def apply(
        matrix: dict[str, PerOperationGuarantee],
        failures: dict[str, str],
    ) -> DowngradeResult:
        """Apply downgrade rules to *matrix* based on *failures*.

        *failures* is a mapping of operation label → failure reason string.
        Supported keys: ``"stop"``, ``"health_check"``, ``"state_transfer"``.

        Raises :class:`ValueError` for an unknown failure key.
        """
        result_matrix = dict(matrix)
        downgraded: dict[str, tuple[PerOperationGuarantee, PerOperationGuarantee]] = {}
        reasons: dict[str, str] = {}
        alerts: list[str] = []

        _RULES = DowngradeEngine._downgrade_rules()
        for op_name, failure_reason in failures.items():
            if op_name not in _RULES:
                raise ValueError(
                    f"Unknown downgrade target: {op_name!r}. "
                    f"Valid keys: {sorted(_RULES)}"
                )
            handlers = _RULES[op_name]
            handler = handlers.get(failure_reason)
            if handler is None:
                logger.debug(
                    "No downgrade rule for op=%r reason=%r; skipping",
                    op_name, failure_reason,
                )
                continue

            old_level = result_matrix[op_name]
            new_level = handler(result_matrix, alerts)
            if new_level is not None and new_level != old_level:
                result_matrix[op_name] = new_level
                downgraded[op_name] = (old_level, new_level)
                reasons[op_name] = failure_reason
                logger.info(
                    "Downgraded %s: %s → %s (%s)",
                    op_name, old_level.name, new_level.name, failure_reason,
                )

        return DowngradeResult(
            matrix=result_matrix,
            downgraded=downgraded,
            reasons=reasons,
            alerts=alerts,
        )

    @staticmethod
    def _downgrade_rules() -> dict[
        str,
        dict[
            str,
            callable[  # noqa: E731
                [dict[str, PerOperationGuarantee], list[str]],
                PerOperationGuarantee | None,
            ],
        ],
    ]:
        """Return the downgrade rule table."""
        return {
            "stop": {
                "sigterm_ignored": lambda m, a:
                    PerOperationGuarantee.BEST_EFFORT,
            },
            "health_check": {
                "health_timeout": lambda m, a:
                    PerOperationGuarantee.BEST_EFFORT,
                "health_500": lambda m, a:
                    PerOperationGuarantee.NOT_SUPPORTED,
            },
            "state_transfer": {
                "serialize_raises": lambda m, a:
                    PerOperationGuarantee.NOT_SUPPORTED,
                "deserialize_raises": lambda m, a:
                    PerOperationGuarantee.NOT_SUPPORTED,
                "crash_during_transfer": lambda m, a: (
                    a.append(
                        "CRITICAL: Crash detected during state transfer — "
                        "state may be corrupted. Manual inspection required."
                    ),
                    PerOperationGuarantee.NOT_SUPPORTED,
                )[1],
            },
        }

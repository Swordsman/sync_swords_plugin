"""HearthPhoenix — Supervisor/worker harness with hotswap capability."""

from .capabilities import (
    Capability,
    CapabilityReport,
    CapabilityScanner,
    GuaranteeLevel,
)
from .contracts import (
    Contract,
    ContractVerifier,
    ContractViolationError,
    Operation,
    VerificationReport,
    VerifiedContractCache,
    WorkerContract,
    contract,
    invariant,
    postcondition,
    precondition,
    run_contract_verification,
)
from .guarantees import (
    DowngradeEngine,
    DowngradeResult,
    GuaranteeMatrix,
    PerOperationGuarantee,
)
from .health import CrashLoopDetector, HealthCheck, HealthResult, HealthStatus
from .bootstrap import Bootstrap, set_child_subreaper
from .bootstrap_handle import BootstrapError, BootstrapHandle
from .fleet import FleetManager
from .lifecycle import WorkerLifecycle
from .logging_config import auto_configure, configure_logging
from .snapshot import Snapshot, SnapshotManager
from .supervisor import Supervisor
from .wrappers import (
    CliAdapter,
    DaemonWrapper,
    FileHealthMonitor,
    HttpAdapter,
    InterfaceAdapter,
    InterfaceDirection,
    InterfaceRegistry,
    Message,
    MessageTranslator,
    PipeAdapter,
    SocketAdapter,
    TranslationEngine,
)

__version__ = "0.2.0"

__all__ = [
    "Capability",
    "CapabilityReport",
    "CapabilityScanner",
    "GuaranteeLevel",
    "CliAdapter",
    "Contract",
    "ContractVerifier",
    "ContractViolationError",
    "DaemonWrapper",
    "DowngradeEngine",
    "DowngradeResult",
    "FileHealthMonitor",
    "GuaranteeMatrix",
    "HttpAdapter",
    "InterfaceAdapter",
    "InterfaceDirection",
    "InterfaceRegistry",
    "Message",
    "MessageTranslator",
    "Operation",
    "PerOperationGuarantee",
    "PipeAdapter",
    "SocketAdapter",
    "Supervisor",
    "TranslationEngine",
    "VerificationReport",
    "VerifiedContractCache",
    "WorkerContract",
    "WorkerLifecycle",
    "SnapshotManager",
    "Snapshot",
    "HealthCheck",
    "HealthResult",
    "HealthStatus",
    "CrashLoopDetector",
    "configure_logging",
    "auto_configure",
    "contract",
    "precondition",
    "postcondition",
    "invariant",
    "run_contract_verification",
    "Bootstrap",
    "BootstrapHandle",
    "BootstrapError",
    "set_child_subreaper",
    "FleetManager",
]

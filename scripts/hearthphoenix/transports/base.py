"""Transport abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import Contract
from ..health import HealthResult


class Transport(Contract, ABC):
    """Pluggable parent↔child communication channel."""

    @abstractmethod
    def configure(self) -> dict[str, str]:
        """Return environment variables / CLI args for the child process."""
        ...

    def on_supervisor_start(self) -> None:
        """Parent-side initialization before the worker starts."""
        pass

    @abstractmethod
    def health_check(self, timeout: float) -> HealthResult:
        """Check whether the worker is healthy."""
        ...

    def shutdown(self, graceful: bool = True) -> None:
        """Request the worker to shut down."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the transport channel is active."""
        ...

    def on_supervisor_stop(self) -> None:
        """Parent-side cleanup after the worker stops."""
        pass

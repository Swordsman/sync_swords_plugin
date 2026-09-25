"""InterfaceAdapter abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..protocol import InterfaceDirection, Message
from ...health import HealthResult


class InterfaceAdapter(ABC):
    """A single protocol interface — can be frontend, backend, or both.

    Extends Transport-concepts for bidirectional, multi-protocol use.
    Adapters may operate in FRONTEND (listening for incoming callers),
    BACKEND (connecting to the daemon), or BIDIRECTIONAL mode.

    ``supports_passthrough`` means *skip structural transform* when the
    frontend and backend share the same protocol type — not "raw bytes".
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def configure(self) -> dict[str, str]:
        """Env vars for the daemon process (backend) or bind params (frontend)."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Bind/listen (frontend) or connect (backend)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Unbind/disconnect."""
        ...

    @abstractmethod
    def send(self, message: Message, timeout: float = 30.0) -> Message:
        """Send a message and return the response.

        Args:
            message: The canonical Message to send.
            timeout: Maximum seconds to wait for a response.  Exceeding this
                should result in a TimeoutError (or be normalised to an error
                Message by the TranslationEngine).

        Returns:
            The response Message.

        Raises:
            TimeoutError: If the backend does not respond within *timeout*.
            ConnectionError: If the adapter is not connected.
        """
        ...

    @abstractmethod
    def health_check(self, timeout: float) -> HealthResult:
        """Check whether the adapter (or the daemon behind it) is healthy."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the adapter channel is active."""
        ...

    @property
    @abstractmethod
    def direction(self) -> InterfaceDirection:
        """FRONTEND, BACKEND, or BIDIRECTIONAL."""
        ...

    @property
    def supports_passthrough(self) -> bool:
        """True if this adapter can operate without structural transformation.

        Passthrough still serializes/deserialises to/from Message — it only
        skips the MessageTranslator structural-transform step.
        """
        return False

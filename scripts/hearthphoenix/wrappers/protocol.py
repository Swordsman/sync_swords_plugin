"""Canonical Message type and InterfaceDirection enum for the translation layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Message:
    """Canonical message exchanged between adapters through the translation engine.

    All adapters serialize/deserialize to/from this type. The TranslationEngine
    routes instances between frontend and backend adapters.
    """

    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    version: int = 1


class InterfaceDirection(Enum):
    """Whether an adapter acts as a frontend, backend, or both."""

    FRONTEND = "frontend"
    BACKEND = "backend"
    BIDIRECTIONAL = "bidirectional"

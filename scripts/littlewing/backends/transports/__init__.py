"""Transport ABC and auto-loader.

Transports answer: where does data go and how does it get there?
Each transport is a .py file in this directory that subclasses Transport.
Registration is automatic via __init_subclass__.
"""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path


class Transport(ABC):
    """Abstract base for storage transports.

    Subclasses must set `name` as a class attribute and implement
    all abstract methods. Registration is automatic.
    """

    _registry: dict[str, type["Transport"]] = {}
    name: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        n = getattr(cls, "name", None)
        if n and not getattr(cls, "__abstractmethods__", None):
            cls._registry[n] = cls

    @abstractmethod
    def write(self, key: str, data: bytes) -> None:
        """Store data under key. Overwrites if key exists."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Retrieve data by key. Raises KeyError if missing."""

    @abstractmethod
    def list(self) -> list[str]:
        """Return all stored keys."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check whether key exists."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove key. No-op if missing."""

    @classmethod
    def get(cls, name: str) -> type["Transport"]:
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry)) or "(none)"
            raise KeyError(f"unknown transport {name!r}, available: {available}")
        return cls._registry[name]

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._registry.keys())


def _load_all():
    pkg_path = str(Path(__file__).parent)
    for finder, modname, ispkg in pkgutil.iter_modules([pkg_path]):
        if not modname.startswith("_"):
            importlib.import_module(f".{modname}", __package__)


_load_all()

"""Transform ABC and auto-loader.

Transforms answer: what happens to the data before storage / after retrieval?
Each transform is a .py file in this directory that subclasses Transform.
Registration is automatic via __init_subclass__.
"""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path


class Transform(ABC):
    """Abstract base for data transforms.

    Subclasses must set `name` as a class attribute and implement
    encode/decode. Registration is automatic.
    """

    _registry: dict[str, type["Transform"]] = {}
    name: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        n = getattr(cls, "name", None)
        if n and not getattr(cls, "__abstractmethods__", None):
            cls._registry[n] = cls

    @abstractmethod
    def encode(self, data: bytes) -> bytes:
        """Transform data before storage."""

    @abstractmethod
    def decode(self, data: bytes) -> bytes:
        """Reverse transform after retrieval."""

    @classmethod
    def get(cls, name: str) -> type["Transform"]:
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry)) or "(none)"
            raise KeyError(f"unknown transform {name!r}, available: {available}")
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

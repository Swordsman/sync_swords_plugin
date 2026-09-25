"""InterfaceRegistry — manages adapter lifecycle, toggle, and queue overflow policy."""

from __future__ import annotations

import logging
from typing import Any

from .protocol import InterfaceDirection, Message
from .queue import BoundedQueue
from .translation_engine import TranslationEngine

logger = logging.getLogger(__name__)


class InterfaceRegistry:
    """Manages all frontend/backend adapters and their enabled/disabled state.

    Coordinates start/stop lifecycle, toggle (enable/disable) at runtime,
    and wires the queue overflow policy into frontend adapters.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._frontends: dict[str, Any] = {}
        self._enabled: dict[str, bool] = {}
        self._queues: dict[str, BoundedQueue] = {}
        self._translation_engine: TranslationEngine | None = None

    def set_translation_engine(self, engine: TranslationEngine) -> None:
        """Set the translation engine used for routing."""
        self._translation_engine = engine

    def register(self, adapter: Any, queue_size: int = 100) -> None:
        """Register a frontend adapter with an optional bounded queue size."""
        name = adapter.name
        if name in self._frontends:
            raise KeyError(f"Adapter already registered: {name}")
        self._frontends[name] = adapter
        self._enabled[name] = True
        self._queues[name] = BoundedQueue(max_size=queue_size)

    def unregister(self, name: str) -> None:
        """Unregister a frontend adapter."""
        if name not in self._frontends:
            raise KeyError(f"Adapter not found: {name}")
        self._frontends[name].stop()
        del self._frontends[name]
        del self._enabled[name]
        del self._queues[name]

    def enable(self, name: str) -> None:
        """Enable a frontend adapter (start listening)."""
        if name not in self._frontends:
            raise KeyError(f"Adapter not found: {name}")
        if not self._enabled.get(name, False):
            adapter = self._frontends[name]
            if hasattr(adapter, "set_request_handler") and self._translation_engine:
                adapter.set_request_handler(
                    lambda msg, src=adapter: self._translation_engine.route(src, msg)
                )
            adapter.start()
            self._enabled[name] = True
            logger.info("Interface %s enabled", name)

    def disable(self, name: str) -> None:
        """Disable a frontend adapter (stop listening, release resources)."""
        if name not in self._frontends:
            raise KeyError(f"Adapter not found: {name}")
        if self._enabled.get(name, False):
            self._frontends[name].stop()
            self._enabled[name] = False
            self._queues[name].clear()
            logger.info("Interface %s disabled", name)

    def list_frontends(self) -> dict[str, bool]:
        """Return {name: enabled} dict of all registered frontends."""
        return {name: self._enabled.get(name, True) for name in self._frontends}

    def start_all(self) -> None:
        """Start backend first, then all enabled frontends."""
        logger.info("Starting all interfaces")
        self._backend.start()
        for name, adapter in self._frontends.items():
            if self._enabled.get(name, True):
                if hasattr(adapter, "set_request_handler") and self._translation_engine:
                    adapter.set_request_handler(
                        lambda msg, src=adapter: self._translation_engine.route(src, msg)
                    )
                adapter.start()
                logger.info("Interface %s started", name)

    def stop_all(self) -> None:
        """Stop frontends first, then backend."""
        logger.info("Stopping all interfaces")
        for name, adapter in self._frontends.items():
            try:
                adapter.stop()
            except Exception:
                logger.exception("Error stopping interface %s", name)
        try:
            self._backend.stop()
        except Exception:
            pass

    def enqueue_request(self, name: str, message: Message) -> Message | None:
        """Enqueue an incoming request from a frontend.

        Returns an error Message if the queue overflows, None otherwise.
        """
        queue = self._queues.get(name)
        if queue is None:
            return None
        if not queue.put(message):
            return Message(
                action="error",
                payload={"reason": "queue_overflow", "dropped": queue.overflow_count},
                metadata={"source": name, "error_code": "QUEUE_OVERFLOW"},
            )
        return None

    def get_queue(self, name: str) -> BoundedQueue | None:
        """Return the bounded queue for a frontend, or None."""
        return self._queues.get(name)

    @property
    def backend(self) -> Any:
        return self._backend

    @property
    def frontends(self) -> dict[str, Any]:
        return self._frontends

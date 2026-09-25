"""TranslationEngine and MessageTranslator — route & translate messages (final).

Supports all 4 adapter types: Socket, HTTP, CLI, Pipe.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..health import HealthResult, HealthStatus
from .protocol import InterfaceDirection, Message

logger = logging.getLogger(__name__)

# Default maximum message size (1 MB)
MAX_MESSAGE_SIZE = 1_048_576


# ── MessageTranslator ─────────────────────────────────────────────────


class MessageTranslator:
    """Converts between canonical Message objects and wire formats.

    Each adapter type registers its serialization/deserialization functions.
    """

    def __init__(self) -> None:
        self._to_message_registry: dict[str, Any] = {}
        self._from_message_registry: dict[str, Any] = {}
        # Structural Message->Message transforms keyed by (src_type, backend_type).
        # Empty until protocol translation is implemented; see translate().
        self._transforms: dict[tuple[str, str], Any] = {}

    def register(
        self,
        adapter_type: str,
        *,
        to_message: Any,
        from_message: Any,
    ) -> None:
        """Register conversion functions for an adapter type."""
        self._to_message_registry[adapter_type] = to_message
        self._from_message_registry[adapter_type] = from_message

    def to_message(self, adapter_type: str, raw_data: Any) -> Message:
        """Convert wire-format data to a canonical Message."""
        converter = self._to_message_registry.get(adapter_type)
        if converter is None:
            raise ValueError(f"No converter registered for adapter type: {adapter_type}")
        return converter(raw_data)

    def from_message(self, adapter_type: str, message: Message) -> Any:
        """Convert a canonical Message to wire-format data."""
        converter = self._from_message_registry.get(adapter_type)
        if converter is None:
            raise ValueError(f"No converter registered for adapter type: {adapter_type}")
        return converter(message)

    def register_transform(
        self, src_type: str, backend_type: str, transform: Any
    ) -> None:
        """Register a structural Message->Message transform for a protocol pair."""
        self._transforms[(src_type, backend_type)] = transform

    def translate(
        self, message: Message, src_type: str, backend_type: str
    ) -> Message:
        """Structurally translate a canonical Message for the backend protocol.

        Returns the message unchanged unless a transform has been registered
        for the (src_type, backend_type) pair. Protocol translation is a
        proposed-but-unimplemented feature; this is its extension point. The
        {action, payload} envelope is currently identical across protocols, so
        identity forwarding is correct until real transforms are registered.
        """
        transform = self._transforms.get((src_type, backend_type))
        if transform is None:
            return message
        return transform(message)


def _detect_adapter_type(adapter: Any) -> str:
    """Return a short type string for an adapter instance."""
    class_name = type(adapter).__name__.lower()
    if "socket" in class_name:
        return "socket"
    if "http" in class_name:
        return "http"
    if "cli" in class_name:
        return "cli"
    if "pipe" in class_name:
        return "pipe"
    return class_name


# ── Conversion functions for all 4 adapter types ──────────────────────


def _socket_to_message(raw: bytes | dict[str, Any]) -> Message:
    if isinstance(raw, dict):
        return Message(
            action=raw.get("action", ""),
            payload=raw.get("payload", {}),
            metadata=raw.get("metadata", {}),
        )
    data = json.loads(raw.decode("utf-8"))
    return Message(
        action=data.get("action", ""),
        payload=data.get("payload", {}),
        metadata=data.get("metadata", {}),
    )


def _socket_from_message(message: Message) -> bytes:
    return json.dumps({"action": message.action, "payload": message.payload}).encode("utf-8")


def _http_to_message(raw: dict[str, Any]) -> Message:
    """Convert an HTTP request/response dict to a Message."""
    return Message(
        action=raw.get("action", raw.get("method", "invoke")),
        payload=raw.get("payload", {}),
        metadata=raw.get("metadata", {}),
    )


def _http_from_message(message: Message) -> dict[str, Any]:
    """Convert a Message to an HTTP request/response dict."""
    return {"action": message.action, "payload": message.payload}


def _cli_to_message(raw: str | dict[str, Any]) -> Message:
    """Convert CLI wire format (JSON string or dict) to a Message."""
    if isinstance(raw, dict):
        return Message(
            action=raw.get("action", ""),
            payload=raw.get("payload", {}),
            metadata=raw.get("metadata", {}),
        )
    if raw.strip():
        data = json.loads(raw)
        return Message(
            action=data.get("action", ""),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )
    return Message(action="", payload={})


def _cli_from_message(message: Message) -> str:
    """Convert a Message to CLI wire format (JSON string)."""
    return json.dumps({"action": message.action, "payload": message.payload})


def _pipe_to_message(raw: bytes | dict[str, Any]) -> Message:
    """Convert Pipe wire format (JSON bytes or dict) to a Message."""
    if isinstance(raw, dict):
        return Message(
            action=raw.get("action", ""),
            payload=raw.get("payload", {}),
            metadata=raw.get("metadata", {}),
        )
    data = json.loads(raw.decode("utf-8"))
    return Message(
        action=data.get("action", ""),
        payload=data.get("payload", {}),
        metadata=data.get("metadata", {}),
    )


def _pipe_from_message(message: Message) -> bytes:
    """Convert a Message to Pipe wire format (JSON bytes with newline)."""
    return json.dumps({"action": message.action, "payload": message.payload}).encode("utf-8")


# ── TranslationEngine ─────────────────────────────────────────────────


class TranslationEngine:
    """Routes messages from frontend adapters to the backend adapter.

    Supports all frontend→backend combinations from the translation matrix.
    Detects passthrough compatibility (skip structural transform).
    Enforces 1 MB message-size limit. Handles timeouts and error propagation.
    """

    def __init__(
        self,
        backend: Any,
        frontends: dict[str, Any],
        translator: MessageTranslator | None = None,
    ) -> None:
        self._backend = backend
        self._frontends = frontends
        self._translator = translator or _build_default_translator()

    def route(self, source: Any, message: Message) -> Message:
        """Translate (if needed), forward to backend, translate response back.

        Args:
            source: The frontend adapter that received the message.
            message: The canonical Message from the frontend.

        Returns:
            The response Message from the backend, translated back to the
            frontend's format if needed.
        """
        # Message-size enforcement (1 MB default)
        payload_size = _estimate_message_size(message)
        if payload_size > MAX_MESSAGE_SIZE:
            logger.warning(
                "Message too large: %d bytes (max %d)", payload_size, MAX_MESSAGE_SIZE
            )
            return Message(
                action="error",
                payload={
                    "reason": "message_too_large",
                    "size_bytes": payload_size,
                    "max_bytes": MAX_MESSAGE_SIZE,
                },
                metadata={"source": "translation_engine", "error_code": "MESSAGE_TOO_LARGE"},
            )

        # Determine adapter types
        src_type = _detect_adapter_type(source)
        backend_type = _detect_adapter_type(self._backend)

        # Passthrough detection: same protocol type AND the source adapter
        # supports passthrough (skip structural transform).
        if src_type == backend_type and getattr(source, "supports_passthrough", False):
            return self._passthrough_route(source, message)

        # Translation path
        return self._translated_route(source, message, src_type, backend_type)

    def _passthrough_route(self, source: Any, message: Message) -> Message:
        """Fast path: skip structural transform when protocols match.

        Passthrough still crosses the Message boundary (the adapter
        serializes/deserializes to/from Message), but the MessageTranslator
        structural mapping step is skipped.
        """
        logger.debug("Passthrough route: %s -> %s", source.name, self._backend.name)
        return self._backend.send(message, timeout=30.0)

    def _translated_route(
        self, source: Any, message: Message, src_type: str, backend_type: str
    ) -> Message:
        """Forward the request to the backend, applying structural translation.

        Structural protocol translation (e.g. mapping an HTTP method+path to a
        backend ``action`` field) is a proposed feature that is not yet
        implemented — this method is its seam. Until a real Message->Message
        transform is registered for the (src_type, backend_type) pair, the
        canonical Message is forwarded unchanged: the {action, payload}
        envelope is currently identical on every protocol, and each adapter
        serializes the Message to its own wire format inside ``send()``.

        Note: do NOT reintroduce a from_message()->to_message() wire round-trip
        here. The adapters already self-serialize, and chaining one adapter's
        wire output into another's deserializer crashes on mismatched pairs
        (bytes vs str vs dict).
        """
        logger.debug("Translated route: %s (%s) -> %s (%s)",
                     source.name, src_type, self._backend.name, backend_type)
        translated = self._translator.translate(message, src_type, backend_type)
        return self._backend.send(translated, timeout=30.0)


def _build_default_translator() -> MessageTranslator:
    """Build a MessageTranslator pre-registered with all 4 adapter types."""
    translator = MessageTranslator()

    translator.register("socket", to_message=_socket_to_message, from_message=_socket_from_message)
    translator.register("http", to_message=_http_to_message, from_message=_http_from_message)
    translator.register("cli", to_message=_cli_to_message, from_message=_cli_from_message)
    translator.register("pipe", to_message=_pipe_to_message, from_message=_pipe_from_message)

    return translator


def _estimate_message_size(message: Message) -> int:
    """Estimate the byte size of a serialised Message."""
    return len(json.dumps({"action": message.action, "payload": message.payload}).encode("utf-8"))

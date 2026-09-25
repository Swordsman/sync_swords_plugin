"""Wrappers subpackage — interface translation layer for external daemons."""

from .daemon_wrapper import DaemonWrapper
from .health_monitor import FileHealthMonitor
from .interface_registry import InterfaceRegistry
from .protocol import InterfaceDirection, Message
from .translation_engine import MessageTranslator, TranslationEngine
from .adapters.base import InterfaceAdapter
from .adapters.cli_adapter import CliAdapter
from .adapters.http_adapter import HttpAdapter
from .adapters.pipe_adapter import PipeAdapter
from .adapters.socket_adapter import SocketAdapter

__all__ = [
    "CliAdapter",
    "DaemonWrapper",
    "FileHealthMonitor",
    "HttpAdapter",
    "InterfaceAdapter",
    "InterfaceDirection",
    "InterfaceRegistry",
    "Message",
    "MessageTranslator",
    "PipeAdapter",
    "SocketAdapter",
    "TranslationEngine",
]

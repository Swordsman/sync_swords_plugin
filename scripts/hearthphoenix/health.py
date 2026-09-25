"""Health-check utilities and crash-loop detection."""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from .contracts import Contract

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRASH_LOOP = "crash_loop"


@dataclass
class HealthResult:
    """Outcome of a single health-check invocation."""

    status: HealthStatus
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class HealthCheck(Contract, ABC):
    """Abstract health check that can be invoked against a transport."""

    @abstractmethod
    def check(self) -> HealthResult:
        ...


class CrashLoopDetector:
    """Sliding-window crash counter with escalation to unrecoverable."""

    def __init__(
        self,
        threshold: int = 3,
        window_seconds: float = 30.0,
        max_restarts: int = 10,
        restart_window_seconds: float = 300.0,
    ) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.max_restarts = max_restarts
        self.restart_window_seconds = restart_window_seconds
        self._crashes: deque[float] = deque()
        self._restarts: deque[float] = deque()
        self._lock = threading.Lock()

    def record_crash(self) -> bool:
        """Record a crash and return *True* if a crash loop is detected."""
        now = time.time()
        with self._lock:
            while self._crashes and (now - self._crashes[0]) > self.window_seconds:
                self._crashes.popleft()
            self._crashes.append(now)
            in_loop = len(self._crashes) >= self.threshold
            if in_loop:
                self._crashes.clear()
            return in_loop

    def record_restart(self) -> None:
        """Record a restart attempt for give-up detection."""
        now = time.time()
        with self._lock:
            while self._restarts and (now - self._restarts[0]) > self.restart_window_seconds:
                self._restarts.popleft()
            self._restarts.append(now)

    def give_up(self) -> bool:
        """Return True when max restarts within the restart window have been exceeded."""
        now = time.time()
        with self._lock:
            while self._restarts and (now - self._restarts[0]) > self.restart_window_seconds:
                self._restarts.popleft()
            return len(self._restarts) >= self.max_restarts

    def reset(self) -> None:
        """Clear all recorded crashes (e.g. after successful recovery)."""
        with self._lock:
            self._crashes.clear()
            self._restarts.clear()

    @property
    def crash_count(self) -> int:
        """Current number of crashes inside the window."""
        now = time.time()
        with self._lock:
            return sum(1 for t in self._crashes if (now - t) <= self.window_seconds)

    @property
    def restart_count(self) -> int:
        """Current number of restarts inside the restart window."""
        now = time.time()
        with self._lock:
            return sum(1 for t in self._restarts if (now - t) <= self.restart_window_seconds)

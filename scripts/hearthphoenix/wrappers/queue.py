"""Queue — bounded FIFO queue with overflow policy (drop oldest)."""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from .protocol import Message

logger = logging.getLogger(__name__)


class BoundedQueue:
    """Bounded FIFO queue with drop-oldest-on-overflow policy.

    When full, drops the oldest message and records an overflow counter.
    """

    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max_size
        self._queue: deque[Message] = deque()
        self._overflow_count = 0

    def put(self, message: Message) -> bool:
        """Add a message to the queue.

        Returns:
            True if the message was enqueued. False if an older message was
            dropped to make room (overflow).
        """
        dropped = False
        if len(self._queue) >= self._max_size:
            self._queue.popleft()
            self._overflow_count += 1
            dropped = True
        self._queue.append(message)
        if dropped:
            logger.warning(
                "Queue overflow: dropped oldest message (queue size %d)",
                self._max_size,
            )
        return not dropped

    def get(self, timeout: float = 0.1) -> Message | None:
        """Retrieve the oldest message, or None if empty within timeout."""
        try:
            return self._queue.popleft() if self._queue else None
        except IndexError:
            return None

    @property
    def size(self) -> int:
        return len(self._queue)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def clear(self) -> None:
        self._queue.clear()

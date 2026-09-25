"""Peer-mesh message types and participant registry.

Message types carried as `msg_type` on the existing `message_bus.Message`
dataclass. Payloads are plain dicts so no schema change to the bus is needed.

Shapes:
  register       payload={name, role, pane?, capabilities}
                   (pane empty/absent = hypervisor-native participant)
  deregister     payload={name}
  list_participants  payload={}            reply -> participants  payload={participants: [...]}
  send           payload={to, from, content}
  received       payload={from, content}
  broker_ready   payload={}                                       (broadcast on broker startup)
  heartbeat      payload={name}                                    (optional liveness signal)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from threading import Lock
from typing import Dict, List, Optional


MSG_REGISTER = "register"
MSG_DEREGISTER = "deregister"
MSG_LIST = "list_participants"
MSG_PARTICIPANTS = "participants"
MSG_SEND = "send"
MSG_RECEIVED = "received"
MSG_BROKER_READY = "broker_ready"
MSG_HEARTBEAT = "heartbeat"

DEFAULT_STALE_SECS = 60.0


@dataclass
class Participant:
    name: str
    role: str
    pane: str = ""
    capabilities: List[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class Registry:
    """In-memory participant registry with stale-entry GC.

    Thread-safe: broker's bus handlers may fire from the asyncio server
    coroutine while the GC task runs in the same loop, but the lock keeps
    external callers safe too.
    """

    def __init__(self, stale_secs: float = DEFAULT_STALE_SECS):
        self._by_name: Dict[str, Participant] = {}
        self._lock = Lock()
        self.stale_secs = stale_secs

    def register(self, name: str, role: str, pane: str = "",
                 capabilities: Optional[List[str]] = None) -> Participant:
        with self._lock:
            p = Participant(
                name=name,
                role=role,
                pane=pane or "",
                capabilities=list(capabilities or []),
            )
            self._by_name[name] = p
            return p

    def deregister(self, name: str) -> bool:
        with self._lock:
            return self._by_name.pop(name, None) is not None

    def touch(self, name: str) -> None:
        with self._lock:
            p = self._by_name.get(name)
            if p is not None:
                p.last_seen = time.time()

    def get(self, name: str) -> Optional[Participant]:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> List[Participant]:
        with self._lock:
            return list(self._by_name.values())

    def gc_stale(self, now: Optional[float] = None) -> List[str]:
        now = now if now is not None else time.time()
        dropped: List[str] = []
        with self._lock:
            for name, p in list(self._by_name.items()):
                if now - p.last_seen > self.stale_secs:
                    del self._by_name[name]
                    dropped.append(name)
        return dropped

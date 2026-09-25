#!/usr/bin/env python3
"""
ACP (Agent Communication Protocol) Handler

Protocol for inter-agent communication:
- Message passing between AI agents
- Session management
- Capability discovery
- Task delegation

Can run over stdio, sockets, or message queues.
"""

import json
import time
import uuid
from typing import Dict, List, Optional, Callable, Any, Set
from dataclasses import dataclass, asdict, field
from enum import Enum
from queue import Queue
import threading


class ACPMessageType(Enum):
    """ACP message types."""
    HELLO = "hello"           # Agent introduction
    BYE = "bye"               # Agent disconnecting
    PING = "ping"             # Keepalive
    PONG = "pong"             # Keepalive response
    
    REQUEST = "request"       # Request action/task
    RESPONSE = "response"     # Response to request
    NOTIFY = "notify"         # One-way notification
    
    CAPABILITY = "capability" # Advertise capabilities
    DISCOVER = "discover"     # Query capabilities
    
    CONTEXT = "context"       # Share context/data
    FORK = "fork"             # Spawn sub-session
    JOIN = "join"             # Join existing session


@dataclass
class ACPMessage:
    """An ACP protocol message."""
    msg_type: str
    src: str                          # Source agent ID
    dst: Optional[str] = None         # Destination (None = broadcast)
    session: Optional[str] = None     # Session ID
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    
    # Payload varies by message type
    payload: Dict = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.msg_type,
            "src": self.src,
            "dst": self.dst,
            "session": self.session,
            "id": self.msg_id,
            "timestamp": self.timestamp,
            "payload": self.payload
        })
    
    @classmethod
    def from_json(cls, line: str) -> 'ACPMessage':
        data = json.loads(line)
        return cls(
            msg_type=data["type"],
            src=data["src"],
            dst=data.get("dst"),
            session=data.get("session"),
            msg_id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", time.time()),
            payload=data.get("payload", {})
        )
    
    @classmethod
    def hello(cls, agent_id: str, capabilities: List[str]) -> 'ACPMessage':
        return cls(
            msg_type=ACPMessageType.HELLO.value,
            src=agent_id,
            payload={"capabilities": capabilities, "version": "0.1.0"}
        )
    
    @classmethod
    def request(cls, src: str, dst: str, action: str, params: Dict) -> 'ACPMessage':
        return cls(
            msg_type=ACPMessageType.REQUEST.value,
            src=src,
            dst=dst,
            payload={"action": action, "params": params}
        )
    
    @classmethod
    def response(cls, src: str, dst: str, request_id: str, 
                result: Any = None, error: str = None) -> 'ACPMessage':
        return cls(
            msg_type=ACPMessageType.RESPONSE.value,
            src=src,
            dst=dst,
            payload={"request_id": request_id, "result": result, "error": error}
        )


@dataclass
class AgentInfo:
    """Information about a connected agent."""
    agent_id: str
    capabilities: List[str]
    connected_at: float
    last_seen: float
    session: Optional[str] = None


class ACPBus:
    """
    Message bus for ACP communication.
    
    Routes messages between agents in the hypervisor environment.
    """
    
    def __init__(self, bus_id: str = "hypervisor"):
        self.bus_id = bus_id
        self.agents: Dict[str, AgentInfo] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # msg_type -> agent_ids
        self.message_log: List[ACPMessage] = []
        self._lock = threading.Lock()
        self._handlers: Dict[str, Callable] = {}
    
    def register_agent(self, agent_id: str, capabilities: List[str]) -> bool:
        """Register an agent on the bus."""
        with self._lock:
            if agent_id in self.agents:
                return False
            
            now = time.time()
            self.agents[agent_id] = AgentInfo(
                agent_id=agent_id,
                capabilities=capabilities,
                connected_at=now,
                last_seen=now
            )
            return True
    
    def unregister_agent(self, agent_id: str):
        """Unregister an agent."""
        with self._lock:
            self.agents.pop(agent_id, None)
            for subs in self.subscriptions.values():
                subs.discard(agent_id)
    
    def subscribe(self, agent_id: str, msg_type: str):
        """Subscribe an agent to message type."""
        with self._lock:
            if msg_type not in self.subscriptions:
                self.subscriptions[msg_type] = set()
            self.subscriptions[msg_type].add(agent_id)
    
    def publish(self, msg: ACPMessage) -> List[str]:
        """
        Publish a message to the bus.
        
        Returns list of recipient agent IDs.
        """
        with self._lock:
            self.message_log.append(msg)
            
            recipients = []
            
            if msg.dst:
                # Direct message
                if msg.dst in self.agents:
                    recipients = [msg.dst]
            else:
                # Broadcast to subscribers
                subs = self.subscriptions.get(msg.msg_type, set())
                recipients = list(subs)
            
            # Update last seen
            if msg.src in self.agents:
                self.agents[msg.src].last_seen = time.time()
            
            return recipients
    
    def get_agents_by_capability(self, capability: str) -> List[str]:
        """Find agents with given capability."""
        with self._lock:
            return [
                aid for aid, info in self.agents.items()
                if capability in info.capabilities
            ]
    
    def call(self, src: str, dst: str, action: str, params: Dict,
            timeout: float = 30.0) -> Optional[ACPMessage]:
        """
        Make synchronous request to another agent.
        
        Blocks until response or timeout.
        """
        request = ACPMessage.request(src, dst, action, params)
        
        # Publish request
        self.publish(request)
        
        # Wait for response
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                for msg in reversed(self.message_log):
                    if (msg.msg_type == ACPMessageType.RESPONSE.value and
                        msg.payload.get("request_id") == request.msg_id and
                        msg.dst == src):
                        return msg
            time.sleep(0.1)
        
        return None  # Timeout


class ACPHandler:
    """
    Handle ACP protocol for an agent.
    
    Connects to ACP bus and handles message routing.
    """
    
    def __init__(self, agent_id: str, bus: Optional[ACPBus] = None):
        self.agent_id = agent_id
        self.bus = bus or ACPBus()
        self.capabilities: List[str] = []
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._inbox: Queue = Queue()
        self._thread: Optional[threading.Thread] = None
    
    def add_capability(self, name: str, handler: Callable):
        """Add a capability and its handler."""
        self.capabilities.append(name)
        self._handlers[name] = handler
    
    def start(self):
        """Start handling ACP messages."""
        # Register with bus
        self.bus.register_agent(self.agent_id, self.capabilities)
        
        # Subscribe to message types we handle
        self.bus.subscribe(self.agent_id, ACPMessageType.REQUEST.value)
        self.bus.subscribe(self.agent_id, ACPMessageType.DISCOVER.value)
        
        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop handling messages."""
        self._running = False
        self.bus.unregister_agent(self.agent_id)
        if self._thread:
            self._thread.join(timeout=1)
    
    def _message_loop(self):
        """Background thread to process incoming messages."""
        while self._running:
            # Check for messages addressed to us
            # In real impl, this would poll from transport
            time.sleep(0.1)
    
    def send(self, msg: ACPMessage):
        """Send a message to the bus."""
        msg.src = self.agent_id
        self.bus.publish(msg)
    
    def request(self, dst: str, action: str, params: Dict,
               timeout: float = 30.0) -> Optional[Any]:
        """Make request to another agent."""
        response = self.bus.call(self.agent_id, dst, action, params, timeout)
        if response and not response.payload.get("error"):
            return response.payload.get("result")
        return None
    
    def discover(self, capability: Optional[str] = None) -> List[AgentInfo]:
        """Discover agents with optional capability filter."""
        if capability:
            agent_ids = self.bus.get_agents_by_capability(capability)
        else:
            agent_ids = list(self.bus.agents.keys())
        
        return [self.bus.agents[aid] for aid in agent_ids]


# Example: Hypervisor MCP resources exposed via ACP
HYPERVISOR_CAPABILITIES = [
    "hypervisor.status",
    "hypervisor.logs",
    "hypervisor.quota",
    "hypervisor.snapshot",
    "hypervisor.rollback",
]

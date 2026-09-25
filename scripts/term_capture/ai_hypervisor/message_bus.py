#!/usr/bin/env python3
"""
Async Message Bus for Multi-Agent Communication.

Non-blocking, event-driven message passing between agents using:
- Unix domain sockets (fast, local)
- Message queues with async I/O
- Event callbacks for real-time response
"""

import asyncio
import json
import os
import socket
import threading
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import queue


@dataclass
class Message:
    """A message between agents."""
    msg_id: str
    src: str
    dst: str  # "broadcast" or specific agent ID
    msg_type: str
    payload: Any
    timestamp: str
    
    @classmethod
    def create(cls, src: str, dst: str, msg_type: str, payload: Any) -> 'Message':
        import uuid
        return cls(
            msg_id=str(uuid.uuid4())[:8],
            src=src,
            dst=dst,
            msg_type=msg_type,
            payload=payload,
            timestamp=datetime.now().isoformat()
        )
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, data: str) -> 'Message':
        return cls(**json.loads(data))


class AsyncMessageBus:
    """
    Async message bus for agent communication.
    
    Uses Unix domain sockets for IPC with asyncio.
    """
    
    def __init__(self, socket_path: Path, agent_id: str):
        self.socket_path = socket_path
        self.agent_id = agent_id
        self.handlers: Dict[str, List[Callable]] = {}
        self.message_log: List[Message] = []
        self.running = False
        
        self._server = None
        self._connections: List[socket.socket] = []
        self._lock = threading.Lock()
        self._client_writers: set[asyncio.StreamWriter] = set()
    
    def register_handler(self, msg_type: str, handler: Callable[[Message], None]):
        """Register a handler for message type."""
        if msg_type not in self.handlers:
            self.handlers[msg_type] = []
        self.handlers[msg_type].append(handler)
    
    def send(self, msg: Message):
        """Send message to bus."""
        with self._lock:
            self.message_log.append(msg)
        
        # Notify handlers
        if msg.msg_type in self.handlers:
            for handler in self.handlers[msg.msg_type]:
                try:
                    handler(msg)
                except Exception as e:
                    print(f"Handler error: {e}")
        
        # Also notify wildcard handlers
        if '*' in self.handlers:
            for handler in self.handlers['*']:
                try:
                    handler(msg)
                except:
                    pass
        
        # Broadcast to connected clients
        if self._client_writers:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._broadcast(msg))
            except RuntimeError:
                pass  # No event loop running, skip broadcast
    
    async def _broadcast(self, msg: Message):
        """Broadcast a framed message to all connected writers."""
        data = msg.to_json().encode()
        frame = len(data).to_bytes(4, 'big') + data
        dead: List[asyncio.StreamWriter] = []
        for writer in list(self._client_writers):
            try:
                writer.write(frame)
                await writer.drain()
            except Exception:
                dead.append(writer)
        for writer in dead:
            self._client_writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass
    
    async def start_server(self):
        """Start async message server."""
        self.running = True
        
        # Remove old socket
        if self.socket_path.exists():
            self.socket_path.unlink()
        
        # Create Unix socket server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path)
        )
        
        print(f"[Bus] Server started on {self.socket_path}")
        
        async with self._server:
            await self._server.serve_forever()
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming client connection."""
        addr = writer.get_extra_info('peername')
        print(f"[Bus] Client connected: {addr}")
        self._client_writers.add(writer)
        
        try:
            while self.running:
                # Read message length (4 bytes)
                length_data = await reader.read(4)
                if not length_data:
                    break
                
                msg_len = int.from_bytes(length_data, 'big')
                
                # Read message
                msg_data = await reader.readexactly(msg_len)
                msg = Message.from_json(msg_data.decode())
                
                # Process message
                self.send(msg)
                
                # Send framed ack
                ack = Message.create(
                    src=self.agent_id,
                    dst=msg.src,
                    msg_type='_ack',
                    payload={'ack_for': msg.msg_id}
                )
                ack_data = ack.to_json().encode()
                writer.write(len(ack_data).to_bytes(4, 'big'))
                writer.write(ack_data)
                await writer.drain()
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Bus] Client error: {e}")
        finally:
            self._client_writers.discard(writer)
            writer.close()
            await writer.wait_closed()
    
    async def connect_and_send(self, msg: Message):
        """Connect to bus and send message."""
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
            
            # Send message
            data = msg.to_json().encode()
            writer.write(len(data).to_bytes(4, 'big'))
            writer.write(data)
            await writer.drain()
            
            # Wait for framed ack
            length_data = await reader.read(4)
            if not length_data:
                writer.close()
                await writer.wait_closed()
                return False
            
            msg_len = int.from_bytes(length_data, 'big')
            ack_data = await reader.readexactly(msg_len)
            ack_msg = Message.from_json(ack_data.decode())
            
            writer.close()
            await writer.wait_closed()
            
            return ack_msg.msg_type == '_ack'
        except Exception as e:
            print(f"[Bus] Send failed: {e}")
            return False
    
    def stop(self):
        """Stop server."""
        self.running = False
        if self._server:
            self._server.close()


class BusClient:
    """
    Bidirectional client for the AsyncMessageBus.
    
    Maintains a persistent Unix socket connection and dispatches
    received messages to registered handlers.
    """
    
    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._handlers: Dict[str, List[Callable[[Message], None]]] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._connected = False
    
    async def connect(self, socket_path: Path):
        """Open a persistent connection to the bus server."""
        self._reader, self._writer = await asyncio.open_unix_connection(str(socket_path))
        self._connected = True
        self._read_task = asyncio.create_task(self._read_loop())
    
    def register_handler(self, msg_type: str, handler: Callable[[Message], None]):
        """Register a handler for message type."""
        if msg_type not in self._handlers:
            self._handlers[msg_type] = []
        self._handlers[msg_type].append(handler)
    
    async def send(self, msg: Message):
        """Send a framed message to the server."""
        if not self._connected or self._writer is None:
            raise ConnectionError("BusClient is not connected")
        data = msg.to_json().encode()
        self._writer.write(len(data).to_bytes(4, 'big'))
        self._writer.write(data)
        await self._writer.drain()
    
    async def _read_loop(self):
        """Background task: read and dispatch messages from the server."""
        try:
            while self._connected:
                length_data = await self._reader.read(4)
                if not length_data:
                    break
                
                msg_len = int.from_bytes(length_data, 'big')
                msg_data = await self._reader.readexactly(msg_len)
                msg = Message.from_json(msg_data.decode())
                
                if msg.msg_type == '_ack':
                    continue
                
                # Dispatch to typed handlers
                if msg.msg_type in self._handlers:
                    for handler in self._handlers[msg.msg_type]:
                        try:
                            handler(msg)
                        except Exception as e:
                            print(f"BusClient handler error: {e}")
                
                # Dispatch to wildcard handlers
                if '*' in self._handlers:
                    for handler in self._handlers['*']:
                        try:
                            handler(msg)
                        except Exception as e:
                            print(f"BusClient wildcard handler error: {e}")
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"BusClient read error: {e}")
        finally:
            self._connected = False
    
    async def disconnect(self):
        """Close the connection cleanly."""
        self._connected = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        self._reader = None
        self._writer = None


class AgentChannel:
    """
    Communication channel for an agent.
    
    Provides send/receive interface on top of message bus.
    """
    
    def __init__(self, agent_id: str, bus: AsyncMessageBus):
        self.agent_id = agent_id
        self.bus = bus
        self.inbox: queue.Queue = queue.Queue()
        self.pending_responses: Dict[str, queue.Queue] = {}
        
        # Register for all messages
        self.bus.register_handler('*', self._on_message)
    
    def _on_message(self, msg: Message):
        """Handle incoming message."""
        # Filter for this agent
        if msg.dst != 'broadcast' and msg.dst != self.agent_id:
            return
        
        # Check if response to pending request
        if msg.msg_type == 'response' and msg.payload.get('in_reply_to'):
            reply_id = msg.payload['in_reply_to']
            if reply_id in self.pending_responses:
                self.pending_responses[reply_id].put(msg)
                return
        
        # Add to general inbox
        self.inbox.put(msg)
    
    def send(self, dst: str, msg_type: str, payload: Any) -> str:
        """Send message (non-blocking)."""
        msg = Message.create(
            src=self.agent_id,
            dst=dst,
            msg_type=msg_type,
            payload=payload
        )
        
        # Send via bus
        asyncio.create_task(self.bus.connect_and_send(msg))
        
        return msg.msg_id
    
    def send_sync(self, dst: str, msg_type: str, payload: Any, timeout: float = 30.0) -> Optional[Message]:
        """Send and wait for response (blocking)."""
        msg_id = self.send(dst, msg_type, payload)
        
        # Create response queue
        response_q = queue.Queue()
        self.pending_responses[msg_id] = response_q
        
        try:
            # Wait for response
            response = response_q.get(timeout=timeout)
            return response
        except queue.Empty:
            return None
        finally:
            del self.pending_responses[msg_id]
    
    def receive(self, timeout: float = None) -> Optional[Message]:
        """Receive message (blocking with timeout)."""
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def receive_nowait(self) -> Optional[Message]:
        """Receive message (non-blocking)."""
        try:
            return self.inbox.get_nowait()
        except queue.Empty:
            return None


# High-level cooperation framework

class CooperativeTask:
    """
    A task worked on cooperatively by multiple agents.
    """
    
    def __init__(self, task_id: str, description: str):
        self.task_id = task_id
        self.description = description
        self.iterations: List[Dict] = []
        self.current_iteration = 0
        self.max_iterations = 20
        
        self.state: Dict[str, Any] = {}
        self.files_created: List[str] = []
    
    def add_iteration(self, agent_id: str, action: str, result: str):
        """Add an iteration to the task."""
        self.current_iteration += 1
        self.iterations.append({
            'iteration': self.current_iteration,
            'agent': agent_id,
            'action': action,
            'result': result[:500],
            'timestamp': datetime.now().isoformat()
        })
    
    def is_complete(self) -> bool:
        """Check if task is complete."""
        return self.current_iteration >= self.max_iterations
    
    def to_dict(self) -> Dict:
        return {
            'task_id': self.task_id,
            'description': self.description,
            'iterations': self.iterations,
            'current_iteration': self.current_iteration,
            'max_iterations': self.max_iterations,
            'state': self.state,
            'files_created': self.files_created
        }


class CooperativeAgent:
    """
    An agent that can participate in cooperative tasks.
    """
    
    def __init__(self, agent_id: str, bus: AsyncMessageBus):
        self.agent_id = agent_id
        self.channel = AgentChannel(agent_id, bus)
        self.capabilities: List[str] = []
        self.current_task: Optional[CooperativeTask] = None
    
    def register_capability(self, name: str, handler: Callable):
        """Register a capability."""
        self.capabilities.append(name)
        self.channel.bus.register_handler(f'capability:{name}', handler)
    
    def join_task(self, task: CooperativeTask):
        """Join a cooperative task."""
        self.current_task = task
    
    def propose_action(self, action: str, result: str = ""):
        """Propose an action to the group."""
        if self.current_task:
            self.current_task.add_iteration(self.agent_id, action, result)
        
        # Broadcast to other agents
        self.channel.send('broadcast', 'action_proposed', {
            'agent': self.agent_id,
            'action': action,
            'task_id': self.current_task.task_id if self.current_task else None
        })


# Example usage for multi-agent cooperation

async def example_cooperation():
    """Example of async multi-agent cooperation."""
    
    # Create message bus
    socket_path = Path('/tmp/ai_coop_bus.sock')
    bus = AsyncMessageBus(socket_path, 'coordinator')
    
    # Start bus server in background
    server_task = asyncio.create_task(bus.start_server())
    
    # Wait for server to start
    await asyncio.sleep(0.5)
    
    # Create agents
    agent_a = CooperativeAgent('agent_a', bus)
    agent_b = CooperativeAgent('agent_b', bus)
    
    # Create shared task
    task = CooperativeTask(
        'website_build',
        'Build a multi-page portfolio website'
    )
    
    agent_a.join_task(task)
    agent_b.join_task(task)
    
    print("=" * 60)
    print("ASYNC MULTI-AGENT COOPERATION")
    print("=" * 60)
    print()
    
    # Cooperation loop
    for i in range(1, 21):
        print(f"\n--- Iteration {i}/20 ---")
        
        # Agent A proposes action
        actions = [
            "Create project structure",
            "Add HTML boilerplate",
            "Design CSS system",
            "Build navigation",
            "Create hero section",
            "Add content pages",
            "Implement responsive design",
            "Add interactivity",
            "Optimize performance",
            "Final review"
        ]
        
        action = actions[min(i-1, len(actions)-1)]
        
        agent_a.propose_action(action, f"Working on {action}")
        
        # Agent B responds (simulated)
        await asyncio.sleep(0.1)
        
        agent_b.propose_action(f"Acknowledge: {action}", f"Completed {action}")
        
        print(f"[Agent A] Proposed: {action}")
        print(f"[Agent B] Responded: Completed {action}")
    
    print("\n" + "=" * 60)
    print("COOPERATION COMPLETE")
    print("=" * 60)
    print(f"\nTotal iterations: {task.current_iteration}")
    
    # Stop server
    bus.stop()
    server_task.cancel()
    
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == '__main__':
    asyncio.run(example_cooperation())

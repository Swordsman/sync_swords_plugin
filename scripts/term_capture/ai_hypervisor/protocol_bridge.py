#!/usr/bin/env python3
"""
Protocol Bridge - Connects AI tool protocols to hypervisor.

Handles:
- MCP (Model Context Protocol) - JSON-RPC over stdio
- ACP (Agent Communication Protocol) - REST/HTTP or message bus
- Custom/vendor-specific protocols

Acts as a transparent proxy that can intercept, log, and modify
protocol messages between AI tool and external services.
"""

import json
import os
import sys
import threading
from typing import Dict, Optional, Callable, Any, List
from dataclasses import dataclass
from queue import Queue
import select

try:
    from .protocols.mcp import MCPHandler, MCPMessage
    from .protocols.acp import ACPHandler, ACPMessage
except ImportError:
    from protocols.mcp import MCPHandler, MCPMessage
    from protocols.acp import ACPHandler, ACPMessage


@dataclass
class ProtocolEvent:
    """A captured protocol event."""
    protocol: str  # 'mcp', 'acp', etc
    direction: str  # 'in', 'out'
    message: Any
    timestamp: float
    size_bytes: int


class ProtocolBridge:
    """
    Bridge between AI tool and its protocols.
    
    Intercepts stdio and socket traffic to:
    - Parse protocol messages
    - Log for analysis
    - Apply transformations
    - Enforce quotas/policies
    """
    
    def __init__(self):
        self.mcp = MCPHandler()
        self.acp: Optional[ACPHandler] = None
        
        self.event_log: List[ProtocolEvent] = []
        self.event_callbacks: List[Callable[[ProtocolEvent], None]] = []
        
        # Message queues for async handling
        self.mcp_in_queue: Queue = Queue()
        self.mcp_out_queue: Queue = Queue()
        
        self._running = False
        self._threads: List[threading.Thread] = []
        
        # Buffers for PTY byte-stream processing
        self._pty_input_buffer = b''
        self._pty_output_buffer = b''
    
    def add_event_callback(self, callback: Callable[[ProtocolEvent], None]):
        """Register callback for protocol events."""
        self.event_callbacks.append(callback)
    
    def intercept_stdio(self, fd_in: int, fd_out: int) -> tuple:
        """
        Intercept stdio for protocol handling.
        
        Returns (read_fd, write_fd) that should replace original fds
        for the intercepted process.
        """
        # Pipe for stdin path: we write processed data -> tool_reads_from_new_in
        tool_read_fd, our_write_fd = os.pipe()
        
        # Pipe for stdout path: tool writes to new_out -> we read from our_read_fd
        our_read_fd, tool_write_fd = os.pipe()
        
        # Start interception thread
        t = threading.Thread(
            target=self._stdio_intercept_loop,
            args=(fd_in, fd_out, our_write_fd, our_read_fd),
            daemon=True
        )
        t.start()
        self._threads.append(t)
        
        return tool_read_fd, tool_write_fd
    
    def _stdio_intercept_loop(self, real_in: int, real_out: int, 
                              our_write_fd: int, our_read_fd: int):
        """Background thread to intercept stdio protocol traffic."""
        while self._running:
            readable, _, _ = select.select([real_in, our_read_fd], [], [], 0.1)
            
            for fd in readable:
                if fd == real_in:
                    # Data from real stdin -> parse and forward to tool
                    try:
                        data = os.read(real_in, 4096)
                    except OSError:
                        continue
                    
                    if not data:
                        continue
                    
                    modified = self._process_input_data(data)
                    try:
                        os.write(our_write_fd, modified)
                    except OSError:
                        pass
                
                elif fd == our_read_fd:
                    # Data from tool (its stdout) -> parse and forward to real stdout
                    try:
                        data = os.read(our_read_fd, 4096)
                    except OSError:
                        continue
                    
                    if not data:
                        continue
                    
                    modified = self._process_output_data(data)
                    try:
                        os.write(real_out, modified)
                    except OSError:
                        pass
    
    def _process_input_data(self, data: bytes) -> bytes:
        """Process data going toward the tool (stdin direction)."""
        self._pty_input_buffer += data
        output = b''
        
        while b'\n' in self._pty_input_buffer:
            line, sep, self._pty_input_buffer = self._pty_input_buffer.partition(b'\n')
            modified = self._handle_incoming(line)
            output += modified + sep
        
        return output
    
    def _process_output_data(self, data: bytes) -> bytes:
        """Process data coming from the tool (stdout direction)."""
        self._pty_output_buffer += data
        output = b''
        
        while b'\n' in self._pty_output_buffer:
            line, sep, self._pty_output_buffer = self._pty_output_buffer.partition(b'\n')
            modified = self._handle_outgoing(line)
            output += modified + sep
        
        return output
    
    def process_pty_input(self, data: bytes) -> bytes:
        """
        Process data being sent to a PTY (input to the AI tool).
        
        This is the synchronous API for PTY layer integration.
        PTYLayer should call this on data before writing to master_fd.
        """
        return self._process_input_data(data)
    
    def process_pty_output(self, data: bytes) -> bytes:
        """
        Process data being read from a PTY (output from the AI tool).
        
        This is the synchronous API for PTY layer integration.
        PTYLayer should call this on data read from master_fd before
        writing to stdout or log files.
        """
        return self._process_output_data(data)
    
    def attach_to_pty_layer(self, pty_layer):
        """
        Wire this ProtocolBridge into a PTYLayer instance.
        
        Patches the PTYLayer's write() method to intercept input,
        and installs an on_output callback to intercept output.
        """
        original_write = pty_layer.write
        
        def wrapped_write(data: bytes):
            processed = self.process_pty_input(data)
            if processed:
                original_write(processed)
        
        pty_layer.write = wrapped_write
        
        # Intercept output by chaining callbacks
        original_on_output = getattr(pty_layer, 'on_output', None)
        
        def wrapped_on_output(data: str, is_input: bool):
            # Note: PTYLayer passes decoded strings to on_output.
            # We intercept at the byte level in the capture loop instead,
            # but for string-level callbacks we just pass through.
            if original_on_output:
                original_on_output(data, is_input)
        
        pty_layer.on_output = wrapped_on_output
    
    def _handle_incoming(self, line: bytes) -> bytes:
        """Handle message from tool (stdin)."""
        try:
            msg = json.loads(line)
            
            # Detect protocol type
            if 'jsonrpc' in msg:
                # MCP message
                event = ProtocolEvent(
                    protocol='mcp',
                    direction='in',
                    message=msg,
                    timestamp=__import__('time').time(),
                    size_bytes=len(line)
                )
                self._emit_event(event)
                
                # Process through MCP handler
                modified = self.mcp.intercept_stdin(line.decode())
                if modified is not None:
                    return modified.encode()
        
        except json.JSONDecodeError:
            pass  # Not JSON, pass through
        
        return line
    
    def _handle_outgoing(self, line: bytes) -> bytes:
        """Handle message to tool (stdout)."""
        try:
            msg = json.loads(line)
            
            if 'jsonrpc' in msg:
                event = ProtocolEvent(
                    protocol='mcp',
                    direction='out',
                    message=msg,
                    timestamp=__import__('time').time(),
                    size_bytes=len(line)
                )
                self._emit_event(event)
                
                modified = self.mcp.intercept_stdout(line.decode())
                if modified is not None:
                    return modified.encode()
        
        except json.JSONDecodeError:
            pass
        
        return line
    
    def _emit_event(self, event: ProtocolEvent):
        """Emit protocol event to callbacks."""
        self.event_log.append(event)
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception:
                pass
    
    def get_mcp_stats(self) -> Dict:
        """Get MCP protocol statistics."""
        mcp_events = [e for e in self.event_log if e.protocol == 'mcp']
        
        requests = [e for e in mcp_events 
                   if e.direction == 'in' and 'method' in e.message]
        responses = [e for e in mcp_events 
                    if e.direction == 'out' and 'result' in e.message]
        
        return {
            'total_messages': len(mcp_events),
            'requests': len(requests),
            'responses': len(responses),
            'bytes_transferred': sum(e.size_bytes for e in mcp_events),
            'methods_called': self._extract_methods(requests)
        }
    
    def _extract_methods(self, events: List[ProtocolEvent]) -> Dict[str, int]:
        """Count method calls from request events."""
        counts = {}
        for e in events:
            method = e.message.get('method', 'unknown')
            counts[method] = counts.get(method, 0) + 1
        return counts
    
    def start(self):
        """Start protocol bridge."""
        self._running = True
    
    def stop(self):
        """Stop protocol bridge."""
        self._running = False
        for t in self._threads:
            t.join(timeout=1)


class HypervisorMCPServer:
    """
    MCP Server that exposes hypervisor capabilities.
    
    Allows AI tools to query hypervisor state via MCP protocol.
    """
    
    def __init__(self, hypervisor):
        self.hypervisor = hypervisor
        self.server = None
        self._thread: Optional[threading.Thread] = None
    
    def start(self, transport: str = 'stdio'):
        """Start MCP server."""
        try:
            from .protocols.mcp import MCPServer
        except ImportError:
            from protocols.mcp import MCPServer
        
        self.server = MCPServer(name="ai-hypervisor")
        
        # Register resources
        self.server.register_resource(
            "hypervisor://status",
            self._get_status
        )
        
        self.server.register_resource(
            "hypervisor://stats",
            self._get_stats
        )
        
        # Register tools
        self.server.register_tool(
            "get_usage",
            self._tool_get_usage,
            description="Get current usage statistics",
            schema={"type": "object", "properties": {}}
        )
        
        if transport == 'stdio':
            self._thread = threading.Thread(
                target=self.server.run_stdio,
                daemon=True
            )
            self._thread.start()
    
    def _get_status(self) -> str:
        """Resource: Get hypervisor status."""
        status = self.hypervisor.get_status()
        return json.dumps(status, indent=2)
    
    def _get_stats(self) -> str:
        """Resource: Get usage statistics."""
        return json.dumps(self.hypervisor.stats.to_dict(), indent=2)
    
    def _tool_get_usage(self) -> str:
        """Tool: Get usage."""
        return json.dumps(self.hypervisor.stats.to_dict())

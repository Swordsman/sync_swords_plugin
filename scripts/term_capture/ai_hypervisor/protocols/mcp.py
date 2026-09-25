#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Handler

MCP is Anthropic's protocol for AI tools to:
- Expose resources (files, data) to models
- Provide tools/functions for models to call
- Manage context and state

Protocol: JSON-RPC 2.0 over stdio
"""

import json
import sys
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, asdict
from queue import Queue


@dataclass
class MCPMessage:
    """An MCP protocol message."""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: Optional[str] = None
    params: Optional[Dict] = None
    result: Optional[Any] = None
    error: Optional[Dict] = None
    
    def is_request(self) -> bool:
        return self.method is not None
    
    def is_response(self) -> bool:
        return self.result is not None or self.error is not None
    
    def is_notification(self) -> bool:
        return self.method is not None and self.id is None
    
    def to_json(self) -> str:
        data = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            data["id"] = self.id
        if self.method:
            data["method"] = self.method
        if self.params:
            data["params"] = self.params
        if self.result is not None:
            data["result"] = self.result
        if self.error:
            data["error"] = self.error
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, line: str) -> 'MCPMessage':
        data = json.loads(line)
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            method=data.get("method"),
            params=data.get("params"),
            result=data.get("result"),
            error=data.get("error"),
        )


class MCPHandler:
    """
    Handle MCP protocol communication.
    
    Intercepts and potentially modifies MCP messages between
    AI tool and its MCP server.
    """
    
    def __init__(self,
                 on_request: Optional[Callable[[MCPMessage], Optional[MCPMessage]]] = None,
                 on_response: Optional[Callable[[MCPMessage], Optional[MCPMessage]]] = None,
                 on_notification: Optional[Callable[[MCPMessage], None]] = None):
        self.on_request = on_request
        self.on_response = on_response
        self.on_notification = on_notification
        
        self.message_queue: Queue = Queue()
        self.request_counter = 0
        self.pending_requests: Dict[int, threading.Event] = {}
        self.responses: Dict[int, MCPMessage] = {}
    
    def intercept_stdin(self, line: str) -> Optional[str]:
        """
        Intercept a line from stdin (tool -> server).
        
        Returns modified line or None to drop.
        """
        try:
            msg = MCPMessage.from_json(line)
        except json.JSONDecodeError:
            return line  # Not JSON, pass through
        
        if msg.is_notification():
            if self.on_notification:
                self.on_notification(msg)
            return line
        
        if msg.is_request():
            if self.on_request:
                modified = self.on_request(msg)
                if modified is None:
                    return None  # Drop request
                return modified.to_json()
        
        return line
    
    def intercept_stdout(self, line: str) -> Optional[str]:
        """
        Intercept a line from stdout (server -> tool).
        
        Returns modified line or None to drop.
        """
        try:
            msg = MCPMessage.from_json(line)
        except json.JSONDecodeError:
            return line  # Not JSON, pass through
        
        if msg.is_response():
            if self.on_response:
                modified = self.on_response(msg)
                if modified is None:
                    return None  # Drop response
                return modified.to_json()
        
        return line
    
    def create_request(self, method: str, params: Dict) -> MCPMessage:
        """Create a new MCP request."""
        self.request_counter += 1
        return MCPMessage(
            id=self.request_counter,
            method=method,
            params=params
        )
    
    def create_notification(self, method: str, params: Dict) -> MCPMessage:
        """Create a new MCP notification (no response expected)."""
        return MCPMessage(
            method=method,
            params=params
        )


class MCPServer:
    """
    MCP Server implementation for providing resources/tools.
    
    Can be used to expose hypervisor capabilities to AI tools
    via the MCP protocol.
    """
    
    def __init__(self, name: str = "ai-hypervisor"):
        self.name = name
        self.resources: Dict[str, Callable] = {}
        self.tools: Dict[str, Callable] = {}
        self.running = False
    
    def register_resource(self, uri: str, handler: Callable):
        """Register a resource handler."""
        self.resources[uri] = handler
    
    def register_tool(self, name: str, handler: Callable, 
                     description: str = "", schema: Dict = None):
        """Register a tool handler."""
        self.tools[name] = {
            "handler": handler,
            "description": description,
            "schema": schema or {}
        }
    
    def handle_message(self, msg: MCPMessage) -> Optional[MCPMessage]:
        """Handle an incoming MCP message."""
        if not msg.is_request():
            return None
        
        method = msg.method
        params = msg.params or {}
        
        # Handle built-in methods
        if method == "initialize":
            return MCPMessage(
                id=msg.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "resources": {},
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": "0.1.0"
                    }
                }
            )
        
        elif method == "resources/list":
            return MCPMessage(
                id=msg.id,
                result={
                    "resources": [
                        {"uri": uri, "name": uri}
                        for uri in self.resources.keys()
                    ]
                }
            )
        
        elif method == "resources/read":
            uri = params.get("uri")
            if uri in self.resources:
                content = self.resources[uri]()
                return MCPMessage(
                    id=msg.id,
                    result={
                        "contents": [
                            {"uri": uri, "text": content}
                        ]
                    }
                )
            return MCPMessage(
                id=msg.id,
                error={"code": -32602, "message": f"Resource not found: {uri}"}
            )
        
        elif method == "tools/list":
            return MCPMessage(
                id=msg.id,
                result={
                    "tools": [
                        {
                            "name": name,
                            "description": info["description"],
                            "inputSchema": info["schema"]
                        }
                        for name, info in self.tools.items()
                    ]
                }
            )
        
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            
            if name in self.tools:
                try:
                    result = self.tools[name]["handler"](**arguments)
                    return MCPMessage(
                        id=msg.id,
                        result={"content": [{"type": "text", "text": str(result)}]}
                    )
                except Exception as e:
                    return MCPMessage(
                        id=msg.id,
                        error={"code": -32603, "message": str(e)}
                    )
            
            return MCPMessage(
                id=msg.id,
                error={"code": -32602, "message": f"Tool not found: {name}"}
            )
        
        # Unknown method
        return MCPMessage(
            id=msg.id,
            error={"code": -32601, "message": f"Method not found: {method}"}
        )
    
    def run_stdio(self):
        """Run server over stdio (for MCP)."""
        self.running = True
        
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                
                try:
                    msg = MCPMessage.from_json(line.strip())
                except json.JSONDecodeError:
                    continue
                
                response = self.handle_message(msg)
                if response:
                    print(response.to_json(), flush=True)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)

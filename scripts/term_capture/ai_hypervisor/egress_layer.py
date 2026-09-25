#!/usr/bin/env python3
"""
EGRESS Layer - Network traffic control and monitoring.

Encapsulates AI tools at the network level:
- Monitors outbound HTTP/HTTPS connections
- Can block/allow specific hosts
- Tracks bandwidth usage per tool
- Can force proxy usage for logging

Implementation strategies:
1. LD_PRELOAD wrapper (intercept connect())
2. Proxy environment variables
3. Network namespace + iptables
4. eBPF tracing (Linux)

For most AI tools, proxy environment variables work well:
- HTTP_PROXY, HTTPS_PROXY
- ANTHROPIC_API_BASE (vendor-specific)
- OPENAI_API_BASE, etc
"""

import os
import json
import socket
import select
import threading
import time
from typing import Optional, List, Callable, Dict
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class NetworkEvent:
    timestamp: float
    host: str
    port: int
    method: str  # CONNECT, GET, POST, etc
    bytes_out: int
    bytes_in: int
    duration_ms: Optional[float]


class EgressLayer:
    """
    Network egress control and monitoring layer.
    
    Uses proxy-based interception as the primary mechanism.
    For stricter control, can use network namespaces.
    """
    
    # Known AI API endpoints
    AI_HOSTS = {
        'api.anthropic.com': 'anthropic',
        'api.openai.com': 'openai',
        'api.moonshot.cn': 'moonshot',
        'generativelanguage.googleapis.com': 'google',
        'api.groq.com': 'groq',
        'api.cohere.com': 'cohere',
    }
    
    def __init__(self,
                 log_file: Optional[Path] = None,
                 allow_internet: bool = True,
                 allowed_hosts: Optional[List[str]] = None,
                 blocked_hosts: Optional[List[str]] = None,
                 on_request: Optional[Callable[[str, str, int, int], None]] = None):
        self.log_file = log_file
        self.allow_internet = allow_internet
        self.allowed_hosts = set(allowed_hosts or [])
        self.blocked_hosts = set(blocked_hosts or [])
        self.on_request = on_request
        
        self._proxy: Optional[ProxyServer] = None
        self._enabled = False
        self._original_env: Dict[str, str] = {}
    
    def enable(self):
        """Enable egress monitoring by starting a local proxy."""
        if self._enabled:
            return
        
        # Store original proxy settings
        for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
                    'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy',
                    'ANTHROPIC_API_BASE', 'OPENAI_API_BASE']:
            self._original_env[var] = os.environ.get(var, '')
        
        # Start local proxy server
        self._proxy = ProxyServer(
            on_event=self._on_proxy_event,
            check_allowed=self.check_allowed,
            classify_host=self.classify_host,
        )
        self._proxy.start()
        
        self._enabled = True
    
    def disable(self):
        """Disable egress monitoring, restore environment."""
        if not self._enabled:
            return
        
        if self._proxy:
            self._proxy.stop()
            self._proxy = None
        
        # Restore original env
        for var, val in self._original_env.items():
            if val:
                os.environ[var] = val
            elif var in os.environ:
                del os.environ[var]
        
        self._enabled = False
    
    def wrap_environment(self, env: Dict[str, str]) -> Dict[str, str]:
        """
        Modify environment to route traffic through monitoring.
        
        Returns modified environment dict.
        """
        if not self._enabled or not self._proxy:
            return env
        
        wrapped = env.copy()
        proxy_url = f"http://127.0.0.1:{self._proxy.port}"
        
        wrapped['HTTP_PROXY'] = proxy_url
        wrapped['HTTPS_PROXY'] = proxy_url
        wrapped['http_proxy'] = proxy_url
        wrapped['https_proxy'] = proxy_url
        wrapped['_AI_HYPERVISOR_EGRESS'] = '1'
        
        # Vendor-specific overrides to route API calls through proxy
        wrapped['ANTHROPIC_API_BASE'] = f'{proxy_url}/anthropic'
        wrapped['OPENAI_API_BASE'] = f'{proxy_url}/openai'
        
        return wrapped
    
    def is_ai_host(self, host: str) -> bool:
        """Check if host is a known AI API endpoint."""
        # Direct match
        if host in self.AI_HOSTS:
            return True
        
        # Subdomain match
        for h in self.AI_HOSTS:
            if host.endswith('.' + h) or host == h:
                return True
        
        return False
    
    def classify_host(self, host: str) -> str:
        """Classify a host by type."""
        if self.is_ai_host(host):
            return 'ai_api'
        
        # Git hosts
        if any(h in host for h in ['github.com', 'gitlab.com', 'bitbucket.org']):
            return 'git'
        
        # Package repos
        if any(h in host for h in ['pypi.org', 'npmjs.com', 'registry']):
            return 'package_registry'
        
        # Search
        if any(h in host for h in ['google.com', 'bing.com', 'duckduckgo.com']):
            return 'search'
        
        return 'other'
    
    def check_allowed(self, host: str) -> bool:
        """Check if host is allowed by policy."""
        if not self.allow_internet:
            # Whitelist mode
            return host in self.allowed_hosts
        
        # Blacklist mode
        if host in self.blocked_hosts:
            return False
        
        return True
    
    def log_request(self, event: NetworkEvent):
        """Log a network request."""
        if self.log_file:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps({
                    'timestamp': event.timestamp,
                    'host': event.host,
                    'port': event.port,
                    'method': event.method,
                    'bytes_out': event.bytes_out,
                    'bytes_in': event.bytes_in,
                    'duration_ms': event.duration_ms,
                    'classification': self.classify_host(event.host),
                }) + '\n')
        
        if self.on_request:
            self.on_request(event.host, event.method, 
                          event.bytes_in, event.bytes_out)
    
    def _on_proxy_event(self, event: NetworkEvent):
        """Callback from ProxyServer when a request is handled."""
        self.log_request(event)


class ProxyServer:
    """
    Minimal HTTP CONNECT proxy for intercepting TLS traffic.
    
    Supports:
    - HTTP CONNECT tunneling for HTTPS
    - Direct HTTP proxying for plain HTTP
    - Host blocking via check_allowed callback
    - Event logging via on_event callback
    """
    
    def __init__(self, port: int = 0,
                 on_event: Optional[Callable[[NetworkEvent], None]] = None,
                 check_allowed: Optional[Callable[[str], bool]] = None,
                 classify_host: Optional[Callable[[str], str]] = None):
        self.port = port
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handlers: List[threading.Thread] = []
        self._lock = threading.Lock()
        
        self.on_event = on_event
        self.check_allowed = check_allowed or (lambda h: True)
        self.classify_host = classify_host or (lambda h: 'other')
    
    def start(self) -> int:
        """Start proxy server, return actual port."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(('127.0.0.1', self.port))
        self._socket.listen(5)
        
        self.port = self._socket.getsockname()[1]
        self._running = True
        
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        
        return self.port
    
    def stop(self):
        """Stop proxy server."""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        
        if self._thread:
            self._thread.join(timeout=2)
        
        with self._lock:
            for t in self._handlers:
                t.join(timeout=1)
            self._handlers.clear()
    
    def _accept_loop(self):
        """Accept incoming client connections."""
        while self._running:
            try:
                self._socket.settimeout(1.0)
                client_sock, addr = self._socket.accept()
                client_sock.settimeout(None)
            except socket.timeout:
                continue
            except OSError:
                break
            
            handler = threading.Thread(
                target=self._handle_client,
                args=(client_sock,),
                daemon=True
            )
            handler.start()
            
            with self._lock:
                self._handlers.append(handler)
                # Clean up finished handlers
                self._handlers = [t for t in self._handlers if t.is_alive()]
    
    def _handle_client(self, client_sock: socket.socket):
        """Handle a single client connection."""
        try:
            # Read the HTTP request line
            request_line = self._read_line(client_sock)
            if not request_line:
                return
            
            parts = request_line.split()
            if len(parts) < 3:
                return
            
            method = parts[0]
            target = parts[1]
            version = parts[2]
            
            # Read headers
            headers = self._read_headers(client_sock)
            
            if method == 'CONNECT':
                self._handle_connect(client_sock, target, headers)
            else:
                self._handle_http_request(client_sock, method, target, headers)
        
        except Exception:
            pass
        finally:
            try:
                client_sock.close()
            except OSError:
                pass
    
    def _read_line(self, sock: socket.socket) -> str:
        """Read a line from socket."""
        buf = b''
        while True:
            try:
                data = sock.recv(1)
            except OSError:
                break
            if not data:
                break
            buf += data
            if buf.endswith(b'\r\n'):
                break
        return buf.decode('utf-8', errors='replace').strip()
    
    def _read_headers(self, sock: socket.socket) -> Dict[str, str]:
        """Read HTTP headers from socket."""
        headers = {}
        while True:
            line = self._read_line(sock)
            if not line or line == '\r\n':
                break
            if ':' in line:
                key, val = line.split(':', 1)
                headers[key.strip().lower()] = val.strip()
        return headers
    
    def _parse_host_port(self, target: str) -> tuple:
        """Parse target into host and port."""
        if target.startswith('http://') or target.startswith('https://'):
            parsed = urlparse(target)
            host = parsed.hostname or ''
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            return host, port
        
        if ':' in target:
            host, port_str = target.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 80
            # Handle IPv6 brackets
            if host.startswith('[') and host.endswith(']'):
                host = host[1:-1]
            return host, port
        
        return target, 80
    
    def _handle_connect(self, client_sock: socket.socket, target: str, headers: Dict[str, str]):
        """Handle HTTP CONNECT method (HTTPS tunneling)."""
        host, port = self._parse_host_port(target)
        
        if not self.check_allowed(host):
            client_sock.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
            return
        
        start_time = time.time()
        bytes_out = 0
        bytes_in = 0
        
        try:
            remote_sock = socket.create_connection((host, port), timeout=10)
        except (OSError, socket.error) as e:
            client_sock.sendall(f'HTTP/1.1 502 Bad Gateway\r\n\r\n'.encode())
            return
        
        # Send connection established
        client_sock.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
        
        # Tunnel data bidirectionally
        try:
            while True:
                readable, _, _ = select.select([client_sock, remote_sock], [], [], 1.0)
                
                if client_sock in readable:
                    data = client_sock.recv(8192)
                    if not data:
                        break
                    remote_sock.sendall(data)
                    bytes_out += len(data)
                
                if remote_sock in readable:
                    data = remote_sock.recv(8192)
                    if not data:
                        break
                    client_sock.sendall(data)
                    bytes_in += len(data)
        
        except (OSError, socket.error):
            pass
        finally:
            duration_ms = (time.time() - start_time) * 1000
            if self.on_event:
                self.on_event(NetworkEvent(
                    timestamp=start_time,
                    host=host,
                    port=port,
                    method='CONNECT',
                    bytes_out=bytes_out,
                    bytes_in=bytes_in,
                    duration_ms=duration_ms
                ))
            try:
                remote_sock.close()
            except OSError:
                pass
    
    def _handle_http_request(self, client_sock: socket.socket, method: str, target: str, headers: Dict[str, str]):
        """Handle direct HTTP proxy request."""
        host, port = self._parse_host_port(target)
        
        if not self.check_allowed(host):
            client_sock.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
            return
        
        start_time = time.time()
        bytes_out = 0
        bytes_in = 0
        
        try:
            remote_sock = socket.create_connection((host, port), timeout=10)
        except (OSError, socket.error):
            client_sock.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
            return
        
        # Read request body if present
        body = b''
        content_length = int(headers.get('content-length', 0))
        if content_length > 0:
            body = self._recv_all(client_sock, content_length)
        
        # Reconstruct request
        parsed = urlparse(target)
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        
        request_line = f'{method} {path} HTTP/1.1\r\n'.encode()
        
        # Filter out proxy-specific headers and rebuild
        filtered_headers = {}
        for k, v in headers.items():
            if k not in ('proxy-connection', 'proxy-authorization'):
                filtered_headers[k] = v
        
        if 'host' not in filtered_headers:
            filtered_headers['host'] = host if port == 80 else f'{host}:{port}'
        
        header_bytes = b''
        for k, v in filtered_headers.items():
            header_bytes += f'{k}: {v}\r\n'.encode()
        header_bytes += b'\r\n'
        
        request_bytes = request_line + header_bytes + body
        
        try:
            remote_sock.sendall(request_bytes)
            bytes_out = len(request_bytes)
            
            # Read and forward response
            while True:
                data = remote_sock.recv(8192)
                if not data:
                    break
                client_sock.sendall(data)
                bytes_in += len(data)
        
        except (OSError, socket.error):
            pass
        finally:
            duration_ms = (time.time() - start_time) * 1000
            if self.on_event:
                self.on_event(NetworkEvent(
                    timestamp=start_time,
                    host=host,
                    port=port,
                    method=method,
                    bytes_out=bytes_out,
                    bytes_in=bytes_in,
                    duration_ms=duration_ms
                ))
            try:
                remote_sock.close()
            except OSError:
                pass
    
    def _recv_all(self, sock: socket.socket, n: int) -> bytes:
        """Receive exactly n bytes from socket."""
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                break
            data += chunk
        return data

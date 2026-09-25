#!/usr/bin/env python3
"""Tests for ai_hypervisor core modules."""

import asyncio
import json
import os
import socket
import sys
import threading
import time
import unittest
import select
from pathlib import Path

# Ensure parent package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from sexp import SExpParser, ProfileBuilder, dump_profile
from protocol_bridge import ProtocolBridge, ProtocolEvent
from egress_layer import EgressLayer, ProxyServer, NetworkEvent
from message_bus import AsyncMessageBus, BusClient, Message


class TestSExpInheritance(unittest.TestCase):
    """Test ProfileBuilder inheritance support."""
    
    def test_inheritance_merges_patterns_and_defaults(self):
        text = """
(profile default
  (defaults (rows 24) (cols 120))
  (scrollback-ignore
    (pattern "^spam$"))
  (scrollback-capture shell-prompt
    (pattern "^\\$\\s+(.+)")
    (group command)
    (priority 10)))

(profile claude
  (inherit default)
  (defaults (cols 100))
  (screen-capture token-usage
    (pattern "Tokens:")
    (priority 100)))
"""
        builder = ProfileBuilder()
        parser = SExpParser()
        exprs = parser.parse(text)
        for expr in exprs:
            if expr.is_list and expr.car.atom == 'profile':
                profile = builder._build_profile(expr)
                builder.profiles[profile.name] = profile
        
        claude = builder.profiles['claude']
        self.assertEqual(claude.default_rows, 24)   # inherited
        self.assertEqual(claude.default_cols, 100)  # overridden
        self.assertEqual(len(claude.scrollback_ignore_patterns), 1)  # inherited
        self.assertEqual(len(claude.scrollback_capture_rules), 1)    # inherited
        self.assertEqual(len(claude.screen_capture_rules), 1)        # own
        self.assertEqual(claude.screen_capture_rules[0].name, 'token-usage')
    
    def test_inheritance_without_parent(self):
        text = """
(profile orphan
  (inherit missing)
  (defaults (rows 10)))
"""
        builder = ProfileBuilder()
        parser = SExpParser()
        exprs = parser.parse(text)
        profile = builder._build_profile(exprs[0])
        self.assertEqual(profile.default_rows, 10)
        self.assertEqual(profile.default_cols, 80)
    
    def test_load_file_default_sexpr(self):
        rules_path = Path(__file__).parent.parent / 'rules' / 'default.sexpr'
        if not rules_path.exists():
            self.skipTest("default.sexpr not found")
        
        builder = ProfileBuilder()
        profiles = builder.load_file(rules_path)
        
        self.assertIn('default', profiles)
        self.assertIn('claude', profiles)
        
        default = profiles['default']
        claude = profiles['claude']
        
        # claude should inherit default's scrollback-ignore patterns
        self.assertGreaterEqual(len(claude.scrollback_ignore_patterns), 1)
        # claude should have its own screen-capture rules
        self.assertEqual(len(claude.screen_capture_rules), 2)


class TestProtocolBridge(unittest.TestCase):
    """Test ProtocolBridge interception and PTY wiring."""
    
    def test_process_pty_output_parses_mcp(self):
        bridge = ProtocolBridge()
        bridge.start()
        events = []
        bridge.add_event_callback(lambda e: events.append(e))
        
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        data = json.dumps(msg).encode() + b'\n'
        result = bridge.process_pty_output(data)
        
        self.assertEqual(result, data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, 'mcp')
        self.assertEqual(events[0].direction, 'out')
        bridge.stop()
    
    def test_process_pty_input_parses_mcp(self):
        bridge = ProtocolBridge()
        bridge.start()
        events = []
        bridge.add_event_callback(lambda e: events.append(e))
        
        msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        data = json.dumps(msg).encode() + b'\n'
        result = bridge.process_pty_input(data)
        
        self.assertEqual(result, data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].protocol, 'mcp')
        self.assertEqual(events[0].direction, 'in')
        bridge.stop()
    
    def test_process_pty_output_non_json_passes_through(self):
        bridge = ProtocolBridge()
        bridge.start()
        data = b'Hello World\nAnother line\n'
        result = bridge.process_pty_output(data)
        self.assertEqual(result, data)
        bridge.stop()
    
    def test_process_pty_partial_line_buffering(self):
        bridge = ProtocolBridge()
        bridge.start()
        
        part1 = b'{"jsonrpc": "2.0"'
        part2 = b', "id": 3, "method": "ping"}\n'
        
        result1 = bridge.process_pty_input(part1)
        self.assertEqual(result1, b'')  # buffering, no newline yet
        
        result2 = bridge.process_pty_input(part2)
        self.assertEqual(result2, part1 + part2)
        bridge.stop()
    
    def test_intercept_stdio_returns_valid_fds(self):
        bridge = ProtocolBridge()
        bridge.start()
        
        # Create dummy fds
        r_in, w_in = os.pipe()
        r_out, w_out = os.pipe()
        
        new_in = None
        new_out = None
        try:
            new_in, new_out = bridge.intercept_stdio(r_in, w_out)
            
            # new_in should be readable, new_out should be writable
            self.assertTrue(isinstance(new_in, int))
            self.assertTrue(isinstance(new_out, int))
            
            # Write to new_out (simulating tool stdout), should eventually come out r_in... wait,
            # no: we write to new_out, the bridge reads it and writes to w_out, which we can read from r_out
            test_data = b'test line\n'
            os.write(new_out, test_data)
            
            # Give the thread a moment
            time.sleep(0.1)
            
            readable, _, _ = select.select([r_out], [], [], 1.0)
            self.assertIn(r_out, readable)
            received = os.read(r_out, 1024)
            self.assertEqual(received, test_data)
        finally:
            for fd in [r_in, w_in, r_out, w_out]:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for fd in [new_in, new_out]:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            bridge.stop()


class TestEgressProxy(unittest.TestCase):
    """Test EgressLayer and ProxyServer."""
    
    def test_proxy_server_starts_and_reports_port(self):
        proxy = ProxyServer()
        port = proxy.start()
        self.assertGreater(port, 0)
        self.assertEqual(proxy.port, port)
        proxy.stop()
    
    def test_egress_enable_starts_proxy_and_sets_env(self):
        egress = EgressLayer(allow_internet=True)
        egress.enable()
        self.assertTrue(egress._enabled)
        self.assertIsNotNone(egress._proxy)
        self.assertGreater(egress._proxy.port, 0)
        
        env = egress.wrap_environment({})
        self.assertIn('HTTP_PROXY', env)
        self.assertIn('HTTPS_PROXY', env)
        self.assertTrue(env['HTTP_PROXY'].startswith('http://127.0.0.1:'))
        
        egress.disable()
        self.assertFalse(egress._enabled)
    
    def test_proxy_http_request(self):
        # Start a simple backend server
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        backend.bind(('127.0.0.1', 0))
        backend.listen(1)
        backend_port = backend.getsockname()[1]
        
        def backend_handler():
            conn, _ = backend.accept()
            try:
                req = conn.recv(1024)
                self.assertIn(b'GET /test', req)
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')
            finally:
                conn.close()
        
        t = threading.Thread(target=backend_handler, daemon=True)
        t.start()
        
        proxy = ProxyServer()
        proxy_port = proxy.start()
        
        try:
            # Connect to proxy
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(('127.0.0.1', proxy_port))
            
            request = f'GET http://127.0.0.1:{backend_port}/test HTTP/1.1\r\nHost: 127.0.0.1:{backend_port}\r\n\r\n'
            client.sendall(request.encode())
            
            response = b''
            for _ in range(50):
                readable, _, _ = select.select([client], [], [], 0.1)
                if readable:
                    chunk = client.recv(1024)
                    if not chunk:
                        break
                    response += chunk
                    if b'\r\n\r\n' in response and response.endswith(b'OK'):
                        break
            
            self.assertIn(b'200 OK', response)
            self.assertIn(b'OK', response)
            client.close()
        finally:
            proxy.stop()
            backend.close()
    
    def test_proxy_blocks_disallowed_host(self):
        egress = EgressLayer(allow_internet=False, allowed_hosts=['allowed.example.com'])
        egress.enable()
        proxy_port = egress._proxy.port
        
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(('127.0.0.1', proxy_port))
            
            request = 'GET http://blocked.example.com/ HTTP/1.1\r\nHost: blocked.example.com\r\n\r\n'
            client.sendall(request.encode())
            
            response = b''
            for _ in range(50):
                readable, _, _ = select.select([client], [], [], 0.1)
                if readable:
                    chunk = client.recv(1024)
                    if not chunk:
                        break
                    response += chunk
            
            self.assertIn(b'403', response)
            client.close()
        finally:
            egress.disable()


class TestMessageBus(unittest.TestCase):
    """Test AsyncMessageBus and BusClient."""

    def test_connect_and_send_ack(self):
        """Fire-and-forget connect_and_send still works with framed ACK."""
        async def _test():
            socket_path = Path('/tmp/test_bus_ack.sock')
            bus = AsyncMessageBus(socket_path, 'test_server')
            server_task = asyncio.create_task(bus.start_server())
            await asyncio.sleep(0.1)
            try:
                received = []
                bus.register_handler('fireforget', lambda msg: received.append(msg))

                msg = Message.create(
                    src='client', dst='broadcast',
                    msg_type='fireforget', payload={}
                )
                ok = await bus.connect_and_send(msg)
                self.assertTrue(ok)
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0].msg_type, 'fireforget')
            finally:
                bus.stop()
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass
                if socket_path.exists():
                    socket_path.unlink()

        asyncio.run(_test())

    def test_bus_client_connect_send_receive(self):
        """BusClient can connect, send, and receive messages."""
        async def _test():
            socket_path = Path('/tmp/test_bus_client.sock')
            bus = AsyncMessageBus(socket_path, 'test_server')
            server_task = asyncio.create_task(bus.start_server())
            await asyncio.sleep(0.1)
            try:
                received = []

                client = BusClient()
                await client.connect(socket_path)
                client.register_handler('test_msg', lambda msg: received.append(msg))

                msg = Message.create(
                    src='test', dst='broadcast',
                    msg_type='test_msg', payload={'data': 42}
                )
                await client.send(msg)

                await asyncio.sleep(0.2)

                self.assertEqual(len(received), 1)
                self.assertEqual(received[0].msg_type, 'test_msg')
                self.assertEqual(received[0].payload, {'data': 42})

                await client.disconnect()
            finally:
                bus.stop()
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass
                if socket_path.exists():
                    socket_path.unlink()

        asyncio.run(_test())

    def test_multiple_bus_clients(self):
        """Multiple BusClients connect and receive broadcasts."""
        async def _test():
            socket_path = Path('/tmp/test_bus_multi.sock')
            bus = AsyncMessageBus(socket_path, 'test_server')
            server_task = asyncio.create_task(bus.start_server())
            await asyncio.sleep(0.1)
            try:
                received_a = []
                received_b = []

                client_a = BusClient()
                await client_a.connect(socket_path)
                client_a.register_handler('chat', lambda msg: received_a.append(msg))

                client_b = BusClient()
                await client_b.connect(socket_path)
                client_b.register_handler('chat', lambda msg: received_b.append(msg))

                msg = Message.create(
                    src='a', dst='broadcast',
                    msg_type='chat', payload={'text': 'hello'}
                )
                await client_a.send(msg)

                await asyncio.sleep(0.2)

                # Both clients receive the broadcast (including sender)
                self.assertEqual(len(received_a), 1)
                self.assertEqual(len(received_b), 1)
                self.assertEqual(received_a[0].payload['text'], 'hello')
                self.assertEqual(received_b[0].payload['text'], 'hello')

                await client_a.disconnect()
                await client_b.disconnect()
            finally:
                bus.stop()
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass
                if socket_path.exists():
                    socket_path.unlink()

        asyncio.run(_test())

    def test_bus_client_disconnect_clean(self):
        """BusClient disconnect closes the read loop cleanly."""
        async def _test():
            socket_path = Path('/tmp/test_bus_disc.sock')
            bus = AsyncMessageBus(socket_path, 'test_server')
            server_task = asyncio.create_task(bus.start_server())
            await asyncio.sleep(0.1)
            try:
                client = BusClient()
                await client.connect(socket_path)
                self.assertTrue(client._connected)
                await client.disconnect()
                self.assertFalse(client._connected)
                self.assertIsNone(client._reader)
                self.assertIsNone(client._writer)
            finally:
                bus.stop()
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    pass
                if socket_path.exists():
                    socket_path.unlink()

        asyncio.run(_test())


if __name__ == '__main__':
    unittest.main()

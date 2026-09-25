#!/usr/bin/env python3
"""
mesh_kimi.py — Hypervisor-native launcher for Kimi CLI on the mesh bus.

Starts Kimi under AIHypervisor with a PTY, connects to the async message bus,
registers with the broker, sends periodic heartbeats, and re-registers on
broker_ready. Cleans up and deregisters on exit.
"""

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "ai_hypervisor"))

from ai_hypervisor import AIHypervisor, HypervisorConfig
from mesh_protocol import MSG_REGISTER, MSG_DEREGISTER, MSG_BROKER_READY, MSG_HEARTBEAT, MSG_SEND, MSG_RECEIVED
from message_bus import BusClient, Message
from pty_layer_v2 import PTYLayer
from sexp import ProfileBuilder


DEFAULT_SOCKET = "/tmp/mesh_bus.sock"
DEFAULT_RULES = _PROJECT_ROOT / "ai_hypervisor" / "rules" / "default.sexpr"


class ProfiledHypervisor(AIHypervisor):
    """AIHypervisor that swaps in a ToolProfile loaded from S-expression rules."""

    def __init__(self, config=None, profile=None):
        super().__init__(config)
        self._profile = profile

    def initialize(self):
        super().initialize()
        if self._profile is not None and self.pty is not None:
            # Preserve log paths and callbacks from base init
            raw_log = self.pty.raw_log
            text_log = self.pty.text_log
            on_output = self.pty.on_output
            on_usage = self.pty.on_usage_pattern

            self.pty.cleanup()
            self.pty = PTYLayer(
                raw_log=raw_log,
                text_log=text_log,
                on_output=on_output,
                on_usage_pattern=on_usage,
                profile=self._profile,
            )
            if self.protocol_bridge:
                self.pty.protocol_bridge = self.protocol_bridge


def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch Kimi CLI under the AI hypervisor on the mesh bus"
    )
    parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET,
        help="Bus unix socket path (default: /tmp/mesh_bus.sock)",
    )
    parser.add_argument(
        "--name",
        default=f"kimi-{os.getpid()}",
        help="Agent name on the bus",
    )
    parser.add_argument(
        "--role",
        default="ai",
        help="Agent role (default: ai)",
    )
    parser.add_argument(
        "--pane",
        default=str(Path.cwd()),
        help="Pane / workspace identifier (default: cwd)",
    )
    parser.add_argument(
        "--capabilities",
        default="chat,code,files",
        help="Comma-separated capabilities (default: chat,code,files)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Hypervisor log directory",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=DEFAULT_RULES,
        help="S-expression rules file",
    )
    parser.add_argument(
        "--no-bus",
        action="store_true",
        help="Run without connecting to the mesh bus",
    )
    parser.add_argument(
        "kimi_args",
        nargs="*",
        help="Arguments to pass to the kimi CLI",
    )
    return parser.parse_args()


async def heartbeat_loop(
    bus: BusClient, name: str, shutdown: asyncio.Event, interval: float = 30.0
):
    """Send heartbeat messages until shutdown is signalled."""
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if shutdown.is_set():
            break
        msg = Message.create(
            src=name,
            dst="broker",
            msg_type=MSG_HEARTBEAT,
            payload={"name": name},
        )
        try:
            await bus.send(msg)
        except Exception as e:
            print(f"[mesh_kimi] Heartbeat failed: {e}")


async def main():
    args = parse_args()

    # Load profile from rules file
    profile = None
    if args.rules.exists():
        builder = ProfileBuilder()
        try:
            profiles = builder.load_file(args.rules)
            profile = profiles.get("default")
            if profile:
                print(f"[mesh_kimi] Loaded profile 'default' from {args.rules}")
            else:
                print(f"[mesh_kimi] No 'default' profile in {args.rules}, using generic")
        except Exception as e:
            print(f"[mesh_kimi] Failed to load rules: {e}")
    else:
        print(f"[mesh_kimi] Rules file not found: {args.rules}")

    # Hypervisor config
    config = HypervisorConfig(
        log_dir=args.log_dir or (Path.home() / ".ai_hypervisor" / "mesh_kimi"),
        log_raw_pty=True,
        log_text_pty=True,
    )

    hv = ProfiledHypervisor(config, profile)
    hv.initialize()

    bus = BusClient()
    shutdown_event = asyncio.Event()
    registered = False
    bus_available = False

    async def do_register():
        nonlocal registered
        msg = Message.create(
            src=args.name,
            dst="broker",
            msg_type=MSG_REGISTER,
            payload={
                "name": args.name,
                "role": args.role,
                "pane": args.pane,
                "capabilities": args.capabilities.split(","),
            },
        )
        try:
            await bus.send(msg)
            registered = True
            print(f"[mesh_kimi] Registered as '{args.name}'")
        except Exception as e:
            print(f"[mesh_kimi] Registration failed: {e}")

    def on_broker_ready(msg):
        if not shutdown_event.is_set():
            asyncio.create_task(do_register())

    bus.register_handler(MSG_BROKER_READY, on_broker_ready)

    # MSG_SEND handler: inject into PTY, capture output, reply with MSG_RECEIVED
    async def _handle_msg_send(msg):
        is_for_me = (msg.dst == args.name) or (msg.payload.get("to") == args.name)
        if not is_for_me:
            return

        content = msg.payload.get("content", "")
        if not content:
            return

        pty_layer = hv.pty
        if not pty_layer or not pty_layer.master_fd:
            print(f"[mesh_kimi] PTY not available, cannot handle message")
            return

        # Snapshot scrollback before writing
        before_scrollback = list(pty_layer.screen.get_scrollback())

        try:
            pty_layer.write((content + "\r\n").encode("utf-8"))
            print(f"[mesh_kimi] Injected message to PTY: {content[:80]!r}")
        except Exception as e:
            print(f"[mesh_kimi] PTY write failed: {e}")
            return

        # Wait for AI to process and generate output
        wait_secs = msg.payload.get("wait", 5.0)
        await asyncio.sleep(wait_secs)

        # Capture output: diff of scrollback + current screen
        after_scrollback = list(pty_layer.screen.get_scrollback())
        new_lines = after_scrollback[len(before_scrollback):]

        response_text = "\n".join(new_lines).strip()
        if not response_text:
            response_text = pty_layer.get_screen().strip()

        reply = Message.create(
            src=args.name,
            dst=msg.src,
            msg_type=MSG_RECEIVED,
            payload={
                "from": args.name,
                "content": response_text,
                "in_reply_to": msg.msg_id,
            },
        )
        try:
            await bus.send(reply)
            print(f"[mesh_kimi] Sent MSG_RECEIVED to {msg.src}")
        except Exception as e:
            print(f"[mesh_kimi] Failed to send MSG_RECEIVED: {e}")

    def on_msg_send(msg):
        asyncio.create_task(_handle_msg_send(msg))

    bus.register_handler(MSG_SEND, on_msg_send)

    # Connect to bus unless --no-bus
    if not args.no_bus:
        try:
            await bus.connect(Path(args.socket))
            bus_available = True
            print(f"[mesh_kimi] Connected to bus at {args.socket}")
        except Exception as e:
            print(f"[mesh_kimi] Bus unavailable ({e}), running without mesh")

    # Initial registration
    if bus_available:
        await do_register()

    # Start heartbeat
    heartbeat_task = None
    if bus_available:
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(bus, args.name, shutdown_event)
        )

    # Signal handling
    loop = asyncio.get_running_loop()

    def on_signal(signum):
        print(f"\n[mesh_kimi] Signal {signum} received, shutting down...")
        shutdown_event.set()
        if hv.pty and hv.pty.pid:
            try:
                os.kill(hv.pty.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal, sig)
        except (NotImplementedError, ValueError):
            pass  # Windows or signal already handled

    # Run Kimi under hypervisor
    exit_code = 0
    try:
        exit_code = await asyncio.to_thread(hv.run_ai_tool, "kimi", args.kimi_args)
    except asyncio.CancelledError:
        exit_code = -1
    finally:
        shutdown_event.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        if bus_available and registered:
            dereg = Message.create(
                src=args.name,
                dst="broker",
                msg_type=MSG_DEREGISTER,
                payload={"name": args.name},
            )
            try:
                await asyncio.wait_for(bus.send(dereg), timeout=2.0)
                print("[mesh_kimi] Deregistered")
            except Exception:
                pass

        if bus_available:
            await bus.disconnect()

        hv.shutdown()

    if exit_code != 0:
        print(f"[mesh_kimi] Kimi exited with code {exit_code}")

    return exit_code


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)

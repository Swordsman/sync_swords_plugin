#!/usr/bin/env python3
"""
Mesh participant launcher for Claude Code CLI.

Runs Claude under AIHypervisor as a native PTY process,
connects to the peer-mesh message bus via BusClient,
and participates in the mesh protocol (register, heartbeat,
re-register on broker_ready, deregister on exit).

No tmux required; Claude runs directly under hypervisor PTY capture.
"""

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure ai_hypervisor is importable when run from term_capture/scripts/
_SCRIPT_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "ai_hypervisor"))
sys.path.insert(0, str(_PROJECT_ROOT))

from ai_hypervisor.hypervisor import AIHypervisor, HypervisorConfig
from ai_hypervisor.message_bus import BusClient, Message
from ai_hypervisor.mesh_protocol import (
    MSG_REGISTER,
    MSG_DEREGISTER,
    MSG_HEARTBEAT,
    MSG_BROKER_READY,
    MSG_SEND,
    MSG_RECEIVED,
)
from ai_hypervisor.sexp import ProfileBuilder


AGENT_NAME = "claude"
DEFAULT_SOCKET = Path("/tmp/mesh_bus.sock")
RULES_PATH = _PROJECT_ROOT / "ai_hypervisor" / "rules" / "default.sexpr"


def load_profile(path: Path, name: str = "default") -> Optional[object]:
    """Load a named profile from an S-expression rule file."""
    if not path.exists():
        return None
    builder = ProfileBuilder()
    profiles = builder.load_file(path)
    return profiles.get(name)


class MeshClaude:
    """
    Launch Claude Code CLI under AIHypervisor and keep it registered
    on the peer-mesh message bus.
    """

    def __init__(
        self,
        socket_path: Path,
        agent_name: str = AGENT_NAME,
        profile_name: str = "default",
    ):
        self.socket_path = socket_path
        self.agent_name = agent_name
        self.profile_name = profile_name

        self.bus_client: Optional[BusClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bus_thread: Optional[threading.Thread] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = threading.Event()
        self._registered = False
        self._hv: Optional[AIHypervisor] = None

    # --- bus lifecycle ---

    def _run_bus_loop(self) -> None:
        """Background thread entry: runs the asyncio event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._bus_main())
        finally:
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            if pending:
                for t in pending:
                    t.cancel()
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()

    async def _bus_main(self) -> None:
        """Connect to bus, register, and run until shutdown."""
        self.bus_client = BusClient()

        try:
            await self.bus_client.connect(self.socket_path)
        except Exception as exc:
            print(f"[mesh_claude] Bus connect failed ({exc}); running without mesh")
            return

        self.bus_client.register_handler(MSG_BROKER_READY, self._on_broker_ready)
        self.bus_client.register_handler(MSG_SEND, self._on_msg_send)

        await self._send_register()
        self._registered = True

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        while not self._shutdown_event.is_set():
            await asyncio.sleep(0.5)

        if self._registered:
            await self._send_deregister()
            self._registered = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        await self.bus_client.disconnect()

    # --- mesh protocol helpers ---

    async def _send_register(self) -> None:
        msg = Message.create(
            src=self.agent_name,
            dst="broker",
            msg_type=MSG_REGISTER,
            payload={
                "name": self.agent_name,
                "role": "agent",
                "pane": "",  # native PTY; no tmux pane
                "capabilities": ["chat", "code"],
            },
        )
        await self.bus_client.send(msg)

    async def _send_deregister(self) -> None:
        msg = Message.create(
            src=self.agent_name,
            dst="broker",
            msg_type=MSG_DEREGISTER,
            payload={"name": self.agent_name},
        )
        await self.bus_client.send(msg)

    async def _send_heartbeat(self) -> None:
        msg = Message.create(
            src=self.agent_name,
            dst="broker",
            msg_type=MSG_HEARTBEAT,
            payload={"name": self.agent_name},
        )
        await self.bus_client.send(msg)

    async def _heartbeat_loop(self) -> None:
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)
                if self._registered:
                    await self._send_heartbeat()
        except asyncio.CancelledError:
            pass

    # --- event handlers ---

    def _on_broker_ready(self, msg: Message) -> None:
        """Broker restarted; re-register."""
        print("[mesh_claude] Broker ready detected, re-registering...")
        if self._loop and self._registered:
            asyncio.create_task(self._send_register())

    def _on_msg_send(self, msg: Message) -> None:
        """Handle incoming MSG_SEND by scheduling an async task."""
        is_for_me = (msg.dst == self.agent_name) or (msg.payload.get("to") == self.agent_name)
        if not is_for_me:
            return
        if self._loop:
            self._loop.create_task(self._handle_msg_send(msg))

    async def _handle_msg_send(self, msg: Message) -> None:
        """Inject message into PTY, capture output, reply with MSG_RECEIVED."""
        content = msg.payload.get("content", "")
        if not content:
            return

        pty_layer = self._hv.pty if self._hv else None
        if not pty_layer or not pty_layer.master_fd:
            print(f"[mesh_claude] PTY not available, cannot handle message")
            return

        # Snapshot scrollback before writing
        before_scrollback = list(pty_layer.screen.get_scrollback())

        try:
            pty_layer.write((content + "\r\n").encode("utf-8"))
            print(f"[mesh_claude] Injected message to PTY: {content[:80]!r}")
        except Exception as e:
            print(f"[mesh_claude] PTY write failed: {e}")
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
            src=self.agent_name,
            dst=msg.src,
            msg_type=MSG_RECEIVED,
            payload={
                "from": self.agent_name,
                "content": response_text,
                "in_reply_to": msg.msg_id,
            },
        )
        try:
            await self.bus_client.send(reply)
            print(f"[mesh_claude] Sent MSG_RECEIVED to {msg.src}")
        except Exception as e:
            print(f"[mesh_claude] Failed to send MSG_RECEIVED: {e}")

    # --- public API ---

    def start(self) -> None:
        """Start the bus client in a background thread."""
        self._bus_thread = threading.Thread(target=self._run_bus_loop, daemon=True)
        self._bus_thread.start()
        time.sleep(0.5)

    def shutdown(self) -> None:
        """Signal shutdown and wait for the bus thread to finish."""
        self._shutdown_event.set()
        if self._bus_thread:
            self._bus_thread.join(timeout=5)

    def run(self) -> int:
        """Run Claude under hypervisor until it exits."""
        config = HypervisorConfig(
            log_dir=Path.home() / ".ai_hypervisor" / "mesh_claude",
            log_raw_pty=True,
            log_text_pty=True,
        )

        with AIHypervisor(config) as hv:
            self._hv = hv
            profile = load_profile(RULES_PATH, self.profile_name)
            if profile and hv.pty:
                hv.pty.profile = profile

            print(f"[mesh_claude] Starting {self.agent_name} under hypervisor...")
            print(f"[mesh_claude] Bus socket: {self.socket_path}")
            print(f"[mesh_claude] Profile: {self.profile_name}")
            print("[mesh_claude] Press Ctrl+C to interrupt, or type 'exit' in Claude\n")

            self.start()

            exit_code = 0
            try:
                exit_code = hv.run_ai_tool("claude", [])
            except KeyboardInterrupt:
                print(f"\n[mesh_claude] Interrupted")
                exit_code = 130
            finally:
                self.shutdown()

        print(f"[mesh_claude] Claude exited with code {exit_code}")
        return exit_code


def main() -> None:
    ap = argparse.ArgumentParser(description="Mesh participant launcher for Claude")
    ap.add_argument(
        "--socket",
        type=Path,
        default=DEFAULT_SOCKET,
        help=f"Message bus Unix socket (default: {DEFAULT_SOCKET})",
    )
    ap.add_argument(
        "--name",
        default=AGENT_NAME,
        help="Agent name on the mesh (default: claude)",
    )
    ap.add_argument(
        "--profile",
        default="default",
        help="S-expression profile from default.sexpr (default: default)",
    )
    args = ap.parse_args()

    launcher = MeshClaude(
        socket_path=args.socket,
        agent_name=args.name,
        profile_name=args.profile,
    )
    sys.exit(launcher.run())


if __name__ == "__main__":
    main()

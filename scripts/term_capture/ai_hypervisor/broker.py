"""Peer-mesh broker daemon.

Bridges the ACP message bus and tmux panes. Dumb pipe-fitting only: routes
`send` by literal `to` field, publishes `received` when a pane emits new
output. Maintains the participant registry from `mesh_protocol`.

Supports two participant kinds:
  * tmux participants – identified by a tmux pane target (e.g. session:window.pane).
    The broker injects input with send-keys and polls capture-pane for output.
  * hypervisor-native participants – no pane; they connect via BusClient and
    handle MSG_SEND / publish MSG_RECEIVED themselves over the socket.

Run with:
    python -m ai_hypervisor.broker [--socket PATH] [--poll-interval SECS]

The `AsyncMessageBus` now supports bidirectional communication via `BusClient`.
Clients connect persistently and receive server-pushed broadcasts (including
`received` and `participants` messages) in real time. The broker lives
server-side, observes all local traffic, and any messages it publishes are
automatically broadcast to connected remote clients.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from .message_bus import AsyncMessageBus, Message
from .mesh_protocol import (
    MSG_BROKER_READY,
    MSG_DEREGISTER,
    MSG_HEARTBEAT,
    MSG_LIST,
    MSG_PARTICIPANTS,
    MSG_RECEIVED,
    MSG_REGISTER,
    MSG_SEND,
    Registry,
)

log = logging.getLogger("broker")

BROKER_SRC = "broker"
DEFAULT_SOCKET = Path("/tmp/mesh_bus.sock")
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_GC_INTERVAL = 15.0
# capture-pane settles lag: see brief § Gotchas.
SEND_SETTLE_DELAY = 2.5


class Broker:
    def __init__(self, bus: AsyncMessageBus, registry: Registry,
                 poll_interval: float = DEFAULT_POLL_INTERVAL,
                 gc_interval: float = DEFAULT_GC_INTERVAL):
        self.bus = bus
        self.registry = registry
        self.poll_interval = poll_interval
        self.gc_interval = gc_interval
        self._last_capture: Dict[str, str] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Dispatch via wildcard so the broker sees every non-broker message
        # and routes it to the appropriate handler by msg_type.
        self._dispatch = {
            MSG_REGISTER: self._on_register,
            MSG_DEREGISTER: self._on_deregister,
            MSG_LIST: self._on_list,
            MSG_SEND: self._on_send,
            MSG_HEARTBEAT: self._on_heartbeat,
        }
        self.bus.register_handler("*", self._on_any)

    def _on_any(self, msg: Message) -> None:
        if msg.src == BROKER_SRC:
            return
        handler = self._dispatch.get(msg.msg_type)
        if handler is None:
            return
        try:
            handler(msg)
        except Exception:
            log.exception("handler %s failed", msg.msg_type)

    # --- handlers (run synchronously inside the asyncio loop) ---

    def _on_register(self, msg: Message) -> None:
        p = msg.payload or {}
        name = p.get("name")
        if not name:
            log.warning("register missing name: %s", msg)
            return
        self.registry.register(
            name=name,
            role=p.get("role", "agent"),
            pane=p.get("pane", ""),
            capabilities=p.get("capabilities") or [],
        )
        log.info("registered %s pane=%s", name, p.get("pane"))

    def _on_deregister(self, msg: Message) -> None:
        name = (msg.payload or {}).get("name") or msg.src
        if self.registry.deregister(name):
            log.info("deregistered %s", name)
        self._last_capture.pop(name, None)

    def _on_heartbeat(self, msg: Message) -> None:
        name = (msg.payload or {}).get("name") or msg.src
        self.registry.touch(name)

    def _on_list(self, msg: Message) -> None:
        reply = Message.create(
            src=BROKER_SRC,
            dst=msg.src,
            msg_type=MSG_PARTICIPANTS,
            payload={"participants": [p.to_dict() for p in self.registry.list()]},
        )
        self.bus.send(reply)
        log.info("list_participants -> %s (%d entries)",
                 msg.src, len(reply.payload["participants"]))

    def _on_send(self, msg: Message) -> None:
        p = msg.payload or {}
        to = p.get("to")
        content = p.get("content", "")
        target = self.registry.get(to) if to else None
        if target is None:
            log.warning("send to unknown participant %r (from=%s)", to, p.get("from"))
            return
        self.registry.touch(to)
        if msg.src in self.registry._by_name:  # noqa: SLF001 — intentional
            self.registry.touch(msg.src)

        # Hypervisor-native participants (empty pane) receive MSG_SEND via the
        # bus broadcast already; no tmux delivery needed.
        if not target.pane:
            log.debug("send to hypervisor-native participant %s (bus broadcast)", to)
            return

        assert self._loop is not None
        self._loop.create_task(self._deliver(target.pane, to, content))

    # --- async workers ---

    async def _deliver(self, pane: str, to_name: str, content: str) -> None:
        # Defensive: _on_send should never call us with an empty pane.
        if not pane:
            log.error("_deliver called with empty pane for %s", to_name)
            return
        ok = await _tmux_send(pane, content)
        if not ok:
            log.error("tmux send-keys failed for pane %s", pane)
            return
        await asyncio.sleep(SEND_SETTLE_DELAY)
        captured = await _tmux_capture(pane)
        new_output = _diff_tail(self._last_capture.get(to_name, ""), captured)
        self._last_capture[to_name] = captured
        if new_output.strip():
            received = Message.create(
                src=BROKER_SRC,
                dst=None,
                msg_type=MSG_RECEIVED,
                payload={"from": to_name, "content": new_output},
            )
            self.bus.send(received)

    async def _pane_poller(self) -> None:
        while True:
            try:
                for participant in self.registry.list():
                    pane = participant.pane
                    # Hypervisor-native participants have no pane; they publish
                    # MSG_RECEIVED themselves. Only poll tmux panes.
                    if not pane:
                        continue
                    captured = await _tmux_capture(pane)
                    prev = self._last_capture.get(participant.name, "")
                    if captured and captured != prev:
                        new_output = _diff_tail(prev, captured)
                        self._last_capture[participant.name] = captured
                        if new_output.strip():
                            msg = Message.create(
                                src=BROKER_SRC,
                                dst=None,
                                msg_type=MSG_RECEIVED,
                                payload={"from": participant.name, "content": new_output},
                            )
                            self.bus.send(msg)
            except Exception:
                log.exception("pane poller error")
            await asyncio.sleep(self.poll_interval)

    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(self.gc_interval)
            dropped = self.registry.gc_stale()
            for name in dropped:
                log.info("gc dropped stale participant %s", name)
                self._last_capture.pop(name, None)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        server_task = asyncio.create_task(self.bus.start_server())
        await asyncio.sleep(0.2)

        ready = Message.create(
            src=BROKER_SRC,
            dst=None,
            msg_type=MSG_BROKER_READY,
            payload={},
        )
        self.bus.send(ready)
        log.info("broker_ready on %s", self.bus.socket_path)

        poll_task = asyncio.create_task(self._pane_poller())
        gc_task = asyncio.create_task(self._gc_loop())
        try:
            await server_task
        finally:
            poll_task.cancel()
            gc_task.cancel()


# --- tmux helpers (canonical target = session:window.pane) ---

async def _tmux_send(pane: str, content: str) -> bool:
    # -l sends literal text (no key-binding interpretation), then Enter.
    proc1 = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", pane, "-l", content,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _, err1 = await proc1.communicate()
    if proc1.returncode != 0:
        log.error("send-keys literal failed: %s", err1.decode(errors="replace"))
        return False
    proc2 = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", pane, "Enter",
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    _, err2 = await proc2.communicate()
    if proc2.returncode != 0:
        log.error("send-keys Enter failed: %s", err2.decode(errors="replace"))
        return False
    return True


async def _tmux_capture(pane: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "tmux", "capture-pane", "-t", pane, "-p", "-S", "-200",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return ""
    return out.decode(errors="replace")


def _diff_tail(prev: str, curr: str) -> str:
    # Prev is a suffix of curr in steady-state: return what's new.
    # Fallback: if prev isn't a clean prefix, publish the full current capture
    # so nothing is silently dropped.
    if not prev:
        return curr
    if curr.startswith(prev):
        return curr[len(prev):]
    i = 0
    max_i = min(len(prev), len(curr))
    while i < max_i and prev[i] == curr[i]:
        i += 1
    return curr[i:] if i > 0 else curr


def main() -> None:
    ap = argparse.ArgumentParser(description="Peer-mesh broker daemon")
    ap.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    ap.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    ap.add_argument("--gc-interval", type=float, default=DEFAULT_GC_INTERVAL)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bus = AsyncMessageBus(args.socket, agent_id=BROKER_SRC)
    registry = Registry()
    broker = Broker(bus, registry,
                    poll_interval=args.poll_interval,
                    gc_interval=args.gc_interval)
    try:
        asyncio.run(broker.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

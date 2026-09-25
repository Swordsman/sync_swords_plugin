#!/usr/bin/env python3
"""Generic mesh participant for testing same-CLI peer communication.

Usage:
    python mesh_participant.py --name kimi-a --socket /tmp/mesh_kimi_test.sock
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ai_hypervisor.message_bus import BusClient, Message
from ai_hypervisor.mesh_protocol import (
    MSG_REGISTER,
    MSG_SEND,
    MSG_RECEIVED,
    MSG_HEARTBEAT,
)

log = logging.getLogger("mesh_participant")


class MeshParticipant:
    def __init__(self, name: str, socket_path: Path):
        self.name = name
        self.socket_path = socket_path
        self.client = BusClient()
        self._received_messages = []

    async def run(self):
        await self.client.connect(self.socket_path)
        log.info("%s connected to %s", self.name, self.socket_path)

        # Register handlers
        self.client.register_handler(MSG_SEND, self._on_send)
        self.client.register_handler("*", self._on_any)

        # Send register message
        reg = Message.create(
            src=self.name,
            dst="broadcast",
            msg_type=MSG_REGISTER,
            payload={
                "name": self.name,
                "role": "agent",
                "pane": "",
                "capabilities": ["chat"],
            },
        )
        await self.client.send(reg)
        log.info("%s registered", self.name)

        # Keep alive
        try:
            while True:
                await asyncio.sleep(10)
                hb = Message.create(
                    src=self.name,
                    dst="broadcast",
                    msg_type=MSG_HEARTBEAT,
                    payload={"name": self.name},
                )
                await self.client.send(hb)
        except asyncio.CancelledError:
            pass
        finally:
            await self.client.disconnect()

    def _on_any(self, msg: Message):
        log.debug("[%s] * %s from=%s to=%s payload=%r",
                  self.name, msg.msg_type, msg.src, msg.dst, msg.payload)

    def _on_send(self, msg: Message):
        payload = msg.payload or {}
        to = payload.get("to")
        content = payload.get("content", "")
        sender = payload.get("from", msg.src)

        if to != self.name:
            return

        log.info("[%s] received MSG_SEND from=%s content=%r",
                 self.name, sender, content)
        self._received_messages.append((sender, content))

        # Reply with MSG_RECEIVED
        reply = Message.create(
            src=self.name,
            dst="broadcast",
            msg_type=MSG_RECEIVED,
            payload={
                "from": self.name,
                "content": f"{self.name} received: {content}",
            },
        )
        asyncio.create_task(self.client.send(reply))
        log.info("[%s] sent MSG_RECEIVED", self.name)


def main():
    ap = argparse.ArgumentParser(description="Mesh participant")
    ap.add_argument("--name", required=True, help="Participant name")
    ap.add_argument("--socket", type=Path, default="/tmp/mesh_bus.sock")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    participant = MeshParticipant(args.name, args.socket)
    try:
        asyncio.run(participant.run())
    except KeyboardInterrupt:
        log.info("%s shutting down", args.name)


if __name__ == "__main__":
    main()

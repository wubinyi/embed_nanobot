"""Mesh channel — bridges LAN mesh transport into the nanobot message bus.

This channel allows nanobot to receive commands from IoT devices on the LAN
and send responses back.  It also enables nanobot-to-nanobot communication
when multiple nanobots run on the same network.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.mesh.discovery import UDPDiscovery
from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.transport import MeshTransport


class MeshChannel(BaseChannel):
    """Chat channel that communicates over the LAN mesh."""

    name = "mesh"

    def __init__(
        self,
        config: Any,
        bus: MessageBus,
        *,
        node_id: str = "",
        tcp_port: int = 18800,
        udp_port: int = 18799,
    ):
        super().__init__(config, bus)
        self.node_id = node_id or getattr(config, "node_id", "") or _default_node_id()
        self.tcp_port = tcp_port or getattr(config, "tcp_port", 18800)
        self.udp_port = udp_port or getattr(config, "udp_port", 18799)
        roles = getattr(config, "roles", None) or ["nanobot"]

        self.discovery = UDPDiscovery(
            node_id=self.node_id,
            tcp_port=self.tcp_port,
            udp_port=self.udp_port,
            roles=roles,
        )
        self.transport = MeshTransport(
            node_id=self.node_id,
            discovery=self.discovery,
            tcp_port=self.tcp_port,
        )
        self.transport.on_message(self._on_mesh_message)

    # -- BaseChannel interface -----------------------------------------------

    async def start(self) -> None:
        """Start discovery and transport."""
        self._running = True
        await self.discovery.start()
        await self.transport.start()
        logger.info(
            f"[MeshChannel] started: node={self.node_id} "
            f"tcp={self.tcp_port} udp={self.udp_port}"
        )

    async def stop(self) -> None:
        self._running = False
        await self.transport.stop()
        await self.discovery.stop()
        logger.info("[MeshChannel] stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a response back to a mesh peer.

        ``msg.chat_id`` is the target node's ID.
        """
        env = MeshEnvelope(
            type=MsgType.RESPONSE,
            source=self.node_id,
            target=msg.chat_id,
            payload={"text": msg.content},
        )
        ok = await self.transport.send(env)
        if not ok:
            logger.warning(f"[MeshChannel] could not deliver to {msg.chat_id}")

    # -- inbound handling ----------------------------------------------------

    async def _on_mesh_message(self, env: MeshEnvelope) -> None:
        """Convert an incoming mesh envelope to an InboundMessage."""
        # Only route actionable types into the agent loop
        if env.type not in (MsgType.CHAT, MsgType.COMMAND):
            return
        content = env.payload.get("text", "")
        if not content:
            return
        await self._handle_message(
            sender_id=env.source,
            chat_id=env.source,  # replies go back to the source node
            content=content,
            metadata={"mesh_type": env.type, "mesh_ts": env.ts},
        )


def _default_node_id() -> str:
    """Generate a stable default node ID from the machine's hostname."""
    import socket

    return f"nanobot-{socket.gethostname()}"

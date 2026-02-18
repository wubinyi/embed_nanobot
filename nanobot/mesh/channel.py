"""Mesh channel — bridges LAN mesh transport into the nanobot message bus.

This channel allows nanobot to receive commands from IoT devices on the LAN
and send responses back.  It also enables nanobot-to-nanobot communication
when multiple nanobots run on the same network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.mesh.discovery import UDPDiscovery
from nanobot.mesh.enrollment import EnrollmentService
from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.security import KeyStore
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

        # --- embed_nanobot: PSK authentication (task 1.9) ---
        psk_auth_enabled = getattr(config, "psk_auth_enabled", True)
        allow_unauthenticated = getattr(config, "allow_unauthenticated", False)
        nonce_window = getattr(config, "nonce_window", 60)
        key_store_path = getattr(config, "key_store_path", "") or ""

        self.key_store: KeyStore | None = None
        if psk_auth_enabled:
            if not key_store_path:
                # Default: <workspace>/mesh_keys.json
                workspace = getattr(config, "_workspace_path", None)
                if workspace:
                    key_store_path = str(Path(workspace) / "mesh_keys.json")
                else:
                    key_store_path = str(
                        Path("~/.nanobot/workspace/mesh_keys.json").expanduser()
                    )
            self.key_store = KeyStore(path=key_store_path, nonce_window=nonce_window)
            self.key_store.load()

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
            key_store=self.key_store,
            psk_auth_enabled=psk_auth_enabled,
            allow_unauthenticated=allow_unauthenticated,
        )
        self.transport.on_message(self._on_mesh_message)

        # --- embed_nanobot: device enrollment (task 1.10) ---
        enrollment_pin_length = getattr(config, "enrollment_pin_length", 6)
        enrollment_pin_timeout = getattr(config, "enrollment_pin_timeout", 300)
        enrollment_max_attempts = getattr(config, "enrollment_max_attempts", 3)

        self.enrollment: EnrollmentService | None = None
        if psk_auth_enabled and self.key_store is not None:
            self.enrollment = EnrollmentService(
                key_store=self.key_store,
                transport=self.transport,
                node_id=self.node_id,
                pin_length=enrollment_pin_length,
                pin_timeout=enrollment_pin_timeout,
                max_attempts=enrollment_max_attempts,
            )
            self.transport.enrollment_service = self.enrollment

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
        # --- embed_nanobot: handle enrollment requests (task 1.10) ---
        if env.type == MsgType.ENROLL_REQUEST:
            if self.enrollment:
                await self.enrollment.handle_enroll_request(env)
            return

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

    # -- enrollment convenience ----------------------------------------------

    def create_enrollment_pin(self) -> tuple[str, float] | None:
        """Generate an enrollment PIN for device pairing.

        Returns ``(pin, expires_at)`` or ``None`` if enrollment is unavailable
        (e.g., PSK auth is disabled).
        """
        if self.enrollment is None:
            logger.warning("[MeshChannel] enrollment unavailable (PSK auth disabled)")
            return None
        return self.enrollment.create_pin()

    def cancel_enrollment_pin(self) -> bool:
        """Cancel the active enrollment PIN."""
        if self.enrollment is None:
            return False
        return self.enrollment.cancel_pin()


def _default_node_id() -> str:
    """Generate a stable default node ID from the machine's hostname."""
    import socket

    return f"nanobot-{socket.gethostname()}"

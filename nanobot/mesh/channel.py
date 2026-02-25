"""Mesh channel — bridges LAN mesh transport into the nanobot message bus.

This channel allows nanobot to receive commands from IoT devices on the LAN
and send responses back.  It also enables nanobot-to-nanobot communication
when multiple nanobots run on the same network.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.mesh.automation import AutomationEngine
from nanobot.mesh.ca import MeshCA, is_available as ca_is_available
from nanobot.mesh.commands import command_to_envelope
from nanobot.mesh.discovery import UDPDiscovery
from nanobot.mesh.enrollment import EnrollmentService
from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.registry import DeviceCapability, DeviceRegistry
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
        # --- embed_nanobot: mTLS certificate authority (task 3.1) ---
        mtls_enabled = getattr(config, "mtls_enabled", False) is True
        ca_dir = getattr(config, "ca_dir", "") or ""
        device_cert_validity_days = getattr(config, "device_cert_validity_days", None)
        if not isinstance(device_cert_validity_days, int) or device_cert_validity_days <= 0:
            device_cert_validity_days = 365

        self.ca: MeshCA | None = None
        server_ssl_ctx = None
        client_ssl_factory = None

        if mtls_enabled and ca_is_available():
            if not ca_dir:
                workspace = getattr(config, "_workspace_path", None)
                if workspace:
                    ca_dir = str(Path(workspace) / "mesh_ca")
                else:
                    ca_dir = str(
                        Path("~/.nanobot/workspace/mesh_ca").expanduser()
                    )
            self.ca = MeshCA(
                ca_dir=ca_dir,
                device_cert_validity_days=device_cert_validity_days,
            )
            self.ca.initialize()
            server_ssl_ctx = self.ca.create_server_ssl_context()
            client_ssl_factory = self._make_client_ssl

        # --- embed_nanobot: payload encryption (task 1.11) ---
        encryption_enabled = getattr(config, "encryption_enabled", True)
        self.transport = MeshTransport(
            node_id=self.node_id,
            discovery=self.discovery,
            tcp_port=self.tcp_port,
            key_store=self.key_store,
            psk_auth_enabled=psk_auth_enabled,
            allow_unauthenticated=allow_unauthenticated,
            encryption_enabled=encryption_enabled,
            server_ssl_context=server_ssl_ctx,
            client_ssl_context_factory=client_ssl_factory,
        )
        # --- embed_nanobot: CRL revocation check (task 3.2) ---
        if self.ca is not None:
            self.transport.revocation_check_fn = self.ca.is_revoked
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
                ca=self.ca,
            )
            self.transport.enrollment_service = self.enrollment

        # --- embed_nanobot: device registry (task 2.1) ---
        registry_path = getattr(config, "registry_path", "") or ""
        if not registry_path:
            workspace = getattr(config, "_workspace_path", None)
            if workspace:
                registry_path = str(Path(workspace) / "device_registry.json")
            else:
                registry_path = str(
                    Path("~/.nanobot/workspace/device_registry.json").expanduser()
                )
        self.registry = DeviceRegistry(path=registry_path)
        self.registry.load()

        # Hook discovery events to keep registry online/offline status in sync
        self.discovery.on_peer_seen(self._on_peer_seen)
        self.discovery.on_peer_lost(self._on_peer_lost)

        # --- embed_nanobot: automation rules engine (task 2.6) ---
        automation_rules_path = getattr(config, "automation_rules_path", "") or ""
        if not automation_rules_path:
            workspace = getattr(config, "_workspace_path", None)
            if workspace:
                automation_rules_path = str(Path(workspace) / "automation_rules.json")
            else:
                automation_rules_path = str(
                    Path("~/.nanobot/workspace/automation_rules.json").expanduser()
                )
        self.automation = AutomationEngine(self.registry, path=automation_rules_path)
        self.automation.load()

    # -- mTLS helpers --------------------------------------------------------

    def _make_client_ssl(self, target_node_id: str) -> ssl.SSLContext | None:
        """Create a client SSL context for connecting to *target_node_id*."""
        if self.ca is None:
            return None
        # Use the Hub's own cert for outgoing mTLS connections.
        return self.ca.create_client_ssl_context("hub")

    # -- embed_nanobot: certificate revocation (task 3.2) --------------------

    async def revoke_device(self, node_id: str, *, remove_from_registry: bool = False) -> bool:
        """Revoke a device's certificate.

        The revocation takes effect immediately for new connections because
        the transport checks ``ca.is_revoked()`` on each inbound connection
        (application-level CRL enforcement).

        Parameters
        ----------
        node_id:
            The device whose certificate should be revoked.
        remove_from_registry:
            If ``True``, also remove the device from the device registry.

        Returns ``True`` if the certificate was revoked, ``False`` if the
        device has no certificate or is already revoked.
        """
        if self.ca is None:
            logger.warning("[MeshChannel] cannot revoke — mTLS not enabled")
            return False

        revoked = self.ca.revoke_device_cert(node_id)
        if not revoked:
            return False

        if remove_from_registry:
            await self.registry.remove_device(node_id)
            logger.info("[MeshChannel] device {} removed from registry", node_id)

        return True

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

        # --- embed_nanobot: handle state reports (task 2.1) ---
        if env.type == MsgType.STATE_REPORT:
            await self._handle_state_report(env)
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

    # -- device registry convenience -----------------------------------------

    async def _handle_state_report(self, env: MeshEnvelope) -> None:
        """Process a STATE_REPORT message and update the device registry."""
        state_data = env.payload.get("state", {})
        if not state_data:
            logger.debug(f"[MeshChannel] empty STATE_REPORT from {env.source}")
            return
        updated = await self.registry.update_state(env.source, state_data)
        if not updated:
            logger.warning(
                f"[MeshChannel] STATE_REPORT from unregistered device {env.source}"
            )
            return

        # --- embed_nanobot: evaluate automation rules (task 2.6) ---
        if self.automation:
            commands = self.automation.evaluate(env.source)
            for cmd in commands:
                envelope = command_to_envelope(cmd, source=self.node_id)
                ok = await self.transport.send(envelope)
                if not ok:
                    logger.warning(
                        f"[MeshChannel] automation dispatch failed: "
                        f"{cmd.action} {cmd.device}.{cmd.capability}"
                    )

    def _on_peer_seen(self, node_id: str, is_new: bool, beacon: dict) -> None:
        """Called by discovery when a peer beacon is received."""
        self.registry.mark_online(node_id)

        # Auto-register device if beacon includes device info and it's unknown
        if is_new or self.registry.get_device(node_id) is None:
            device_type = beacon.get("device_type", "")
            raw_caps = beacon.get("capabilities", [])
            if device_type and raw_caps:
                caps = []
                for c in raw_caps:
                    try:
                        caps.append(DeviceCapability.from_dict(c))
                    except (KeyError, TypeError):
                        pass
                # Schedule async registration
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        self.registry.register_device(
                            node_id,
                            device_type,
                            capabilities=caps,
                            metadata=beacon.get("metadata", {}),
                        )
                    )
                except RuntimeError:
                    pass  # No running loop — skip auto-registration

    def _on_peer_lost(self, node_id: str) -> None:
        """Called by discovery when a peer is pruned as offline."""
        self.registry.mark_offline(node_id)

    def get_device_summary(self) -> str:
        """Return human-readable device summary for LLM context."""
        return self.registry.summary()


def _default_node_id() -> str:
    """Generate a stable default node ID from the machine's hostname."""
    import socket

    return f"nanobot-{socket.gethostname()}"

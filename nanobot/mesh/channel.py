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
from nanobot.mesh.ble import BLEBridge
from nanobot.mesh.ca import MeshCA, is_available as ca_is_available
from nanobot.mesh.commands import command_to_envelope
from nanobot.mesh.dashboard import MeshDashboard
from nanobot.mesh.discovery import UDPDiscovery
from nanobot.mesh.enrollment import EnrollmentService
from nanobot.mesh.federation import FederationManager
from nanobot.mesh.groups import GroupManager
from nanobot.mesh.industrial import IndustrialBridge
from nanobot.mesh.pipeline import SensorPipeline
from nanobot.mesh.ota import FirmwareStore, OTAManager, OTASession
from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.registry import DeviceCapability, DeviceRegistry
from nanobot.mesh.resilience import supervised_task
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

        # --- embed_nanobot: OTA firmware update (task 3.3) ---
        firmware_dir = getattr(config, "firmware_dir", "") or ""
        ota_chunk_size = getattr(config, "ota_chunk_size", 4096)
        ota_chunk_timeout = getattr(config, "ota_chunk_timeout", 30)

        self.firmware_store: FirmwareStore | None = None
        self.ota: OTAManager | None = None
        if firmware_dir:
            self.firmware_store = FirmwareStore(firmware_dir)
            self.firmware_store.load()
            self.ota = OTAManager(
                store=self.firmware_store,
                send_fn=self.transport.send,
                node_id=self.node_id,
                chunk_size=ota_chunk_size,
                chunk_ack_timeout=ota_chunk_timeout,
            )

        # --- embed_nanobot: device grouping and scenes (task 3.4) ---
        groups_path = getattr(config, "groups_path", "") or ""
        scenes_path = getattr(config, "scenes_path", "") or ""
        if not groups_path:
            workspace = getattr(config, "_workspace_path", None)
            if workspace:
                groups_path = str(Path(workspace) / "device_groups.json")
            else:
                groups_path = str(
                    Path("~/.nanobot/workspace/device_groups.json").expanduser()
                )
        if not scenes_path:
            workspace = getattr(config, "_workspace_path", None)
            if workspace:
                scenes_path = str(Path(workspace) / "device_scenes.json")
            else:
                scenes_path = str(
                    Path("~/.nanobot/workspace/device_scenes.json").expanduser()
                )
        self.groups = GroupManager(groups_path, scenes_path)
        self.groups.load()

        # --- embed_nanobot: monitoring dashboard (task 3.6) ---
        _raw_port = getattr(config, "dashboard_port", 0)
        dashboard_port = _raw_port if isinstance(_raw_port, int) else 0
        self.dashboard: MeshDashboard | None = None
        if dashboard_port > 0:
            self.dashboard = MeshDashboard(
                port=dashboard_port,
                data_fn=lambda: {
                    "registry": self.registry,
                    "discovery": self.discovery,
                    "groups": self.groups,
                    "automation": self.automation,
                    "ota": self.ota,
                    "firmware_store": self.firmware_store,
                    "node_id": self.node_id,
                    "pipeline": self.pipeline,
                },
            )

        # --- embed_nanobot: PLC/industrial integration (task 4.1) ---
        industrial_config_path = getattr(config, "industrial_config_path", "") or ""
        self.industrial: IndustrialBridge | None = None
        if industrial_config_path:
            self.industrial = IndustrialBridge(
                config_path=industrial_config_path,
                registry=self.registry,
                on_state_update=self._on_industrial_state_update,
            )
            self.industrial.load()

        # --- embed_nanobot: hub-to-hub federation (task 4.2) ---
        federation_config_path = getattr(config, "federation_config_path", "") or ""
        self.federation: FederationManager | None = None
        if federation_config_path:
            self.federation = FederationManager(
                hub_id=self.node_id,
                config_path=federation_config_path,
                registry=self.registry,
                on_remote_state=self._on_federation_state_update,
            )
            self.federation.set_local_command_handler(self._execute_local_command)
            self.federation.load()

        # --- embed_nanobot: sensor data pipeline (task 4.4) ---
        pipeline_enabled = getattr(config, "pipeline_enabled", False) is True
        pipeline_path = getattr(config, "pipeline_path", "") or ""
        _raw_max = getattr(config, "pipeline_max_points", 10000)
        pipeline_max_points = _raw_max if isinstance(_raw_max, int) else 10000
        _raw_flush = getattr(config, "pipeline_flush_interval", 60)
        pipeline_flush_interval = _raw_flush if isinstance(_raw_flush, int) else 60
        self.pipeline: SensorPipeline | None = None
        if pipeline_enabled:
            if not pipeline_path:
                workspace = getattr(config, "_workspace_path", None)
                if workspace:
                    pipeline_path = str(Path(workspace) / "sensor_data.json")
                else:
                    pipeline_path = str(
                        Path("~/.nanobot/workspace/sensor_data.json").expanduser()
                    )
            self.pipeline = SensorPipeline(
                path=pipeline_path,
                max_points=pipeline_max_points,
                flush_interval=float(pipeline_flush_interval),
            )
            self.pipeline.load()

        # --- embed_nanobot: BLE sensor support (task 4.5) ---
        ble_config_path = getattr(config, "ble_config_path", "") or ""
        self.ble: BLEBridge | None = None
        if ble_config_path:
            self.ble = BLEBridge(
                config_path=ble_config_path,
                registry=self.registry,
                on_state_update=self._on_ble_state_update,
            )
            self.ble.load()

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
        """Start discovery and transport with error isolation."""
        self._running = True
        try:
            await self.discovery.start()
        except Exception as exc:
            logger.error("[MeshChannel] discovery start failed: {}", exc)
            self._running = False
            raise
        try:
            await self.transport.start()
        except Exception as exc:
            logger.error("[MeshChannel] transport start failed, stopping discovery: {}", exc)
            try:
                await self.discovery.stop()
            except Exception:
                pass
            self._running = False
            raise
        # --- embed_nanobot: monitoring dashboard (task 3.6) ---
        if self.dashboard is not None:
            try:
                await self.dashboard.start()
            except Exception as exc:
                logger.error("[MeshChannel] dashboard start failed: {}", exc)
        # --- embed_nanobot: PLC/industrial integration (task 4.1) ---
        if self.industrial is not None:
            try:
                await self.industrial.start()
            except Exception as exc:
                logger.error("[MeshChannel] industrial bridge start failed: {}", exc)
        # --- embed_nanobot: hub-to-hub federation (task 4.2) ---
        if self.federation is not None:
            try:
                await self.federation.start()
            except Exception as exc:
                logger.error("[MeshChannel] federation start failed: {}", exc)
        # --- embed_nanobot: sensor data pipeline (task 4.4) ---
        if self.pipeline is not None:
            try:
                await self.pipeline.start()
            except Exception as exc:
                logger.error("[MeshChannel] pipeline start failed: {}", exc)
        # --- embed_nanobot: BLE sensor support (task 4.5) ---
        if self.ble is not None:
            try:
                await self.ble.start()
            except Exception as exc:
                logger.error("[MeshChannel] BLE bridge start failed: {}", exc)
        logger.info(
            f"[MeshChannel] started: node={self.node_id} "
            f"tcp={self.tcp_port} udp={self.udp_port}"
        )

    async def stop(self) -> None:
        self._running = False
        # Stop transport first (it depends on discovery), then discovery.
        # Errors in one should not prevent stopping the other.
        try:
            await self.transport.stop()
        except Exception as exc:
            logger.error("[MeshChannel] transport stop error: {}", exc)
        try:
            await self.discovery.stop()
        except Exception as exc:
            logger.error("[MeshChannel] discovery stop error: {}", exc)
        # --- embed_nanobot: monitoring dashboard (task 3.6) ---
        if self.dashboard is not None:
            try:
                await self.dashboard.stop()
            except Exception as exc:
                logger.error("[MeshChannel] dashboard stop error: {}", exc)
        # --- embed_nanobot: PLC/industrial integration (task 4.1) ---
        if self.industrial is not None:
            try:
                await self.industrial.stop()
            except Exception as exc:
                logger.error("[MeshChannel] industrial bridge stop error: {}", exc)
        # --- embed_nanobot: hub-to-hub federation (task 4.2) ---
        if self.federation is not None:
            try:
                await self.federation.stop()
            except Exception as exc:
                logger.error("[MeshChannel] federation stop error: {}", exc)
        # --- embed_nanobot: sensor data pipeline (task 4.4) ---
        if self.pipeline is not None:
            try:
                await self.pipeline.stop()
            except Exception as exc:
                logger.error("[MeshChannel] pipeline stop error: {}", exc)
        # --- embed_nanobot: BLE sensor support (task 4.5) ---
        if self.ble is not None:
            try:
                await self.ble.stop()
            except Exception as exc:
                logger.error("[MeshChannel] BLE bridge stop error: {}", exc)
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

        # --- embed_nanobot: handle OTA messages (task 3.3) ---
        _OTA_TYPES = (
            MsgType.OTA_ACCEPT, MsgType.OTA_REJECT,
            MsgType.OTA_CHUNK_ACK, MsgType.OTA_VERIFY, MsgType.OTA_ABORT,
        )
        if env.type in _OTA_TYPES:
            if self.ota:
                await self.ota.handle_ota_message(env)
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

        # --- embed_nanobot: record sensor data (task 4.4) ---
        if self.pipeline is not None:
            self.pipeline.record_state(env.source, state_data)

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

        # --- embed_nanobot: propagate state to federated hubs (task 4.2) ---
        if self.federation:
            supervised_task(
                self.federation.broadcast_state_update(env.source, state_data),
                name=f"federation-state-{env.source}",
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
                # Schedule async registration — supervised to catch errors
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    supervised_task(
                        self.registry.register_device(
                            node_id,
                            device_type,
                            capabilities=caps,
                            metadata=beacon.get("metadata", {}),
                        ),
                        name=f"auto-register-{node_id}",
                    )
                except RuntimeError:
                    pass  # No running loop — skip auto-registration

    def _on_peer_lost(self, node_id: str) -> None:
        """Called by discovery when a peer is pruned as offline."""
        self.registry.mark_offline(node_id)

    def get_device_summary(self) -> str:
        """Return human-readable device summary for LLM context."""
        return self.registry.summary()

    # -- OTA convenience methods (task 3.3) ----------------------------------

    async def start_ota_update(
        self, node_id: str, firmware_id: str, *, chunk_size: int | None = None,
    ) -> OTASession | None:
        """Initiate an OTA update for a device. Returns session or None."""
        if self.ota is None:
            logger.warning("[MeshChannel] OTA unavailable (firmware_dir not set)")
            return None
        return await self.ota.start_update(node_id, firmware_id, chunk_size=chunk_size)

    async def abort_ota_update(self, node_id: str, reason: str = "cancelled") -> bool:
        """Abort an active OTA update. Returns True if found."""
        if self.ota is None:
            return False
        return await self.ota.abort_update(node_id, reason)

    def get_ota_status(self, node_id: str) -> dict | None:
        """Return OTA update status for a device."""
        if self.ota is None:
            return None
        return self.ota.get_status(node_id)

    # -- Groups/Scenes convenience methods (task 3.4) -----------------------

    async def execute_scene(self, scene_id: str) -> list[bool]:
        """Execute all commands in a scene. Returns per-command send results."""
        commands = self.groups.get_scene_commands(scene_id)
        if not commands:
            return []
        results: list[bool] = []
        for cmd in commands:
            env = command_to_envelope(cmd, source=self.node_id)
            ok = await self.transport.send(env)
            results.append(ok)
        return results

    async def execute_group_command(
        self,
        group_id: str,
        action: str,
        capability: str = "",
        params: dict | None = None,
    ) -> list[bool]:
        """Fan out a command to all devices in a group. Returns per-device send results."""
        commands = self.groups.fan_out_group_command(group_id, action, capability, params)
        if not commands:
            return []
        results: list[bool] = []
        for cmd in commands:
            env = command_to_envelope(cmd, source=self.node_id)
            ok = await self.transport.send(env)
            results.append(ok)
        return results

    # -- Industrial/PLC convenience methods (task 4.1) -----------------------

    def _on_industrial_state_update(self, node_id: str, state: dict) -> None:
        """Callback from IndustrialBridge after polling. Triggers automation."""
        if self.automation:
            commands = self.automation.evaluate(node_id)
            for cmd in commands:
                # Industrial commands go through the bridge, not mesh transport
                if self.industrial and self.industrial.is_industrial_device(cmd.device):
                    supervised_task(
                        self.industrial.execute_command(
                            cmd.device, cmd.capability, cmd.params.get("value"),
                        ),
                        name=f"industrial-cmd-{cmd.device}",
                    )
                else:
                    env = command_to_envelope(cmd, source=self.node_id)
                    supervised_task(
                        self.transport.send(env),
                        name=f"automation-cmd-{cmd.device}",
                    )

    async def execute_industrial_command(
        self, node_id: str, capability: str, value: Any,
    ) -> bool:
        """Write a value to a PLC device. Returns True on success."""
        if self.industrial is None:
            logger.warning("[MeshChannel] industrial bridge not configured")
            return False
        return await self.industrial.execute_command(node_id, capability, value)

    # -- Federation convenience methods (task 4.2) --------------------------

    async def _execute_local_command(
        self, node_id: str, capability: str, value: Any,
    ) -> bool:
        """Execute a command on a local device (called by federation for forwarded commands)."""
        # Try industrial bridge first
        if self.industrial and self.industrial.is_industrial_device(node_id):
            return await self.industrial.execute_command(node_id, capability, value)
        # Fall back to mesh transport
        from nanobot.mesh.commands import DeviceCommand
        cmd = DeviceCommand(
            device=node_id,
            action="set",
            capability=capability,
            params={"value": value},
        )
        env = command_to_envelope(cmd, source=self.node_id)
        return await self.transport.send(env)

    def _on_federation_state_update(self, node_id: str, state: dict) -> None:
        """Callback from FederationManager when a remote device state changes."""
        if self.automation:
            commands = self.automation.evaluate(node_id)
            for cmd in commands:
                # Route command to appropriate destination
                if self.industrial and self.industrial.is_industrial_device(cmd.device):
                    supervised_task(
                        self.industrial.execute_command(
                            cmd.device, cmd.capability, cmd.params.get("value"),
                        ),
                        name=f"fed-industrial-cmd-{cmd.device}",
                    )
                elif self.federation and self.federation.is_remote_device(cmd.device):
                    supervised_task(
                        self.federation.forward_command(
                            cmd.device, cmd.capability, cmd.params.get("value"),
                        ),
                        name=f"fed-forward-cmd-{cmd.device}",
                    )
                else:
                    env = command_to_envelope(cmd, source=self.node_id)
                    supervised_task(
                        self.transport.send(env),
                        name=f"fed-local-cmd-{cmd.device}",
                    )

    async def forward_to_federation(
        self, node_id: str, capability: str, value: Any,
    ) -> bool:
        """Forward a command to a device on a remote hub. Returns True on success."""
        if self.federation is None:
            logger.warning("[MeshChannel] federation not configured")
            return False
        return await self.federation.forward_command(node_id, capability, value)

    # -- BLE convenience methods (task 4.5) ---------------------------------

    def _on_ble_state_update(self, node_id: str, state: dict) -> None:
        """Callback from BLEBridge after scan. Records to pipeline and runs automation."""
        # Record to sensor pipeline
        if self.pipeline is not None:
            self.pipeline.record_state(node_id, state)

        # Evaluate automation rules
        if self.automation:
            commands = self.automation.evaluate(node_id)
            for cmd in commands:
                env = command_to_envelope(cmd, source=self.node_id)
                supervised_task(
                    self.transport.send(env),
                    name=f"ble-automation-cmd-{cmd.device}",
                )


def _default_node_id() -> str:
    """Generate a stable default node ID from the machine's hostname."""
    import socket

    return f"nanobot-{socket.gethostname()}"

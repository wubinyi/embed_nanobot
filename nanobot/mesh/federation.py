"""Multi-Hub federation — hub-to-hub mesh for cross-subnet device access.

When multiple nanobot hubs run on different subnets (floors, buildings, sites),
federation allows them to:

1. Share device registries so every hub sees all devices
2. Forward commands to devices on remote hubs
3. Propagate state changes across hubs for cross-hub automation

Each hub maintains persistent TCP connections to its configured peer hubs.
The wire protocol reuses the existing length-prefixed JSON format from
``nanobot.mesh.protocol``.

Configuration
-------------
Set ``federation_config_path`` in MeshConfig to point to a JSON file:

.. code-block:: json

   {
     "peers": [
       {"hub_id": "factory-2", "host": "192.168.2.100", "port": 18800}
     ],
     "sync_interval": 30.0
   }
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.mesh.protocol import MeshEnvelope, MsgType, read_envelope, write_envelope


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FederationPeerConfig:
    """Static configuration for one peer hub."""

    hub_id: str
    host: str
    port: int = 18800

    @classmethod
    def from_dict(cls, data: dict) -> "FederationPeerConfig":
        return cls(
            hub_id=data["hub_id"],
            host=data["host"],
            port=int(data.get("port", 18800)),
        )


@dataclass
class FederationConfig:
    """Top-level federation config parsed from JSON file."""

    peers: list[FederationPeerConfig] = field(default_factory=list)
    sync_interval: float = 30.0

    @classmethod
    def from_dict(cls, data: dict) -> "FederationConfig":
        peers = [FederationPeerConfig.from_dict(p) for p in data.get("peers", [])]
        return cls(
            peers=peers,
            sync_interval=float(data.get("sync_interval", 30.0)),
        )


# ---------------------------------------------------------------------------
# HubLink — persistent TCP connection to one peer hub
# ---------------------------------------------------------------------------

class HubLink:
    """Persistent bidirectional TCP connection to a single peer hub.

    On connection, sends a ``FEDERATION_HELLO`` to identify ourselves.
    Runs a background receive loop that dispatches inbound messages to
    callbacks registered via ``on_message()``.
    Automatically reconnects on connection loss with exponential backoff.
    """

    RECONNECT_BASE: float = 2.0
    RECONNECT_MAX: float = 60.0
    CONNECT_TIMEOUT: float = 10.0
    PING_INTERVAL: float = 15.0

    def __init__(
        self,
        peer: FederationPeerConfig,
        local_hub_id: str,
    ) -> None:
        self.peer = peer
        self.local_hub_id = local_hub_id
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._running = False
        self._recv_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._handlers: list[Callable[[MeshEnvelope], Any]] = []
        self._connected = False
        self._reconnect_delay = self.RECONNECT_BASE

    # -- public API ---

    @property
    def connected(self) -> bool:
        return self._connected

    def on_message(self, handler: Callable[[MeshEnvelope], Any]) -> None:
        """Register a callback for inbound envelopes from this hub."""
        self._handlers.append(handler)

    async def start(self) -> None:
        """Start the link — connect and begin receive loop."""
        self._running = True
        await self._connect()
        if not self._connected:
            # Schedule reconnect in background
            self._schedule_reconnect()

    async def stop(self) -> None:
        """Stop the link and close the connection."""
        self._running = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            try:
                await self._ping_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._close_connection()

    async def send(self, env: MeshEnvelope) -> bool:
        """Send an envelope to the peer hub. Returns True on success."""
        if not self._connected or self._writer is None:
            return False
        try:
            write_envelope(self._writer, env)
            await self._writer.drain()
            return True
        except (OSError, ConnectionError) as exc:
            logger.warning(
                "[Federation/Link] send to {} failed: {}",
                self.peer.hub_id, exc,
            )
            await self._on_connection_lost()
            return False

    # -- connection management ---

    async def _connect(self) -> None:
        """Attempt to connect to the peer hub."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.peer.host, self.peer.port),
                timeout=self.CONNECT_TIMEOUT,
            )
            self._connected = True
            self._reconnect_delay = self.RECONNECT_BASE
            logger.info(
                "[Federation/Link] connected to {} @ {}:{}",
                self.peer.hub_id, self.peer.host, self.peer.port,
            )
            # Send hello
            hello = MeshEnvelope(
                type=MsgType.FEDERATION_HELLO.value,
                source=self.local_hub_id,
                target=self.peer.hub_id,
                payload={"hub_id": self.local_hub_id},
            )
            write_envelope(self._writer, hello)
            await self._writer.drain()
            # Start receive loop and ping loop
            self._recv_task = asyncio.ensure_future(self._receive_loop())
            self._ping_task = asyncio.ensure_future(self._ping_loop())
        except (OSError, asyncio.TimeoutError) as exc:
            logger.warning(
                "[Federation/Link] connect to {} @ {}:{} failed: {}",
                self.peer.hub_id, self.peer.host, self.peer.port, exc,
            )
            self._connected = False

    async def _close_connection(self) -> None:
        """Close the TCP connection if open."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, Exception):
                pass
            self._writer = None
        self._reader = None

    async def _on_connection_lost(self) -> None:
        """Handle unexpected connection loss."""
        await self._close_connection()
        if self._running:
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnect attempt with exponential backoff."""
        if not self._running:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already scheduled

        async def _reconnect() -> None:
            while self._running and not self._connected:
                logger.info(
                    "[Federation/Link] reconnecting to {} in {:.0f}s",
                    self.peer.hub_id, self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                if not self._running:
                    break
                await self._connect()
                if not self._connected:
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2,
                        self.RECONNECT_MAX,
                    )

        self._reconnect_task = asyncio.ensure_future(_reconnect())

    # -- receive loop ---

    async def _receive_loop(self) -> None:
        """Read envelopes from the peer hub until connection closes."""
        try:
            while self._running and self._reader:
                env = await read_envelope(self._reader)
                if env is None:
                    break  # EOF or malformed data
                for handler in self._handlers:
                    try:
                        result = handler(env)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        logger.error(
                            "[Federation/Link] handler error for {}: {}",
                            self.peer.hub_id, exc,
                        )
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        except (OSError, ConnectionError) as exc:
            logger.warning(
                "[Federation/Link] receive from {} lost: {}",
                self.peer.hub_id, exc,
            )
        finally:
            if self._running:
                await self._on_connection_lost()

    # -- ping loop ---

    async def _ping_loop(self) -> None:
        """Send periodic pings to detect dead connections."""
        try:
            while self._running and self._connected:
                await asyncio.sleep(self.PING_INTERVAL)
                if not self._running or not self._connected:
                    break
                ping = MeshEnvelope(
                    type=MsgType.FEDERATION_PING.value,
                    source=self.local_hub_id,
                    target=self.peer.hub_id,
                )
                ok = await self.send(ping)
                if not ok:
                    break
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# FederationManager — orchestrates hub-to-hub communication
# ---------------------------------------------------------------------------

class FederationManager:
    """Manages hub-to-hub federation for cross-subnet device access.

    Parameters
    ----------
    hub_id:
        This hub's unique identifier (same as mesh node_id).
    config_path:
        Path to the federation JSON configuration file.
    registry:
        Reference to the local DeviceRegistry for syncing.
    on_remote_state:
        Callback ``(node_id: str, state: dict) → None`` invoked when a
        remote device's state changes.
    """

    def __init__(
        self,
        hub_id: str,
        config_path: str,
        registry: Any = None,
        on_remote_state: Callable[[str, dict], Any] | None = None,
    ) -> None:
        self.hub_id = hub_id
        self.config_path = config_path
        self.registry = registry
        self.on_remote_state = on_remote_state

        self._config: FederationConfig | None = None
        self._links: dict[str, HubLink] = {}  # hub_id → HubLink
        # Remote devices: hub_id → {node_id → device_info_dict}
        self._remote_devices: dict[str, dict[str, dict]] = {}
        # Reverse lookup: node_id → hub_id
        self._device_hub_map: dict[str, str] = {}
        self._sync_task: asyncio.Task | None = None
        self._running = False
        # Pending command futures: (node_id, capability) → asyncio.Future
        self._pending_commands: dict[tuple[str, str], asyncio.Future] = {}
        # Inbound connection handler (for hubs that connect to us)
        self._inbound_links: dict[str, HubLink] = {}

    # -- config loading ---

    def load(self) -> int:
        """Load federation config from JSON file.

        Returns the number of peer hubs configured, or 0 on error.
        """
        path = Path(self.config_path)
        if not path.exists():
            logger.warning(
                "[Federation] config file not found: {}", self.config_path,
            )
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._config = FederationConfig.from_dict(data)
            logger.info(
                "[Federation] loaded config: {} peers, sync interval {}s",
                len(self._config.peers), self._config.sync_interval,
            )
            return len(self._config.peers)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("[Federation] failed to parse config: {}", exc)
            return 0

    # -- lifecycle ---

    async def start(self) -> None:
        """Connect to all peer hubs and start the sync loop."""
        if not self._config or not self._config.peers:
            logger.info("[Federation] no peers configured, skipping start")
            return
        self._running = True
        # Create and start links
        for peer_cfg in self._config.peers:
            link = HubLink(peer_cfg, self.hub_id)
            link.on_message(self._handle_message)
            self._links[peer_cfg.hub_id] = link
            await link.start()
        # Start sync loop
        self._sync_task = asyncio.ensure_future(self._sync_loop())
        logger.info(
            "[Federation] started with {} peer hubs",
            len(self._links),
        )

    async def stop(self) -> None:
        """Disconnect from all peer hubs and stop sync."""
        self._running = False
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except (asyncio.CancelledError, Exception):
                pass
        # Cancel pending command futures
        for key, fut in self._pending_commands.items():
            if not fut.done():
                fut.cancel()
        self._pending_commands.clear()
        # Stop all links
        for link in self._links.values():
            await link.stop()
        self._links.clear()
        self._remote_devices.clear()
        self._device_hub_map.clear()
        logger.info("[Federation] stopped")

    # -- sync loop ---

    async def _sync_loop(self) -> None:
        """Periodically sync our device registry to all peer hubs."""
        try:
            while self._running:
                interval = (
                    self._config.sync_interval if self._config else 30.0
                )
                await asyncio.sleep(interval)
                if not self._running:
                    break
                await self._broadcast_registry_sync()
        except asyncio.CancelledError:
            pass

    async def _broadcast_registry_sync(self) -> None:
        """Send our device registry snapshot to all connected peer hubs."""
        devices = self._get_local_device_list()
        for hub_id, link in self._links.items():
            if not link.connected:
                continue
            env = MeshEnvelope(
                type=MsgType.FEDERATION_SYNC.value,
                source=self.hub_id,
                target=hub_id,
                payload={"hub_id": self.hub_id, "devices": devices},
            )
            await link.send(env)

    def _get_local_device_list(self) -> list[dict]:
        """Build a snapshot of local devices for syncing."""
        if self.registry is None:
            return []
        devices = []
        try:
            for node_id, info in self.registry.devices.items():
                dev = {
                    "node_id": info.node_id,
                    "device_type": info.device_type,
                    "name": getattr(info, "name", info.node_id),
                    "online": info.online,
                    "state": dict(info.state) if info.state else {},
                    "capabilities": [
                        {
                            "name": c.name,
                            "cap_type": c.cap_type,
                            "value_range": c.value_range,
                            "unit": c.unit,
                        }
                        for c in info.capabilities
                    ],
                }
                devices.append(dev)
        except Exception as exc:
            logger.error("[Federation] error building device list: {}", exc)
        return devices

    # -- message handling ---

    async def _handle_message(self, env: MeshEnvelope) -> None:
        """Dispatch an inbound federation message from a peer hub."""
        msg_type = env.type
        if msg_type == MsgType.FEDERATION_HELLO.value:
            self._handle_hello(env)
        elif msg_type == MsgType.FEDERATION_SYNC.value:
            self._handle_sync(env)
        elif msg_type == MsgType.FEDERATION_COMMAND.value:
            await self._handle_command(env)
        elif msg_type == MsgType.FEDERATION_RESPONSE.value:
            self._handle_response(env)
        elif msg_type == MsgType.FEDERATION_STATE.value:
            await self._handle_state(env)
        elif msg_type == MsgType.FEDERATION_PING.value:
            await self._handle_ping(env)
        elif msg_type == MsgType.FEDERATION_PONG.value:
            pass  # Just confirms link is alive
        else:
            logger.debug(
                "[Federation] unknown message type from {}: {}",
                env.source, msg_type,
            )

    def _handle_hello(self, env: MeshEnvelope) -> None:
        """Process a FEDERATION_HELLO from a peer hub."""
        remote_hub = env.payload.get("hub_id", env.source)
        logger.info("[Federation] received hello from hub: {}", remote_hub)

    def _handle_sync(self, env: MeshEnvelope) -> None:
        """Process a FEDERATION_SYNC — update our view of remote devices."""
        remote_hub = env.payload.get("hub_id", env.source)
        devices = env.payload.get("devices", [])
        # Clear old entries for this hub
        old_nodes = set(self._remote_devices.get(remote_hub, {}).keys())
        new_map: dict[str, dict] = {}
        for dev in devices:
            node_id = dev.get("node_id", "")
            if node_id:
                new_map[node_id] = dev
                self._device_hub_map[node_id] = remote_hub
        # Remove stale entries from reverse map
        removed = old_nodes - set(new_map.keys())
        for node_id in removed:
            self._device_hub_map.pop(node_id, None)
        self._remote_devices[remote_hub] = new_map
        logger.debug(
            "[Federation] synced {} devices from hub {}",
            len(new_map), remote_hub,
        )

    async def _handle_command(self, env: MeshEnvelope) -> None:
        """Process a FEDERATION_COMMAND — execute on local device."""
        node_id = env.payload.get("target_node", "")
        capability = env.payload.get("capability", "")
        value = env.payload.get("value")
        requesting_hub = env.source
        success = False
        result_value = None
        error = ""
        # Try to execute locally via the command callback
        if self._execute_local_command:
            try:
                success = await self._execute_local_command(
                    node_id, capability, value,
                )
                if success and self.registry:
                    dev = self.registry.get_device(node_id)
                    if dev:
                        result_value = dev.state.get(capability)
            except Exception as exc:
                error = str(exc)
        # Send response back
        resp = MeshEnvelope(
            type=MsgType.FEDERATION_RESPONSE.value,
            source=self.hub_id,
            target=requesting_hub,
            payload={
                "target_node": node_id,
                "capability": capability,
                "success": success,
                "value": result_value,
                "error": error,
            },
        )
        link = self._links.get(requesting_hub)
        if link and link.connected:
            await link.send(resp)

    def _handle_response(self, env: MeshEnvelope) -> None:
        """Process a FEDERATION_RESPONSE — resolve pending command future."""
        node_id = env.payload.get("target_node", "")
        capability = env.payload.get("capability", "")
        key = (node_id, capability)
        fut = self._pending_commands.pop(key, None)
        if fut and not fut.done():
            fut.set_result(env.payload.get("success", False))

    async def _handle_state(self, env: MeshEnvelope) -> None:
        """Process a FEDERATION_STATE — update remote device state."""
        node_id = env.payload.get("node_id", "")
        state = env.payload.get("state", {})
        remote_hub = env.payload.get("hub_id", env.source)
        # Update our view
        if remote_hub in self._remote_devices:
            dev = self._remote_devices[remote_hub].get(node_id)
            if dev:
                dev["state"] = state
        # Notify callback
        if self.on_remote_state and node_id and state:
            try:
                result = self.on_remote_state(node_id, state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "[Federation] remote state callback error: {}", exc,
                )

    async def _handle_ping(self, env: MeshEnvelope) -> None:
        """Respond to a FEDERATION_PING with PONG."""
        link = self._links.get(env.source)
        if link and link.connected:
            pong = MeshEnvelope(
                type=MsgType.FEDERATION_PONG.value,
                source=self.hub_id,
                target=env.source,
            )
            await link.send(pong)

    # -- command forwarding ---

    # Callback set by channel to execute commands on local devices
    _execute_local_command: Callable[..., Any] | None = None

    def set_local_command_handler(
        self,
        handler: Callable[..., Any],
    ) -> None:
        """Set the callback for executing commands on local devices.

        Called by MeshChannel to wire federation into local command dispatch.
        """
        self._execute_local_command = handler

    async def forward_command(
        self,
        node_id: str,
        capability: str,
        value: Any,
        timeout: float = 10.0,
    ) -> bool:
        """Forward a command to a device on a remote hub.

        Returns True if the remote hub confirms success.
        """
        hub_id = self._device_hub_map.get(node_id)
        if not hub_id:
            logger.warning(
                "[Federation] cannot forward command: device {} not found "
                "on any remote hub", node_id,
            )
            return False
        link = self._links.get(hub_id)
        if not link or not link.connected:
            logger.warning(
                "[Federation] cannot forward command: hub {} not connected",
                hub_id,
            )
            return False
        # Create a future for the response
        key = (node_id, capability)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._pending_commands[key] = fut
        # Send the command
        env = MeshEnvelope(
            type=MsgType.FEDERATION_COMMAND.value,
            source=self.hub_id,
            target=hub_id,
            payload={
                "target_node": node_id,
                "capability": capability,
                "value": value,
            },
        )
        sent = await link.send(env)
        if not sent:
            self._pending_commands.pop(key, None)
            return False
        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_commands.pop(key, None)
            logger.warning(
                "[Federation] command timeout for {}:{} on hub {}",
                node_id, capability, hub_id,
            )
            return False

    # -- state propagation ---

    async def broadcast_state_update(
        self,
        node_id: str,
        state: dict,
    ) -> None:
        """Push a local device's state change to all connected peer hubs."""
        env = MeshEnvelope(
            type=MsgType.FEDERATION_STATE.value,
            source=self.hub_id,
            target="*",
            payload={
                "hub_id": self.hub_id,
                "node_id": node_id,
                "state": state,
            },
        )
        for hub_id, link in self._links.items():
            if link.connected:
                await link.send(env)

    # -- queries ---

    def is_remote_device(self, node_id: str) -> bool:
        """Check if a device lives on a remote hub."""
        return node_id in self._device_hub_map

    def get_device_hub(self, node_id: str) -> str | None:
        """Return the hub_id that owns a device, or None if unknown."""
        return self._device_hub_map.get(node_id)

    def list_remote_devices(self) -> dict[str, list[dict]]:
        """Return all remote devices grouped by hub_id."""
        result: dict[str, list[dict]] = {}
        for hub_id, devices in self._remote_devices.items():
            result[hub_id] = list(devices.values())
        return result

    def get_all_federated_devices(self) -> list[dict]:
        """Return a flat list of all remote devices."""
        devices: list[dict] = []
        for hub_devices in self._remote_devices.values():
            devices.extend(hub_devices.values())
        return devices

    def list_hubs(self) -> list[dict]:
        """Return status of all hub links for monitoring."""
        hubs: list[dict] = []
        for hub_id, link in self._links.items():
            hubs.append({
                "hub_id": hub_id,
                "host": link.peer.host,
                "port": link.peer.port,
                "connected": link.connected,
                "devices": len(self._remote_devices.get(hub_id, {})),
            })
        return hubs

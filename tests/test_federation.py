"""Tests for nanobot/mesh/federation.py — Multi-Hub federation."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.federation import (
    FederationConfig,
    FederationManager,
    FederationPeerConfig,
    HubLink,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType


# ---------------------------------------------------------------------------
# Config dataclass tests
# ---------------------------------------------------------------------------

class TestFederationPeerConfig:
    def test_from_dict_full(self):
        d = {"hub_id": "hub-b", "host": "192.168.2.1", "port": 19000}
        cfg = FederationPeerConfig.from_dict(d)
        assert cfg.hub_id == "hub-b"
        assert cfg.host == "192.168.2.1"
        assert cfg.port == 19000

    def test_from_dict_default_port(self):
        d = {"hub_id": "hub-b", "host": "10.0.0.5"}
        cfg = FederationPeerConfig.from_dict(d)
        assert cfg.port == 18800


class TestFederationConfig:
    def test_from_dict(self):
        d = {
            "peers": [
                {"hub_id": "hub-b", "host": "10.0.0.5", "port": 18800},
                {"hub_id": "hub-c", "host": "10.0.0.6"},
            ],
            "sync_interval": 15.0,
        }
        cfg = FederationConfig.from_dict(d)
        assert len(cfg.peers) == 2
        assert cfg.sync_interval == 15.0
        assert cfg.peers[0].hub_id == "hub-b"
        assert cfg.peers[1].port == 18800

    def test_from_dict_defaults(self):
        cfg = FederationConfig.from_dict({})
        assert len(cfg.peers) == 0
        assert cfg.sync_interval == 30.0

    def test_from_dict_no_peers_key(self):
        cfg = FederationConfig.from_dict({"sync_interval": 5.0})
        assert len(cfg.peers) == 0
        assert cfg.sync_interval == 5.0


# ---------------------------------------------------------------------------
# HubLink tests
# ---------------------------------------------------------------------------

class TestHubLinkProperties:
    def test_initial_state(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        assert link.connected is False
        assert link.peer.hub_id == "hub-b"
        assert link.local_hub_id == "hub-a"

    def test_on_message_registers_handler(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        handler = MagicMock()
        link.on_message(handler)
        assert handler in link._handlers


class TestHubLinkSend:
    @pytest.mark.asyncio
    async def test_send_when_disconnected(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        env = MeshEnvelope(
            type=MsgType.FEDERATION_PING.value,
            source="hub-a",
            target="hub-b",
        )
        result = await link.send(env)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_when_connected(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        link._connected = True
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        link._writer = mock_writer
        env = MeshEnvelope(
            type=MsgType.FEDERATION_PING.value,
            source="hub-a",
            target="hub-b",
        )
        result = await link.send(env)
        assert result is True
        mock_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_handles_connection_error(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        link._connected = True
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock(side_effect=ConnectionError("broken"))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        link._writer = mock_writer
        env = MeshEnvelope(
            type=MsgType.FEDERATION_PING.value,
            source="hub-a",
            target="hub-b",
        )
        result = await link.send(env)
        assert result is False
        assert link.connected is False


class TestHubLinkLifecycle:
    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        await link.stop()  # Should not raise
        assert link.connected is False

    @pytest.mark.asyncio
    async def test_start_connect_failure_schedules_reconnect(self):
        peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        link = HubLink(peer, "hub-a")
        with patch("asyncio.open_connection", side_effect=OSError("refused")):
            await link.start()
        assert link.connected is False
        assert link._running is True
        # Reconnect task should be scheduled
        assert link._reconnect_task is not None
        # Clean up
        await link.stop()


# ---------------------------------------------------------------------------
# FederationManager — config loading
# ---------------------------------------------------------------------------

class TestFederationManagerLoad:
    def test_load_nonexistent_file(self, tmp_path):
        mgr = FederationManager(
            hub_id="hub-a",
            config_path=str(tmp_path / "nonexistent.json"),
        )
        assert mgr.load() == 0

    def test_load_valid_config(self, tmp_path):
        cfg = {
            "peers": [
                {"hub_id": "hub-b", "host": "10.0.0.5", "port": 18800},
            ],
            "sync_interval": 10.0,
        }
        path = tmp_path / "federation.json"
        path.write_text(json.dumps(cfg))
        mgr = FederationManager(
            hub_id="hub-a",
            config_path=str(path),
        )
        assert mgr.load() == 1
        assert mgr._config is not None
        assert mgr._config.sync_interval == 10.0

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json!")
        mgr = FederationManager(
            hub_id="hub-a",
            config_path=str(path),
        )
        assert mgr.load() == 0

    def test_load_multiple_peers(self, tmp_path):
        cfg = {
            "peers": [
                {"hub_id": "hub-b", "host": "10.0.0.5"},
                {"hub_id": "hub-c", "host": "10.0.0.6"},
                {"hub_id": "hub-d", "host": "10.0.0.7"},
            ],
        }
        path = tmp_path / "federation.json"
        path.write_text(json.dumps(cfg))
        mgr = FederationManager(
            hub_id="hub-a",
            config_path=str(path),
        )
        assert mgr.load() == 3


# ---------------------------------------------------------------------------
# FederationManager — message handling (sync)
# ---------------------------------------------------------------------------

class TestFederationSync:
    def test_handle_sync_updates_remote_devices(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        env = MeshEnvelope(
            type=MsgType.FEDERATION_SYNC.value,
            source="hub-b",
            target="hub-a",
            payload={
                "hub_id": "hub-b",
                "devices": [
                    {"node_id": "dev-1", "device_type": "sensor", "online": True, "state": {"temp": 25}},
                    {"node_id": "dev-2", "device_type": "light", "online": False, "state": {}},
                ],
            },
        )
        mgr._handle_sync(env)
        assert len(mgr._remote_devices["hub-b"]) == 2
        assert mgr._device_hub_map["dev-1"] == "hub-b"
        assert mgr._device_hub_map["dev-2"] == "hub-b"
        assert mgr.is_remote_device("dev-1")
        assert mgr.get_device_hub("dev-2") == "hub-b"

    def test_handle_sync_removes_stale_devices(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        # First sync with 2 devices
        mgr._handle_sync(MeshEnvelope(
            type=MsgType.FEDERATION_SYNC.value,
            source="hub-b",
            target="hub-a",
            payload={
                "hub_id": "hub-b",
                "devices": [
                    {"node_id": "dev-1", "device_type": "sensor", "online": True, "state": {}},
                    {"node_id": "dev-2", "device_type": "light", "online": True, "state": {}},
                ],
            },
        ))
        assert mgr.is_remote_device("dev-2")
        # Second sync removes dev-2
        mgr._handle_sync(MeshEnvelope(
            type=MsgType.FEDERATION_SYNC.value,
            source="hub-b",
            target="hub-a",
            payload={
                "hub_id": "hub-b",
                "devices": [
                    {"node_id": "dev-1", "device_type": "sensor", "online": True, "state": {}},
                ],
            },
        ))
        assert mgr.is_remote_device("dev-1")
        assert not mgr.is_remote_device("dev-2")
        assert mgr.get_device_hub("dev-2") is None

    def test_handle_sync_multiple_hubs(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._handle_sync(MeshEnvelope(
            type=MsgType.FEDERATION_SYNC.value,
            source="hub-b",
            target="hub-a",
            payload={"hub_id": "hub-b", "devices": [
                {"node_id": "b-dev-1", "device_type": "sensor", "online": True, "state": {}},
            ]},
        ))
        mgr._handle_sync(MeshEnvelope(
            type=MsgType.FEDERATION_SYNC.value,
            source="hub-c",
            target="hub-a",
            payload={"hub_id": "hub-c", "devices": [
                {"node_id": "c-dev-1", "device_type": "motor", "online": True, "state": {}},
            ]},
        ))
        assert mgr.get_device_hub("b-dev-1") == "hub-b"
        assert mgr.get_device_hub("c-dev-1") == "hub-c"
        all_devices = mgr.get_all_federated_devices()
        assert len(all_devices) == 2


# ---------------------------------------------------------------------------
# FederationManager — command forwarding
# ---------------------------------------------------------------------------

class TestFederationCommandForward:
    @pytest.mark.asyncio
    async def test_forward_unknown_device(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        result = await mgr.forward_command("unknown-dev", "speed", 100)
        assert result is False

    @pytest.mark.asyncio
    async def test_forward_disconnected_hub(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._device_hub_map["dev-1"] = "hub-b"
        mock_link = MagicMock()
        mock_link.connected = False
        mgr._links["hub-b"] = mock_link
        result = await mgr.forward_command("dev-1", "speed", 100)
        assert result is False

    @pytest.mark.asyncio
    async def test_forward_with_response(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._running = True
        mgr._device_hub_map["dev-1"] = "hub-b"
        mock_link = MagicMock()
        mock_link.connected = True

        async def fake_send(env):
            # Simulate immediate response
            key = ("dev-1", "speed")
            fut = mgr._pending_commands.get(key)
            if fut and not fut.done():
                fut.set_result(True)
            return True

        mock_link.send = fake_send
        mgr._links["hub-b"] = mock_link
        result = await mgr.forward_command("dev-1", "speed", 1500, timeout=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_forward_timeout(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._running = True
        mgr._device_hub_map["dev-1"] = "hub-b"
        mock_link = MagicMock()
        mock_link.connected = True
        mock_link.send = AsyncMock(return_value=True)
        mgr._links["hub-b"] = mock_link
        result = await mgr.forward_command("dev-1", "speed", 1500, timeout=0.1)
        assert result is False


# ---------------------------------------------------------------------------
# FederationManager — command handling (inbound)
# ---------------------------------------------------------------------------

class TestFederationCommandHandling:
    @pytest.mark.asyncio
    async def test_handle_command_executes_locally(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mock_link = MagicMock()
        mock_link.connected = True
        mock_link.send = AsyncMock(return_value=True)
        mgr._links["hub-b"] = mock_link

        exec_called = {}

        async def local_handler(node_id, capability, value):
            exec_called["node_id"] = node_id
            exec_called["capability"] = capability
            exec_called["value"] = value
            return True

        mgr._execute_local_command = local_handler

        env = MeshEnvelope(
            type=MsgType.FEDERATION_COMMAND.value,
            source="hub-b",
            target="hub-a",
            payload={
                "target_node": "local-dev-1",
                "capability": "brightness",
                "value": 80,
            },
        )
        await mgr._handle_command(env)
        assert exec_called["node_id"] == "local-dev-1"
        assert exec_called["capability"] == "brightness"
        assert exec_called["value"] == 80
        # Check that a response was sent back
        mock_link.send.assert_called_once()
        resp_env = mock_link.send.call_args[0][0]
        assert resp_env.type == MsgType.FEDERATION_RESPONSE.value
        assert resp_env.payload["success"] is True


# ---------------------------------------------------------------------------
# FederationManager — response handling
# ---------------------------------------------------------------------------

class TestFederationResponseHandling:
    def test_handle_response_resolves_future(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            mgr._pending_commands[("dev-1", "speed")] = fut
            env = MeshEnvelope(
                type=MsgType.FEDERATION_RESPONSE.value,
                source="hub-b",
                target="hub-a",
                payload={
                    "target_node": "dev-1",
                    "capability": "speed",
                    "success": True,
                    "value": 1500,
                },
            )
            mgr._handle_response(env)
            assert fut.done()
            assert fut.result() is True
            assert ("dev-1", "speed") not in mgr._pending_commands
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# FederationManager — state propagation
# ---------------------------------------------------------------------------

class TestFederationState:
    @pytest.mark.asyncio
    async def test_handle_state_updates_view(self):
        callback_called = {}

        async def on_remote_state(node_id, state):
            callback_called["node_id"] = node_id
            callback_called["state"] = state

        mgr = FederationManager(
            hub_id="hub-a",
            config_path="",
            on_remote_state=on_remote_state,
        )
        # Pre-populate remote device
        mgr._remote_devices["hub-b"] = {
            "dev-1": {"node_id": "dev-1", "state": {"temp": 20}},
        }
        env = MeshEnvelope(
            type=MsgType.FEDERATION_STATE.value,
            source="hub-b",
            target="hub-a",
            payload={
                "hub_id": "hub-b",
                "node_id": "dev-1",
                "state": {"temp": 30},
            },
        )
        await mgr._handle_state(env)
        assert mgr._remote_devices["hub-b"]["dev-1"]["state"]["temp"] == 30
        assert callback_called["node_id"] == "dev-1"
        assert callback_called["state"]["temp"] == 30

    @pytest.mark.asyncio
    async def test_broadcast_state_update(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mock_link = MagicMock()
        mock_link.connected = True
        mock_link.send = AsyncMock(return_value=True)
        mgr._links["hub-b"] = mock_link

        await mgr.broadcast_state_update("local-dev-1", {"speed": 1500})
        mock_link.send.assert_called_once()
        sent_env = mock_link.send.call_args[0][0]
        assert sent_env.type == MsgType.FEDERATION_STATE.value
        assert sent_env.payload["node_id"] == "local-dev-1"
        assert sent_env.payload["state"]["speed"] == 1500

    @pytest.mark.asyncio
    async def test_broadcast_skips_disconnected(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mock_link = MagicMock()
        mock_link.connected = False
        mock_link.send = AsyncMock()
        mgr._links["hub-b"] = mock_link

        await mgr.broadcast_state_update("local-dev-1", {"speed": 1500})
        mock_link.send.assert_not_called()


# ---------------------------------------------------------------------------
# FederationManager — ping handling
# ---------------------------------------------------------------------------

class TestFederationPing:
    @pytest.mark.asyncio
    async def test_handle_ping_sends_pong(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mock_link = MagicMock()
        mock_link.connected = True
        mock_link.send = AsyncMock(return_value=True)
        mgr._links["hub-b"] = mock_link
        env = MeshEnvelope(
            type=MsgType.FEDERATION_PING.value,
            source="hub-b",
            target="hub-a",
        )
        await mgr._handle_ping(env)
        mock_link.send.assert_called_once()
        pong = mock_link.send.call_args[0][0]
        assert pong.type == MsgType.FEDERATION_PONG.value


# ---------------------------------------------------------------------------
# FederationManager — queries
# ---------------------------------------------------------------------------

class TestFederationQueries:
    def test_is_remote_device(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._device_hub_map["dev-remote"] = "hub-b"
        assert mgr.is_remote_device("dev-remote")
        assert not mgr.is_remote_device("dev-local")

    def test_get_device_hub(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._device_hub_map["dev-1"] = "hub-b"
        assert mgr.get_device_hub("dev-1") == "hub-b"
        assert mgr.get_device_hub("dev-unknown") is None

    def test_list_remote_devices(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._remote_devices["hub-b"] = {
            "dev-1": {"node_id": "dev-1"},
            "dev-2": {"node_id": "dev-2"},
        }
        mgr._remote_devices["hub-c"] = {
            "dev-3": {"node_id": "dev-3"},
        }
        result = mgr.list_remote_devices()
        assert len(result["hub-b"]) == 2
        assert len(result["hub-c"]) == 1

    def test_get_all_federated_devices(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._remote_devices["hub-b"] = {
            "dev-1": {"node_id": "dev-1"},
        }
        mgr._remote_devices["hub-c"] = {
            "dev-2": {"node_id": "dev-2"},
            "dev-3": {"node_id": "dev-3"},
        }
        all_devs = mgr.get_all_federated_devices()
        assert len(all_devs) == 3

    def test_list_hubs(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mock_link = MagicMock()
        mock_link.connected = True
        mock_link.peer = FederationPeerConfig(hub_id="hub-b", host="10.0.0.5", port=18800)
        mgr._links["hub-b"] = mock_link
        mgr._remote_devices["hub-b"] = {"dev-1": {}, "dev-2": {}}
        hubs = mgr.list_hubs()
        assert len(hubs) == 1
        assert hubs[0]["hub_id"] == "hub-b"
        assert hubs[0]["connected"] is True
        assert hubs[0]["devices"] == 2


# ---------------------------------------------------------------------------
# FederationManager — local device list
# ---------------------------------------------------------------------------

class TestFederationLocalDeviceList:
    def test_no_registry(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        assert mgr._get_local_device_list() == []

    def test_with_mock_registry(self):
        mock_registry = MagicMock()
        mock_dev = MagicMock()
        mock_dev.node_id = "local-1"
        mock_dev.device_type = "sensor"
        mock_dev.name = "Temperature Sensor"
        mock_dev.online = True
        mock_dev.state = {"temp": 22}
        mock_cap = MagicMock()
        mock_cap.name = "temperature"
        mock_cap.cap_type = "number"
        mock_cap.value_range = [0, 100]
        mock_cap.unit = "°C"
        mock_dev.capabilities = [mock_cap]
        mock_registry.devices = {"local-1": mock_dev}
        mgr = FederationManager(
            hub_id="hub-a",
            config_path="",
            registry=mock_registry,
        )
        devices = mgr._get_local_device_list()
        assert len(devices) == 1
        assert devices[0]["node_id"] == "local-1"
        assert devices[0]["device_type"] == "sensor"
        assert devices[0]["capabilities"][0]["name"] == "temperature"


# ---------------------------------------------------------------------------
# FederationManager — lifecycle
# ---------------------------------------------------------------------------

class TestFederationLifecycle:
    @pytest.mark.asyncio
    async def test_start_with_no_config(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        await mgr.start()  # Should not raise since _config is None
        assert not mgr._running

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        mgr._running = True
        mgr._remote_devices["hub-b"] = {"dev-1": {}}
        mgr._device_hub_map["dev-1"] = "hub-b"
        await mgr.stop()
        assert not mgr._running
        assert len(mgr._remote_devices) == 0
        assert len(mgr._device_hub_map) == 0


# ---------------------------------------------------------------------------
# FederationManager — message dispatch
# ---------------------------------------------------------------------------

class TestFederationMessageDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_hello(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        env = MeshEnvelope(
            type=MsgType.FEDERATION_HELLO.value,
            source="hub-b",
            target="hub-a",
            payload={"hub_id": "hub-b"},
        )
        # Should not raise
        await mgr._handle_message(env)

    @pytest.mark.asyncio
    async def test_dispatch_unknown_type(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        env = MeshEnvelope(
            type="federation_unknown",
            source="hub-b",
            target="hub-a",
        )
        # Should not raise
        await mgr._handle_message(env)


# ---------------------------------------------------------------------------
# Channel integration tests
# ---------------------------------------------------------------------------

class TestChannelFederationIntegration:
    def test_federation_none_when_no_config(self):
        """Federation should be None when federation_config_path is empty."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "test-hub"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = "/tmp/test_fed_registry.json"
        config.automation_rules_path = "/tmp/test_fed_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_fed_groups.json"
        config.scenes_path = "/tmp/test_fed_scenes.json"
        config.dashboard_port = 0
        config.industrial_config_path = ""
        config.federation_config_path = ""
        bus = MagicMock()
        channel = MeshChannel(config, bus)
        assert channel.federation is None

    def test_federation_created_when_config_set(self, tmp_path):
        """Federation should be created when federation_config_path points to a file."""
        from nanobot.mesh.channel import MeshChannel

        cfg_file = tmp_path / "federation.json"
        cfg_file.write_text(json.dumps({
            "peers": [{"hub_id": "hub-b", "host": "10.0.0.5"}],
        }))

        config = MagicMock()
        config.node_id = "test-hub"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = str(tmp_path / "registry.json")
        config.automation_rules_path = str(tmp_path / "auto.json")
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = str(tmp_path / "groups.json")
        config.scenes_path = str(tmp_path / "scenes.json")
        config.dashboard_port = 0
        config.industrial_config_path = ""
        config.federation_config_path = str(cfg_file)
        bus = MagicMock()
        channel = MeshChannel(config, bus)
        assert channel.federation is not None
        assert isinstance(channel.federation, FederationManager)

    @pytest.mark.asyncio
    async def test_forward_to_federation_no_config(self):
        """forward_to_federation should return False when federation is not configured."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "test-hub"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = "/tmp/test_fed2_registry.json"
        config.automation_rules_path = "/tmp/test_fed2_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_fed2_groups.json"
        config.scenes_path = "/tmp/test_fed2_scenes.json"
        config.dashboard_port = 0
        config.industrial_config_path = ""
        config.federation_config_path = ""
        bus = MagicMock()
        channel = MeshChannel(config, bus)
        result = await channel.forward_to_federation("dev-1", "speed", 100)
        assert result is False


# ---------------------------------------------------------------------------
# set_local_command_handler
# ---------------------------------------------------------------------------

class TestSetLocalCommandHandler:
    def test_set_handler(self):
        mgr = FederationManager(hub_id="hub-a", config_path="")
        handler = AsyncMock()
        mgr.set_local_command_handler(handler)
        assert mgr._execute_local_command is handler

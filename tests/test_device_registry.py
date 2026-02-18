"""Tests for device capability registry (task 2.1).

Covers:
- DeviceCapability / DeviceInfo data model
- DeviceRegistry CRUD operations
- State management
- Online/offline tracking
- Persistence (load/save)
- Event callbacks
- Discovery integration hooks
- LLM context helpers
- MeshChannel integration
- Edge cases (empty, duplicate, malformed data)
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceInfo,
    DeviceRegistry,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_registry_path():
    """Create a temporary file path for the registry."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # Delete so registry starts fresh
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def registry(tmp_registry_path):
    """Create a fresh DeviceRegistry instance."""
    reg = DeviceRegistry(path=tmp_registry_path)
    reg.load()
    return reg


def _temp_cap() -> DeviceCapability:
    return DeviceCapability(
        name="temperature",
        cap_type=CapabilityType.SENSOR,
        data_type=DataType.FLOAT,
        unit="°C",
        value_range=(-40, 80),
    )


def _light_caps() -> list[DeviceCapability]:
    return [
        DeviceCapability(
            name="power",
            cap_type=CapabilityType.ACTUATOR,
            data_type=DataType.BOOL,
        ),
        DeviceCapability(
            name="brightness",
            cap_type=CapabilityType.PROPERTY,
            data_type=DataType.INT,
            unit="%",
            value_range=(0, 100),
        ),
        DeviceCapability(
            name="color_mode",
            cap_type=CapabilityType.PROPERTY,
            data_type=DataType.ENUM,
            enum_values=["white", "color", "scene"],
        ),
    ]


# ===================================================================
# Test: Data model
# ===================================================================

class TestDeviceCapability:
    """DeviceCapability serialization and deserialization."""

    def test_to_dict_minimal(self):
        cap = DeviceCapability(
            name="power",
            cap_type=CapabilityType.ACTUATOR,
            data_type=DataType.BOOL,
        )
        d = cap.to_dict()
        assert d["name"] == "power"
        assert d["cap_type"] == "actuator"
        assert d["data_type"] == "bool"
        # Optional fields should be absent
        assert "unit" not in d
        assert "value_range" not in d
        assert "enum_values" not in d

    def test_to_dict_full(self):
        cap = DeviceCapability(
            name="brightness",
            cap_type=CapabilityType.PROPERTY,
            data_type=DataType.INT,
            unit="%",
            value_range=(0, 100),
            enum_values=[],  # empty shouldn't appear
            description="Light brightness level",
        )
        d = cap.to_dict()
        assert d["unit"] == "%"
        assert d["value_range"] == [0, 100]
        assert "enum_values" not in d  # empty list omitted
        assert d["description"] == "Light brightness level"

    def test_roundtrip(self):
        cap = DeviceCapability(
            name="mode",
            cap_type=CapabilityType.PROPERTY,
            data_type=DataType.ENUM,
            enum_values=["auto", "cool", "heat"],
        )
        d = cap.to_dict()
        restored = DeviceCapability.from_dict(d)
        assert restored.name == cap.name
        assert restored.cap_type == cap.cap_type
        assert restored.data_type == cap.data_type
        assert restored.enum_values == cap.enum_values

    def test_from_dict_defaults(self):
        cap = DeviceCapability.from_dict({"name": "x"})
        assert cap.name == "x"
        assert cap.cap_type == CapabilityType.PROPERTY
        assert cap.data_type == DataType.STRING
        assert cap.unit == ""
        assert cap.value_range is None


class TestDeviceInfo:
    """DeviceInfo serialization and queries."""

    def test_to_dict_roundtrip(self):
        caps = _light_caps()
        info = DeviceInfo(
            node_id="light-01",
            device_type="smart_light",
            name="Living Room Light",
            capabilities=caps,
            state={"power": True, "brightness": 80},
            online=True,
            last_seen=1000.0,
            registered_at=900.0,
            metadata={"firmware": "1.2.0"},
        )
        d = info.to_dict()
        restored = DeviceInfo.from_dict(d)
        assert restored.node_id == "light-01"
        assert restored.device_type == "smart_light"
        assert restored.name == "Living Room Light"
        assert len(restored.capabilities) == 3
        assert restored.state["power"] is True
        assert restored.metadata["firmware"] == "1.2.0"

    def test_get_capability(self):
        info = DeviceInfo(
            node_id="test",
            device_type="test",
            capabilities=_light_caps(),
        )
        assert info.get_capability("brightness") is not None
        assert info.get_capability("brightness").data_type == DataType.INT
        assert info.get_capability("nonexistent") is None

    def test_capability_names(self):
        info = DeviceInfo(
            node_id="test",
            device_type="test",
            capabilities=_light_caps(),
        )
        names = info.capability_names()
        assert "power" in names
        assert "brightness" in names
        assert "color_mode" in names


# ===================================================================
# Test: Registry CRUD
# ===================================================================

class TestRegistryCRUD:
    """Register, update, remove, and query devices."""

    @pytest.mark.asyncio
    async def test_register_new_device(self, registry):
        info = await registry.register_device(
            "sensor-01",
            "temperature_sensor",
            name="Kitchen Sensor",
            capabilities=[_temp_cap()],
            metadata={"firmware": "2.0"},
        )
        assert info.node_id == "sensor-01"
        assert info.device_type == "temperature_sensor"
        assert info.name == "Kitchen Sensor"
        assert len(info.capabilities) == 1
        assert info.metadata["firmware"] == "2.0"
        assert registry.device_count == 1

    @pytest.mark.asyncio
    async def test_register_same_device_updates(self, registry):
        await registry.register_device("d1", "type_a", name="Old Name")
        await registry.register_device(
            "d1", "type_b",
            name="New Name",
            capabilities=[_temp_cap()],
        )
        assert registry.device_count == 1
        info = registry.get_device("d1")
        assert info.device_type == "type_b"
        assert info.name == "New Name"
        assert len(info.capabilities) == 1

    @pytest.mark.asyncio
    async def test_register_preserves_state(self, registry):
        await registry.register_device("d1", "type_a")
        await registry.update_state("d1", {"temp": 25.0})
        await registry.register_device("d1", "type_a", capabilities=[_temp_cap()])
        info = registry.get_device("d1")
        assert info.state["temp"] == 25.0  # Preserved

    @pytest.mark.asyncio
    async def test_remove_device(self, registry):
        await registry.register_device("d1", "test")
        assert registry.device_count == 1
        removed = await registry.remove_device("d1")
        assert removed is True
        assert registry.device_count == 0
        assert registry.get_device("d1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, registry):
        removed = await registry.remove_device("ghost")
        assert removed is False

    @pytest.mark.asyncio
    async def test_get_device(self, registry):
        await registry.register_device("d1", "test")
        assert registry.get_device("d1") is not None
        assert registry.get_device("ghost") is None

    @pytest.mark.asyncio
    async def test_get_all_devices(self, registry):
        await registry.register_device("d1", "type_a")
        await registry.register_device("d2", "type_b")
        await registry.register_device("d3", "type_a")
        all_devs = registry.get_all_devices()
        assert len(all_devs) == 3

    @pytest.mark.asyncio
    async def test_get_devices_by_type(self, registry):
        await registry.register_device("d1", "sensor")
        await registry.register_device("d2", "light")
        await registry.register_device("d3", "sensor")
        sensors = registry.get_devices_by_type("sensor")
        assert len(sensors) == 2

    @pytest.mark.asyncio
    async def test_get_devices_with_capability(self, registry):
        await registry.register_device(
            "d1", "sensor",
            capabilities=[_temp_cap()],
        )
        await registry.register_device(
            "d2", "light",
            capabilities=_light_caps(),
        )
        temp_devices = registry.get_devices_with_capability("temperature")
        assert len(temp_devices) == 1
        assert temp_devices[0].node_id == "d1"

        power_devices = registry.get_devices_with_capability("power")
        assert len(power_devices) == 1
        assert power_devices[0].node_id == "d2"

    @pytest.mark.asyncio
    async def test_default_name_is_node_id(self, registry):
        await registry.register_device("my-device", "test")
        info = registry.get_device("my-device")
        assert info.name == "my-device"


# ===================================================================
# Test: State management
# ===================================================================

class TestStateManagement:
    """update_state, partial updates, unknown devices."""

    @pytest.mark.asyncio
    async def test_update_state(self, registry):
        await registry.register_device("d1", "sensor", capabilities=[_temp_cap()])
        ok = await registry.update_state("d1", {"temperature": 23.5})
        assert ok is True
        info = registry.get_device("d1")
        assert info.state["temperature"] == 23.5

    @pytest.mark.asyncio
    async def test_partial_state_update(self, registry):
        await registry.register_device("d1", "light", capabilities=_light_caps())
        await registry.update_state("d1", {"power": True, "brightness": 80})
        await registry.update_state("d1", {"brightness": 50})
        info = registry.get_device("d1")
        assert info.state["power"] is True  # Unchanged
        assert info.state["brightness"] == 50  # Updated

    @pytest.mark.asyncio
    async def test_update_state_unknown_device(self, registry):
        ok = await registry.update_state("ghost", {"x": 1})
        assert ok is False

    @pytest.mark.asyncio
    async def test_no_change_doesnt_fire_event(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append(e))
        await registry.register_device("d1", "test")
        events.clear()
        await registry.update_state("d1", {"x": 10})
        assert "state_changed" in events
        events.clear()
        # Same value — no change
        await registry.update_state("d1", {"x": 10})
        assert "state_changed" not in events


# ===================================================================
# Test: Online/offline tracking
# ===================================================================

class TestOnlineOffline:
    """mark_online, mark_offline, sync_with_discovery."""

    @pytest.mark.asyncio
    async def test_mark_online_offline(self, registry):
        await registry.register_device("d1", "test")
        assert registry.get_device("d1").online is False

        registry.mark_online("d1")
        assert registry.get_device("d1").online is True
        assert registry.online_count == 1

        registry.mark_offline("d1")
        assert registry.get_device("d1").online is False
        assert registry.online_count == 0

    @pytest.mark.asyncio
    async def test_mark_unknown_device(self, registry):
        # Should not raise
        registry.mark_online("ghost")
        registry.mark_offline("ghost")

    @pytest.mark.asyncio
    async def test_online_events(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append((d.node_id, e)))
        await registry.register_device("d1", "test")
        events.clear()

        registry.mark_online("d1")
        assert ("d1", "online") in events

        events.clear()
        registry.mark_online("d1")  # Already online — no event
        assert len(events) == 0

        registry.mark_offline("d1")
        assert ("d1", "offline") in events

    @pytest.mark.asyncio
    async def test_get_online_devices(self, registry):
        await registry.register_device("d1", "test")
        await registry.register_device("d2", "test")
        registry.mark_online("d1")
        online = registry.get_online_devices()
        assert len(online) == 1
        assert online[0].node_id == "d1"

    @pytest.mark.asyncio
    async def test_sync_with_discovery(self, registry):
        await registry.register_device("d1", "test")
        await registry.register_device("d2", "test")
        await registry.register_device("d3", "test")
        registry.mark_online("d1")
        registry.mark_online("d2")
        registry.mark_online("d3")

        # d2 goes offline
        registry.sync_with_discovery({"d1", "d3"})
        assert registry.get_device("d1").online is True
        assert registry.get_device("d2").online is False
        assert registry.get_device("d3").online is True


# ===================================================================
# Test: Persistence
# ===================================================================

class TestPersistence:
    """Load and save registry to disk."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_registry_path):
        reg1 = DeviceRegistry(path=tmp_registry_path)
        reg1.load()
        await reg1.register_device(
            "sensor-01", "temp_sensor",
            name="Kitchen",
            capabilities=[_temp_cap()],
        )
        await reg1.update_state("sensor-01", {"temperature": 22.5})

        # Load into a new registry instance
        reg2 = DeviceRegistry(path=tmp_registry_path)
        reg2.load()
        assert reg2.device_count == 1
        info = reg2.get_device("sensor-01")
        assert info.name == "Kitchen"
        assert info.state["temperature"] == 22.5
        assert info.online is False  # All devices start offline on load
        assert len(info.capabilities) == 1

    @pytest.mark.asyncio
    async def test_load_missing_file(self, tmp_registry_path):
        # Path doesn't exist yet
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()
        assert reg.device_count == 0

    @pytest.mark.asyncio
    async def test_load_empty_file(self, tmp_registry_path):
        Path(tmp_registry_path).write_text("")
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()
        assert reg.device_count == 0

    @pytest.mark.asyncio
    async def test_load_malformed_json(self, tmp_registry_path):
        Path(tmp_registry_path).write_text("{invalid json}")
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()  # Should not raise
        assert reg.device_count == 0

    @pytest.mark.asyncio
    async def test_load_malformed_device_entry(self, tmp_registry_path):
        data = {"version": 1, "devices": [{"bad": "data"}, {"node_id": "ok", "device_type": "test"}]}
        Path(tmp_registry_path).write_text(json.dumps(data))
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()
        assert reg.device_count == 1  # Skips malformed, keeps valid

    @pytest.mark.asyncio
    async def test_persistence_after_remove(self, tmp_registry_path):
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()
        await reg.register_device("d1", "test")
        await reg.register_device("d2", "test")
        await reg.remove_device("d1")

        reg2 = DeviceRegistry(path=tmp_registry_path)
        reg2.load()
        assert reg2.device_count == 1
        assert reg2.get_device("d2") is not None

    @pytest.mark.asyncio
    async def test_json_structure(self, tmp_registry_path):
        reg = DeviceRegistry(path=tmp_registry_path)
        reg.load()
        await reg.register_device("d1", "test")
        data = json.loads(Path(tmp_registry_path).read_text())
        assert data["version"] == 1
        assert "updated_at" in data
        assert len(data["devices"]) == 1


# ===================================================================
# Test: Event system
# ===================================================================

class TestEventSystem:
    """Callback notifications for device lifecycle events."""

    @pytest.mark.asyncio
    async def test_registered_event(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append((d.node_id, e)))
        await registry.register_device("d1", "test")
        assert ("d1", "registered") in events

    @pytest.mark.asyncio
    async def test_updated_event(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append((d.node_id, e)))
        await registry.register_device("d1", "test")
        await registry.register_device("d1", "test_v2")
        assert ("d1", "updated") in events

    @pytest.mark.asyncio
    async def test_removed_event(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append((d.node_id, e)))
        await registry.register_device("d1", "test")
        await registry.remove_device("d1")
        assert ("d1", "removed") in events

    @pytest.mark.asyncio
    async def test_state_changed_event(self, registry):
        events = []
        registry.on_event(lambda d, e: events.append((d.node_id, e)))
        await registry.register_device("d1", "test")
        await registry.update_state("d1", {"x": 1})
        assert ("d1", "state_changed") in events

    @pytest.mark.asyncio
    async def test_callback_error_doesnt_break_registry(self, registry):
        def bad_callback(d, e):
            raise RuntimeError("boom")

        registry.on_event(bad_callback)
        events = []
        registry.on_event(lambda d, e: events.append(e))
        # Should not raise despite first callback failing
        await registry.register_device("d1", "test")
        assert "registered" in events


# ===================================================================
# Test: LLM context helpers
# ===================================================================

class TestLLMContext:
    """Summary and structured output for LLM context."""

    @pytest.mark.asyncio
    async def test_summary_empty(self, registry):
        assert registry.summary() == "No devices registered."

    @pytest.mark.asyncio
    async def test_summary_with_devices(self, registry):
        await registry.register_device(
            "sensor-01", "temp_sensor",
            name="Kitchen Sensor",
            capabilities=[_temp_cap()],
        )
        await registry.update_state("sensor-01", {"temperature": 23.5})
        registry.mark_online("sensor-01")

        summary = registry.summary()
        assert "1 online / 1 total" in summary
        assert "Kitchen Sensor" in summary
        assert "temperature: 23.5°C" in summary
        assert "ONLINE" in summary

    @pytest.mark.asyncio
    async def test_summary_offline_device_shows_last_seen(self, registry):
        await registry.register_device("d1", "test", name="Test Device")
        info = registry.get_device("d1")
        info.last_seen = time.time() - 120  # 2 minutes ago
        summary = registry.summary()
        assert "OFFLINE" in summary
        assert "last seen 2min ago" in summary

    @pytest.mark.asyncio
    async def test_to_dict_for_llm(self, registry):
        await registry.register_device(
            "light-01", "smart_light",
            name="Desk Lamp",
            capabilities=_light_caps(),
        )
        await registry.update_state("light-01", {"power": True})
        result = registry.to_dict_for_llm()
        assert len(result) == 1
        assert result[0]["node_id"] == "light-01"
        assert result[0]["name"] == "Desk Lamp"
        assert result[0]["current_state"]["power"] is True
        assert len(result[0]["capabilities"]) == 3


# ===================================================================
# Test: Discovery integration
# ===================================================================

class TestDiscoveryIntegration:
    """Discovery beacon parsing with capabilities field."""

    def test_peer_info_has_capabilities(self):
        from nanobot.mesh.discovery import PeerInfo
        peer = PeerInfo(
            node_id="device-01",
            ip="192.168.1.50",
            tcp_port=18800,
            capabilities=[{"name": "temperature", "cap_type": "sensor", "data_type": "float"}],
            device_type="temp_sensor",
        )
        assert len(peer.capabilities) == 1
        assert peer.device_type == "temp_sensor"

    def test_peer_info_defaults(self):
        from nanobot.mesh.discovery import PeerInfo
        peer = PeerInfo(node_id="x", ip="1.2.3.4", tcp_port=18800)
        assert peer.capabilities == []
        assert peer.device_type == ""


# ===================================================================
# Test: Protocol extension
# ===================================================================

class TestProtocol:
    """STATE_REPORT message type."""

    def test_state_report_type_exists(self):
        assert MsgType.STATE_REPORT == "state_report"

    def test_state_report_envelope(self):
        env = MeshEnvelope(
            type=MsgType.STATE_REPORT,
            source="sensor-01",
            target="hub",
            payload={"state": {"temperature": 23.5, "humidity": 45}},
        )
        data = env.to_bytes()
        restored = MeshEnvelope.from_bytes(data[4:])  # Skip length prefix
        assert restored.type == "state_report"
        assert restored.payload["state"]["temperature"] == 23.5


# ===================================================================
# Test: Channel integration
# ===================================================================

class TestChannelIntegration:
    """MeshChannel integration with DeviceRegistry."""

    @pytest.mark.asyncio
    async def test_state_report_updates_registry(self, tmp_registry_path):
        """STATE_REPORT messages should update the registry."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = tmp_registry_path
        config._workspace_path = None

        bus = MagicMock()
        bus.publish = AsyncMock()

        channel = MeshChannel(config, bus)

        # Manually register a device in the registry
        await channel.registry.register_device("sensor-01", "temp_sensor")

        # Simulate a STATE_REPORT
        env = MeshEnvelope(
            type=MsgType.STATE_REPORT,
            source="sensor-01",
            target="hub-01",
            payload={"state": {"temperature": 23.5}},
        )
        await channel._on_mesh_message(env)

        info = channel.registry.get_device("sensor-01")
        assert info.state["temperature"] == 23.5

    @pytest.mark.asyncio
    async def test_state_report_unknown_device(self, tmp_registry_path):
        """STATE_REPORT from unregistered device should be logged but not crash."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = tmp_registry_path
        config._workspace_path = None

        bus = MagicMock()
        bus.publish = AsyncMock()

        channel = MeshChannel(config, bus)

        env = MeshEnvelope(
            type=MsgType.STATE_REPORT,
            source="unknown-device",
            target="hub-01",
            payload={"state": {"x": 1}},
        )
        # Should not raise
        await channel._on_mesh_message(env)

    def test_device_summary_exposed(self, tmp_registry_path):
        """MeshChannel exposes get_device_summary()."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = tmp_registry_path
        config._workspace_path = None

        bus = MagicMock()
        channel = MeshChannel(config, bus)
        summary = channel.get_device_summary()
        assert "No devices registered" in summary


# ===================================================================
# Test: Config field
# ===================================================================

class TestConfig:
    """registry_path config field."""

    def test_mesh_config_has_registry_path(self):
        from nanobot.config.schema import MeshConfig
        config = MeshConfig()
        assert hasattr(config, "registry_path")
        assert config.registry_path == ""

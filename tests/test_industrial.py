"""Tests for PLC/industrial device integration (task 4.1).

Covers: data type encoding/decoding, config parsing, protocol adapter
interface, IndustrialBridge lifecycle, registry integration, command
dispatch, channel integration, and protocol registry.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.industrial import (
    BridgeConfig,
    IndustrialBridge,
    IndustrialProtocol,
    ModbusTCPAdapter,
    PLCDeviceConfig,
    PLCPointConfig,
    StubAdapter,
    _REGISTER_COUNT,
    _to_cap_type,
    _to_device_data_type,
    decode_registers,
    encode_value,
    get_protocol_adapter,
    register_protocol,
)
from nanobot.mesh.registry import CapabilityType, DataType, DeviceRegistry


# ---------------------------------------------------------------------------
# Test: Data type helpers
# ---------------------------------------------------------------------------

class TestDecodeRegisters:
    def test_bool_true(self):
        assert decode_registers([1], "bool") is True

    def test_bool_false(self):
        assert decode_registers([0], "bool") is False

    def test_uint16(self):
        assert decode_registers([1000], "uint16") == 1000

    def test_int16_positive(self):
        assert decode_registers([500], "int16") == 500

    def test_int16_negative(self):
        # -100 as 16-bit unsigned = 65436
        raw = struct.unpack(">H", struct.pack(">h", -100))[0]
        assert decode_registers([raw], "int16") == -100

    def test_uint32(self):
        val = 100000
        raw_bytes = struct.pack(">I", val)
        regs = [struct.unpack(">H", raw_bytes[i:i+2])[0] for i in range(0, 4, 2)]
        assert decode_registers(regs, "uint32") == val

    def test_int32_negative(self):
        val = -50000
        raw_bytes = struct.pack(">i", val)
        regs = [struct.unpack(">H", raw_bytes[i:i+2])[0] for i in range(0, 4, 2)]
        assert decode_registers(regs, "int32") == val

    def test_float32(self):
        val = 23.5
        raw_bytes = struct.pack(">f", val)
        regs = [struct.unpack(">H", raw_bytes[i:i+2])[0] for i in range(0, 4, 2)]
        result = decode_registers(regs, "float32")
        assert abs(result - val) < 0.001

    def test_float64(self):
        val = 123456.789
        raw_bytes = struct.pack(">d", val)
        regs = [struct.unpack(">H", raw_bytes[i:i+2])[0] for i in range(0, 8, 2)]
        result = decode_registers(regs, "float64")
        assert abs(result - val) < 0.001

    def test_unknown_type_returns_first_register(self):
        assert decode_registers([42], "unknown_type") == 42


class TestEncodeValue:
    def test_bool_true(self):
        assert encode_value(True, "bool") == [1]

    def test_bool_false(self):
        assert encode_value(False, "bool") == [0]

    def test_uint16(self):
        assert encode_value(1000, "uint16") == [1000]

    def test_int16_negative(self):
        regs = encode_value(-100, "int16")
        assert decode_registers(regs, "int16") == -100

    def test_float32_roundtrip(self):
        val = 23.5
        regs = encode_value(val, "float32")
        result = decode_registers(regs, "float32")
        assert abs(result - val) < 0.001

    def test_uint32_roundtrip(self):
        val = 100000
        regs = encode_value(val, "uint32")
        assert decode_registers(regs, "uint32") == val

    def test_unknown_type(self):
        assert encode_value(42, "unknown_type") == [42]


class TestTypeMapping:
    def test_to_device_data_type_bool(self):
        assert _to_device_data_type("bool") == DataType.BOOL

    def test_to_device_data_type_uint16(self):
        assert _to_device_data_type("uint16") == DataType.INT

    def test_to_device_data_type_int32(self):
        assert _to_device_data_type("int32") == DataType.INT

    def test_to_device_data_type_float32(self):
        assert _to_device_data_type("float32") == DataType.FLOAT

    def test_to_device_data_type_unknown(self):
        assert _to_device_data_type("weird") == DataType.STRING

    def test_to_cap_type_sensor(self):
        assert _to_cap_type("sensor") == CapabilityType.SENSOR

    def test_to_cap_type_actuator(self):
        assert _to_cap_type("actuator") == CapabilityType.ACTUATOR

    def test_to_cap_type_unknown(self):
        assert _to_cap_type("unknown") == CapabilityType.PROPERTY


# ---------------------------------------------------------------------------
# Test: Configuration parsing
# ---------------------------------------------------------------------------

class TestPLCPointConfig:
    def test_from_dict_minimal(self):
        pt = PLCPointConfig.from_dict({"capability": "temp"})
        assert pt.capability == "temp"
        assert pt.cap_type == "sensor"
        assert pt.register_type == "holding"
        assert pt.data_type == "uint16"
        assert pt.scale == 1.0
        assert pt.value_range is None

    def test_from_dict_full(self):
        pt = PLCPointConfig.from_dict({
            "capability": "speed",
            "cap_type": "actuator",
            "register_type": "holding",
            "address": 200,
            "data_type": "float32",
            "unit": "RPM",
            "scale": 0.1,
            "range": [0, 3000],
        })
        assert pt.capability == "speed"
        assert pt.cap_type == "actuator"
        assert pt.address == 200
        assert pt.data_type == "float32"
        assert pt.unit == "RPM"
        assert pt.scale == 0.1
        assert pt.value_range == (0.0, 3000.0)

    def test_to_device_capability(self):
        pt = PLCPointConfig(
            capability="temperature",
            cap_type="sensor",
            data_type="float32",
            unit="°C",
        )
        cap = pt.to_device_capability()
        assert cap.name == "temperature"
        assert cap.cap_type == CapabilityType.SENSOR
        assert cap.data_type == DataType.FLOAT
        assert cap.unit == "°C"


class TestPLCDeviceConfig:
    def test_from_dict(self):
        dev = PLCDeviceConfig.from_dict({
            "node_id": "plc-01",
            "device_type": "plc_sensor",
            "name": "Assembly Temp",
            "points": [{"capability": "temp"}],
        })
        assert dev.node_id == "plc-01"
        assert dev.device_type == "plc_sensor"
        assert dev.name == "Assembly Temp"
        assert len(dev.points) == 1

    def test_to_capabilities(self):
        dev = PLCDeviceConfig(
            node_id="plc-01",
            points=[
                PLCPointConfig(capability="temp", cap_type="sensor", data_type="float32"),
                PLCPointConfig(capability="valve", cap_type="actuator", data_type="bool"),
            ],
        )
        caps = dev.to_capabilities()
        assert len(caps) == 2
        assert caps[0].name == "temp"
        assert caps[1].name == "valve"


class TestBridgeConfig:
    def test_from_dict(self):
        bc = BridgeConfig.from_dict({
            "bridge_id": "modbus-01",
            "protocol": "modbus_tcp",
            "host": "192.168.1.50",
            "port": 502,
            "unit_id": 1,
            "poll_interval": 10.0,
            "devices": [
                {"node_id": "plc-01", "points": [{"capability": "temp"}]},
            ],
        })
        assert bc.bridge_id == "modbus-01"
        assert bc.host == "192.168.1.50"
        assert bc.port == 502
        assert bc.poll_interval == 10.0
        assert len(bc.devices) == 1

    def test_defaults(self):
        bc = BridgeConfig.from_dict({"bridge_id": "test"})
        assert bc.protocol == "modbus_tcp"
        assert bc.host == "127.0.0.1"
        assert bc.port == 502
        assert bc.unit_id == 1
        assert bc.poll_interval == 5.0


# ---------------------------------------------------------------------------
# Test: StubAdapter
# ---------------------------------------------------------------------------

class TestStubAdapter:
    @pytest.mark.asyncio
    async def test_connect_returns_false(self):
        stub = StubAdapter()
        assert await stub.connect() is False

    @pytest.mark.asyncio
    async def test_disconnect_noop(self):
        stub = StubAdapter()
        await stub.disconnect()  # should not raise

    @pytest.mark.asyncio
    async def test_read_returns_none(self):
        stub = StubAdapter()
        pt = PLCPointConfig(capability="test")
        assert await stub.read_point(pt) is None

    @pytest.mark.asyncio
    async def test_write_returns_false(self):
        stub = StubAdapter()
        pt = PLCPointConfig(capability="test")
        assert await stub.write_point(pt, 42) is False

    def test_connected_false(self):
        stub = StubAdapter()
        assert stub.connected is False


# ---------------------------------------------------------------------------
# Test: Protocol registry
# ---------------------------------------------------------------------------

class TestProtocolRegistry:
    def test_register_and_get(self):
        class CustomAdapter(IndustrialProtocol):
            async def connect(self): return True
            async def disconnect(self): pass
            async def read_point(self, point, unit_id=1): return None
            async def write_point(self, point, value, unit_id=1): return False
            @property
            def connected(self): return False

        register_protocol("custom_test", CustomAdapter)
        assert get_protocol_adapter("custom_test") is CustomAdapter

    def test_get_unknown_returns_none(self):
        assert get_protocol_adapter("nonexistent_protocol") is None


# ---------------------------------------------------------------------------
# Mock adapter for IndustrialBridge tests
# ---------------------------------------------------------------------------

class MockAdapter(IndustrialProtocol):
    """In-memory mock adapter for testing the bridge without real PLC."""

    def __init__(self, **kwargs):
        self._connected = False
        self._registers: dict[tuple[str, int], Any] = {}  # (reg_type, addr) → value

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def read_point(self, point: PLCPointConfig, unit_id: int = 1) -> Any | None:
        if not self._connected:
            return None
        key = (point.register_type, point.address)
        raw = self._registers.get(key)
        if raw is None:
            return None
        return raw * point.scale if isinstance(raw, (int, float)) and not isinstance(raw, bool) else raw

    async def write_point(self, point: PLCPointConfig, value: Any, unit_id: int = 1) -> bool:
        if not self._connected:
            return False
        if point.scale and point.scale != 1.0 and isinstance(value, (int, float)):
            value = value / point.scale
        key = (point.register_type, point.address)
        self._registers[key] = value
        return True

    def set_register(self, reg_type: str, address: int, value: Any) -> None:
        self._registers[(reg_type, address)] = value


# Register mock adapter for tests
register_protocol("mock_test", MockAdapter)


# ---------------------------------------------------------------------------
# Test: IndustrialBridge — config loading
# ---------------------------------------------------------------------------

class TestBridgeLoading:
    def test_load_nonexistent_file(self, tmp_path):
        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(tmp_path / "nope.json"), reg)
        count = bridge.load()
        assert count == 0
        assert bridge.bridge_count == 0

    def test_load_valid_config(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "test-01",
                "protocol": "mock_test",
                "host": "127.0.0.1",
                "port": 502,
                "devices": [{
                    "node_id": "plc-temp",
                    "device_type": "plc_sensor",
                    "points": [
                        {"capability": "temp", "address": 100, "data_type": "float32"},
                        {"capability": "valve", "cap_type": "actuator", "address": 200, "data_type": "bool"},
                    ],
                }],
            }],
        }
        cfg_path = tmp_path / "industrial.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        count = bridge.load()
        assert count == 1
        assert bridge.bridge_count == 1
        assert bridge.device_count == 1
        assert bridge.is_industrial_device("plc-temp")
        assert not bridge.is_industrial_device("unknown")

    def test_load_invalid_json(self, tmp_path):
        cfg_path = tmp_path / "bad.json"
        cfg_path.write_text("not valid json{{{")
        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        count = bridge.load()
        assert count == 0

    def test_load_multiple_bridges(self, tmp_path):
        config = {
            "bridges": [
                {"bridge_id": "b1", "protocol": "mock_test", "devices": [{"node_id": "d1", "points": []}]},
                {"bridge_id": "b2", "protocol": "mock_test", "devices": [{"node_id": "d2", "points": []}, {"node_id": "d3", "points": []}]},
            ]
        }
        cfg_path = tmp_path / "multi.json"
        cfg_path.write_text(json.dumps(config))
        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        assert bridge.bridge_count == 2
        assert bridge.device_count == 3


# ---------------------------------------------------------------------------
# Test: IndustrialBridge — lifecycle (start/stop)
# ---------------------------------------------------------------------------

class TestBridgeLifecycle:
    @pytest.mark.asyncio
    async def test_start_registers_devices(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "test-01",
                "protocol": "mock_test",
                "host": "127.0.0.1",
                "devices": [{
                    "node_id": "plc-temp",
                    "device_type": "plc_sensor",
                    "name": "Temp Sensor",
                    "points": [
                        {"capability": "temp", "cap_type": "sensor", "address": 100, "data_type": "float32", "unit": "°C"},
                    ],
                }],
            }],
        }
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()

        try:
            # Device should be registered
            dev = reg.get_device("plc-temp")
            assert dev is not None
            assert dev.device_type == "plc_sensor"
            assert dev.name == "Temp Sensor"
            assert dev.online is True
            assert len(dev.capabilities) == 1
            assert dev.capabilities[0].name == "temp"
            assert dev.metadata.get("bridge_id") == "test-01"
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_stop_disconnects(self, tmp_path):
        config = {"bridges": [{"bridge_id": "b1", "protocol": "mock_test", "devices": []}]}
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()
        assert len(bridge._adapters) == 1
        await bridge.stop()
        assert len(bridge._adapters) == 0

    @pytest.mark.asyncio
    async def test_start_with_unavailable_protocol(self, tmp_path):
        config = {"bridges": [{"bridge_id": "b1", "protocol": "nonexistent", "devices": []}]}
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()
        # Should use StubAdapter, not crash
        assert len(bridge._adapters) == 1
        await bridge.stop()


# ---------------------------------------------------------------------------
# Test: IndustrialBridge — command execution
# ---------------------------------------------------------------------------

class TestBridgeCommands:
    @pytest.mark.asyncio
    async def test_execute_command(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "test-01",
                "protocol": "mock_test",
                "devices": [{
                    "node_id": "plc-01",
                    "points": [
                        {"capability": "valve", "cap_type": "actuator", "register_type": "coil", "address": 10, "data_type": "bool"},
                    ],
                }],
            }],
        }
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()

        try:
            ok = await bridge.execute_command("plc-01", "valve", True)
            assert ok is True
            # Registry state should be updated
            dev = reg.get_device("plc-01")
            assert dev is not None
            assert dev.state.get("valve") is True
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_execute_command_unknown_device(self, tmp_path):
        config = {"bridges": [{"bridge_id": "b1", "protocol": "mock_test", "devices": []}]}
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()

        try:
            ok = await bridge.execute_command("unknown", "temp", 25)
            assert ok is False
        finally:
            await bridge.stop()

    @pytest.mark.asyncio
    async def test_execute_command_disconnected(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "b1",
                "protocol": "mock_test",
                "devices": [{"node_id": "d1", "points": [{"capability": "v", "address": 0}]}],
            }],
        }
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()

        # Manually disconnect
        adapter = list(bridge._adapters.values())[0]
        await adapter.disconnect()

        try:
            ok = await bridge.execute_command("d1", "v", 42)
            assert ok is False
        finally:
            await bridge.stop()


# ---------------------------------------------------------------------------
# Test: IndustrialBridge — list_bridges
# ---------------------------------------------------------------------------

class TestListBridges:
    @pytest.mark.asyncio
    async def test_list_bridges_status(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "test-01",
                "protocol": "mock_test",
                "host": "192.168.1.50",
                "port": 502,
                "poll_interval": 10.0,
                "devices": [{"node_id": "d1", "points": []}],
            }],
        }
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg)
        bridge.load()
        await bridge.start()

        try:
            bridges = bridge.list_bridges()
            assert len(bridges) == 1
            b = bridges[0]
            assert b["bridge_id"] == "test-01"
            assert b["protocol"] == "mock_test"
            assert b["host"] == "192.168.1.50"
            assert b["connected"] is True
            assert b["device_count"] == 1
            assert b["poll_interval"] == 10.0
        finally:
            await bridge.stop()


# ---------------------------------------------------------------------------
# Test: Polling loop (single cycle)
# ---------------------------------------------------------------------------

class TestPolling:
    @pytest.mark.asyncio
    async def test_poll_updates_registry(self, tmp_path):
        config = {
            "bridges": [{
                "bridge_id": "test-01",
                "protocol": "mock_test",
                "poll_interval": 0.1,  # Fast for testing
                "devices": [{
                    "node_id": "plc-temp",
                    "points": [{"capability": "temp", "address": 100, "data_type": "uint16"}],
                }],
            }],
        }
        cfg_path = tmp_path / "ind.json"
        cfg_path.write_text(json.dumps(config))

        state_updates = []
        def on_update(node_id, state):
            state_updates.append((node_id, state))

        reg = DeviceRegistry(path=str(tmp_path / "reg.json"))
        bridge = IndustrialBridge(str(cfg_path), reg, on_state_update=on_update)
        bridge.load()
        await bridge.start()

        try:
            # Set a register value in the mock adapter
            adapter = list(bridge._adapters.values())[0]
            adapter.set_register("holding", 100, 250)

            # Wait for one poll cycle
            await asyncio.sleep(0.3)

            # Check registry was updated
            dev = reg.get_device("plc-temp")
            assert dev is not None
            assert dev.state.get("temp") == 250

            # Callback should have been called
            assert len(state_updates) >= 1
            assert state_updates[-1][0] == "plc-temp"
            assert state_updates[-1][1]["temp"] == 250
        finally:
            await bridge.stop()


# ---------------------------------------------------------------------------
# Test: Channel integration
# ---------------------------------------------------------------------------

class TestChannelIntegration:
    def test_industrial_none_when_no_config(self):
        """When industrial_config_path is empty, channel.industrial should be None."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-1"
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
        config.registry_path = "/tmp/test_reg.json"
        config.automation_rules_path = "/tmp/test_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_groups.json"
        config.scenes_path = "/tmp/test_scenes.json"
        config.dashboard_port = 0
        config.industrial_config_path = ""

        bus = MagicMock()
        ch = MeshChannel(config, bus)
        assert ch.industrial is None

    def test_industrial_created_when_config_set(self, tmp_path):
        """When industrial_config_path is set, channel.industrial should be created."""
        from nanobot.mesh.channel import MeshChannel

        # Create a minimal config file
        cfg_path = tmp_path / "industrial.json"
        cfg_path.write_text(json.dumps({"bridges": []}))

        config = MagicMock()
        config.node_id = "hub-1"
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
        config.registry_path = str(tmp_path / "reg.json")
        config.automation_rules_path = str(tmp_path / "auto.json")
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = str(tmp_path / "groups.json")
        config.scenes_path = str(tmp_path / "scenes.json")
        config.dashboard_port = 0
        config.industrial_config_path = str(cfg_path)

        bus = MagicMock()
        ch = MeshChannel(config, bus)
        assert ch.industrial is not None
        assert isinstance(ch.industrial, IndustrialBridge)

    @pytest.mark.asyncio
    async def test_execute_industrial_command_no_bridge(self):
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-1"
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
        config.registry_path = "/tmp/test_reg.json"
        config.automation_rules_path = "/tmp/test_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_groups.json"
        config.scenes_path = "/tmp/test_scenes.json"
        config.dashboard_port = 0
        config.industrial_config_path = ""

        bus = MagicMock()
        ch = MeshChannel(config, bus)
        result = await ch.execute_industrial_command("plc-01", "temp", 25)
        assert result is False

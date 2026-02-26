"""Tests for nanobot.mesh.ble — BLE bridge for battery-powered sensors."""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.ble import (
    BLEAdvertisement,
    BLEBridge,
    BLECapabilityDef,
    BLEConfig,
    BLEDeviceProfile,
    BLEScanner,
    BleakBLEScanner,
    StubScanner,
    decode_value,
)


# ---------------------------------------------------------------------------
# BLEAdvertisement
# ---------------------------------------------------------------------------


class TestBLEAdvertisement:
    """Test BLEAdvertisement dataclass."""

    def test_node_id_from_address(self):
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="Test",
            rssi=-65,
            manufacturer_data={},
            service_data={},
        )
        assert adv.node_id == "ble-aabbccddeeff"

    def test_node_id_lowercase(self):
        adv = BLEAdvertisement(
            address="11:22:33:44:55:66",
            name="",
            rssi=-80,
            manufacturer_data={},
            service_data={},
        )
        assert adv.node_id == "ble-112233445566"


# ---------------------------------------------------------------------------
# BLECapabilityDef
# ---------------------------------------------------------------------------


class TestBLECapabilityDef:
    """Test BLECapabilityDef parsing."""

    def test_from_dict_full(self):
        d = {
            "name": "temperature",
            "data_source": "service",
            "service_uuid": "0000181a-0000-1000-8000-00805f9b34fb",
            "byte_offset": 0,
            "byte_length": 2,
            "data_type": "int16",
            "scale": 0.01,
            "unit": "°C",
            "cap_type": "sensor",
        }
        cap = BLECapabilityDef.from_dict(d)
        assert cap.name == "temperature"
        assert cap.data_source == "service"
        assert cap.scale == 0.01
        assert cap.unit == "°C"

    def test_from_dict_defaults(self):
        d = {"name": "raw"}
        cap = BLECapabilityDef.from_dict(d)
        assert cap.data_source == "manufacturer"
        assert cap.byte_offset == 0
        assert cap.byte_length == 2
        assert cap.scale == 1.0

    def test_from_dict_manufacturer(self):
        d = {
            "name": "battery",
            "data_source": "manufacturer",
            "company_id": 0x004C,
            "byte_offset": 4,
            "byte_length": 1,
            "data_type": "uint8",
            "scale": 1.0,
            "unit": "%",
        }
        cap = BLECapabilityDef.from_dict(d)
        assert cap.company_id == 0x004C
        assert cap.data_type == "uint8"


# ---------------------------------------------------------------------------
# decode_value
# ---------------------------------------------------------------------------


class TestDecodeValue:
    """Test byte-level value decoding."""

    def test_int16(self):
        cap = BLECapabilityDef(name="temp", data_source="service", data_type="int16",
                                byte_offset=0, byte_length=2, scale=0.01)
        raw = struct.pack("<h", 2350)  # 23.50°C
        assert decode_value(raw, cap) == 23.5

    def test_uint16(self):
        cap = BLECapabilityDef(name="hum", data_source="service", data_type="uint16",
                                byte_offset=0, byte_length=2, scale=0.1)
        raw = struct.pack("<H", 650)  # 65.0%
        assert decode_value(raw, cap) == 65.0

    def test_uint8(self):
        cap = BLECapabilityDef(name="bat", data_source="manufacturer", data_type="uint8",
                                byte_offset=0, byte_length=1, scale=1.0)
        raw = struct.pack("B", 85)
        assert decode_value(raw, cap) == 85.0

    def test_int8(self):
        cap = BLECapabilityDef(name="temp", data_source="service", data_type="int8",
                                byte_offset=0, byte_length=1, scale=1.0)
        raw = struct.pack("b", -10)
        assert decode_value(raw, cap) == -10.0

    def test_float32(self):
        cap = BLECapabilityDef(name="pressure", data_source="service", data_type="float32",
                                byte_offset=0, byte_length=4, scale=1.0)
        raw = struct.pack("<f", 101.325)
        result = decode_value(raw, cap)
        assert result is not None
        assert abs(result - 101.325) < 0.001

    def test_offset(self):
        cap = BLECapabilityDef(name="hum", data_source="service", data_type="uint16",
                                byte_offset=2, byte_length=2, scale=0.01)
        raw = struct.pack("<hH", 2350, 6500)  # temp then humidity
        assert decode_value(raw, cap) == 65.0

    def test_too_short(self):
        cap = BLECapabilityDef(name="temp", data_source="service", data_type="int16",
                                byte_offset=0, byte_length=2, scale=1.0)
        raw = b"\x01"  # too short
        assert decode_value(raw, cap) is None

    def test_unknown_type(self):
        cap = BLECapabilityDef(name="x", data_source="service", data_type="float64",
                                byte_offset=0, byte_length=8, scale=1.0)
        raw = b"\x00" * 8
        assert decode_value(raw, cap) is None


# ---------------------------------------------------------------------------
# BLEDeviceProfile
# ---------------------------------------------------------------------------


class TestBLEDeviceProfile:
    """Test profile matching."""

    def test_matches_exact(self):
        profile = BLEDeviceProfile(
            name="Xiaomi Thermo", name_pattern="^LYWSD",
            device_type="thermo",
        )
        assert profile.matches("LYWSD03MMC") is True

    def test_no_match(self):
        profile = BLEDeviceProfile(
            name="Xiaomi", name_pattern="^LYWSD",
            device_type="thermo",
        )
        assert profile.matches("Govee_H5075") is False

    def test_case_insensitive(self):
        profile = BLEDeviceProfile(
            name="Test", name_pattern="^test",
            device_type="generic",
        )
        assert profile.matches("TEST-DEVICE") is True

    def test_empty_name_no_match(self):
        profile = BLEDeviceProfile(
            name="Test", name_pattern="test",
            device_type="generic",
        )
        assert profile.matches("") is False

    def test_bad_regex(self):
        profile = BLEDeviceProfile(
            name="Bad", name_pattern="[invalid",
            device_type="generic",
        )
        assert profile.matches("anything") is False

    def test_from_dict(self):
        d = {
            "name": "Govee Sensor",
            "name_pattern": "^GVH5",
            "device_type": "temp_humidity",
            "capabilities": [
                {"name": "temperature", "data_source": "manufacturer",
                 "company_id": 0xEC88, "byte_offset": 3, "byte_length": 2,
                 "data_type": "int16", "scale": 0.01, "unit": "°C"},
            ],
        }
        p = BLEDeviceProfile.from_dict(d)
        assert p.name == "Govee Sensor"
        assert len(p.capabilities) == 1
        assert p.capabilities[0].company_id == 0xEC88


# ---------------------------------------------------------------------------
# BLEConfig
# ---------------------------------------------------------------------------


class TestBLEConfig:
    """Test config parsing."""

    def test_from_dict(self):
        d = {
            "scan_interval": 60,
            "scan_duration": 15,
            "device_timeout": 300,
            "profiles": [
                {"name": "Test", "name_pattern": "^TEST", "device_type": "test"},
            ],
        }
        cfg = BLEConfig.from_dict(d)
        assert cfg.scan_interval == 60
        assert cfg.scan_duration == 15
        assert cfg.device_timeout == 300
        assert len(cfg.profiles) == 1

    def test_defaults(self):
        cfg = BLEConfig.from_dict({})
        assert cfg.scan_interval == 30
        assert cfg.scan_duration == 10
        assert cfg.device_timeout == 120
        assert cfg.profiles == []


# ---------------------------------------------------------------------------
# StubScanner
# ---------------------------------------------------------------------------


class TestStubScanner:
    """Test StubScanner for testing."""

    @pytest.mark.asyncio
    async def test_empty_scan(self):
        s = StubScanner()
        result = await s.scan(1.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_add_advertisement(self):
        s = StubScanner()
        adv = BLEAdvertisement("AA:BB:CC:DD:EE:FF", "Test", -65, {}, {})
        s.add_advertisement(adv)
        result = await s.scan(1.0)
        assert len(result) == 1
        assert result[0].name == "Test"

    @pytest.mark.asyncio
    async def test_clear(self):
        s = StubScanner()
        s.add_advertisement(BLEAdvertisement("AA:BB:CC:DD:EE:FF", "Test", -65, {}, {}))
        s.clear()
        result = await s.scan(1.0)
        assert result == []


# ---------------------------------------------------------------------------
# BLEBridge — config loading
# ---------------------------------------------------------------------------


class TestBLEBridgeLoad:
    """Test config loading."""

    def test_load_valid(self, tmp_path):
        path = str(tmp_path / "ble.json")
        config = {
            "scan_interval": 20,
            "profiles": [
                {"name": "Test", "name_pattern": "^TEST", "device_type": "test",
                 "capabilities": [{"name": "temp", "data_source": "manufacturer",
                                   "company_id": 1, "byte_offset": 0,
                                   "byte_length": 2, "data_type": "int16"}]},
            ],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        assert bridge.load() == 1
        assert bridge.config is not None
        assert bridge.config.scan_interval == 20

    def test_load_missing_file(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        assert bridge.load() == 0

    def test_load_corrupt(self, tmp_path):
        path = str(tmp_path / "bad.json")
        Path(path).write_text("not json")
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        assert bridge.load() == 0


# ---------------------------------------------------------------------------
# BLEBridge — profile matching
# ---------------------------------------------------------------------------


class TestBLEBridgeMatching:
    """Test device profile matching."""

    def _make_bridge(self, tmp_path, profiles):
        path = str(tmp_path / "ble.json")
        config = {"profiles": profiles}
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()
        return bridge

    def test_match_first(self, tmp_path):
        bridge = self._make_bridge(tmp_path, [
            {"name": "A", "name_pattern": "^AAA", "device_type": "a"},
            {"name": "B", "name_pattern": "^BBB", "device_type": "b"},
        ])
        profile = bridge._match_profile("AAA-device", bridge.config.profiles)
        assert profile is not None
        assert profile.name == "A"

    def test_no_match(self, tmp_path):
        bridge = self._make_bridge(tmp_path, [
            {"name": "A", "name_pattern": "^AAA", "device_type": "a"},
        ])
        profile = bridge._match_profile("ZZZ-unknown", bridge.config.profiles)
        assert profile is None

    def test_empty_name(self, tmp_path):
        bridge = self._make_bridge(tmp_path, [
            {"name": "A", "name_pattern": ".*", "device_type": "a"},
        ])
        profile = bridge._match_profile("", bridge.config.profiles)
        assert profile is None


# ---------------------------------------------------------------------------
# BLEBridge — decode advertisement
# ---------------------------------------------------------------------------


class TestBLEBridgeDecode:
    """Test advertisement decoding."""

    def test_decode_manufacturer_data(self, tmp_path):
        path = str(tmp_path / "ble.json")
        config = {
            "profiles": [{
                "name": "Sensor",
                "name_pattern": "^SENSOR",
                "device_type": "test_sensor",
                "capabilities": [
                    {"name": "temperature", "data_source": "manufacturer",
                     "company_id": 0x0059, "byte_offset": 0, "byte_length": 2,
                     "data_type": "int16", "scale": 0.01, "unit": "°C"},
                ],
            }],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()

        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="SENSOR-01",
            rssi=-55,
            manufacturer_data={0x0059: struct.pack("<h", 2350)},
            service_data={},
        )
        profile = bridge._match_profile(adv.name, bridge.config.profiles)
        state = bridge._decode_advertisement(adv, profile)
        assert "temperature" in state
        assert state["temperature"] == 23.5

    def test_decode_service_data(self, tmp_path):
        path = str(tmp_path / "ble.json")
        uuid = "0000181a-0000-1000-8000-00805f9b34fb"
        config = {
            "profiles": [{
                "name": "EnvSensor",
                "name_pattern": "^ENV",
                "device_type": "env_sensor",
                "capabilities": [
                    {"name": "humidity", "data_source": "service",
                     "service_uuid": uuid, "byte_offset": 0,
                     "byte_length": 2, "data_type": "uint16", "scale": 0.1},
                ],
            }],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()

        adv = BLEAdvertisement(
            address="11:22:33:44:55:66",
            name="ENV-SENSOR",
            rssi=-70,
            manufacturer_data={},
            service_data={uuid: struct.pack("<H", 650)},
        )
        profile = bridge._match_profile(adv.name, bridge.config.profiles)
        state = bridge._decode_advertisement(adv, profile)
        assert state["humidity"] == 65.0

    def test_decode_missing_data(self, tmp_path):
        path = str(tmp_path / "ble.json")
        config = {
            "profiles": [{
                "name": "X",
                "name_pattern": "^X",
                "device_type": "x",
                "capabilities": [
                    {"name": "temp", "data_source": "manufacturer",
                     "company_id": 99, "byte_offset": 0,
                     "byte_length": 2, "data_type": "int16"},
                ],
            }],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()

        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="X-DEVICE",
            rssi=-60,
            manufacturer_data={},  # no company_id 99
            service_data={},
        )
        profile = bridge._match_profile(adv.name, bridge.config.profiles)
        state = bridge._decode_advertisement(adv, profile)
        assert state == {}


# ---------------------------------------------------------------------------
# BLEBridge — process advertisements
# ---------------------------------------------------------------------------


class TestBLEBridgeProcess:
    """Test _process_advertisements end-to-end."""

    def _create_bridge(self, tmp_path, callback=None):
        path = str(tmp_path / "ble.json")
        config = {
            "profiles": [{
                "name": "TempSensor",
                "name_pattern": "^TEMP",
                "device_type": "temp_sensor",
                "capabilities": [
                    {"name": "temperature", "data_source": "manufacturer",
                     "company_id": 1, "byte_offset": 0, "byte_length": 2,
                     "data_type": "int16", "scale": 0.01, "unit": "°C",
                     "cap_type": "sensor"},
                ],
            }],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        registry.register_device = AsyncMock()
        registry.update_state = AsyncMock(return_value=True)
        registry.get_device = MagicMock(return_value=None)
        bridge = BLEBridge(
            config_path=path,
            registry=registry,
            on_state_update=callback,
        )
        bridge.load()
        return bridge

    @pytest.mark.asyncio
    async def test_process_registers_new_device(self, tmp_path):
        bridge = self._create_bridge(tmp_path)
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="TEMP-001",
            rssi=-55,
            manufacturer_data={1: struct.pack("<h", 2200)},
            service_data={},
        )
        await bridge._process_advertisements([adv])
        bridge.registry.register_device.assert_called_once()
        node_id = adv.node_id
        assert node_id in bridge._managed_devices

    @pytest.mark.asyncio
    async def test_process_updates_state(self, tmp_path):
        bridge = self._create_bridge(tmp_path)
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="TEMP-001",
            rssi=-55,
            manufacturer_data={1: struct.pack("<h", 2200)},
            service_data={},
        )
        await bridge._process_advertisements([adv])
        bridge.registry.update_state.assert_called_once()
        call_args = bridge.registry.update_state.call_args
        state = call_args[0][1]
        assert "temperature" in state
        assert state["temperature"] == 22.0
        assert "rssi" in state

    @pytest.mark.asyncio
    async def test_process_calls_callback(self, tmp_path):
        callback = MagicMock()
        bridge = self._create_bridge(tmp_path, callback=callback)
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="TEMP-001",
            rssi=-55,
            manufacturer_data={1: struct.pack("<h", 2500)},
            service_data={},
        )
        await bridge._process_advertisements([adv])
        callback.assert_called_once()
        node_id, state = callback.call_args[0]
        assert node_id == adv.node_id
        assert state["temperature"] == 25.0

    @pytest.mark.asyncio
    async def test_process_skips_unmatched(self, tmp_path):
        bridge = self._create_bridge(tmp_path)
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="UNKNOWN-DEVICE",
            rssi=-80,
            manufacturer_data={},
            service_data={},
        )
        await bridge._process_advertisements([adv])
        bridge.registry.register_device.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_does_not_re_register(self, tmp_path):
        bridge = self._create_bridge(tmp_path)
        adv = BLEAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            name="TEMP-001",
            rssi=-55,
            manufacturer_data={1: struct.pack("<h", 2200)},
            service_data={},
        )
        # Process twice
        await bridge._process_advertisements([adv])
        await bridge._process_advertisements([adv])
        # Should only register once
        assert bridge.registry.register_device.call_count == 1


# ---------------------------------------------------------------------------
# BLEBridge — stale device pruning
# ---------------------------------------------------------------------------


class TestBLEBridgePruning:
    """Test stale device pruning."""

    def test_prune_stale(self, tmp_path):
        path = str(tmp_path / "ble.json")
        Path(path).write_text(json.dumps({"profiles": []}))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()

        bridge._device_last_seen["ble-aabbccddeeff"] = time.time() - 200
        bridge._device_last_seen["ble-112233445566"] = time.time()

        bridge._prune_stale_devices(120)
        registry.mark_offline.assert_called_once_with("ble-aabbccddeeff")
        assert "ble-aabbccddeeff" not in bridge._device_last_seen
        assert "ble-112233445566" in bridge._device_last_seen

    def test_prune_nothing_stale(self, tmp_path):
        path = str(tmp_path / "ble.json")
        Path(path).write_text(json.dumps({"profiles": []}))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge.load()

        bridge._device_last_seen["ble-aabb"] = time.time()
        bridge._prune_stale_devices(120)
        registry.mark_offline.assert_not_called()


# ---------------------------------------------------------------------------
# BLEBridge — lifecycle
# ---------------------------------------------------------------------------


class TestBLEBridgeLifecycle:
    """Test start/stop."""

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path):
        path = str(tmp_path / "ble.json")
        Path(path).write_text(json.dumps({"scan_interval": 1, "profiles": []}))
        registry = MagicMock()
        stub = StubScanner()
        bridge = BLEBridge(config_path=path, registry=registry, scanner=stub)
        bridge.load()

        await bridge.start()
        assert bridge._running is True
        await asyncio.sleep(0.05)
        await bridge.stop()
        assert bridge._running is False

    @pytest.mark.asyncio
    async def test_scan_loop_processes(self, tmp_path):
        path = str(tmp_path / "ble.json")
        config = {
            "scan_interval": 0,  # don't wait
            "scan_duration": 0,
            "profiles": [
                {"name": "T", "name_pattern": "^T", "device_type": "t",
                 "capabilities": [{"name": "val", "data_source": "manufacturer",
                                   "company_id": 1, "byte_offset": 0,
                                   "byte_length": 2, "data_type": "int16"}]},
            ],
        }
        Path(path).write_text(json.dumps(config))
        registry = MagicMock()
        registry.register_device = AsyncMock()
        registry.update_state = AsyncMock(return_value=True)
        registry.get_device = MagicMock(return_value=None)

        stub = StubScanner()
        stub.add_advertisement(BLEAdvertisement(
            "AA:BB:CC:DD:EE:FF", "T-001", -60,
            {1: struct.pack("<h", 100)}, {},
        ))

        bridge = BLEBridge(config_path=path, registry=registry, scanner=stub)
        bridge.load()
        await bridge.start()
        await asyncio.sleep(0.2)
        await bridge.stop()

        registry.register_device.assert_called()
        registry.update_state.assert_called()


# ---------------------------------------------------------------------------
# BLEBridge — queries
# ---------------------------------------------------------------------------


class TestBLEBridgeQueries:
    """Test query methods."""

    def test_is_ble_device(self, tmp_path):
        path = str(tmp_path / "ble.json")
        Path(path).write_text(json.dumps({"profiles": []}))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge._managed_devices.add("ble-aabb")
        assert bridge.is_ble_device("ble-aabb") is True
        assert bridge.is_ble_device("other") is False

    def test_list_devices(self, tmp_path):
        path = str(tmp_path / "ble.json")
        Path(path).write_text(json.dumps({"profiles": []}))
        registry = MagicMock()
        bridge = BLEBridge(config_path=path, registry=registry)
        bridge._managed_devices.update(["ble-aa", "ble-bb"])
        devices = bridge.list_devices()
        assert set(devices) == {"ble-aa", "ble-bb"}


# ---------------------------------------------------------------------------
# Data type mapping
# ---------------------------------------------------------------------------


class TestDataTypeMapping:
    """Test _map_data_type static method."""

    def test_float32(self):
        assert BLEBridge._map_data_type("float32") == "float"

    def test_int_types(self):
        for t in ("uint8", "int8", "uint16", "int16", "uint32", "int32"):
            assert BLEBridge._map_data_type(t) == "int"

    def test_unknown_defaults_float(self):
        assert BLEBridge._map_data_type("unknown") == "float"


# ---------------------------------------------------------------------------
# Channel integration
# ---------------------------------------------------------------------------


class TestChannelBLEIntegration:
    """Test MeshChannel BLE integration."""

    def _make_config(self, **overrides):
        cfg = MagicMock()
        cfg.node_id = "test-hub"
        cfg.tcp_port = 18800
        cfg.udp_port = 18799
        cfg.roles = ["nanobot"]
        cfg.psk_auth_enabled = False
        cfg.allow_unauthenticated = True
        cfg.nonce_window = 60
        cfg.key_store_path = ""
        cfg.mtls_enabled = False
        cfg.ca_dir = ""
        cfg.device_cert_validity_days = 365
        cfg.encryption_enabled = False
        cfg.enrollment_pin_length = 6
        cfg.enrollment_pin_timeout = 300
        cfg.enrollment_max_attempts = 3
        cfg.registry_path = "/tmp/test_reg.json"
        cfg.automation_rules_path = "/tmp/test_auto.json"
        cfg.firmware_dir = ""
        cfg.ota_chunk_size = 4096
        cfg.ota_chunk_timeout = 30
        cfg.groups_path = "/tmp/groups.json"
        cfg.scenes_path = "/tmp/scenes.json"
        cfg.dashboard_port = 0
        cfg.industrial_config_path = ""
        cfg.federation_config_path = ""
        cfg.pipeline_enabled = False
        cfg.pipeline_path = ""
        cfg.pipeline_max_points = 10000
        cfg.pipeline_flush_interval = 60
        cfg.ble_config_path = ""
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_ble_disabled_by_default(self):
        cfg = self._make_config()
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.ble is None

    def test_ble_enabled(self, tmp_path):
        ble_path = str(tmp_path / "ble.json")
        Path(ble_path).write_text(json.dumps({
            "profiles": [{"name": "T", "name_pattern": "^T", "device_type": "t"}],
        }))
        cfg = self._make_config(ble_config_path=ble_path)
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.ble is not None
        assert len(ch.ble.config.profiles) == 1

    def test_ble_state_callback_records_to_pipeline(self, tmp_path):
        ble_path = str(tmp_path / "ble.json")
        Path(ble_path).write_text(json.dumps({"profiles": []}))
        sensor_path = str(tmp_path / "sensor_data.json")
        cfg = self._make_config(
            ble_config_path=ble_path,
            pipeline_enabled=True,
            pipeline_path=sensor_path,
        )
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.ble is not None
        assert ch.pipeline is not None

        # Simulate BLE state callback
        ch._on_ble_state_update("ble-aabb", {"temperature": 23.5})
        readings = ch.pipeline.query("ble-aabb", "temperature")
        assert len(readings) == 1
        assert readings[0].value == 23.5


# Import at bottom to avoid collection issues
from nanobot.mesh.channel import MeshChannel

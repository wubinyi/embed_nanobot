"""Tests for standardized device command schema (task 2.2).

Covers:
- DeviceCommand / CommandResponse / BatchCommand data model
- Command validation against device registry
- Value type/range validation
- Mesh envelope conversion
- LLM command description generator
- Edge cases
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.mesh.commands import (
    Action,
    BatchCommand,
    CommandResponse,
    CommandStatus,
    DeviceCommand,
    command_to_envelope,
    describe_device_commands,
    parse_command_from_envelope,
    parse_response_from_envelope,
    response_to_envelope,
    validate_command,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_registry_path():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def registry(tmp_registry_path):
    reg = DeviceRegistry(path=tmp_registry_path)
    reg.load()
    return reg


@pytest.fixture
def populated_registry(registry):
    """Registry with a light and sensor pre-registered."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(registry.register_device(
            "light-01", "smart_light",
            name="Desk Lamp",
            capabilities=[
                DeviceCapability("power", CapabilityType.ACTUATOR, DataType.BOOL),
                DeviceCapability("brightness", CapabilityType.PROPERTY, DataType.INT,
                                 unit="%", value_range=(0, 100)),
                DeviceCapability("color_mode", CapabilityType.PROPERTY, DataType.ENUM,
                                 enum_values=["white", "color", "scene"]),
            ],
        ))
        loop.run_until_complete(registry.register_device(
            "sensor-01", "temp_sensor",
            name="Kitchen Sensor",
            capabilities=[
                DeviceCapability("temperature", CapabilityType.SENSOR, DataType.FLOAT,
                                 unit="°C", value_range=(-40, 80)),
                DeviceCapability("humidity", CapabilityType.SENSOR, DataType.FLOAT,
                                 unit="%", value_range=(0, 100)),
            ],
        ))
        registry.mark_online("light-01")
        registry.mark_online("sensor-01")
    finally:
        loop.close()
    return registry


# ===================================================================
# Test: Data model
# ===================================================================

class TestDeviceCommand:
    """DeviceCommand serialization."""

    def test_to_dict_full(self):
        cmd = DeviceCommand(
            device="light-01",
            action="set",
            capability="brightness",
            params={"value": 80},
        )
        d = cmd.to_dict()
        assert d["device"] == "light-01"
        assert d["action"] == "set"
        assert d["capability"] == "brightness"
        assert d["params"]["value"] == 80

    def test_to_dict_minimal(self):
        cmd = DeviceCommand(device="d1", action="get")
        d = cmd.to_dict()
        assert "capability" not in d
        assert "params" not in d

    def test_roundtrip(self):
        cmd = DeviceCommand(
            device="light-01",
            action="set",
            capability="brightness",
            params={"value": 80},
        )
        restored = DeviceCommand.from_dict(cmd.to_dict())
        assert restored.device == cmd.device
        assert restored.action == cmd.action
        assert restored.capability == cmd.capability
        assert restored.params == cmd.params

    def test_from_dict_defaults(self):
        cmd = DeviceCommand.from_dict({})
        assert cmd.device == ""
        assert cmd.action == ""
        assert cmd.capability == ""
        assert cmd.params == {}


class TestCommandResponse:
    """CommandResponse serialization."""

    def test_ok_response(self):
        resp = CommandResponse(
            device="light-01",
            status=CommandStatus.OK,
            capability="brightness",
            value=80,
        )
        assert resp.is_ok is True
        d = resp.to_dict()
        assert d["status"] == "ok"
        assert d["value"] == 80
        assert "error" not in d

    def test_error_response(self):
        resp = CommandResponse(
            device="light-01",
            status=CommandStatus.ERROR,
            capability="brightness",
            error="Device busy",
        )
        assert resp.is_ok is False
        d = resp.to_dict()
        assert d["error"] == "Device busy"

    def test_roundtrip(self):
        resp = CommandResponse(
            device="d1", status="ok", capability="temp", value=23.5
        )
        restored = CommandResponse.from_dict(resp.to_dict())
        assert restored.device == resp.device
        assert restored.status == resp.status
        assert restored.value == resp.value


class TestBatchCommand:
    """BatchCommand serialization."""

    def test_batch_roundtrip(self):
        batch = BatchCommand(
            commands=[
                DeviceCommand("light-01", "set", "power", {"value": True}),
                DeviceCommand("light-01", "set", "brightness", {"value": 80}),
            ],
            stop_on_error=True,
        )
        d = batch.to_dict()
        assert len(d["commands"]) == 2
        assert d["stop_on_error"] is True
        restored = BatchCommand.from_dict(d)
        assert len(restored.commands) == 2
        assert restored.stop_on_error is True


# ===================================================================
# Test: Validation
# ===================================================================

class TestValidation:
    """Command validation against device registry."""

    def test_valid_set_command(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": 80})
        errors = validate_command(cmd, populated_registry)
        assert errors == []

    def test_valid_get_command(self, populated_registry):
        cmd = DeviceCommand("sensor-01", "get", "temperature")
        errors = validate_command(cmd, populated_registry)
        assert errors == []

    def test_valid_toggle_command(self, populated_registry):
        cmd = DeviceCommand("light-01", "toggle", "power")
        errors = validate_command(cmd, populated_registry)
        assert errors == []

    def test_unknown_device(self, populated_registry):
        cmd = DeviceCommand("ghost", "get", "temperature")
        errors = validate_command(cmd, populated_registry)
        assert any("not found" in e for e in errors)

    def test_unknown_action(self, populated_registry):
        cmd = DeviceCommand("light-01", "destroy", "power")
        errors = validate_command(cmd, populated_registry)
        assert any("Unknown action" in e for e in errors)

    def test_unknown_capability(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "volume", {"value": 50})
        errors = validate_command(cmd, populated_registry)
        assert any("no capability" in e for e in errors)

    def test_set_sensor_rejected(self, populated_registry):
        cmd = DeviceCommand("sensor-01", "set", "temperature", {"value": 25})
        errors = validate_command(cmd, populated_registry)
        assert any("Cannot 'set' a sensor" in e for e in errors)

    def test_toggle_non_bool_rejected(self, populated_registry):
        cmd = DeviceCommand("light-01", "toggle", "brightness")
        errors = validate_command(cmd, populated_registry)
        assert any("non-boolean" in e for e in errors)

    def test_offline_device_warning(self, populated_registry):
        populated_registry.mark_offline("light-01")
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": 80})
        errors = validate_command(cmd, populated_registry)
        assert any("offline" in e for e in errors)

    def test_missing_capability_for_set(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "", {"value": True})
        errors = validate_command(cmd, populated_registry)
        assert any("Missing 'capability'" in e for e in errors)

    def test_execute_without_capability_ok(self, populated_registry):
        cmd = DeviceCommand("light-01", "execute", "", {"function": "reset"})
        errors = validate_command(cmd, populated_registry)
        # execute doesn't require capability
        assert not any("Missing 'capability'" in e for e in errors)


# ===================================================================
# Test: Value validation
# ===================================================================

class TestValueValidation:
    """Type and range validation for SET values."""

    def test_bool_type_valid(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "power", {"value": True})
        assert validate_command(cmd, populated_registry) == []

    def test_bool_type_invalid(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "power", {"value": 1})
        errors = validate_command(cmd, populated_registry)
        assert any("must be bool" in e for e in errors)

    def test_int_type_valid(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": 50})
        assert validate_command(cmd, populated_registry) == []

    def test_int_type_invalid_string(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": "fifty"})
        errors = validate_command(cmd, populated_registry)
        assert any("must be int" in e for e in errors)

    def test_int_range_too_low(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": -10})
        errors = validate_command(cmd, populated_registry)
        assert any("out of range" in e for e in errors)

    def test_int_range_too_high(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": 200})
        errors = validate_command(cmd, populated_registry)
        assert any("out of range" in e for e in errors)

    def test_int_range_boundary_ok(self, populated_registry):
        cmd0 = DeviceCommand("light-01", "set", "brightness", {"value": 0})
        cmd100 = DeviceCommand("light-01", "set", "brightness", {"value": 100})
        assert validate_command(cmd0, populated_registry) == []
        assert validate_command(cmd100, populated_registry) == []

    def test_float_accepts_int(self, populated_registry):
        cmd = DeviceCommand("sensor-01", "get", "temperature")
        # GET doesn't need value validation, just test no error
        assert validate_command(cmd, populated_registry) == []

    def test_enum_valid(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "color_mode", {"value": "white"})
        assert validate_command(cmd, populated_registry) == []

    def test_enum_invalid(self, populated_registry):
        cmd = DeviceCommand("light-01", "set", "color_mode", {"value": "disco"})
        errors = validate_command(cmd, populated_registry)
        assert any("not in allowed values" in e for e in errors)


# ===================================================================
# Test: Envelope conversion
# ===================================================================

class TestEnvelopeConversion:
    """Convert between commands and mesh envelopes."""

    def test_command_to_envelope(self):
        cmd = DeviceCommand("light-01", "set", "brightness", {"value": 80})
        env = command_to_envelope(cmd, source="hub-01")
        assert env.type == MsgType.COMMAND
        assert env.source == "hub-01"
        assert env.target == "light-01"
        assert env.payload["device"] == "light-01"
        assert env.payload["action"] == "set"
        assert env.payload["params"]["value"] == 80

    def test_parse_command_from_envelope(self):
        env = MeshEnvelope(
            type=MsgType.COMMAND,
            source="hub-01",
            target="light-01",
            payload={
                "device": "light-01",
                "action": "set",
                "capability": "brightness",
                "params": {"value": 80},
            },
        )
        cmd = parse_command_from_envelope(env)
        assert cmd is not None
        assert cmd.device == "light-01"
        assert cmd.action == "set"
        assert cmd.params["value"] == 80

    def test_parse_command_wrong_type(self):
        env = MeshEnvelope(type=MsgType.CHAT, source="a", target="b", payload={})
        assert parse_command_from_envelope(env) is None

    def test_response_to_envelope(self):
        resp = CommandResponse("light-01", "ok", "brightness", 80)
        env = response_to_envelope(resp, source="light-01", target="hub-01")
        assert env.type == MsgType.RESPONSE
        assert env.source == "light-01"
        assert env.target == "hub-01"
        assert env.payload["status"] == "ok"

    def test_parse_response_from_envelope(self):
        env = MeshEnvelope(
            type=MsgType.RESPONSE,
            source="light-01",
            target="hub-01",
            payload={
                "device": "light-01",
                "status": "ok",
                "capability": "brightness",
                "value": 80,
            },
        )
        resp = parse_response_from_envelope(env)
        assert resp is not None
        assert resp.is_ok is True
        assert resp.value == 80

    def test_parse_response_wrong_type(self):
        env = MeshEnvelope(type=MsgType.CHAT, source="a", target="b", payload={})
        assert parse_response_from_envelope(env) is None

    def test_roundtrip_via_bytes(self):
        """Command → envelope → bytes → envelope → command."""
        cmd = DeviceCommand("sensor-01", "get", "temperature")
        env = command_to_envelope(cmd, source="hub")
        raw = env.to_bytes()
        env2 = MeshEnvelope.from_bytes(raw[4:])
        cmd2 = parse_command_from_envelope(env2)
        assert cmd2 is not None
        assert cmd2.device == "sensor-01"
        assert cmd2.action == "get"
        assert cmd2.capability == "temperature"


# ===================================================================
# Test: LLM description
# ===================================================================

class TestLLMDescription:
    """Command description generator for LLM context."""

    def test_empty_registry(self, registry):
        desc = describe_device_commands(registry)
        assert "No devices" in desc

    def test_populated_registry(self, populated_registry):
        desc = describe_device_commands(populated_registry)
        assert "Desk Lamp" in desc
        assert "light-01" in desc
        assert "brightness" in desc
        assert "ONLINE" in desc
        assert "0–100" in desc
        assert "white" in desc
        assert "Kitchen Sensor" in desc
        assert "temperature" in desc

    def test_shows_current_state(self, populated_registry):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                populated_registry.update_state("light-01", {"brightness": 75})
            )
        finally:
            loop.close()
        desc = describe_device_commands(populated_registry)
        assert "current: 75" in desc

    def test_action_reference(self, populated_registry):
        desc = describe_device_commands(populated_registry)
        assert "Action Reference" in desc
        assert "set" in desc
        assert "get" in desc
        assert "toggle" in desc


# ===================================================================
# Test: Action enum
# ===================================================================

class TestAction:
    def test_values(self):
        assert Action.SET == "set"
        assert Action.GET == "get"
        assert Action.TOGGLE == "toggle"
        assert Action.EXECUTE == "execute"

    def test_status_values(self):
        assert CommandStatus.OK == "ok"
        assert CommandStatus.ERROR == "error"

"""Tests for DeviceControlTool — NL→device command bridge (task 2.3).

Covers:
- Tool metadata (name, description, parameters schema)
- list action — empty and populated registry
- command action — valid commands, validation failures, transport failures
- state action — existing/missing devices, with/without state
- describe action — LLM description output
- Edge cases: missing params, offline devices, unknown devices
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.device import DeviceControlTool
from nanobot.mesh.commands import Action, DeviceCommand
from nanobot.mesh.protocol import MeshEnvelope
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
def mock_transport():
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=True)
    return transport


@pytest.fixture
def tool(registry, mock_transport):
    return DeviceControlTool(
        registry=registry,
        transport=mock_transport,
        node_id="hub-01",
    )


@pytest.fixture
def populated_tool(registry, mock_transport):
    """Tool with pre-registered devices."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(registry.register_device(
            "light-01", "smart_light",
            name="Living Room Light",
            capabilities=[
                DeviceCapability("power", CapabilityType.ACTUATOR, DataType.BOOL),
                DeviceCapability("brightness", CapabilityType.PROPERTY, DataType.INT,
                                 unit="%", value_range=(0, 100)),
            ],
        ))
        loop.run_until_complete(registry.register_device(
            "sensor-01", "temp_sensor",
            name="Kitchen Sensor",
            capabilities=[
                DeviceCapability("temperature", CapabilityType.SENSOR, DataType.FLOAT,
                                 unit="°C", value_range=(-40, 80)),
            ],
        ))
        registry.mark_online("light-01")
        registry.mark_online("sensor-01")
        loop.run_until_complete(
            registry.update_state("sensor-01", {"temperature": 23.5})
        )
    finally:
        loop.close()
    return DeviceControlTool(
        registry=registry,
        transport=mock_transport,
        node_id="hub-01",
    )


# ===================================================================
# Test: Tool metadata
# ===================================================================


class TestToolMetadata:

    def test_name(self, tool):
        assert tool.name == "device_control"

    def test_description(self, tool):
        assert "device" in tool.description.lower()

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert params["required"] == ["action"]

    def test_to_schema(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "device_control"


# ===================================================================
# Test: list action
# ===================================================================


class TestListAction:

    @pytest.mark.asyncio
    async def test_empty_registry(self, tool):
        result = await tool.execute(action="list")
        assert "No devices" in result

    @pytest.mark.asyncio
    async def test_populated(self, populated_tool):
        result = await populated_tool.execute(action="list")
        assert "Living Room Light" in result
        assert "light-01" in result
        assert "ONLINE" in result
        assert "Kitchen Sensor" in result
        assert "power" in result
        assert "brightness" in result

    @pytest.mark.asyncio
    async def test_shows_device_count(self, populated_tool):
        result = await populated_tool.execute(action="list")
        assert "(2)" in result


# ===================================================================
# Test: command action
# ===================================================================


class TestCommandAction:

    @pytest.mark.asyncio
    async def test_set_power(self, populated_tool, mock_transport):
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="power",
            value=True,
        )
        assert "Command sent" in result
        assert "light-01" in result
        mock_transport.send.assert_called_once()
        env = mock_transport.send.call_args[0][0]
        assert isinstance(env, MeshEnvelope)
        assert env.payload["action"] == "set"

    @pytest.mark.asyncio
    async def test_set_brightness(self, populated_tool, mock_transport):
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="brightness",
            value=80,
        )
        assert "Command sent" in result
        assert "80" in result
        env = mock_transport.send.call_args[0][0]
        assert env.payload["params"]["value"] == 80

    @pytest.mark.asyncio
    async def test_get_temperature(self, populated_tool, mock_transport):
        result = await populated_tool.execute(
            action="command",
            device="sensor-01",
            command_action="get",
            capability="temperature",
        )
        assert "Command sent" in result
        assert "sensor-01" in result

    @pytest.mark.asyncio
    async def test_toggle_power(self, populated_tool, mock_transport):
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="toggle",
            capability="power",
        )
        assert "Command sent" in result

    @pytest.mark.asyncio
    async def test_validation_failure_unknown_device(self, populated_tool):
        result = await populated_tool.execute(
            action="command",
            device="ghost-99",
            command_action="set",
            capability="power",
            value=True,
        )
        assert "validation failed" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_validation_failure_set_sensor(self, populated_tool):
        result = await populated_tool.execute(
            action="command",
            device="sensor-01",
            command_action="set",
            capability="temperature",
            value=25,
        )
        assert "validation failed" in result
        assert "sensor" in result.lower()

    @pytest.mark.asyncio
    async def test_validation_failure_out_of_range(self, populated_tool):
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="brightness",
            value=200,
        )
        assert "validation failed" in result
        assert "out of range" in result

    @pytest.mark.asyncio
    async def test_transport_failure(self, populated_tool, mock_transport):
        mock_transport.send.return_value = False
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="power",
            value=True,
        )
        assert "Failed to deliver" in result

    @pytest.mark.asyncio
    async def test_missing_device(self, populated_tool):
        result = await populated_tool.execute(
            action="command",
            command_action="set",
            capability="power",
            value=True,
        )
        assert "Error" in result
        assert "device" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_command_action(self, populated_tool):
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            capability="power",
            value=True,
        )
        assert "Error" in result
        assert "command_action" in result.lower()

    @pytest.mark.asyncio
    async def test_offline_device_warning(self, populated_tool):
        populated_tool._registry.mark_offline("light-01")
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="power",
            value=True,
        )
        assert "validation failed" in result
        assert "offline" in result

    @pytest.mark.asyncio
    async def test_value_merged_into_params(self, populated_tool, mock_transport):
        """value kwarg should merge into params dict."""
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="brightness",
            value=50,
        )
        assert "Command sent" in result
        env = mock_transport.send.call_args[0][0]
        assert env.payload["params"]["value"] == 50

    @pytest.mark.asyncio
    async def test_execute_with_params(self, populated_tool, mock_transport):
        """execute action with custom params."""
        result = await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="execute",
            params={"function": "reset"},
        )
        assert "Command sent" in result
        env = mock_transport.send.call_args[0][0]
        assert env.payload["params"]["function"] == "reset"


# ===================================================================
# Test: state action
# ===================================================================


class TestStateAction:

    @pytest.mark.asyncio
    async def test_device_with_state(self, populated_tool):
        result = await populated_tool.execute(action="state", device="sensor-01")
        assert "Kitchen Sensor" in result
        assert "temperature" in result
        assert "23.5" in result
        assert "ONLINE" in result

    @pytest.mark.asyncio
    async def test_device_without_state(self, populated_tool):
        result = await populated_tool.execute(action="state", device="light-01")
        assert "Living Room Light" in result
        assert "No state reported" in result

    @pytest.mark.asyncio
    async def test_unknown_device(self, populated_tool):
        result = await populated_tool.execute(action="state", device="nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_missing_device_id(self, populated_tool):
        result = await populated_tool.execute(action="state")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_shows_capabilities(self, populated_tool):
        result = await populated_tool.execute(action="state", device="light-01")
        assert "power" in result
        assert "brightness" in result
        assert "Capabilities" in result


# ===================================================================
# Test: describe action
# ===================================================================


class TestDescribeAction:

    @pytest.mark.asyncio
    async def test_empty_registry(self, tool):
        result = await tool.execute(action="describe")
        assert "No devices" in result

    @pytest.mark.asyncio
    async def test_populated(self, populated_tool):
        result = await populated_tool.execute(action="describe")
        assert "Living Room Light" in result
        assert "light-01" in result
        assert "Action Reference" in result

    @pytest.mark.asyncio
    async def test_contains_json_example(self, populated_tool):
        result = await populated_tool.execute(action="describe")
        assert '"device"' in result
        assert '"action"' in result


# ===================================================================
# Test: unknown action
# ===================================================================


class TestUnknownAction:

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="foobar")
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_empty_action(self, tool):
        result = await tool.execute(action="")
        assert "Unknown action" in result


# ===================================================================
# Test: envelope construction
# ===================================================================


class TestEnvelopeConstruction:

    @pytest.mark.asyncio
    async def test_source_is_hub_node_id(self, populated_tool, mock_transport):
        await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="get",
            capability="power",
        )
        env = mock_transport.send.call_args[0][0]
        assert env.source == "hub-01"
        assert env.target == "light-01"

    @pytest.mark.asyncio
    async def test_envelope_type_is_command(self, populated_tool, mock_transport):
        await populated_tool.execute(
            action="command",
            device="light-01",
            command_action="set",
            capability="power",
            value=True,
        )
        env = mock_transport.send.call_args[0][0]
        assert env.type == "command"

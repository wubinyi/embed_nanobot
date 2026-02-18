"""Tests for device-aware routing (task 2.4).

Covers:
- is_device_related() — matches device names, node_ids, types, capabilities
- is_device_related() — rejects non-device text, handles edge cases
- build_force_local_fn() — closure captures registry
- HybridRouter force_local_fn integration — routes device commands to local
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceRegistry,
)
from nanobot.mesh.routing import build_force_local_fn, is_device_related
from nanobot.providers.hybrid_router import HybridRouterProvider


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
    finally:
        loop.close()
    return registry


@pytest.fixture
def mock_local_provider():
    provider = AsyncMock()
    provider.chat = AsyncMock()
    return provider


@pytest.fixture
def mock_api_provider():
    provider = AsyncMock()
    provider.chat = AsyncMock()
    return provider


# ===================================================================
# Test: is_device_related()
# ===================================================================


class TestIsDeviceRelated:

    def test_matches_device_name(self, populated_registry):
        assert is_device_related("Turn on the Living Room Light", populated_registry)

    def test_matches_device_name_case_insensitive(self, populated_registry):
        assert is_device_related("turn on the living room light", populated_registry)

    def test_matches_node_id(self, populated_registry):
        assert is_device_related("send command to light-01", populated_registry)

    def test_matches_device_type(self, populated_registry):
        assert is_device_related("show all smart_light devices", populated_registry)

    def test_matches_device_type_with_spaces(self, populated_registry):
        assert is_device_related("show all smart light devices", populated_registry)

    def test_matches_capability_name(self, populated_registry):
        assert is_device_related("set the brightness to 80%", populated_registry)

    def test_matches_temperature(self, populated_registry):
        assert is_device_related("what's the temperature?", populated_registry)

    def test_rejects_unrelated_text(self, populated_registry):
        assert not is_device_related("what is the capital of France?", populated_registry)

    def test_rejects_empty_text(self, populated_registry):
        assert not is_device_related("", populated_registry)

    def test_empty_registry(self, registry):
        assert not is_device_related("turn on the light", registry)

    def test_short_capability_names_skipped(self, registry):
        """Capability names < 3 chars are skipped to avoid false positives."""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(registry.register_device(
                "dev-01", "gadget",
                capabilities=[DeviceCapability("on", CapabilityType.ACTUATOR, DataType.BOOL)],
            ))
        finally:
            loop.close()
        # "on" is only 2 chars → skipped
        assert not is_device_related("turn on the lights please", registry)

    def test_capability_word_boundary(self, populated_registry):
        """Capability match uses word boundaries."""
        # "power" should match "power" but not "PowerPoint"
        assert is_device_related("toggle the power", populated_registry)

    def test_no_false_match_on_embedded_word(self, populated_registry):
        """Capability name embedded in a larger word shouldn't match."""
        # "brightness" shouldn't match "brightnessing" (not a word, but tests boundary)
        assert not is_device_related("the brightnessing of enlightenment", populated_registry)


# ===================================================================
# Test: build_force_local_fn()
# ===================================================================


class TestBuildForceLocalFn:

    def test_returns_callable(self, populated_registry):
        fn = build_force_local_fn(populated_registry)
        assert callable(fn)

    def test_device_text_returns_true(self, populated_registry):
        fn = build_force_local_fn(populated_registry)
        assert fn("set brightness to 80") is True

    def test_non_device_text_returns_false(self, populated_registry):
        fn = build_force_local_fn(populated_registry)
        assert fn("what is 2 + 2?") is False

    def test_captures_registry(self, registry):
        """Fn captures registry — newly added devices are detected."""
        fn = build_force_local_fn(registry)
        assert fn("turn on the light") is False

        # Add a device
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(registry.register_device(
                "light-01", "smart_light", name="Light",
                capabilities=[DeviceCapability("power", CapabilityType.ACTUATOR, DataType.BOOL)],
            ))
        finally:
            loop.close()

        # Now it should match (same fn, registry was mutated)
        assert fn("check the power status") is True


# ===================================================================
# Test: HybridRouter integration
# ===================================================================


class TestHybridRouterForceLocal:

    @pytest.mark.asyncio
    async def test_force_local_fn_skips_difficulty_judge(
        self, mock_local_provider, mock_api_provider
    ):
        """When force_local_fn returns True, local model is used directly."""
        from nanobot.providers.base import LLMResponse
        mock_local_provider.chat.return_value = LLMResponse(content="Light turned on")

        router = HybridRouterProvider(
            local_provider=mock_local_provider,
            api_provider=mock_api_provider,
            local_model="local/model",
            api_model="api/model",
        )
        router.force_local_fn = lambda text: "light" in text.lower()

        messages = [{"role": "user", "content": "Turn on the light"}]
        result = await router.chat(messages)

        assert result.content == "Light turned on"
        # Local called exactly once (NOT twice — difficulty judge was skipped)
        mock_local_provider.chat.assert_called_once()
        mock_api_provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_local_fn_false_goes_through_normal_routing(
        self, mock_local_provider, mock_api_provider
    ):
        """When force_local_fn returns False, normal difficulty routing applies."""
        from nanobot.providers.base import LLMResponse
        # Difficulty judge returns easy
        mock_local_provider.chat.return_value = LLMResponse(
            content='{"difficulty": "easy", "score": 0.2}'
        )

        router = HybridRouterProvider(
            local_provider=mock_local_provider,
            api_provider=mock_api_provider,
            local_model="local/model",
            api_model="api/model",
        )
        router.force_local_fn = lambda text: False

        messages = [{"role": "user", "content": "What is 2+2?"}]
        await router.chat(messages)

        # Local called twice: once for force_local check (returned False),
        # once for difficulty judge, once for actual response
        assert mock_local_provider.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_no_force_local_fn_normal_routing(
        self, mock_local_provider, mock_api_provider
    ):
        """Without force_local_fn, normal routing applies."""
        from nanobot.providers.base import LLMResponse
        mock_local_provider.chat.return_value = LLMResponse(
            content='{"difficulty": "easy", "score": 0.1}'
        )

        router = HybridRouterProvider(
            local_provider=mock_local_provider,
            api_provider=mock_api_provider,
            local_model="local/model",
            api_model="api/model",
        )
        # force_local_fn is None by default

        messages = [{"role": "user", "content": "Hello"}]
        await router.chat(messages)

        # Local called for difficulty judge + actual response
        assert mock_local_provider.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_force_local_fn_exception_falls_through(
        self, mock_local_provider, mock_api_provider
    ):
        """If force_local_fn raises, fall through to normal routing."""
        from nanobot.providers.base import LLMResponse
        mock_local_provider.chat.return_value = LLMResponse(
            content='{"difficulty": "easy", "score": 0.1}'
        )

        router = HybridRouterProvider(
            local_provider=mock_local_provider,
            api_provider=mock_api_provider,
            local_model="local/model",
            api_model="api/model",
        )
        router.force_local_fn = lambda text: 1 / 0  # ZeroDivisionError

        messages = [{"role": "user", "content": "test"}]
        # Should not raise — falls through to normal routing
        await router.chat(messages)
        assert mock_local_provider.chat.call_count == 2

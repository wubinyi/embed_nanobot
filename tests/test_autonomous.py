"""Tests for the autonomous device monitoring service (task 5.1.1)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.autonomous import AutonomousService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(node_id: str, online: bool = True, caps: list[str] | None = None,
                 state: dict | None = None, device_type: str = "esp32"):
    """Create a mock DeviceInfo."""
    d = MagicMock()
    d.node_id = node_id
    d.online = online
    d.device_type = device_type
    d.state = state or {}
    cap_objs = []
    for c in (caps or []):
        cap = MagicMock()
        cap.name = c
        cap_objs.append(cap)
    d.capabilities = cap_objs
    return d


def _make_registry(devices: list | None = None):
    reg = MagicMock()
    reg.get_all_devices.return_value = devices or []
    return reg


# ---------------------------------------------------------------------------
# Config / constructor tests
# ---------------------------------------------------------------------------

class TestAutonomousConfig:
    def test_default_disabled(self):
        svc = AutonomousService()
        assert svc.enabled is False
        assert svc.autonomy_level == "monitor-only"
        assert svc.interval_s == 1800

    def test_interval_floor(self):
        svc = AutonomousService(interval_s=10)
        assert svc.interval_s == 60  # floor at 1 minute

    def test_invalid_level_defaults(self):
        svc = AutonomousService(autonomy_level="invalid")
        assert svc.autonomy_level == "monitor-only"

    def test_valid_levels(self):
        for level in ("monitor-only", "suggest", "act"):
            svc = AutonomousService(autonomy_level=level)
            assert svc.autonomy_level == level


# ---------------------------------------------------------------------------
# Context builder tests
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_empty_context(self):
        svc = AutonomousService()
        ctx = svc.build_context()
        assert "Autonomous Device Scan" in ctx
        assert "OBSERVE ONLY" in ctx

    def test_context_includes_devices(self):
        devices = [
            _make_device("esp32-01", True, ["led"], {"led": True}),
            _make_device("esp32-02", False, ["temp"]),
        ]
        svc = AutonomousService(registry=_make_registry(devices))
        ctx = svc.build_context()
        assert "esp32-01" in ctx
        assert "esp32-02" in ctx
        assert "Online: 1" in ctx
        assert "Offline: 1" in ctx
        assert "led=True" in ctx

    def test_context_includes_topics(self):
        svc = AutonomousService(exploration_topics=["check energy usage", "monitor temperature"])
        ctx = svc.build_context()
        assert "check energy usage" in ctx
        assert "monitor temperature" in ctx
        assert "Exploration Topics" in ctx

    def test_suggest_level_instruction(self):
        svc = AutonomousService(autonomy_level="suggest")
        ctx = svc.build_context()
        assert "SUGGEST" in ctx

    def test_act_level_instruction(self):
        svc = AutonomousService(autonomy_level="act")
        ctx = svc.build_context()
        assert "MAY take actions" in ctx

    def test_context_includes_pipeline_summary(self):
        pipeline = MagicMock()
        pipeline.summary.return_value = "Temperature avg: 24.5°C"
        svc = AutonomousService(pipeline=pipeline)
        ctx = svc.build_context()
        assert "Temperature avg: 24.5°C" in ctx
        assert "Sensor Data Summary" in ctx

    def test_context_includes_automation_rules(self):
        automation = MagicMock()
        automation.describe_rules.return_value = "Rule: turn off AC when temp < 20"
        svc = AutonomousService(automation=automation)
        ctx = svc.build_context()
        assert "Rule: turn off AC when temp < 20" in ctx
        assert "Active Automation Rules" in ctx


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_disabled(self):
        svc = AutonomousService(enabled=False)
        await svc.start()
        assert svc._task is None

    @pytest.mark.asyncio
    async def test_start_enabled(self):
        svc = AutonomousService(enabled=True, interval_s=60)
        await svc.start()
        assert svc._running is True
        assert svc._task is not None
        svc.stop()
        assert svc._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        svc = AutonomousService(enabled=True, interval_s=60)
        await svc.start()
        task = svc._task
        svc.stop()
        await asyncio.sleep(0)  # let cancellation propagate
        assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# Tick / execution tests
# ---------------------------------------------------------------------------

class TestTick:
    @pytest.mark.asyncio
    async def test_tick_monitor_only_logs(self):
        """Monitor-only should execute but NOT notify."""
        on_execute = AsyncMock(return_value="Temperature normal.")
        on_notify = AsyncMock()
        devices = [_make_device("esp32-01", True, ["temp"], {"temp": 24})]
        svc = AutonomousService(
            registry=_make_registry(devices),
            on_execute=on_execute,
            on_notify=on_notify,
            autonomy_level="monitor-only",
            enabled=True,
        )
        await svc._tick()
        on_execute.assert_called_once()
        on_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_suggest_notifies(self):
        """Suggest level should notify user."""
        on_execute = AsyncMock(return_value="Suggest: turn on heater.")
        on_notify = AsyncMock()
        svc = AutonomousService(
            registry=_make_registry([_make_device("d1")]),
            on_execute=on_execute,
            on_notify=on_notify,
            autonomy_level="suggest",
            enabled=True,
        )
        await svc._tick()
        on_execute.assert_called_once()
        on_notify.assert_called_once_with("Suggest: turn on heater.")

    @pytest.mark.asyncio
    async def test_tick_act_notifies(self):
        """Act level should also notify."""
        on_execute = AsyncMock(return_value="Turned on heater.")
        on_notify = AsyncMock()
        svc = AutonomousService(
            registry=_make_registry([_make_device("d1")]),
            on_execute=on_execute,
            on_notify=on_notify,
            autonomy_level="act",
            enabled=True,
        )
        await svc._tick()
        on_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_empty_response(self):
        on_execute = AsyncMock(return_value="")
        on_notify = AsyncMock()
        svc = AutonomousService(
            registry=_make_registry([_make_device("d1")]),
            on_execute=on_execute,
            on_notify=on_notify,
            autonomy_level="suggest",
            enabled=True,
        )
        await svc._tick()
        on_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_no_execute_callback(self):
        svc = AutonomousService(
            registry=_make_registry([_make_device("d1")]),
            on_execute=None,
            autonomy_level="suggest",
            enabled=True,
        )
        # Should not raise
        await svc._tick()


# ---------------------------------------------------------------------------
# Trigger now
# ---------------------------------------------------------------------------

class TestTriggerNow:
    @pytest.mark.asyncio
    async def test_trigger_now(self):
        on_execute = AsyncMock(return_value="All devices healthy.")
        svc = AutonomousService(
            registry=_make_registry([_make_device("d1")]),
            on_execute=on_execute,
            enabled=True,
        )
        result = await svc.trigger_now()
        assert result == "All devices healthy."

    @pytest.mark.asyncio
    async def test_trigger_now_no_callback(self):
        svc = AutonomousService(on_execute=None)
        result = await svc.trigger_now()
        assert result is None

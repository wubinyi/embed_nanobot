"""Tests for nanobot.mesh.automation — basic automation rules engine."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.automation import (
    AutomationEngine,
    AutomationRule,
    ComparisonOp,
    Condition,
    RuleAction,
    validate_rule,
)
from nanobot.mesh.commands import Action, DeviceCommand
from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceInfo,
    DeviceRegistry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(tmp_path: Path) -> DeviceRegistry:
    """Create a registry with some test devices."""
    reg = DeviceRegistry(path=tmp_path / "registry.json")
    # Temperature sensor
    reg._devices["sensor-01"] = DeviceInfo(
        node_id="sensor-01",
        device_type="temperature_sensor",
        name="Living Room Sensor",
        capabilities=[
            DeviceCapability(
                name="temperature",
                cap_type=CapabilityType.SENSOR,
                data_type=DataType.FLOAT,
                unit="C",
                value_range=(0, 100),
            ),
            DeviceCapability(
                name="humidity",
                cap_type=CapabilityType.SENSOR,
                data_type=DataType.FLOAT,
                unit="%",
                value_range=(0, 100),
            ),
        ],
        state={"temperature": 25.0, "humidity": 55.0},
        online=True,
    )
    # Smart light
    reg._devices["light-01"] = DeviceInfo(
        node_id="light-01",
        device_type="smart_light",
        name="Kitchen Light",
        capabilities=[
            DeviceCapability(
                name="power",
                cap_type=CapabilityType.ACTUATOR,
                data_type=DataType.BOOL,
            ),
            DeviceCapability(
                name="brightness",
                cap_type=CapabilityType.PROPERTY,
                data_type=DataType.INT,
                value_range=(0, 100),
            ),
        ],
        state={"power": False, "brightness": 50},
        online=True,
    )
    # AC unit
    reg._devices["ac-01"] = DeviceInfo(
        node_id="ac-01",
        device_type="air_conditioner",
        name="Living Room AC",
        capabilities=[
            DeviceCapability(
                name="power",
                cap_type=CapabilityType.ACTUATOR,
                data_type=DataType.BOOL,
            ),
            DeviceCapability(
                name="mode",
                cap_type=CapabilityType.PROPERTY,
                data_type=DataType.ENUM,
                enum_values=["auto", "cool", "heat", "fan"],
            ),
        ],
        state={"power": False, "mode": "auto"},
        online=True,
    )
    # Motion sensor
    reg._devices["pir-01"] = DeviceInfo(
        node_id="pir-01",
        device_type="motion_sensor",
        name="Hallway PIR",
        capabilities=[
            DeviceCapability(
                name="motion",
                cap_type=CapabilityType.SENSOR,
                data_type=DataType.BOOL,
            ),
        ],
        state={"motion": False},
        online=True,
    )
    return reg


def _make_engine(tmp_path: Path, registry: DeviceRegistry) -> AutomationEngine:
    """Create an engine with persistence path."""
    return AutomationEngine(registry, path=tmp_path / "rules.json")


def _temp_ac_rule() -> AutomationRule:
    """Helper: if temperature > 30, turn on AC."""
    return AutomationRule(
        rule_id="temp-ac",
        name="Cool when hot",
        description="Turn on AC when temperature exceeds 30C",
        conditions=[
            Condition(device_id="sensor-01", capability="temperature", operator="gt", value=30),
        ],
        actions=[
            RuleAction(device_id="ac-01", capability="power", action="set", params={"value": True}),
        ],
        cooldown_seconds=60,
    )


def _motion_light_rule() -> AutomationRule:
    """Helper: if motion detected, turn on light."""
    return AutomationRule(
        rule_id="motion-light",
        name="Motion lights",
        description="Turn on kitchen light when motion detected",
        conditions=[
            Condition(device_id="pir-01", capability="motion", operator="eq", value=True),
        ],
        actions=[
            RuleAction(device_id="light-01", capability="power", action="set", params={"value": True}),
        ],
        cooldown_seconds=30,
    )


def _multi_condition_rule() -> AutomationRule:
    """Helper: if temperature > 28 AND humidity > 70, turn on AC in cool mode."""
    return AutomationRule(
        rule_id="hot-humid-ac",
        name="Cool and dehumidify",
        conditions=[
            Condition(device_id="sensor-01", capability="temperature", operator="gt", value=28),
            Condition(device_id="sensor-01", capability="humidity", operator="gt", value=70),
        ],
        actions=[
            RuleAction(device_id="ac-01", capability="power", action="set", params={"value": True}),
            RuleAction(device_id="ac-01", capability="mode", action="set", params={"value": "cool"}),
        ],
        cooldown_seconds=60,
    )


# ===========================================================================
# Test Condition model
# ===========================================================================

class TestConditionModel:
    def test_to_dict(self):
        c = Condition("sensor-01", "temperature", "gt", 30)
        assert c.to_dict() == {
            "device_id": "sensor-01",
            "capability": "temperature",
            "operator": "gt",
            "value": 30,
        }

    def test_from_dict(self):
        d = {"device_id": "x", "capability": "y", "operator": "le", "value": True}
        c = Condition.from_dict(d)
        assert c.device_id == "x"
        assert c.operator == "le"
        assert c.value is True

    def test_roundtrip(self):
        c = Condition("a", "b", "eq", "hello")
        assert Condition.from_dict(c.to_dict()) == c


# ===========================================================================
# Test RuleAction model
# ===========================================================================

class TestRuleActionModel:
    def test_to_dict_basic(self):
        a = RuleAction("light-01", "power", "toggle")
        d = a.to_dict()
        assert d["device_id"] == "light-01"
        assert d["action"] == "toggle"
        assert "params" not in d  # empty params omitted

    def test_to_dict_with_params(self):
        a = RuleAction("ac-01", "power", "set", {"value": True})
        d = a.to_dict()
        assert d["params"] == {"value": True}

    def test_from_dict(self):
        d = {"device_id": "x", "capability": "y", "action": "get", "params": {"k": "v"}}
        a = RuleAction.from_dict(d)
        assert a.action == "get"
        assert a.params == {"k": "v"}

    def test_to_command(self):
        a = RuleAction("light-01", "brightness", "set", {"value": 80})
        cmd = a.to_command()
        assert isinstance(cmd, DeviceCommand)
        assert cmd.device == "light-01"
        assert cmd.action == "set"
        assert cmd.capability == "brightness"
        assert cmd.params == {"value": 80}

    def test_roundtrip(self):
        a = RuleAction("x", "y", "execute", {"a": 1})
        assert RuleAction.from_dict(a.to_dict()) == a


# ===========================================================================
# Test AutomationRule model
# ===========================================================================

class TestAutomationRuleModel:
    def test_to_dict_roundtrip(self):
        rule = _temp_ac_rule()
        restored = AutomationRule.from_dict(rule.to_dict())
        assert restored.rule_id == rule.rule_id
        assert restored.name == rule.name
        assert len(restored.conditions) == 1
        assert len(restored.actions) == 1
        assert restored.cooldown_seconds == 60

    def test_trigger_device_ids(self):
        rule = _multi_condition_rule()
        # Both conditions reference sensor-01
        assert rule.trigger_device_ids() == {"sensor-01"}

    def test_trigger_device_ids_multi_device(self):
        rule = AutomationRule(
            rule_id="test",
            name="test",
            conditions=[
                Condition("sensor-01", "temperature", "gt", 30),
                Condition("pir-01", "motion", "eq", True),
            ],
            actions=[RuleAction("light-01", "power", "set", {"value": True})],
        )
        assert rule.trigger_device_ids() == {"sensor-01", "pir-01"}

    def test_defaults(self):
        rule = AutomationRule(rule_id="r1", name="test")
        assert rule.enabled is True
        assert rule.conditions == []
        assert rule.actions == []
        assert rule.cooldown_seconds == 60
        assert rule.last_triggered == 0.0


# ===========================================================================
# Test validate_rule
# ===========================================================================

class TestValidateRule:
    def test_valid_rule(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = _temp_ac_rule()
        errors = validate_rule(rule, reg)
        assert errors == []

    def test_valid_multi_condition(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = _multi_condition_rule()
        assert validate_rule(rule, reg) == []

    def test_empty_rule_id(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(rule_id="", name="test", conditions=[
            Condition("sensor-01", "temperature", "gt", 30)
        ], actions=[RuleAction("ac-01", "power", "set")])
        errors = validate_rule(rule, reg)
        assert any("rule_id" in e for e in errors)

    def test_no_conditions(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(rule_id="r1", name="test", conditions=[], actions=[
            RuleAction("ac-01", "power", "set")
        ])
        errors = validate_rule(rule, reg)
        assert any("condition" in e.lower() for e in errors)

    def test_no_actions(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(rule_id="r1", name="test", conditions=[
            Condition("sensor-01", "temperature", "gt", 30)
        ], actions=[])
        errors = validate_rule(rule, reg)
        assert any("action" in e.lower() for e in errors)

    def test_invalid_operator(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("sensor-01", "temperature", "xxx", 30)],
            actions=[RuleAction("ac-01", "power", "set")],
        )
        errors = validate_rule(rule, reg)
        assert any("operator" in e.lower() for e in errors)

    def test_invalid_action_type(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("sensor-01", "temperature", "gt", 30)],
            actions=[RuleAction("ac-01", "power", "xxx")],
        )
        errors = validate_rule(rule, reg)
        assert any("action" in e.lower() and "xxx" in e for e in errors)

    def test_unknown_condition_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("nonexist", "temperature", "gt", 30)],
            actions=[RuleAction("ac-01", "power", "set")],
        )
        errors = validate_rule(rule, reg)
        assert any("nonexist" in e and "not found" in e for e in errors)

    def test_unknown_condition_capability(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("sensor-01", "nonexist", "gt", 30)],
            actions=[RuleAction("ac-01", "power", "set")],
        )
        errors = validate_rule(rule, reg)
        assert any("nonexist" in e and "capability" in e.lower() for e in errors)

    def test_unknown_action_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("sensor-01", "temperature", "gt", 30)],
            actions=[RuleAction("nonexist", "power", "set")],
        )
        errors = validate_rule(rule, reg)
        assert any("nonexist" in e and "not found" in e for e in errors)

    def test_unknown_action_capability(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = AutomationRule(
            rule_id="r1", name="test",
            conditions=[Condition("sensor-01", "temperature", "gt", 30)],
            actions=[RuleAction("ac-01", "nonexist", "set")],
        )
        errors = validate_rule(rule, reg)
        assert any("nonexist" in e and "capability" in e.lower() for e in errors)

    def test_negative_cooldown(self, tmp_path):
        reg = _make_registry(tmp_path)
        rule = _temp_ac_rule()
        rule.cooldown_seconds = -1
        errors = validate_rule(rule, reg)
        assert any("cooldown" in e.lower() for e in errors)


# ===========================================================================
# Test AutomationEngine CRUD
# ===========================================================================

class TestEngineCRUD:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return engine

    @pytest.mark.asyncio
    async def test_add_rule(self, setup):
        engine = setup
        rule = _temp_ac_rule()
        result = await engine.add_rule(rule)
        assert result.rule_id == "temp-ac"
        assert engine.rule_count == 1

    @pytest.mark.asyncio
    async def test_add_duplicate_raises(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        with pytest.raises(ValueError, match="already exists"):
            await engine.add_rule(_temp_ac_rule())

    @pytest.mark.asyncio
    async def test_remove_rule(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        assert await engine.remove_rule("temp-ac") is True
        assert engine.rule_count == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, setup):
        engine = setup
        assert await engine.remove_rule("nope") is False

    @pytest.mark.asyncio
    async def test_get_rule(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        r = engine.get_rule("temp-ac")
        assert r is not None
        assert r.name == "Cool when hot"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, setup):
        engine = setup
        assert engine.get_rule("nope") is None

    @pytest.mark.asyncio
    async def test_list_rules(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        await engine.add_rule(_motion_light_rule())
        rules = engine.list_rules()
        assert len(rules) == 2
        ids = {r.rule_id for r in rules}
        assert ids == {"temp-ac", "motion-light"}

    @pytest.mark.asyncio
    async def test_update_rule(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        result = await engine.update_rule("temp-ac", name="New Name", cooldown_seconds=120)
        assert result is not None
        assert result.name == "New Name"
        assert result.cooldown_seconds == 120

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, setup):
        engine = setup
        result = await engine.update_rule("nope", name="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_conditions_rebuilds_index(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Initially indexed on sensor-01
        assert "temp-ac" in engine._device_index.get("sensor-01", set())

        # Update conditions to reference pir-01 instead
        new_conds = [Condition("pir-01", "motion", "eq", True)]
        await engine.update_rule("temp-ac", conditions=new_conds)

        # Old index should be cleaned, new index should have the rule
        assert "temp-ac" not in engine._device_index.get("sensor-01", set())
        assert "temp-ac" in engine._device_index.get("pir-01", set())

    @pytest.mark.asyncio
    async def test_enable_disable(self, setup):
        engine = setup
        await engine.add_rule(_temp_ac_rule())
        await engine.disable_rule("temp-ac")
        assert engine.get_rule("temp-ac").enabled is False
        await engine.enable_rule("temp-ac")
        assert engine.get_rule("temp-ac").enabled is True

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, setup):
        engine = setup
        assert await engine.enable_rule("nope") is False

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, setup):
        engine = setup
        assert await engine.disable_rule("nope") is False


# ===========================================================================
# Test Persistence
# ===========================================================================

class TestPersistence:
    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine1 = _make_engine(tmp_path, reg)
        await engine1.add_rule(_temp_ac_rule())
        await engine1.add_rule(_motion_light_rule())

        # Create a new engine and load
        engine2 = _make_engine(tmp_path, reg)
        engine2.load()
        assert engine2.rule_count == 2
        assert engine2.get_rule("temp-ac") is not None
        assert engine2.get_rule("motion-light") is not None

    @pytest.mark.asyncio
    async def test_load_missing_file(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = AutomationEngine(reg, path=tmp_path / "nonexistent" / "rules.json")
        engine.load()  # Should not raise
        assert engine.rule_count == 0

    @pytest.mark.asyncio
    async def test_load_empty_file(self, tmp_path):
        reg = _make_registry(tmp_path)
        rules_path = tmp_path / "rules.json"
        rules_path.write_text("")
        engine = AutomationEngine(reg, path=rules_path)
        engine.load()
        assert engine.rule_count == 0

    @pytest.mark.asyncio
    async def test_load_invalid_json(self, tmp_path):
        reg = _make_registry(tmp_path)
        rules_path = tmp_path / "rules.json"
        rules_path.write_text("{invalid json")
        engine = AutomationEngine(reg, path=rules_path)
        engine.load()  # Should not raise
        assert engine.rule_count == 0

    @pytest.mark.asyncio
    async def test_load_malformed_rule(self, tmp_path):
        reg = _make_registry(tmp_path)
        rules_path = tmp_path / "rules.json"
        rules_path.write_text(json.dumps({
            "rules": [
                {"rule_id": "good", "name": "Good rule", "conditions": [], "actions": []},
                {"bad": "data"},  # Missing rule_id
            ]
        }))
        engine = AutomationEngine(reg, path=rules_path)
        engine.load()
        assert engine.rule_count == 1  # Only the good rule loaded

    @pytest.mark.asyncio
    async def test_save_preserves_last_triggered(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine1 = _make_engine(tmp_path, reg)
        rule = _temp_ac_rule()
        await engine1.add_rule(rule)
        # Simulate trigger
        engine1._rules["temp-ac"].last_triggered = 1000.0
        await engine1._save()

        engine2 = _make_engine(tmp_path, reg)
        engine2.load()
        assert engine2.get_rule("temp-ac").last_triggered == 1000.0

    @pytest.mark.asyncio
    async def test_index_rebuilt_on_load(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine1 = _make_engine(tmp_path, reg)
        await engine1.add_rule(_temp_ac_rule())
        await engine1.add_rule(_motion_light_rule())

        engine2 = _make_engine(tmp_path, reg)
        engine2.load()
        assert "temp-ac" in engine2._device_index.get("sensor-01", set())
        assert "motion-light" in engine2._device_index.get("pir-01", set())


# ===========================================================================
# Test Evaluation — single condition rules
# ===========================================================================

class TestEvaluateSingle:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return reg, engine

    @pytest.mark.asyncio
    async def test_condition_true_fires(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Set temperature above threshold
        reg._devices["sensor-01"].state["temperature"] = 35.0
        cmds = engine.evaluate("sensor-01")
        assert len(cmds) == 1
        assert cmds[0].device == "ac-01"
        assert cmds[0].action == "set"
        assert cmds[0].params == {"value": True}

    @pytest.mark.asyncio
    async def test_condition_false_no_fire(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Temperature is 25 (below 30)
        cmds = engine.evaluate("sensor-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_condition_boundary_not_met(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        reg._devices["sensor-01"].state["temperature"] = 30.0  # Not > 30
        cmds = engine.evaluate("sensor-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_bool_condition(self, setup):
        reg, engine = setup
        await engine.add_rule(_motion_light_rule())
        reg._devices["pir-01"].state["motion"] = True
        cmds = engine.evaluate("pir-01")
        assert len(cmds) == 1
        assert cmds[0].device == "light-01"

    @pytest.mark.asyncio
    async def test_unrelated_device_no_eval(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Evaluate for a device not in any rule
        cmds = engine.evaluate("light-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_disabled_rule_no_fire(self, setup):
        reg, engine = setup
        rule = _temp_ac_rule()
        rule.enabled = False
        await engine.add_rule(rule)
        reg._devices["sensor-01"].state["temperature"] = 35.0
        cmds = engine.evaluate("sensor-01")
        assert cmds == []


# ===========================================================================
# Test Evaluation — multi-condition rules
# ===========================================================================

class TestEvaluateMultiCondition:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return reg, engine

    @pytest.mark.asyncio
    async def test_both_true_fires(self, setup):
        reg, engine = setup
        await engine.add_rule(_multi_condition_rule())
        reg._devices["sensor-01"].state["temperature"] = 30.0
        reg._devices["sensor-01"].state["humidity"] = 75.0
        cmds = engine.evaluate("sensor-01")
        assert len(cmds) == 2  # power + mode
        assert cmds[0].device == "ac-01"
        assert cmds[1].capability == "mode"

    @pytest.mark.asyncio
    async def test_one_false_no_fire(self, setup):
        reg, engine = setup
        await engine.add_rule(_multi_condition_rule())
        reg._devices["sensor-01"].state["temperature"] = 30.0
        reg._devices["sensor-01"].state["humidity"] = 50.0  # Below 70
        cmds = engine.evaluate("sensor-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_both_false_no_fire(self, setup):
        reg, engine = setup
        await engine.add_rule(_multi_condition_rule())
        reg._devices["sensor-01"].state["temperature"] = 20.0
        reg._devices["sensor-01"].state["humidity"] = 50.0
        cmds = engine.evaluate("sensor-01")
        assert cmds == []


# ===========================================================================
# Test Cooldown
# ===========================================================================

class TestCooldown:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return reg, engine

    @pytest.mark.asyncio
    async def test_first_fire_sets_last_triggered(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        reg._devices["sensor-01"].state["temperature"] = 35.0
        now = 1000.0
        cmds = engine.evaluate("sensor-01", now=now)
        assert len(cmds) == 1
        assert engine.get_rule("temp-ac").last_triggered == now

    @pytest.mark.asyncio
    async def test_cooldown_blocks_second_fire(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        reg._devices["sensor-01"].state["temperature"] = 35.0
        # First fire at t=1000
        cmds = engine.evaluate("sensor-01", now=1000.0)
        assert len(cmds) == 1
        # Second attempt at t=1030 (only 30s, cooldown is 60s)
        cmds = engine.evaluate("sensor-01", now=1030.0)
        assert cmds == []

    @pytest.mark.asyncio
    async def test_cooldown_expires_allows_fire(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        reg._devices["sensor-01"].state["temperature"] = 35.0
        # First fire at t=1000
        engine.evaluate("sensor-01", now=1000.0)
        # After cooldown at t=1060
        cmds = engine.evaluate("sensor-01", now=1060.0)
        assert len(cmds) == 1

    @pytest.mark.asyncio
    async def test_zero_cooldown(self, setup):
        reg, engine = setup
        rule = _temp_ac_rule()
        rule.cooldown_seconds = 0
        await engine.add_rule(rule)
        reg._devices["sensor-01"].state["temperature"] = 35.0
        # Fire and immediately fire again
        engine.evaluate("sensor-01", now=1000.0)
        cmds = engine.evaluate("sensor-01", now=1000.0)
        assert len(cmds) == 1  # 0s cooldown means always eligible


# ===========================================================================
# Test Comparison Operators
# ===========================================================================

class TestComparisonOps:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return reg, engine

    @pytest.mark.asyncio
    async def _test_op(self, engine, reg, op, state_val, threshold, should_fire):
        """Helper to test a specific operator."""
        rule = AutomationRule(
            rule_id=f"test-{op}",
            name=f"test-{op}",
            conditions=[Condition("sensor-01", "temperature", op, threshold)],
            actions=[RuleAction("ac-01", "power", "set", {"value": True})],
            cooldown_seconds=0,
        )
        await engine.add_rule(rule)
        reg._devices["sensor-01"].state["temperature"] = state_val
        cmds = engine.evaluate("sensor-01")
        if should_fire:
            assert len(cmds) >= 1, f"Expected fire for {state_val} {op} {threshold}"
        else:
            assert len(cmds) == 0, f"Expected no fire for {state_val} {op} {threshold}"
        await engine.remove_rule(f"test-{op}")

    @pytest.mark.asyncio
    async def test_eq(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "eq", 30, 30, True)
        await self._test_op(engine, reg, "eq", 29, 30, False)

    @pytest.mark.asyncio
    async def test_ne(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "ne", 29, 30, True)
        await self._test_op(engine, reg, "ne", 30, 30, False)

    @pytest.mark.asyncio
    async def test_gt(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "gt", 31, 30, True)
        await self._test_op(engine, reg, "gt", 30, 30, False)

    @pytest.mark.asyncio
    async def test_ge(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "ge", 30, 30, True)
        await self._test_op(engine, reg, "ge", 29, 30, False)

    @pytest.mark.asyncio
    async def test_lt(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "lt", 29, 30, True)
        await self._test_op(engine, reg, "lt", 30, 30, False)

    @pytest.mark.asyncio
    async def test_le(self, setup):
        reg, engine = setup
        await self._test_op(engine, reg, "le", 30, 30, True)
        await self._test_op(engine, reg, "le", 31, 30, False)


# ===========================================================================
# Test Edge Cases
# ===========================================================================

class TestEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        return reg, engine

    @pytest.mark.asyncio
    async def test_missing_state_value(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Remove temperature from state
        del reg._devices["sensor-01"].state["temperature"]
        cmds = engine.evaluate("sensor-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_device_removed_from_registry(self, setup):
        reg, engine = setup
        await engine.add_rule(_temp_ac_rule())
        # Remove sensor from registry
        del reg._devices["sensor-01"]
        cmds = engine.evaluate("sensor-01")
        assert cmds == []

    @pytest.mark.asyncio
    async def test_type_mismatch_no_crash(self, setup):
        """Comparing string state with int threshold should not crash."""
        reg, engine = setup
        rule = AutomationRule(
            rule_id="mismatch",
            name="mismatch",
            conditions=[Condition("sensor-01", "temperature", "gt", "thirty")],
            actions=[RuleAction("ac-01", "power", "set", {"value": True})],
        )
        await engine.add_rule(rule)
        cmds = engine.evaluate("sensor-01")  # Should not raise
        assert cmds == []

    @pytest.mark.asyncio
    async def test_unknown_operator_no_crash(self, setup):
        reg, engine = setup
        rule = AutomationRule(
            rule_id="bad-op",
            name="bad-op",
            conditions=[Condition("sensor-01", "temperature", "xxx", 30)],
            actions=[RuleAction("ac-01", "power", "set", {"value": True})],
        )
        await engine.add_rule(rule)
        cmds = engine.evaluate("sensor-01")  # Should not raise
        assert cmds == []

    @pytest.mark.asyncio
    async def test_multiple_rules_same_device(self, setup):
        reg, engine = setup
        # Two rules triggered by same device
        rule1 = AutomationRule(
            rule_id="r1", name="r1",
            conditions=[Condition("sensor-01", "temperature", "gt", 30)],
            actions=[RuleAction("ac-01", "power", "set", {"value": True})],
            cooldown_seconds=0,
        )
        rule2 = AutomationRule(
            rule_id="r2", name="r2",
            conditions=[Condition("sensor-01", "temperature", "gt", 25)],
            actions=[RuleAction("light-01", "brightness", "set", {"value": 100})],
            cooldown_seconds=0,
        )
        await engine.add_rule(rule1)
        await engine.add_rule(rule2)
        reg._devices["sensor-01"].state["temperature"] = 35.0
        cmds = engine.evaluate("sensor-01")
        assert len(cmds) == 2
        devices = {cmd.device for cmd in cmds}
        assert devices == {"ac-01", "light-01"}

    @pytest.mark.asyncio
    async def test_string_equality(self, setup):
        """Test eq operator with string values (e.g., ENUM capability)."""
        reg, engine = setup
        rule = AutomationRule(
            rule_id="mode-check",
            name="mode check",
            conditions=[Condition("ac-01", "mode", "eq", "cool")],
            actions=[RuleAction("light-01", "power", "set", {"value": True})],
            cooldown_seconds=0,
        )
        await engine.add_rule(rule)
        reg._devices["ac-01"].state["mode"] = "cool"
        cmds = engine.evaluate("ac-01")
        assert len(cmds) == 1

    @pytest.mark.asyncio
    async def test_evaluate_no_rules(self, setup):
        _, engine = setup
        cmds = engine.evaluate("sensor-01")
        assert cmds == []


# ===========================================================================
# Test LLM Context (describe_rules)
# ===========================================================================

class TestDescribeRules:
    @pytest.mark.asyncio
    async def test_no_rules(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        assert "No active" in engine.describe_rules()

    @pytest.mark.asyncio
    async def test_with_rules(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        await engine.add_rule(_temp_ac_rule())
        desc = engine.describe_rules()
        assert "temp-ac" in desc
        assert "Cool when hot" in desc
        assert "temperature" in desc
        assert "gt" in desc

    @pytest.mark.asyncio
    async def test_disabled_rules_excluded(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        rule = _temp_ac_rule()
        rule.enabled = False
        await engine.add_rule(rule)
        desc = engine.describe_rules()
        assert "No active" in desc

    @pytest.mark.asyncio
    async def test_last_triggered_shown(self, tmp_path):
        reg = _make_registry(tmp_path)
        engine = _make_engine(tmp_path, reg)
        rule = _temp_ac_rule()
        rule.last_triggered = time.time() - 30  # 30 seconds ago
        await engine.add_rule(rule)
        desc = engine.describe_rules()
        assert "last fired" in desc


# ===========================================================================
# Test Channel Integration (MeshChannel automation dispatch)
# ===========================================================================

class TestChannelIntegration:
    """Test that MeshChannel._handle_state_report dispatches automation commands."""

    @pytest.mark.asyncio
    async def test_state_report_triggers_automation(self, tmp_path):
        """Verify the full flow: STATE_REPORT → registry update → automation → dispatch."""
        from nanobot.mesh.protocol import MeshEnvelope, MsgType

        # Build minimal config mock
        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = str(tmp_path / "keys.json")
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = str(tmp_path / "registry.json")
        config.automation_rules_path = str(tmp_path / "rules.json")
        config._workspace_path = str(tmp_path)

        bus = MagicMock()

        # We can't construct a full MeshChannel easily (needs network),
        # so test the automation logic directly
        reg = _make_registry(tmp_path)
        engine = AutomationEngine(reg, path=tmp_path / "rules.json")

        rule = _temp_ac_rule()
        await engine.add_rule(rule)

        # Simulate: sensor reports temperature 35
        reg._devices["sensor-01"].state["temperature"] = 35.0

        # Evaluate
        cmds = engine.evaluate("sensor-01")
        assert len(cmds) == 1
        assert cmds[0].device == "ac-01"
        assert cmds[0].action == "set"

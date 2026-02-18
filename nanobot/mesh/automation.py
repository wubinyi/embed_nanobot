"""Basic automation rules engine for device state-driven actions.

Evaluates user-defined rules when device state changes and generates
``DeviceCommand`` objects for dispatch by the mesh channel.

Architecture
------------
- Rules are evaluated **synchronously** (pure value comparisons, no I/O).
- Async dispatch is handled by the caller (``MeshChannel``).
- Rules are indexed by the device IDs in their conditions for O(1) lookup.
- Cooldown prevents re-triggering within a configurable time window.
- Rules persist to a JSON file alongside the device registry.

Usage from MeshChannel
----------------------
>>> engine = AutomationEngine(registry, path="automation_rules.json")
>>> engine.load()
>>> # When a device state changes:
>>> commands = engine.evaluate("sensor-01")
>>> for cmd in commands:
...     await transport.send(command_to_envelope(cmd, source=node_id))
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.mesh.commands import Action, DeviceCommand
from nanobot.mesh.registry import DeviceRegistry


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class ComparisonOp(str, Enum):
    """Operators for condition evaluation."""
    EQ = "eq"   # ==
    NE = "ne"   # !=
    GT = "gt"   # >
    GE = "ge"   # >=
    LT = "lt"   # <
    LE = "le"   # <=


_OP_FUNCS: dict[str, Any] = {
    ComparisonOp.EQ: lambda a, b: a == b,
    ComparisonOp.NE: lambda a, b: a != b,
    ComparisonOp.GT: lambda a, b: a > b,
    ComparisonOp.GE: lambda a, b: a >= b,
    ComparisonOp.LT: lambda a, b: a < b,
    ComparisonOp.LE: lambda a, b: a <= b,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Condition:
    """A single condition comparing a device capability's current value.

    Examples
    --------
    Temperature above 30:
        Condition(device_id="sensor-01", capability="temperature", operator="gt", value=30)

    Motion detected:
        Condition(device_id="pir-01", capability="motion", operator="eq", value=True)
    """
    device_id: str       # Source device node_id
    capability: str      # Capability name to monitor
    operator: str        # ComparisonOp value
    value: Any           # Threshold / comparison value

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "capability": self.capability,
            "operator": self.operator,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Condition:
        return cls(
            device_id=d["device_id"],
            capability=d["capability"],
            operator=d["operator"],
            value=d["value"],
        )


@dataclass
class RuleAction:
    """An action to execute when rule conditions are met.

    Produces a ``DeviceCommand`` for dispatch.

    Examples
    --------
    Turn on AC:
        RuleAction(device_id="ac-01", capability="power", action="set", params={"value": True})

    Toggle lights:
        RuleAction(device_id="light-01", capability="power", action="toggle")
    """
    device_id: str                                  # Target device node_id
    capability: str                                 # Target capability
    action: str = Action.SET                        # Action type
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "device_id": self.device_id,
            "capability": self.capability,
            "action": self.action,
        }
        if self.params:
            d["params"] = self.params
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RuleAction:
        return cls(
            device_id=d["device_id"],
            capability=d["capability"],
            action=d.get("action", Action.SET),
            params=d.get("params", {}),
        )

    def to_command(self) -> DeviceCommand:
        """Convert this action into a ``DeviceCommand``."""
        return DeviceCommand(
            device=self.device_id,
            action=self.action,
            capability=self.capability,
            params=dict(self.params),
        )


@dataclass
class AutomationRule:
    """A complete automation rule with conditions and actions.

    **Evaluation semantics**: All conditions must be true (AND logic).
    When satisfied and cooldown has elapsed, all actions fire in order.

    Examples
    --------
    "If temperature > 30, turn on AC":
        AutomationRule(
            rule_id="temp-ac",
            name="Cool when hot",
            conditions=[Condition("sensor-01", "temperature", "gt", 30)],
            actions=[RuleAction("ac-01", "power", "set", {"value": True})],
        )
    """
    rule_id: str
    name: str
    description: str = ""
    enabled: bool = True
    conditions: list[Condition] = field(default_factory=list)
    actions: list[RuleAction] = field(default_factory=list)
    cooldown_seconds: int = 60
    last_triggered: float = 0.0  # Unix timestamp; 0 = never triggered

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "cooldown_seconds": self.cooldown_seconds,
            "last_triggered": self.last_triggered,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutomationRule:
        return cls(
            rule_id=d["rule_id"],
            name=d.get("name", ""),
            description=d.get("description", ""),
            enabled=d.get("enabled", True),
            conditions=[Condition.from_dict(c) for c in d.get("conditions", [])],
            actions=[RuleAction.from_dict(a) for a in d.get("actions", [])],
            cooldown_seconds=d.get("cooldown_seconds", 60),
            last_triggered=d.get("last_triggered", 0.0),
        )

    def trigger_device_ids(self) -> set[str]:
        """Return the set of device IDs referenced in conditions."""
        return {c.device_id for c in self.conditions}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_rule(
    rule: AutomationRule,
    registry: DeviceRegistry,
) -> list[str]:
    """Validate a rule against the device registry.

    Checks that referenced devices and capabilities exist, operators are
    valid, and the rule has at least one condition and one action.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    if not rule.rule_id:
        errors.append("Rule must have a non-empty rule_id")

    if not rule.conditions:
        errors.append("Rule must have at least one condition")

    if not rule.actions:
        errors.append("Rule must have at least one action")

    valid_ops = {op.value for op in ComparisonOp}
    valid_actions = {a.value for a in Action}

    # Validate conditions
    for i, cond in enumerate(rule.conditions):
        prefix = f"Condition[{i}]"
        if cond.operator not in valid_ops:
            errors.append(
                f"{prefix}: Unknown operator '{cond.operator}'. "
                f"Valid: {sorted(valid_ops)}"
            )
        device = registry.get_device(cond.device_id)
        if device is None:
            errors.append(f"{prefix}: Device '{cond.device_id}' not found in registry")
        elif device.get_capability(cond.capability) is None:
            errors.append(
                f"{prefix}: Device '{cond.device_id}' has no capability "
                f"'{cond.capability}'. Available: {device.capability_names()}"
            )

    # Validate actions
    for i, act in enumerate(rule.actions):
        prefix = f"Action[{i}]"
        if act.action not in valid_actions:
            errors.append(
                f"{prefix}: Unknown action '{act.action}'. "
                f"Valid: {sorted(valid_actions)}"
            )
        device = registry.get_device(act.device_id)
        if device is None:
            errors.append(f"{prefix}: Device '{act.device_id}' not found in registry")
        elif device.get_capability(act.capability) is None:
            errors.append(
                f"{prefix}: Device '{act.device_id}' has no capability "
                f"'{act.capability}'. Available: {device.capability_names()}"
            )

    if rule.cooldown_seconds < 0:
        errors.append(f"Cooldown must be non-negative, got {rule.cooldown_seconds}")

    return errors


# ---------------------------------------------------------------------------
# Automation engine
# ---------------------------------------------------------------------------

class AutomationEngine:
    """Evaluates automation rules when device state changes.

    The engine is **synchronous** by design — ``evaluate()`` performs pure
    value comparisons and returns a list of ``DeviceCommand`` objects.
    The caller (``MeshChannel``) handles async dispatch.

    Persistence
    -----------
    Rules are stored in a JSON file. The engine loads on init and writes
    through on every mutation (add/remove/update/enable/disable/trigger).

    Thread / async safety
    ---------------------
    File writes are guarded by an ``asyncio.Lock``. Evaluation is
    synchronous and reads only immutable snapshots.
    """

    def __init__(self, registry: DeviceRegistry, path: str | Path):
        self._registry = registry
        self._path = Path(path)
        self._rules: dict[str, AutomationRule] = {}  # rule_id → rule
        self._device_index: dict[str, set[str]] = {}  # device_id → {rule_ids}
        self._lock = asyncio.Lock()

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Load rules from disk. Missing file → empty rule set."""
        if not self._path.exists():
            logger.debug(f"[Automation] no file at {self._path}, starting with no rules")
            return

        try:
            text = self._path.read_text(encoding="utf-8").strip()
            if not text:
                logger.debug(f"[Automation] empty file at {self._path}, starting fresh")
                return
            data = json.loads(text)
            for d in data.get("rules", []):
                try:
                    rule = AutomationRule.from_dict(d)
                    self._rules[rule.rule_id] = rule
                    self._index_rule(rule)
                except (KeyError, TypeError) as exc:
                    logger.warning(f"[Automation] skipping malformed rule: {exc}")
            logger.info(f"[Automation] loaded {len(self._rules)} rules from {self._path}")
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"[Automation] failed to load {self._path}: {exc}")

    async def _save(self) -> None:
        """Persist rules to disk (async-safe)."""
        async with self._lock:
            self._save_sync()

    def _save_sync(self) -> None:
        """Synchronous save — call only under the lock or in non-async context."""
        data = {
            "version": 1,
            "updated_at": time.time(),
            "rules": [r.to_dict() for r in self._rules.values()],
        }
        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(str(tmp), str(self._path))
        except OSError as exc:
            logger.error(f"[Automation] failed to save: {exc}")

    # -- index management ----------------------------------------------------

    def _index_rule(self, rule: AutomationRule) -> None:
        """Add a rule to the device index."""
        for device_id in rule.trigger_device_ids():
            if device_id not in self._device_index:
                self._device_index[device_id] = set()
            self._device_index[device_id].add(rule.rule_id)

    def _unindex_rule(self, rule: AutomationRule) -> None:
        """Remove a rule from the device index."""
        for device_id in rule.trigger_device_ids():
            rule_set = self._device_index.get(device_id)
            if rule_set:
                rule_set.discard(rule.rule_id)
                if not rule_set:
                    del self._device_index[device_id]

    def _rebuild_index(self) -> None:
        """Rebuild the entire device index from scratch."""
        self._device_index.clear()
        for rule in self._rules.values():
            self._index_rule(rule)

    # -- CRUD ----------------------------------------------------------------

    async def add_rule(self, rule: AutomationRule) -> AutomationRule:
        """Add a new automation rule.

        Raises ``ValueError`` if a rule with the same ID already exists.
        """
        if rule.rule_id in self._rules:
            raise ValueError(f"Rule '{rule.rule_id}' already exists")
        self._rules[rule.rule_id] = rule
        self._index_rule(rule)
        await self._save()
        logger.info(f"[Automation] added rule '{rule.rule_id}' ({rule.name})")
        return rule

    async def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule. Returns True if it existed."""
        rule = self._rules.pop(rule_id, None)
        if rule is None:
            return False
        self._unindex_rule(rule)
        await self._save()
        logger.info(f"[Automation] removed rule '{rule_id}'")
        return True

    async def update_rule(
        self,
        rule_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        conditions: list[Condition] | None = None,
        actions: list[RuleAction] | None = None,
        cooldown_seconds: int | None = None,
    ) -> AutomationRule | None:
        """Update fields of an existing rule. Returns the updated rule or None."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return None

        if name is not None:
            rule.name = name
        if description is not None:
            rule.description = description
        if enabled is not None:
            rule.enabled = enabled
        if conditions is not None:
            self._unindex_rule(rule)
            rule.conditions = conditions
            self._index_rule(rule)
        if actions is not None:
            rule.actions = actions
        if cooldown_seconds is not None:
            rule.cooldown_seconds = cooldown_seconds

        await self._save()
        logger.info(f"[Automation] updated rule '{rule_id}'")
        return rule

    def get_rule(self, rule_id: str) -> AutomationRule | None:
        """Look up a rule by ID."""
        return self._rules.get(rule_id)

    def list_rules(self) -> list[AutomationRule]:
        """Return all rules."""
        return list(self._rules.values())

    async def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule. Returns True if the rule exists."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.enabled = True
        await self._save()
        return True

    async def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule. Returns True if the rule exists."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.enabled = False
        await self._save()
        return True

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # -- evaluation ----------------------------------------------------------

    def evaluate(
        self,
        trigger_device_id: str,
        *,
        now: float | None = None,
    ) -> list[DeviceCommand]:
        """Evaluate all rules triggered by a device state change.

        Parameters
        ----------
        trigger_device_id:
            The device whose state just changed.
        now:
            Current time (for testing). Defaults to ``time.time()``.

        Returns
        -------
        List of ``DeviceCommand`` objects to dispatch. Empty if no rules fire.
        """
        now = now or time.time()
        commands: list[DeviceCommand] = []

        # Find rules that reference this device
        rule_ids = self._device_index.get(trigger_device_id, set())
        if not rule_ids:
            return commands

        for rule_id in list(rule_ids):  # copy to avoid mutation during iteration
            rule = self._rules.get(rule_id)
            if rule is None or not rule.enabled:
                continue

            # Check cooldown
            if not self._check_cooldown(rule, now):
                logger.debug(
                    f"[Automation] rule '{rule_id}' skipped (cooldown: "
                    f"{now - rule.last_triggered:.0f}s < {rule.cooldown_seconds}s)"
                )
                continue

            # Evaluate all conditions (AND logic)
            if self._evaluate_conditions(rule):
                logger.info(
                    f"[Automation] rule '{rule.name}' ({rule_id}) FIRED — "
                    f"triggered by device '{trigger_device_id}'"
                )
                rule.last_triggered = now
                for act in rule.actions:
                    commands.append(act.to_command())

        return commands

    def _check_cooldown(self, rule: AutomationRule, now: float) -> bool:
        """Return True if the rule's cooldown has elapsed."""
        if rule.last_triggered == 0.0:
            return True  # Never triggered before
        return (now - rule.last_triggered) >= rule.cooldown_seconds

    def _evaluate_conditions(self, rule: AutomationRule) -> bool:
        """Evaluate all conditions of a rule (AND logic).

        Returns True only if ALL conditions are satisfied.
        """
        for cond in rule.conditions:
            if not self._check_condition(cond):
                return False
        return True

    def _check_condition(self, cond: Condition) -> bool:
        """Evaluate a single condition against the registry's current state."""
        device = self._registry.get_device(cond.device_id)
        if device is None:
            logger.debug(
                f"[Automation] condition check: device '{cond.device_id}' not found"
            )
            return False

        current_value = device.state.get(cond.capability)
        if current_value is None:
            logger.debug(
                f"[Automation] condition check: device '{cond.device_id}' "
                f"has no state for '{cond.capability}'"
            )
            return False

        op_func = _OP_FUNCS.get(cond.operator)
        if op_func is None:
            logger.warning(f"[Automation] unknown operator '{cond.operator}'")
            return False

        try:
            return op_func(current_value, cond.value)
        except TypeError:
            # Incompatible types for comparison (e.g., str > int)
            logger.debug(
                f"[Automation] type mismatch comparing "
                f"{type(current_value).__name__} {cond.operator} "
                f"{type(cond.value).__name__}"
            )
            return False

    # -- LLM context ---------------------------------------------------------

    def describe_rules(self) -> str:
        """Generate a human-readable summary of active rules for LLM context."""
        rules = [r for r in self._rules.values() if r.enabled]
        if not rules:
            return "No active automation rules."

        lines = [f"Active automation rules ({len(rules)}):"]
        for r in rules:
            cond_parts = []
            for c in r.conditions:
                cond_parts.append(
                    f"{c.device_id}.{c.capability} {c.operator} {c.value}"
                )
            action_parts = []
            for a in r.actions:
                params_str = ""
                if a.params:
                    params_str = f" {a.params}"
                action_parts.append(
                    f"{a.action} {a.device_id}.{a.capability}{params_str}"
                )
            conditions_str = " AND ".join(cond_parts)
            actions_str = ", ".join(action_parts)
            status = ""
            if r.last_triggered:
                ago = int(time.time() - r.last_triggered)
                if ago < 60:
                    status = f" (last fired {ago}s ago)"
                elif ago < 3600:
                    status = f" (last fired {ago // 60}min ago)"
                else:
                    status = f" (last fired {ago // 3600}h ago)"
            lines.append(
                f"  - [{r.rule_id}] \"{r.name}\": "
                f"IF {conditions_str} THEN {actions_str}"
                f" (cooldown: {r.cooldown_seconds}s){status}"
            )
        return "\n".join(lines)

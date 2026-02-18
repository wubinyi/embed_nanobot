# f10: Basic Automation Rules Engine — Dev Implementation

**Task**: 2.6  
**Status**: Done  
**Date**: 2026-02-18  

---

## What Was Built

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/automation.py` | ~380 | Rule data model (`Condition`, `RuleAction`, `AutomationRule`, `ComparisonOp`), `AutomationEngine` (CRUD, indexed evaluation, cooldown, persistence, LLM context), `validate_rule()` |
| `tests/test_automation.py` | ~550 | 75 tests across 10 test classes |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/mesh/channel.py` | +2 imports (`AutomationEngine`, `command_to_envelope`), +14 lines in `__init__` (automation init + load), +10 lines in `_handle_state_report` (evaluate + dispatch) |
| `nanobot/config/schema.py` | +1 field `automation_rules_path` appended to `MeshConfig` |

## Key Design Decisions

### 1. Synchronous Evaluation
`AutomationEngine.evaluate()` is pure sync — compares current device state values against condition thresholds using simple operators. No I/O, no awaits. The async part (dispatching commands via transport) is handled by the caller (`MeshChannel`). This makes the engine trivially testable.

### 2. Device-Indexed Rules
Rules are indexed by the device IDs in their conditions (`_device_index: dict[str, set[str]]`). When device X's state changes, only rules referencing X are evaluated — O(1) lookup per indexed device. The index auto-updates on add/remove/update operations.

### 3. Cooldown Mechanism
Each rule has `cooldown_seconds` (default 60). After firing, the rule won't fire again until the cooldown expires. This prevents:
- Infinite loops (rule fires → state change → rule fires again)
- Flash-firing from noisy sensors
- Cascading loops across devices (each rule has independent cooldown)

The `evaluate()` method accepts an optional `now` parameter for deterministic testing.

### 4. Channel Integration
The automation engine hooks into `MeshChannel._handle_state_report()`:
```
STATE_REPORT → registry.update_state() → automation.evaluate() → transport.send()
```
Dispatch failures are logged as warnings but don't block further processing.

### 5. AND Logic for Conditions
All conditions in a rule must be true for the rule to fire. This is the simplest semantics that covers 90%+ of use cases ("if temp > 30 AND humidity > 70, turn on AC"). OR logic can be achieved by creating multiple rules.

### 6. Validation
`validate_rule()` checks:
- Non-empty rule_id
- At least one condition and one action
- Valid operators (eq, ne, gt, ge, lt, le)
- Valid action types (set, get, toggle, execute)
- Condition devices/capabilities exist in registry
- Action devices/capabilities exist in registry
- Non-negative cooldown

## Deviations from Design

None. Implementation follows the design log exactly.

## Code Snippets

### Core Evaluation Loop
```python
def evaluate(self, trigger_device_id, *, now=None):
    now = now or time.time()
    commands = []
    rule_ids = self._device_index.get(trigger_device_id, set())
    for rule_id in list(rule_ids):
        rule = self._rules.get(rule_id)
        if rule is None or not rule.enabled:
            continue
        if not self._check_cooldown(rule, now):
            continue
        if self._evaluate_conditions(rule):
            rule.last_triggered = now
            for act in rule.actions:
                commands.append(act.to_command())
    return commands
```

### Channel Dispatch Hook
```python
# In _handle_state_report(), after registry.update_state():
if self.automation:
    commands = self.automation.evaluate(env.source)
    for cmd in commands:
        envelope = command_to_envelope(cmd, source=self.node_id)
        ok = await self.transport.send(envelope)
```

### Documentation Freshness Check
- architecture.md: Updated — added automation.py to mesh components
- configuration.md: Updated — added automation_rules_path field
- customization.md: OK — no new extension patterns
- PRD.md: Updated — marked DS-03 progress
- agent.md: OK — no upstream convention changes

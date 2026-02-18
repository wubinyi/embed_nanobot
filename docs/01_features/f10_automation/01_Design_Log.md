# f10: Basic Automation Rules Engine — Design Log

**Task**: 2.6  
**Status**: In progress  
**Date**: 2026-02-18  

---

## Problem Statement

Smart home / smart factory hubs need reactive automation: "when temperature exceeds 30°C, turn on the AC," "when motion detected, turn on lights." Currently, the user must manually issue every device command through the agent. A rules engine evaluates conditions automatically when device state changes and fires device commands without human intervention.

## Architect Proposal

### Architecture

```
STATE_REPORT  →  MeshChannel._handle_state_report()
                      │
                      ▼
              Registry.update_state()
                      │
                      ▼
          AutomationEngine.evaluate(device_id)
              │  (sync: pure condition checks)
              ▼
         [list[DeviceCommand]]
              │
              ▼  (async: MeshChannel dispatches)
         transport.send(command_envelope)
```

### Data Model

- **Condition**: `{device_id, capability, operator, value}` — compares a device capability's current state against a threshold using one of `eq|ne|gt|ge|lt|le`.
- **RuleAction**: `{device_id, capability, action, params}` — generates a `DeviceCommand` when all conditions are met.
- **AutomationRule**: `{rule_id, name, description, enabled, conditions: list[Condition], actions: list[RuleAction], cooldown_seconds, last_triggered}` — AND logic (all conditions must be true).

### Key Design Decisions

1. **Sync evaluation**: The engine's `evaluate()` method is synchronous — it reads current state from the registry and compares values. No I/O. This keeps the engine simple and testable.

2. **Channel dispatches**: MeshChannel holds the transport reference. After evaluate() returns commands, the channel sends them asynchronously. Clean separation of concerns.

3. **Device-indexed rules**: Rules are indexed by the device_id(s) appearing in their conditions. When device X's state changes, only rules referencing device X are evaluated — O(1) lookup per rule set.

4. **Cooldown mechanism**: Each rule has a `cooldown_seconds` (default 60). After a rule fires, it won't fire again until the cooldown expires. This prevents:
   - Infinite loops (rule A triggers device → state change → rule fires again)
   - Rapid-fire commands from noisy sensors

5. **Validation on add**: When a rule is added, `validate_rule()` checks:
   - All condition devices/capabilities exist in the registry
   - All action devices/capabilities exist in the registry
   - Operators are valid
   - The rule has at least one condition and one action

6. **Persistence**: Rules are stored in a JSON file alongside existing registry and key_store files.

## Reviewer Challenge

### Concern 1: Infinite Loops
**Risk**: Rule A fires command to device X → X reports new state → triggers Rule A again.  
**Mitigation**: Cooldown mechanism. Even with a 1-second cooldown, the loop is bounded. Default 60 seconds is safe for most cases. Additionally, users should be warned in documentation.

### Concern 2: Cross-device Cascading
**Risk**: Rule A→device X→Rule B→device Y→Rule C→device Z in rapid succession.  
**Mitigation**: Each rule has its own cooldown. Cross-device cascading is valid behavior (e.g., thermostat triggers AC triggers fan), but the cooldown on each rule independently prevents runaway chains.

### Concern 3: Security
**Question**: Can devices inject arbitrary rules?  
**Answer**: No. Rules are defined by the hub operator (via config file or future API). Devices only send STATE_REPORT messages; they cannot create rules.

### Concern 4: Performance on Resource-Constrained Devices
**Question**: Is evaluating rules on every state change expensive?  
**Answer**: The engine is indexed by device_id — only matching rules are evaluated. Each evaluation is a few comparisons (O(conditions)). On a Raspberry Pi 4 with 100 rules, this is microseconds.

## Consensus

Design approved. Implementation proceeds with the architecture above.

## File Plan

| File | Type | Purpose |
|------|------|---------|
| `nanobot/mesh/automation.py` | NEW | ~300 LOC — data model + AutomationEngine |
| `nanobot/mesh/channel.py` | MODIFIED | +10 lines (init engine, dispatch on state change) |
| `nanobot/config/schema.py` | MODIFIED | +1 field appended to MeshConfig |
| `tests/test_automation.py` | NEW | ~40+ tests |

### Conflict Surface
- `channel.py`: Appended automation init+dispatch block inside existing embed_nanobot section
- `schema.py`: 1 new field appended at end of MeshConfig
- `automation.py`: New file — zero conflict risk

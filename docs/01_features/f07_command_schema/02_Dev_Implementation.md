# f07: Standardized Device Command Schema — Dev Implementation

**Task**: 2.2 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Implementation Summary

Single new module `nanobot/mesh/commands.py` (~330 LOC) implementing the full command schema with zero modifications to existing upstream or shared files.

## 2. Module: `nanobot/mesh/commands.py`

### Enums

```python
class Action(str, Enum):
    SET = "set"        # Set a capability value
    GET = "get"        # Query current value
    TOGGLE = "toggle"  # Toggle boolean capability
    EXECUTE = "execute" # Custom device function

class CommandStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
```

### Dataclasses

- **`DeviceCommand`**: `device`, `action`, `capability`, `params` — with `to_dict()` / `from_dict()`.
- **`CommandResponse`**: `device`, `status`, `capability`, `value`, `error` — with `is_ok` property.
- **`BatchCommand`**: `commands: list[DeviceCommand]`, `stop_on_error: bool`.

### Validation

`validate_command(cmd, registry) -> list[str]` performs 6-level validation:

1. Action validity (must be in Action enum)
2. Device existence (must be in registry)
3. Online status (warning if offline)
4. Capability existence (required for set/get/toggle, optional for execute)
5. Action/capability compatibility (no set on sensor, no toggle on non-bool)
6. Value type and range checking via `_validate_value()` helper

### Mesh Envelope Integration

- `command_to_envelope()` — wraps command as `MsgType.COMMAND` envelope
- `parse_command_from_envelope()` — extracts command from envelope, returns None for wrong type
- `response_to_envelope()` — wraps response as `MsgType.RESPONSE` envelope
- `parse_response_from_envelope()` — extracts response, returns None for wrong type

### LLM Context Generator

`describe_device_commands(registry)` outputs Markdown with:
- Per-device listing: name, node_id, type, online status
- Per-capability: name, type, data range, unit, current value
- Action reference section with example JSON

## 3. Deviations from Plan

None. Implementation matches the design exactly.

## 4. Key Design Decisions

1. **Dataclasses over Pydantic**: Keeps the module dependency-free (no pydantic import needed). Consistent with registry.py pattern.
2. **`validate_command()` as free function**: Easier to test, doesn't couple validation to command lifecycle.
3. **Offline = warning, not error**: Devices may come online between validation and dispatch. Let the caller decide.
4. **`execute` action has no capability validation**: Device-specific functions are too varied. Device-side validation is the responsibility.
5. **`bool` explicitly excluded from int/float checks**: Python `bool` is a subclass of `int`, so `isinstance(True, int)` is True. We check `isinstance(value, bool)` first.

## 5. Documentation Freshness Check

- architecture.md: Updated — added commands.py to mesh layer components
- configuration.md: OK — no new config fields (commands.py is code-only)
- customization.md: OK — no new extension patterns
- PRD.md: OK — DS-02 will be marked Done in roadmap update
- agent.md: OK — no upstream convention changes

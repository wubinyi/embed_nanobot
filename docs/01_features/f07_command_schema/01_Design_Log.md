# f07: Standardized Device Command Schema — Design Log

**Task**: 2.2 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Requirements (from PRD)

> **DS-02**: Standardized Device Command Schema  
> Natural-language requests translated to structured JSON commands.  
> Commands: `set`, `get`, `toggle`, plus custom `execute`.  
> Validation against device capabilities before dispatch.

## 2. Architect Proposal

### 2.1 Data Model

Three core dataclasses:

| Class | Purpose |
|-------|---------|
| `DeviceCommand` | Command sent to a device (device, action, capability, params) |
| `CommandResponse` | Response received (device, status, capability, value, error) |
| `BatchCommand` | Ordered list of commands with optional stop-on-error |

Two enums:

| Enum | Values |
|------|--------|
| `Action` | `set`, `get`, `toggle`, `execute` |
| `CommandStatus` | `ok`, `error` |

### 2.2 Validation Strategy

`validate_command(cmd, registry)` returns `list[str]` of errors:

1. **Action validity** — must be in `Action` enum values.
2. **Device existence** — must be in registry.
3. **Online status** — warn (not block) if device offline.
4. **Capability existence** — must exist on device (except for `execute`).
5. **Action/capability compatibility**:
   - `set` on a `SENSOR` → rejected (sensors are read-only).
   - `toggle` on non-`BOOL` → rejected.
6. **Value type/range** for `set`:
   - `BOOL` → must be actual `bool` (not `int` 0/1).
   - `INT` → must be `int` (not `bool`), within range.
   - `FLOAT` → must be `int|float` (not `bool`), within range.
   - `STRING` → must be `str`.
   - `ENUM` → must be in `enum_values` list.

### 2.3 Mesh Integration

- `command_to_envelope(cmd, source)` → `MeshEnvelope` (type=COMMAND)
- `parse_command_from_envelope(env)` → `DeviceCommand | None`
- `response_to_envelope(resp, source, target)` → `MeshEnvelope` (type=RESPONSE)
- `parse_response_from_envelope(env)` → `CommandResponse | None`

Reuses existing `MsgType.COMMAND` and `MsgType.RESPONSE` from protocol.py — no protocol changes needed.

### 2.4 LLM Context

`describe_device_commands(registry)` generates Markdown describing all devices, capabilities, value ranges, and action reference. Injected into the LLM system prompt so it can produce valid commands.

## 3. Reviewer Assessment

**[Reviewer]**: Design is clean and well-isolated.

- **Positive**: Pure functions, no shared file modifications, dataclass-based (easy to serialize).
- **Security**: Validation prevents invalid commands reaching devices — good defense-in-depth.
- **Concern**: `execute` action is very open — any params accepted. Should be documented as requiring device-side validation.
- **IoT edge case**: Batch commands with mixed online/offline devices — current validation will warn per-device, which is sufficient.
- **Upstream conflict**: Zero. `commands.py` is a new file in `nanobot/mesh/` — no shared-file modifications.

**[Architect]**: Agreed. `execute` flexibility is intentional — device-specific functions vary too much to validate generically. Documentation will clarify.

## 4. Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/commands.py` | Command/Response models, validation, envelope conversion, LLM descriptor |
| `tests/test_device_commands.py` | Comprehensive test suite |
| `docs/01_features/f07_command_schema/` | Feature documentation |

### Modified Files

None. Zero conflict surface — pure additive.

### Dependencies

- `nanobot/mesh/protocol.py` — uses `MeshEnvelope`, `MsgType.COMMAND`, `MsgType.RESPONSE` (already exist)
- `nanobot/mesh/registry.py` — uses `DeviceRegistry`, `DeviceCapability`, `CapabilityType`, `DataType` (from task 2.1)

### Test Plan

- Data model: serialization roundtrips for all three dataclasses
- Validation: 11 test cases covering all error paths
- Value validation: type checks × range checks for all DataType values
- Envelope: conversion roundtrips including binary serialization
- LLM description: output content verification
- Enums: value verification

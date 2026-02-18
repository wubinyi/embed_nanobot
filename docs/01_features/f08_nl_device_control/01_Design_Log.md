# f08: Natural Language → Device Command (LLM Skill) — Design Log

**Task**: 2.3 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Requirements (from PRD)

> Natural language → device command translation (LLM skill)  
> User says "turn on the light" → agent generates and dispatches a validated DeviceCommand.

**Dependencies**: Command schema (2.2), Hybrid Router (1.2), Device Registry (2.1).

## 2. Architect Proposal

### 2.1 Architecture

Two components bridging the agent to the mesh device ecosystem:

| Component | Type | Purpose |
|-----------|------|---------|
| `DeviceControlTool` | Agent Tool | Provide the agent with list/command/state/describe actions for device control |
| `device-control` SKILL | Markdown Skill | Teach the agent NL→command translation patterns |

### 2.2 DeviceControlTool (`nanobot/agent/tools/device.py`)

Extends `Tool` base class with four actions:

| Action | Purpose | Parameters |
|--------|---------|------------|
| `list` | Summary of all registered devices | None |
| `command` | Validate and send a device command | device, command_action, capability, value, params |
| `state` | Query a specific device's current state | device |
| `describe` | Full capability reference for LLM reasoning | None |

The `command` action:
1. Builds a `DeviceCommand` from parameters
2. Validates against registry via `validate_command()`
3. Creates a `MeshEnvelope` via `command_to_envelope()`
4. Dispatches through `MeshTransport.send()`

### 2.3 Device-Control Skill

`always: true` skill (~200 tokens) providing:
- Quick reference table of common device commands
- Step-by-step NL→command workflow
- Action type reference (set/get/toggle/execute)
- Important notes (validation, offline, sensors read-only)

### 2.4 Integration

Tool registered in `nanobot/cli/commands.py` after ChannelManager creates MeshChannel:
- Gets `registry` and `transport` refs from MeshChannel instance
- Only registered when mesh channel is enabled

## 3. Reviewer Assessment

**[Reviewer]**: Clean two-component design.

- **Positive**: Tool uses the existing `Tool` base class and `ToolRegistry` — zero framework changes.
- **Positive**: Skill is lightweight (`always: true` → ~200 tokens), worth the cost for core functionality.
- **Conflict surface**: 1 append block in `commands.py` — minimal, well-isolated.
- **Security**: All commands validated before dispatch. No raw passthrough.
- **IoT concern**: Fire-and-forget dispatch. No response correlation yet — acceptable for v1, noted for future.
- **Concern**: Agent might hallucinate device IDs. Skill instructs to call `list` first when unsure.

**[Architect]**: Agreed on all points. Response correlation (task 2.x future) will add command_id tracking.

## 4. Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/agent/tools/device.py` | DeviceControlTool — list, command, state, describe |
| `nanobot/skills/device-control/SKILL.md` | Always-active NL→command skill |
| `tests/test_device_control_tool.py` | 32 tests across 7 test classes |
| `docs/01_features/f08_nl_device_control/` | Feature documentation |

### Modified Files

| File | Change | Conflict Risk |
|------|--------|---------------|
| `nanobot/cli/commands.py` | Append: register DeviceControlTool when mesh enabled | Low (isolated block) |

### Test Plan

- Tool metadata: name, description, parameters schema, OpenAI format
- list: empty + populated registry
- command: valid set/get/toggle/execute, validation failures (unknown device, sensor set, out of range, offline), transport failure, missing params
- state: existing/unknown/missing device, with/without state
- describe: empty + populated
- Edge cases: unknown action, empty action, value merge into params

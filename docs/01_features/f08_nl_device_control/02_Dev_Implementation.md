# f08: Natural Language → Device Command — Dev Implementation

**Task**: 2.3 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Implementation Summary

Two new files implement the NL→device command pipeline. One shared file modified (append-only).

## 2. New Module: `nanobot/agent/tools/device.py`

`DeviceControlTool` extends `Tool` base class (~190 LOC):

### Constructor

```python
def __init__(self, registry: DeviceRegistry, transport: MeshTransport, node_id: str)
```

Takes direct references to MeshChannel's registry and transport, avoiding any global state.

### Actions

**`list`**: Iterates `registry.get_all_devices()`, formats name/node_id/type/status/caps.

**`command`**: Core flow:
1. Build `DeviceCommand` from kwargs (device, command_action, capability, value/params)
2. Merge `value` into `params["value"]` if not already present
3. Call `validate_command(cmd, registry)` — returns errors or empty list
4. If valid: `command_to_envelope(cmd, source=node_id)` → `transport.send(envelope)`
5. Return success/failure message to agent

**`state`**: Calls `registry.get_device(id)`, formats state dict with units from capabilities.

**`describe`**: Delegates to `describe_device_commands(registry)` from commands.py.

### Key Design Decisions

1. **Direct transport dispatch** (not via bus): The bus `OutboundMessage` format is text-oriented for chat channels. Device commands need `MsgType.COMMAND` envelopes. Direct transport access is cleaner.
2. **Value/params merge**: The `value` parameter is a convenience shortcut. If the agent passes both `value=80` and `params={"other": "x"}`, they're merged as `{"value": 80, "other": "x"}`.
3. **Fire-and-forget**: No response await — the command is dispatched and the result is synchronous (sent/failed). Device responses arrive as separate inbound messages.

## 3. New Skill: `nanobot/skills/device-control/SKILL.md`

`always: true` skill (injected in every system prompt):

- Quick reference table: 7 common patterns (list, set, get, toggle, state, describe)
- "How to Handle Device Requests" workflow: identify device → determine action → send command → report result
- Action reference: set/get/toggle/execute with constraints
- Important notes: validation, offline warning, sensors read-only, boolean toggles only

~200 tokens system prompt cost.

## 4. Modified: `nanobot/cli/commands.py`

Appended after channel manager creation (line ~450):

```python
# --- embed_nanobot extensions: device control tool (task 2.3) ---
if "mesh" in channels.channels:
    from nanobot.agent.tools.device import DeviceControlTool
    mesh_ch = channels.channels["mesh"]
    agent.tools.register(DeviceControlTool(
        registry=mesh_ch.registry,
        transport=mesh_ch.transport,
        node_id=mesh_ch.node_id,
    ))
```

Guarded by try/except with logger.warning fallback.

## 5. Deviations from Plan

None.

## 6. Documentation Freshness Check

- architecture.md: Updated — added DeviceControlTool to agent tools section, device-control skill to skills list
- configuration.md: OK — no new config fields (tool is auto-registered when mesh enabled)
- customization.md: OK — no new extension patterns
- PRD.md: OK — will be updated in roadmap
- agent.md: OK — no upstream convention changes

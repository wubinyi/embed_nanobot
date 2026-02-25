# f15: Device Grouping and Scenes — Dev Implementation

**Task**: 3.4 — Device grouping and scenes  
**Branch**: `copilot/device-groups`  
**Date**: 2026-02-25  

---

## Summary

Implemented device groups (named collections of node_ids) and scenes (named command batches) as a standalone `GroupManager` class in `nanobot/mesh/groups.py`, with channel integration and JSON persistence.

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/groups.py` | ~306 | DeviceGroup, Scene dataclasses + GroupManager with CRUD, persistence, fan-out, LLM descriptions |
| `tests/test_groups.py` | ~290 | 35 tests covering all functionality |
| `docs/01_features/f15_groups/01_Design_Log.md` | Design decisions |
| `docs/01_features/f15_groups/02_Dev_Implementation.md` | This file |
| `docs/01_features/f15_groups/03_Test_Report.md` | Test results |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/config/schema.py` | Added `groups_path: str = ""` and `scenes_path: str = ""` to `MeshConfig` |
| `nanobot/mesh/channel.py` | Added `GroupManager` import, creation in `__init__`, convenience methods `execute_scene()` and `execute_group_command()` |
| `docs/configuration.md` | Added groups_path and scenes_path documentation |

## Key Implementation Details

### Data Model

- `DeviceGroup`: group_id, name, device_ids list, metadata dict. Serializable via `to_dict()`/`from_dict()`.
- `Scene`: scene_id, name, commands (list of DeviceCommand dicts), description. `to_device_commands()` converts stored dicts to `DeviceCommand` objects, skipping malformed entries.

### GroupManager

- **Persistence**: Dual JSON files (`groups.json`, `scenes.json`). Auto-creates parent directories. Saves after every mutation.
- **Group CRUD**: `add_group()`, `remove_group()`, `get_group()`, `list_groups()`, `add_device_to_group()`, `remove_device_from_group()`.
- **Scene CRUD**: `add_scene()`, `remove_scene()`, `get_scene()`, `list_scenes()`.
- **Execution helpers**:
  - `get_scene_commands(scene_id)` → `list[DeviceCommand]`
  - `fan_out_group_command(group_id, action, capability, params)` → one `DeviceCommand` per device in the group.
- **LLM context**: `describe_groups()` and `describe_scenes()` return Markdown suitable for injection into LLM system prompts.

### Channel Integration

- `MeshChannel.__init__` creates `GroupManager` if groups_path or scenes_path is configured (defaults to `workspace/groups.json` and `workspace/scenes.json`).
- `execute_scene(scene_id)`: Gets scene commands → sends each via transport → returns `list[bool]`.
- `execute_group_command(group_id, action, capability, params)`: Fan-out → sends each → returns `list[bool]`.

### Deviations from Design

None. Implementation matches the design plan exactly.

## Documentation Freshness Check

- architecture.md: OK (groups.py is in mesh/ which is already documented)
- configuration.md: Updated — added groups_path and scenes_path fields
- customization.md: OK
- PRD.md: OK (will be updated at roadmap phase)
- agent.md: OK — no upstream convention changes

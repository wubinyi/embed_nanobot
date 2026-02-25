# f15: Device Grouping and Scenes — Design Log

**Task**: 3.4 — Device grouping and scenes  
**Branch**: `copilot/device-groups`  
**Date**: 2026-02-25  

---

## Motivation

Users naturally think in terms of rooms and scenarios, not individual device IDs:
- "Turn off the living room" → all lights in the living room
- "Good night" → lock doors, dim lights, set thermostat to 18°C, arm alarm

The system needs:
1. **Device groups**: Named collections of device node_ids (e.g., "living_room", "all_lights")
2. **Scenes**: Named sets of device commands that execute as a batch (e.g., "good_night", "movie_mode")

## Architecture

### Data Model

**DeviceGroup**: Named set of device node_ids with optional metadata.
```python
@dataclass
class DeviceGroup:
    group_id: str          # e.g. "living_room"
    name: str              # "Living Room"
    device_ids: list[str]  # ["light-01", "light-02", "tv-01"]
    metadata: dict = {}    # tags, room type, floor, etc.
```

**Scene**: Named batch of commands with optional description.
```python
@dataclass
class Scene:
    scene_id: str           # e.g. "good_night"
    name: str               # "Good Night"
    commands: list[dict]    # DeviceCommand dicts
    description: str = ""
```

### GroupManager (`nanobot/mesh/groups.py`)

- CRUD for groups and scenes
- `execute_scene(scene_id)` → generates DeviceCommands, returns list
- `get_group_devices(group_id)` → resolves group to DeviceInfo list (from registry)
- `get_group_commands(group_id, action, capability, params)` → fan-out a single action to all group members
- JSON persistence (`groups.json` and `scenes.json` in workspace)
- Validation against registry

### Channel Integration

- `MeshChannel` gets `groups: GroupManager | None` attribute
- Convenience methods: `execute_scene()`, `get_group()`, `list_groups()`, etc.

## Key Decisions

1. **Separate from automation**: Groups/scenes are user-controlled (triggered explicitly), automation is event-driven (triggered by device state changes)
2. **No nested groups**: Keep it flat for simplicity
3. **Scene commands are templates**: Stored as DeviceCommand dicts, validated at execution time
4. **Group fan-out**: A command to a group becomes N individual commands (one per group member)

## Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/groups.py` | DeviceGroup, Scene, GroupManager |
| `tests/test_groups.py` | Tests |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/channel.py` | Add GroupManager creation, convenience methods |
| `nanobot/config/schema.py` | Add `groups_path`, `scenes_path` fields |

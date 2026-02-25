# f15: Device Grouping and Scenes — Test Report

**Task**: 3.4 — Device grouping and scenes  
**Date**: 2026-02-25  

---

## Test File

`tests/test_groups.py` — 35 tests

## Test Results

```
35 passed in 0.59s
Full regression: 607 passed in 12.80s (572 baseline + 35 new)
```

## Test Coverage

### TestDeviceGroup (2 tests)
- `test_to_dict_roundtrip` — serialize/deserialize preserves all fields
- `test_from_dict_minimal` — minimal dict with just group_id uses defaults

### TestScene (4 tests)
- `test_to_dict_roundtrip` — serialize/deserialize preserves all fields
- `test_to_device_commands` — converts command dicts to DeviceCommand objects correctly
- `test_to_device_commands_malformed` — malformed dicts produce empty-field DeviceCommands (from_dict uses .get defaults)
- `test_from_dict_minimal` — minimal dict with just scene_id

### TestGroupManagerGroups (11 tests)
- `test_add_and_get` — basic CRUD
- `test_list_groups` — returns all groups
- `test_remove_group` — remove existing/missing
- `test_add_device_to_group` — appends device
- `test_add_device_idempotent` — re-adding existing device is no-op
- `test_add_device_no_group` — returns False for missing group
- `test_remove_device_from_group` — removes device
- `test_remove_device_not_in_group` — returns False if device not present
- `test_remove_device_no_group` — returns False for missing group
- `test_group_persistence` — save/load cycle via separate GroupManager instances
- `test_overwrite_group` — same group_id replaces existing

### TestGroupManagerScenes (6 tests)
- `test_add_and_get` — basic CRUD
- `test_list_scenes` — returns all scenes
- `test_remove_scene` — remove existing/missing
- `test_scene_persistence` — save/load cycle via separate instances
- `test_get_scene_commands` — expands scene to DeviceCommand list
- `test_get_scene_commands_missing` — empty list for unknown scene

### TestFanOut (3 tests)
- `test_fan_out_group_command` — generates one DeviceCommand per group member with correct params
- `test_fan_out_missing_group` — empty list for unknown group
- `test_fan_out_empty_group` — empty list for group with no devices

### TestDescriptions (4 tests)
- `test_describe_groups` — Markdown contains group name, id, devices
- `test_describe_groups_empty` — returns empty string when no groups
- `test_describe_scenes` — Markdown contains scene name, id, description
- `test_describe_scenes_empty` — returns empty string when no scenes

### TestChannelGroupsIntegration (5 tests)
- `test_groups_manager_created` — MeshChannel creates GroupManager in __init__
- `test_execute_scene` — executes scene commands via transport, returns results
- `test_execute_scene_empty` — empty list for missing scene
- `test_execute_group_command` — fans out command to all group devices via transport
- `test_execute_group_command_empty` — empty list for missing group

## Edge Cases Covered
- Empty groups (no devices)
- Missing groups/scenes (non-existent IDs)
- Malformed scene commands
- Idempotent operations (add device already in group)
- Persistence roundtrip (separate manager instances)
- Overwriting existing groups

## Known Gaps
- No concurrency tests (GroupManager is synchronous, no threading concerns in current usage)
- No corrupt file recovery tests (JSON parse errors logged, empty state used)

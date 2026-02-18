# Dev Implementation — f06: Device Capability Registry

**Task**: 2.1 — Device capability registry and state management  
**Date**: 2026-02-18

---

## Implementation Summary

### New Module: `nanobot/mesh/registry.py` (~350 LOC)

Core classes:
- **`CapabilityType`** (enum): `SENSOR`, `ACTUATOR`, `PROPERTY`
- **`DataType`** (enum): `BOOL`, `INT`, `FLOAT`, `STRING`, `ENUM`
- **`DeviceCapability`** (dataclass): Describes one device function with type, data type, unit, range, enum values
- **`DeviceInfo`** (dataclass): Full device record with capabilities, state, online status, metadata
- **`DeviceRegistry`**: Central registry class with CRUD, state management, persistence, events

Key design patterns:
- **JSON file persistence** with atomic writes (write to `.tmp`, `os.replace`)
- **Async lock** for concurrent state update safety
- **Event callback system** for "registered", "updated", "removed", "online", "offline", "state_changed"
- **LLM context helpers**: `summary()` for human-readable text, `to_dict_for_llm()` for structured data

### Protocol Extension: `STATE_REPORT`

Added `STATE_REPORT` message type to `MsgType` enum. Payload format:
```json
{"state": {"temperature": 23.5, "humidity": 45}}
```

### Discovery Enhancement

Extended `PeerInfo` dataclass with `capabilities` (list of dicts) and `device_type` fields.  
Added `on_peer_seen()` / `on_peer_lost()` callback registration to `UDPDiscovery`.  
Beacon handler now parses `capabilities` and `device_type` from beacon payloads and notifies callbacks.

### Channel Integration

`MeshChannel` now:
- Creates and loads a `DeviceRegistry` instance
- Handles `STATE_REPORT` messages (updates device state)
- Hooks into discovery `on_peer_seen`/`on_peer_lost` for automatic online/offline tracking
- Auto-registers new devices when beacons include `device_type` + `capabilities`
- Exposes `get_device_summary()` for easy LLM context access

### Config Addition

Added `registry_path: str = ""` to `MeshConfig` — path to `device_registry.json` (defaults to `<workspace>/device_registry.json`).

## Deviations from Plan

None — implemented as designed.

## Dependencies

Zero new dependencies. Uses only Python stdlib (`json`, `os`, `time`, `asyncio`, `pathlib`, `dataclasses`, `enum`).

### Documentation Freshness Check
- architecture.md: Updated — added device registry to mesh stack diagram
- configuration.md: Updated — added registryPath field
- customization.md: OK — no new extension patterns
- PRD.md: OK — DM-01 can be marked done
- agent.md: OK — no convention changes

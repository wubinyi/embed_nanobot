# Design Log — f06: Device Capability Registry

**Task**: 2.1 — Device capability registry and state management  
**Phase**: 2 — Device Ecosystem  
**Date**: 2026-02-18  
**Complexity**: L (Large)

---

## Problem Statement

The mesh network can transport messages between devices, but there's no central knowledge of **what devices exist**, **what they can do**, or **what their current state is**. The AI Hub needs this information to:
- Generate correct device commands
- Answer state queries ("Is the light on?")
- Build automation rules
- Present device status to users

## Design Decision — Architect/Reviewer Debate

### Architect Proposal

A `DeviceRegistry` class in `nanobot/mesh/registry.py` that:
1. Maintains an in-memory dict of `DeviceInfo` objects keyed by `node_id`
2. Persists to a JSON file (`device_registry.json`) in the workspace
3. Supports event callbacks for UI/automation reactivity
4. Integrates with discovery beacons for auto-registration
5. Provides LLM-friendly summary output for context injection

### Reviewer Challenges

| Challenge | Resolution |
|-----------|------------|
| **State in same file as capabilities?** | Yes — single file keeps it simple. Devices report state infrequently. Write-through on mutation is fast enough. |
| **Online/offline detection?** | Leverages existing discovery `peer_timeout` (30s). Added `on_peer_seen`/`on_peer_lost` callbacks to discovery. |
| **Thread safety for concurrent state updates?** | `asyncio.Lock` guards file writes. Dict key operations are atomic in CPython. |
| **Upstream conflict risk?** | New file `registry.py` = zero risk. `protocol.py`, `channel.py`, `discovery.py` are embed-only. Only `schema.py` is shared (append-only). |
| **Memory usage with many devices?** | At 50 devices (PRD target), the in-memory dict is <100KB. JSON file is <50KB. No concern. |
| **What if beacon doesn't include capabilities?** | Graceful degradation — device is discovered but capabilities list is empty. Can be populated manually or via STATE_REPORT. |

## Data Model

```
DeviceCapability
├── name: str          (e.g. "temperature")
├── cap_type: str      (sensor / actuator / property)
├── data_type: str     (bool / int / float / string / enum)
├── unit: str          (°C, %, lux)
├── value_range: tuple (min, max)
└── enum_values: list  (for enum type)

DeviceInfo
├── node_id: str
├── device_type: str
├── name: str
├── capabilities: list[DeviceCapability]
├── state: dict        (capability_name → current value)
├── online: bool
├── last_seen: float
├── registered_at: float
└── metadata: dict     (firmware version, etc.)
```

## Integration Points

- **Discovery beacons**: Extended with `capabilities` and `device_type` fields
- **New MsgType**: `STATE_REPORT` for devices pushing state changes
- **MeshChannel**: Initializes registry, handles STATE_REPORT, hooks discovery events
- **LLM context**: `registry.summary()` produces human-readable device list

## File Plan

| Action | File | Changes |
|--------|------|---------|
| **New** | `nanobot/mesh/registry.py` | DeviceRegistry, DeviceCapability, DeviceInfo, CapabilityType, DataType |
| **New** | `tests/test_device_registry.py` | 50 tests across 10 test classes |
| **Modified** | `nanobot/mesh/protocol.py` | Added `STATE_REPORT` to MsgType |
| **Modified** | `nanobot/mesh/discovery.py` | Added `capabilities`/`device_type` to PeerInfo, `on_peer_seen`/`on_peer_lost` callbacks |
| **Modified** | `nanobot/mesh/channel.py` | Integrated registry, STATE_REPORT handling, discovery hooks |
| **Modified** | `nanobot/config/schema.py` | Added `registry_path` to MeshConfig |

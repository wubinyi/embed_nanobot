# f21 BLE Sensor Support — Dev Implementation

**Task**: 4.5 BLE mesh support for battery-powered sensors  
**Branch**: `copilot/ble-mesh`  
**Date**: 2026-02-26  

---

## Summary

Implemented passive BLE advertisement scanning with configurable device profiles.
BLE sensors are auto-registered in the device registry and readings are fed
through the standard state update pipeline (automation + sensor pipeline).

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/ble.py` | ~380 | BLE bridge: scanner ABC, BleakBLEScanner, StubScanner, BLEDeviceProfile, BLECapabilityDef, BLEBridge orchestrator |
| `tests/test_ble.py` | ~480 | 50 tests across 16 test classes |

## Files Modified

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Added `ble_config_path: str = ""` |
| `nanobot/mesh/channel.py` | Import BLEBridge; init when config set; start/stop; `_on_ble_state_update` callback (pipeline + automation) |

## Architecture Decisions

### Adapter Pattern
- `BLEScanner` ABC with `scan(duration)` → `list[BLEAdvertisement]`
- `BleakBLEScanner` — real hardware via `bleak` library (optional dependency)
- `StubScanner` — test stub returning pre-configured advertisements
- Follows same pattern as IndustrialBridge's protocol adapters

### Device Profile System
- JSON config with regex-based device name matching
- Byte-level decode rules: data source (manufacturer/service), byte offset, length, struct format, scale factor
- Supports 7 data types: uint8, int8, uint16, int16, uint32, int32, float32
- Auto-registration with full capability metadata

### Passive Scanning Model
- Periodic scan loop (configurable interval + duration)
- Parses BLE advertisements (manufacturer data + service data)
- No active GATT connections needed — ideal for battery sensors
- Device timeout-based pruning marks offline devices

### State Update Pipeline
- BLE readings → registry update → state callback → pipeline record + automation
- RSSI included in every state update for signal quality monitoring

## Deviations from Design

None. Implementation matches design log exactly.

---

### Documentation Freshness Check
- architecture.md: Updated — added ble.py to mesh components
- configuration.md: Updated — added BLE config fields + setup guide
- customization.md: OK — no new extension points
- PRD.md: OK — no status changes needed yet
- agent.md: OK — no upstream convention changes

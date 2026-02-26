# f21 BLE Sensor Support — Test Report

**Task**: 4.5 BLE mesh support for battery-powered sensors  
**Date**: 2026-02-26  
**Result**: 50 passed, 0 failed  
**Full regression**: 894 passed (844 baseline + 50 new), 0 failures  

---

## Test File

`tests/test_ble.py` — 50 tests across 16 classes

## Test Classes

| Class | Tests | Covers |
|-------|-------|--------|
| TestBLEAdvertisement | 2 | node_id derivation from MAC address |
| TestBLECapabilityDef | 3 | from_dict full, defaults, manufacturer |
| TestDecodeValue | 8 | int16, uint16, uint8, int8, float32, byte offset, too short, unknown type |
| TestBLEDeviceProfile | 6 | Exact match, no match, case insensitive, empty name, bad regex, from_dict |
| TestBLEConfig | 2 | from_dict with all fields, defaults |
| TestStubScanner | 3 | Empty scan, add advertisement, clear |
| TestBLEBridgeLoad | 3 | Valid config, missing file, corrupt file |
| TestBLEBridgeMatching | 3 | First match, no match, empty name |
| TestBLEBridgeDecode | 3 | Manufacturer data, service data, missing data |
| TestBLEBridgeProcess | 5 | Register new device, update state, callback, skip unmatched, no re-register |
| TestBLEBridgePruning | 2 | Prune stale device, nothing stale |
| TestBLEBridgeLifecycle | 2 | Start/stop, scan loop processes |
| TestBLEBridgeQueries | 2 | is_ble_device, list_devices |
| TestDataTypeMapping | 3 | float32, int types, unknown default |
| TestChannelBLEIntegration | 3 | Disabled by default, enabled, pipeline recording |

## Edge Cases Covered

- **Bad regex in profile**: Gracefully returns no match
- **Empty device name**: Returns no match (prevents wildcard accidents)
- **Missing advertisement data**: Returns empty state (no crash)
- **Too-short byte payload**: decode_value returns None
- **Unknown data type**: Returns None
- **Corrupt config file**: Loads empty config, returns 0 profiles
- **Missing config file**: Same graceful fallback
- **Duplicate advertisements**: Device registered once, state updated every time
- **Stale device pruning**: Correctly marks offline, preserves fresh devices
- **MagicMock safety**: String config field uses `or ""` pattern

## Test Execution

```
$ python -m pytest tests/test_ble.py -v
50 passed in 1.39s

$ python -m pytest tests/
894 passed in 16.08s
```

# f21 BLE Mesh Support — Design Log

**Task**: 4.5 BLE mesh support for battery-powered sensors  
**Date**: 2026-02-26  
**Status**: In Progress  

---

## Architect/Reviewer Discussion

### Problem Statement
Battery-powered BLE sensors (Xiaomi, Govee, SwitchBot, etc.) broadcast readings
via BLE advertisements. The Hub needs to:
1. Passively scan for BLE advertisements
2. Decode manufacturer-specific data using configurable profiles
3. Register BLE devices in the standard device registry
4. Feed sensor readings into the sensor data pipeline
5. Track device presence (online/offline via advertisement freshness)

### Design: BLE Adapter Pattern

**[Architect]** Following the same pattern as IndustrialBridge (task 4.1):
- Abstract `BLEScanner` base with `StubScanner` fallback
- Optional `bleak` dependency for real BLE hardware
- External JSON config for device profiles (advertisement decoders)
- Periodic scan loop with configurable interval
- Registry integration + pipeline auto-recording via state update callback

**[Reviewer]** Concerns:
1. **Battery-powered devices**: They advertise infrequently (1-60s). Scan window
   must be long enough to catch advertisements.
2. **Security**: BLE advertisements are unencrypted by default. The profile config
   should note this.
3. **Resource usage**: Continuous BLE scanning uses CPU/radio. Configurable scan
   interval is good.
4. **BLE Mesh vs BLE advertising**: True BLE Mesh (SIG Mesh) is complex. For
   battery sensors, passive scanning is sufficient and much simpler.

**Consensus**: Implement passive advertisement scanning with configurable profiles.
No BLE Mesh (SIG Mesh) protocol — just standard BLE advertisements. Optional
`bleak` dependency with stub fallback for testing.

---

## Architecture

```
BLEDeviceProfile         — Decoder config for one device type
├── name_pattern         — regex to match device name in advertisements
├── capabilities         — list of capability definitions with byte-level decode rules
└── from_dict()

BLEConfig                — Top-level BLE configuration
├── scan_interval        — seconds between scans (default 30)
├── scan_duration        — seconds per scan window (default 10)
├── device_timeout       — seconds before a device is marked offline (default 120)
├── profiles             — list of BLEDeviceProfile
└── from_dict()

BLEScanner (ABC)         — Abstract BLE scanner
├── scan(duration)       — returns list of (address, name, rssi, manufacturer_data, service_data)
└── stop()

BleakScanner(BLEScanner) — Real BLE scanner using bleak
StubScanner(BLEScanner)  — Testing stub that returns configured dummy data

BLEBridge                — Orchestrator
├── __init__(config_path, registry, on_state_update)
├── load()               — parse JSON config
├── start()              — begin scan loop
├── stop()               — cancel loop
├── _scan_loop()         — periodic scanning
├── _process_advertisements(results)
├── _match_profile(name) — find matching profile
├── _decode_capability(raw_data, cap_def) → value
├── is_ble_device(node_id) — check if device is managed by this bridge
└── list_devices()       — return BLE device list
```

## Data Model

```python
@dataclass
class BLECapabilityDef:
    name: str           # e.g. "temperature"
    data_source: str    # "manufacturer" or "service"
    company_id: int     # BLE company ID (for manufacturer data), 0 for service data
    service_uuid: str   # for service data, empty for manufacturer
    byte_offset: int    # starting byte in the data payload
    byte_length: int    # number of bytes
    data_type: str      # "int16", "uint16", "uint8", "float32"
    scale: float        # multiply raw value by this (e.g., 0.01 for centidegrees)
    unit: str           # "°C", "%", "V", etc.
    cap_type: str       # CapabilityType value (sensor/actuator/property)

@dataclass
class BLEDeviceProfile:
    name: str                       # profile name
    name_pattern: str               # regex to match BLE device name
    device_type: str                # device registry type
    capabilities: list[BLECapabilityDef]

@dataclass
class BLEConfig:
    scan_interval: int = 30
    scan_duration: int = 10
    device_timeout: int = 120
    profiles: list[BLEDeviceProfile]
```

## Config File Format

**ble_config.json**:
```json
{
  "scan_interval": 30,
  "scan_duration": 10,
  "device_timeout": 120,
  "profiles": [
    {
      "name": "Xiaomi Thermometer",
      "name_pattern": "^LYWSD.*",
      "device_type": "temperature_humidity_sensor",
      "capabilities": [
        {
          "name": "temperature",
          "data_source": "service",
          "service_uuid": "0000181a-0000-1000-8000-00805f9b34fb",
          "byte_offset": 0,
          "byte_length": 2,
          "data_type": "int16",
          "scale": 0.01,
          "unit": "°C",
          "cap_type": "sensor"
        },
        {
          "name": "humidity",
          "data_source": "service",
          "service_uuid": "0000181a-0000-1000-8000-00805f9b34fb",
          "byte_offset": 2,
          "byte_length": 2,
          "data_type": "uint16",
          "scale": 0.01,
          "unit": "%",
          "cap_type": "sensor"
        }
      ]
    }
  ]
}
```

## Integration Points

### Schema (schema.py)
```python
ble_config_path: str = ""    # Path to BLE config JSON. Empty = disabled.
```

### Channel (channel.py)
- Import `BLEBridge`
- Init when `ble_config_path` is non-empty
- Start/stop BLE bridge in start()/stop()
- State update callback feeds registry + pipeline

## Implementation Plan

| File | Action | Purpose |
|------|--------|---------|
| `nanobot/mesh/ble.py` | Create | BLE bridge module |
| `nanobot/config/schema.py` | Modify | Append `ble_config_path` field |
| `nanobot/mesh/channel.py` | Modify | Init/start/stop BLE bridge, wire state callback |
| `tests/test_ble.py` | Create | Tests for BLE bridge |
| `docs/01_features/f21_ble/` | Create | Design, implementation, test docs |
| `docs/configuration.md` | Modify | Add BLE config fields + example |
| `docs/architecture.md` | Modify | Add ble.py to mesh components |
| `docs/00_system/Project_Roadmap.md` | Modify | Mark 4.5 done |

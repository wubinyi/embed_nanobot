# f18 — PLC/Industrial Device Integration: Design Log

**Task**: 4.1 — PLC/industrial device integration  
**Priority**: P1 | **Complexity**: L  
**Dependencies**: Registry (2.1), Commands (2.2)  
**Date**: 2026-02-26

## 1. Problem Statement

The mesh network currently supports ESP32-style devices that run our custom mesh protocol. Industrial environments use PLCs (Programmable Logic Controllers) that communicate via standard industrial protocols: Modbus TCP/RTU, OPC-UA, EtherNet/IP, etc.

We need a protocol adapter layer that bridges industrial devices into the nanobot ecosystem, making them appear as regular devices in the registry with standard capabilities.

## 2. Architect/Reviewer Debate

### [Architect] Proposal
- New module `nanobot/mesh/industrial.py` with:
  - `IndustrialProtocol` abstract base class defining the adapter interface
  - `ModbusTCPAdapter` concrete implementation for Modbus TCP
  - `PLCDeviceConfig` dataclass for declaring PLC points → device mappings
  - `IndustrialBridge` orchestrator that manages adapters, polling, and command translation
- Configuration-driven: PLC points defined in a JSON file (like device_registry.json pattern)
- Polling loop reads sensor values on interval, pushes to registry as state updates
- Command dispatch translates `DeviceCommand` → protocol write operations

### [Reviewer] Challenges
1. **Dependency management**: pymodbus is a heavy dependency. Make it optional with graceful degradation.
   - *Resolution*: Optional import with `HAS_PYMODBUS = False` fallback, like we do with `cryptography`.
2. **Connection resilience**: Industrial networks can be noisy. Modbus connections drop.
   - *Resolution*: Auto-reconnect with exponential backoff using existing `RetryPolicy`.
3. **Data type mapping**: Modbus registers are 16-bit. How to handle 32-bit floats, signed ints?
   - *Resolution*: Config declares data interpretation (uint16, int16, float32, bool). Adapter handles struct pack/unpack.
4. **Polling frequency**: Too fast = PLC overload. Too slow = stale data.
   - *Resolution*: Per-device configurable poll interval (default 5s).
5. **Thread safety**: pymodbus is sync. Must not block the event loop.
   - *Resolution*: Use `asyncio.to_thread()` for sync Modbus calls.

### Consensus
Build a clean protocol adapter framework. Ship with Modbus TCP adapter (most common industrial protocol). Keep pymodbus optional. Use config-driven point mapping. Integrate with existing registry + command infrastructure.

## 3. Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/industrial.py` | Protocol adapter framework + Modbus TCP + IndustrialBridge |
| `tests/test_industrial.py` | Tests for all industrial components |
| `docs/01_features/f18_plc/01_Design_Log.md` | This file |
| `docs/01_features/f18_plc/02_Dev_Implementation.md` | Implementation notes |
| `docs/01_features/f18_plc/03_Test_Report.md` | Test results |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Add `industrial_config_path` field to MeshConfig |
| `nanobot/mesh/channel.py` | Import IndustrialBridge, init from config, start/stop in lifecycle |
| `docs/configuration.md` | Document `industrialConfigPath` field |

### Data Flow

```
PLC (Modbus TCP)
    │
    │ poll_interval (5s default)
    ▼
IndustrialBridge
    │
    ├── ModbusTCPAdapter.read_points() → state dict
    │       │
    │       ▼
    │   registry.update_state(node_id, state)
    │       │
    │       ▼
    │   AutomationEngine.evaluate() (via STATE_REPORT path)
    │
    └── on DeviceCommand for PLC device:
            │
            ▼
        ModbusTCPAdapter.write_point(capability, value)
```

### PLC Configuration Format (industrial_config.json)

```json
{
  "bridges": [
    {
      "bridge_id": "plc-modbus-01",
      "protocol": "modbus_tcp",
      "host": "192.168.1.50",
      "port": 502,
      "unit_id": 1,
      "poll_interval": 5.0,
      "devices": [
        {
          "node_id": "plc-temp-01",
          "device_type": "plc_sensor",
          "name": "Assembly Line Temp",
          "points": [
            {
              "capability": "temperature",
              "cap_type": "sensor",
              "register_type": "holding",
              "address": 100,
              "data_type": "float32",
              "unit": "°C",
              "scale": 0.1
            },
            {
              "capability": "fan_speed",
              "cap_type": "actuator",
              "register_type": "holding",
              "address": 200,
              "data_type": "uint16",
              "unit": "RPM",
              "range": [0, 3000]
            }
          ]
        }
      ]
    }
  ]
}
```

### Upstream Impact
- Zero — new isolated module, append-only config field
- No conflict surface increase (only new file + 1 field in schema.py + minor channel wiring)

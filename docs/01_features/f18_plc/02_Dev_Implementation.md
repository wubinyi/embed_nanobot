# f18 — PLC/Industrial Device Integration: Development Implementation

**Task**: 4.1 — PLC/industrial device integration  
**Branch**: `copilot/plc-integration`  
**Date**: 2026-02-26  

## Summary

Implemented a protocol adapter framework for integrating PLC/industrial devices into the nanobot mesh ecosystem. PLCs communicate via industrial protocols (Modbus TCP, OPC-UA) and their registers are mapped to standard `DeviceCapability` entries in the shared registry, making them fully compatible with automation rules, the dashboard, LLM device control, and all existing mesh features.

## Architecture

```
industrial_config.json
    │
    ▼
IndustrialBridge.load()
    ├── BridgeConfig[0] → ModbusTCPAdapter(host, port)
    │       ├── PLCDeviceConfig → registry.register_device()
    │       └── poll_loop() → adapter.read_point() → registry.update_state()
    └── BridgeConfig[1] → ...

DeviceCommand for PLC device:
    channel.execute_industrial_command() → bridge.execute_command()
        → adapter.write_point()
```

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/industrial.py` | ~430 | Protocol adapter framework + Modbus TCP adapter + IndustrialBridge orchestrator |
| `tests/test_industrial.py` | ~490 | 54 tests across 14 test classes |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Added `industrial_config_path: str = ""` to MeshConfig |
| `nanobot/mesh/channel.py` | Import IndustrialBridge, init from config, start/stop in lifecycle, add `execute_industrial_command()` and `_on_industrial_state_update()` callback |
| `docs/configuration.md` | Document `industrialConfigPath` field + setup guide |

## Implementation Details

### Protocol Adapter Framework

- **`IndustrialProtocol`** (ABC): `connect()`, `disconnect()`, `read_point()`, `write_point()`, `connected` property
- **`ModbusTCPAdapter`**: Concrete implementation for Modbus TCP using `pymodbus >= 3.0` (optional dependency)
- **`StubAdapter`**: No-op adapter when protocol library unavailable — allows config parsing without installation
- **Protocol registry**: `register_protocol(name, cls)` / `get_protocol_adapter(name)` for extensibility

### Data Type Handling

| PLC Type | Registers | Python Type | Registry DataType |
|----------|-----------|-------------|-------------------|
| `bool` | 1 (coil) | `bool` | BOOL |
| `uint16` | 1 | `int` | INT |
| `int16` | 1 | `int` | INT |
| `uint32` | 2 | `int` | INT |
| `int32` | 2 | `int` | INT |
| `float32` | 2 | `float` | FLOAT |
| `float64` | 4 | `float` | FLOAT |

- `decode_registers()` / `encode_value()`: Big-endian struct pack/unpack for multi-register types
- `scale` config: multiply raw value on read, divide on write (e.g., `scale: 0.1` converts register 225 → 22.5°C)

### IndustrialBridge Orchestrator

- **Config-driven**: JSON file with `bridges[]` array, each containing host/port/protocol/devices
- **Lifecycle**: `load()` → `start()` (connect + register + poll) → `stop()` (cancel tasks + disconnect)
- **Polling**: Per-bridge `asyncio.Task` with configurable interval (default 5s). Auto-reconnect on disconnect.
- **Command dispatch**: `execute_command(node_id, capability, value)` routes to correct adapter
- **Registry integration**: Devices auto-registered with full capabilities on bridge start. State updated on every poll.
- **Monitoring**: `list_bridges()` returns connection status for dashboard integration

### Channel Integration

- `industrial_config_path` config field controls creation (empty = disabled)
- Bridge started after dashboard (non-critical), stopped with error isolation
- `_on_industrial_state_update()` callback evaluates automation rules, routes commands to industrial bridge or mesh transport as appropriate
- `execute_industrial_command()` convenience method for direct PLC writes

## Deviations from Design

- None — design was executed as planned.

## Documentation Freshness Check

- architecture.md: OK — industrial.py is part of mesh module, no new top-level module
- configuration.md: Updated — added `industrialConfigPath` field + PLC setup guide
- customization.md: OK — protocol adapter extension follows existing patterns
- PRD.md: OK — will update status table when Phase 4 reviewed
- agent.md: OK — no upstream convention changes

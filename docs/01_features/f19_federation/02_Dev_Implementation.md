# f19 — Multi-Hub Federation: Dev Implementation

**Task**: 4.2 — Multi-Hub federation (hub-to-hub mesh)  
**Date**: 2026-02-26  
**Branch**: `copilot/hub-federation`

---

## Architecture

```
Hub A                                     Hub B
┌──────────────┐    TCP (persistent)    ┌──────────────┐
│ FederationMgr│◄──────────────────────►│ FederationMgr│
│  ├ HubLink B │    HELLO/SYNC/CMD/     │  ├ HubLink A │
│  │           │    STATE/PING/PONG     │  │           │
│  ├ _remote   │                        │  ├ _remote   │
│  │  devices  │                        │  │  devices  │
│  └ _device   │                        │  └ _device   │
│    hub_map   │                        │    hub_map   │
├──────────────┤                        ├──────────────┤
│ DeviceRegistry (local devices)        │ DeviceRegistry│
│ AutomationEngine                      │ Automation    │
│ IndustrialBridge                      │               │
│ MeshTransport (device protocol)       │ MeshTransport │
└──────────────┘                        └──────────────┘
```

## New Module: `nanobot/mesh/federation.py` (~500 LOC)

### Config Dataclasses

- **`FederationPeerConfig`**: `hub_id`, `host`, `port` (default 18800), `from_dict()`
- **`FederationConfig`**: `peers: list[FederationPeerConfig]`, `sync_interval` (default 30s), `from_dict()`

### `HubLink` — Persistent TCP Connection

- Manages a single bidirectional TCP connection to a peer hub
- On connect: sends `FEDERATION_HELLO` to identify
- Background `_receive_loop()`: reads envelopes, dispatches to handlers
- Background `_ping_loop()`: sends `FEDERATION_PING` every 15s
- Auto-reconnect with exponential backoff (2s base, 60s max, 10s connect timeout)
- `send(env)` returns False if disconnected or on write error

### `FederationManager` — Orchestrator

- `load()`: parse JSON config, return peer count
- `start()`: create HubLinks for all peers, start sync loop
- `stop()`: cancel sync, cancel pending commands, stop all links
- `_sync_loop()`: every `sync_interval` seconds, broadcast our device list
- `_broadcast_registry_sync()`: serialize local devices, send to all connected peers
- `_handle_message()`: dispatch by type (HELLO, SYNC, COMMAND, RESPONSE, STATE, PING, PONG)
- `forward_command()`: send FEDERATION_COMMAND with future-based response wait (timeout 10s)
- `broadcast_state_update()`: push state change to all connected peers
- `set_local_command_handler()`: wire up command execution for forwarded commands
- Queries: `is_remote_device()`, `get_device_hub()`, `list_remote_devices()`, `get_all_federated_devices()`, `list_hubs()`

## Protocol Messages (7 new MsgType entries)

| Type | Direction | Payload |
|------|-----------|---------|
| `FEDERATION_HELLO` | A→B | `{hub_id}` — initial handshake |
| `FEDERATION_SYNC` | A→B | `{hub_id, devices:[{node_id, device_type, name, online, state, capabilities}]}` |
| `FEDERATION_COMMAND` | A→B | `{target_node, capability, value}` — forward command |
| `FEDERATION_RESPONSE` | B→A | `{target_node, capability, success, value, error}` — command result |
| `FEDERATION_STATE` | A→B | `{hub_id, node_id, state}` — device state push |
| `FEDERATION_PING` | A→B | empty — keepalive |
| `FEDERATION_PONG` | B→A | empty — keepalive response |

## Config Changes

- `MeshConfig.federation_config_path: str = ""` — path to federation.json

## Channel Integration

- **Init**: `FederationManager` created when `federation_config_path` non-empty; `set_local_command_handler()` wired to `_execute_local_command()`
- **Start**: `federation.start()` after industrial bridge (error-isolated)
- **Stop**: `federation.stop()` after industrial bridge (error-isolated)
- **State propagation**: `_handle_state_report()` broadcasts to federation after automation
- **Command routing**: `_on_federation_state_update()` routes automation commands to industrial, federation, or mesh transport as appropriate
- **Convenience**: `forward_to_federation()` delegates to federation manager

## Deviations from Design

None — implementation follows the design log exactly.

### Documentation Freshness Check
- architecture.md: Updated — added federation.py to mesh component list
- configuration.md: Updated — added federationConfigPath field + example
- customization.md: OK — no new extension patterns
- PRD.md: OK — task 4.2 still listed (to be marked done in roadmap)
- agent.md: OK — no upstream convention changes

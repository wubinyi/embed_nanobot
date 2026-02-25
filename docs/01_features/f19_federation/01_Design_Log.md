# f19 — Multi-Hub Federation: Design Log

**Task**: 4.2 — Multi-Hub federation (hub-to-hub mesh)  
**Priority**: P1 | **Complexity**: XL  
**Dependencies**: Mesh (1.3), mTLS (3.1), Registry (2.1), Commands (2.2)

---

## Problem Statement

Current mesh architecture is **LAN-only** — all devices and the hub exist on a single subnet discovered via UDP broadcast. Smart factory and multi-site deployments need hubs in different locations (floors, buildings, cities) to share device visibility and forward commands across boundaries.

## Design Goals

1. **Cross-subnet device visibility**: Hub A's devices visible to Hub B (and vice versa)
2. **Cross-hub command forwarding**: Commands from Hub A to devices on Hub B transparently routed
3. **Cross-hub state propagation**: State changes on one hub propagated to federated peers
4. **Cross-hub automation**: Automation rules can reference devices on remote hubs
5. **Fault tolerance**: Hub link failure degrades gracefully (remote devices go offline)
6. **Security**: Hub-to-hub connections via existing mTLS or PSK auth
7. **Zero changes to device protocol**: Devices don't know about federation — hub handles routing

## Architecture

### Architect/Reviewer Debate

**[Architect]**: Two options considered:

**Option A — Virtual peers in discovery**: Inject remote hub addresses into UDPDiscovery as "virtual peers". Reuse existing transport for all messaging. Add federation-specific message types.
- Pro: Minimal new code, reuses full transport pipeline (auth, encryption, TLS)
- Con: Mixes device-level and hub-level connections; hub connections need persistence and retry semantics different from device TCP

**Option B — Separate federation module**: FederationManager with its own persistent TCP connections to peer hubs. Dedicated wire protocol layered on read_envelope/write_envelope.
- Pro: Clean separation, federation-specific logic (sync, forward, heartbeat) isolated
- Con: Some TCP code duplication

**[Reviewer]**: Option B is better. Hub-to-hub connections are fundamentally different from device connections:
1. They should be **persistent** (not connect-per-message like current transport)
2. They need **bidirectional** communication on a single connection
3. They need **reconnection** with exponential backoff
4. Security considerations differ (hub certificates vs device certificates)

Mixing these into UDPDiscovery/MeshTransport would complicate both.

**[Architect]**: Agreed. Option B. We'll reuse `read_envelope`/`write_envelope` from protocol.py for the wire format but manage connections independently.

### Design

```
┌─────────────────────────────────────────────────────────┐
│  Hub A (hub-factory-1)                                  │
│                                                         │
│  ┌───────────────┐       ┌──────────────────────┐      │
│  │ MeshChannel   │──────→│ FederationManager    │      │
│  │               │       │  ├─ HubLink(hub-B)   │──────┤──→ TCP to Hub B
│  │  ┌──────────┐ │       │  ├─ HubLink(hub-C)   │──────┤──→ TCP to Hub C
│  │  │ Registry │◄├───────│  ├─ _remote_devices   │      │
│  │  │ Automati │◄├───────│  └─ _sync_loop()      │      │
│  │  └──────────┘ │       └──────────────────────┘      │
│  └───────────────┘                                      │
└─────────────────────────────────────────────────────────┘
```

**Key components**:

1. **FederationPeerConfig** — dataclass: `hub_id`, `host`, `port`
2. **FederationConfig** — dataclass: `peers[]`, `sync_interval` (default 30s), `from_dict()`
3. **HubLink** — persistent bidirectional TCP connection to a single peer hub:
   - `connect()` / `disconnect()` with auto-reconnect
   - `send(msg_dict)` — sends length-prefixed JSON message
   - `_receive_loop()` — background task reading inbound messages
   - Connection health with heartbeat
4. **FederationManager** — orchestrates all hub-to-hub communication:
   - `load(config_path)` — parse federation JSON config
   - `start()` / `stop()` — lifecycle
   - `_sync_loop()` — periodic registry sync to all peers
   - `forward_command(node_id, capability, value)` — route command to correct hub
   - `is_remote_device(node_id)` — check if device lives on a remote hub
   - `get_device_hub(node_id)` — which hub owns the device
   - `list_remote_devices()` — all remote devices grouped by hub

### Wire Protocol (hub-to-hub)

Uses existing `read_envelope`/`write_envelope` for framing, with new federation message types:

```
FEDERATION_HELLO     — initial handshake (hub_id, capabilities)
FEDERATION_SYNC      — registry snapshot (devices list)
FEDERATION_COMMAND   — forward a command to a remote device
FEDERATION_RESPONSE  — response from forwarded command
FEDERATION_STATE     — push state change from device owner hub
FEDERATION_PING      — keepalive
FEDERATION_PONG      — keepalive response
```

### Config

**config.json** (appended to MeshConfig):
```json
"federationConfigPath": "/path/to/federation.json"
```

**federation.json**:
```json
{
  "peers": [
    {"hub_id": "hub-factory-2", "host": "192.168.2.100", "port": 18800},
    {"hub_id": "hub-home", "host": "10.0.0.5", "port": 18800}
  ],
  "sync_interval": 30.0
}
```

### Channel Integration

- **Init**: Create FederationManager if `federation_config_path` non-empty
- **Start**: Start federation after transport (non-critical, error-isolated)
- **Stop**: Stop federation before transport
- **Command routing**: Check federation first before local transport
- **State updates**: Push state changes to federated peers
- **Automation**: Remote device state changes trigger local automation rules

## File Plan

### New Files
| File | Purpose |
|------|---------|
| `nanobot/mesh/federation.py` | FederationManager, HubLink, config dataclasses |
| `tests/test_federation.py` | Unit tests |
| `docs/01_features/f19_federation/` | Design, implementation, test docs |

### Modified Files
| File | Change |
|------|--------|
| `nanobot/config/schema.py` | +1 field: `federation_config_path` |
| `nanobot/mesh/channel.py` | Federation init/start/stop, command routing, state push |
| `nanobot/mesh/protocol.py` | +7 MsgType entries for federation |
| `docs/configuration.md` | +`federationConfigPath` field + example |
| `docs/architecture.md` | +federation component description |

### Test Plan
- HubLink: connect, disconnect, reconnect, send/receive, connection loss
- FederationManager: load config, start/stop lifecycle, registry sync, command forward, device lookup
- Channel integration: federation wiring, command routing through federation

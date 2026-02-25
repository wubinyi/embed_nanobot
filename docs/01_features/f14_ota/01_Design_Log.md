# f14: OTA Firmware Update Protocol — Design Log

**Task**: 3.3 — OTA firmware update protocol  
**Branch**: `copilot/ota-firmware`  
**Date**: 2026-02-25  

---

## Motivation

The Hub manages ESP32/embedded devices over the mesh. Devices need firmware updates without physical access. The Hub must be able to:
1. Store firmware images (binaries) for different device types
2. Push firmware to specific devices over the existing mesh transport (TCP + TLS)
3. Track update progress per device
4. Verify firmware integrity before and after transfer (SHA-256)
5. Support resumable transfers (chunked delivery)

## Architecture

### Overview

OTA is **Hub-initiated** — the Hub pushes firmware to devices. This matches our mesh model (Hub is the authority, devices are clients). The protocol runs over the existing TCP mesh transport using new message types.

### Protocol Flow

```
Hub                                       Device
 │                                          │
 │  OTA_OFFER {version, size, sha256}       │
 │─────────────────────────────────────────>│
 │                                          │
 │  OTA_ACCEPT / OTA_REJECT                 │
 │<─────────────────────────────────────────│
 │                                          │
 │  OTA_CHUNK {seq, data_b64, total}        │
 │─────────────────────────────────────────>│
 │                                          │ (repeat)
 │  OTA_CHUNK_ACK {seq}                     │
 │<─────────────────────────────────────────│
 │                                          │ (repeat)
 │  ... all chunks sent ...                 │
 │                                          │
 │  OTA_VERIFY {sha256}                     │
 │<─────────────────────────────────────────│
 │                                          │
 │  OTA_COMPLETE / OTA_ABORT                │
 │─────────────────────────────────────────>│
```

### Message Types

New `MsgType` enum entries:

| Type | Direction | Payload |
|------|-----------|---------|
| `OTA_OFFER` | Hub → Device | `{firmware_id, version, size, sha256, device_type, chunk_size}` |
| `OTA_ACCEPT` | Device → Hub | `{firmware_id}` |
| `OTA_REJECT` | Device → Hub | `{firmware_id, reason}` |
| `OTA_CHUNK` | Hub → Device | `{firmware_id, seq, total_chunks, data}` (base64) |
| `OTA_CHUNK_ACK` | Device → Hub | `{firmware_id, seq}` |
| `OTA_VERIFY` | Device → Hub | `{firmware_id, sha256}` (device's computed hash) |
| `OTA_COMPLETE` | Hub → Device | `{firmware_id}` (apply update) |
| `OTA_ABORT` | Either → Other | `{firmware_id, reason}` |

### Hub-Side Components

#### FirmwareManager (`nanobot/mesh/ota.py`)
- Manages firmware image store (directory-based, one file per firmware)
- Metadata: `{firmware_id, version, device_type, size, sha256, added_date}`
- Stores metadata in `firmware_manifest.json`
- Binary files stored in `firmware_dir/` (named by firmware_id)
- Operations: `add_firmware()`, `remove_firmware()`, `list_firmware()`, `get_firmware_info()`

#### OTASession (internal to ota.py)
- Tracks one active OTA transfer to one device
- State machine: `OFFERED` → `ACCEPTED` → `TRANSFERRING` → `VERIFYING` → `COMPLETE`
- Tracks: current chunk seq, acked chunks, started_at, errors
- Timeout per phase

#### OTAManager (internal to ota.py)
- Orchestrates OTA updates across devices
- Can run one update per device concurrently (not one global)
- `start_update(node_id, firmware_id)` → creates session, sends OTA_OFFER
- `_handle_ota_message(env)` → processes device responses, drives state machine
- Progress callback for UI/logging

### Channel Integration

`MeshChannel` gets:
- `ota_manager: OTAManager | None` attribute (created if firmware_dir configured)
- `start_ota_update(node_id, firmware_id)` convenience method
- OTA message routing in `_on_mesh_message()`

### Chunk Size

Default 4096 bytes (base64 → ~5.5KB per envelope). Small enough for ESP32 RAM. Configurable per firmware offer.

### Security Considerations

- **Integrity**: SHA-256 hash of entire firmware verified both before and after transfer
- **Authentication**: OTA messages travel over TLS (mTLS) if enabled, or HMAC-signed
- **Authorization**: Only the Hub can send OTA_OFFER/OTA_CHUNK (enforced by message type handling)
- **No code signing**: Firmware is not cryptographically signed by a vendor. This is a limitation — future task could add Ed25519 firmware signatures.

## Reviewer Challenge

**Q: What if a chunk is lost or the device disconnects mid-transfer?**
A: The Hub tracks which chunks have been ACK'd. On disconnect, the session enters a timeout state. The Hub can re-send un-ACK'd chunks (resend from `last_acked_seq + 1`). The session can be resumed or aborted.

**Q: What if the device runs out of storage?**
A: The OTA_OFFER includes firmware `size`. The device should check available storage before sending OTA_ACCEPT. If it can't fit, it sends OTA_REJECT with reason "insufficient_storage".

**Q: Memory pressure on Hub with large firmware + many devices?**
A: Firmware is read from disk chunk-by-chunk, not loaded into memory. Each session only holds metadata (~200 bytes). Concurrent updates to different devices are fine.

**Q: Should OTA be fire-and-forget or synchronous?**
A: It's async with progress tracking. `start_update()` returns immediately with a session ID. Progress is tracked via the session state machine and available via `get_update_status()`.

## Key Decisions

1. **Hub-initiated push**: Hub decides when to update, not device poll-based
2. **Chunked transfer**: 4KB default chunks, base64-encoded in JSON payload
3. **Per-device concurrency**: Multiple devices can update simultaneously
4. **Firmware store**: Directory-based with JSON manifest
5. **No code signing**: Out of scope for now (firmware integrity via SHA-256 only)
6. **Resume support**: Track ACK'd chunks, can resend from last ACK point

## Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/ota.py` | FirmwareManager, OTASession, OTAManager |
| `tests/test_ota.py` | Tests for OTA protocol |
| `docs/01_features/f14_ota/01_Design_Log.md` | This file |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Add OTA_* message types to MsgType enum |
| `nanobot/mesh/channel.py` | Add OTAManager creation, message routing, convenience methods |
| `nanobot/config/schema.py` | Add `firmware_dir` field to MeshConfig |

### Config Additions

```python
# Appended to MeshConfig:
firmware_dir: str = ""  # Directory for firmware images. Empty = OTA disabled.
ota_chunk_size: int = 4096  # Bytes per chunk
ota_chunk_timeout: int = 30  # Seconds to wait for chunk ACK
```

### No New Dependencies
Uses only stdlib (hashlib, base64, json, pathlib).

# f14: OTA Firmware Update Protocol — Dev Implementation

**Task**: 3.3 — OTA firmware update protocol  
**Branch**: `copilot/ota-firmware`  
**Date**: 2026-02-25  

---

## Summary

Implemented a chunked, Hub-initiated OTA firmware update protocol for mesh devices. Firmware is stored locally, transferred in base64-encoded chunks over the existing TCP mesh transport (with TLS if enabled), and verified end-to-end via SHA-256.

## New Files

### `nanobot/mesh/ota.py` (~410 LOC)

Three main components:

**FirmwareStore** — Directory-based firmware image storage with JSON manifest.
- `add_firmware(firmware_id, version, device_type, data)` → computes SHA-256, writes binary, updates manifest
- `remove_firmware(firmware_id)` → deletes binary + manifest entry
- `read_chunk(firmware_id, offset, size)` → reads chunk from disk (no full file in memory)
- `list_firmware()`, `get_firmware(firmware_id)`
- Persistence: `firmware_manifest.json` + `{firmware_id}.bin` files

**OTASession** — State machine for one active transfer:
- States: `OFFERED` → `TRANSFERRING` → `VERIFYING` → `COMPLETE` (or `FAILED`/`REJECTED`)
- Tracks: chunk progress, ACK watermark, timestamps, errors
- `progress` property: 0.0–1.0 fraction based on ACK'd chunks
- `to_status()`: summary dict for external consumers

**OTAManager** — Orchestrates concurrent updates across devices:
- `start_update(node_id, firmware_id)` → sends `OTA_OFFER`, creates session
- `abort_update(node_id, reason)` → sends `OTA_ABORT`, marks session failed
- `handle_ota_message(env)` → processes device responses (ACCEPT/REJECT/CHUNK_ACK/VERIFY/ABORT)
- `on_progress(callback)` → register progress callbacks
- One session per device, multiple concurrent devices supported
- Chunks read from disk on demand (not buffered in memory)

### Protocol Messages

8 new `MsgType` entries in `protocol.py`:

| Message | Direction | Purpose |
|---------|-----------|---------|
| `OTA_OFFER` | Hub → Device | Propose firmware update (version, size, sha256, chunk_size) |
| `OTA_ACCEPT` | Device → Hub | Device accepts the offer |
| `OTA_REJECT` | Device → Hub | Device rejects (with reason) |
| `OTA_CHUNK` | Hub → Device | One chunk (seq, base64 data, total_chunks) |
| `OTA_CHUNK_ACK` | Device → Hub | Acknowledge receipt of chunk seq |
| `OTA_VERIFY` | Device → Hub | Device's computed SHA-256 of reassembled firmware |
| `OTA_COMPLETE` | Hub → Device | Hash matches, apply update |
| `OTA_ABORT` | Either direction | Abort transfer (with reason) |

## Modified Files

### `nanobot/mesh/protocol.py`
- Added 8 OTA message types to `MsgType` enum (append-only)

### `nanobot/config/schema.py`
- 3 fields appended to `MeshConfig`:
  - `firmware_dir: str = ""` — firmware storage directory (empty = OTA disabled)
  - `ota_chunk_size: int = 4096` — bytes per chunk
  - `ota_chunk_timeout: int = 30` — seconds to wait for chunk ACK

### `nanobot/mesh/channel.py`
- Import `FirmwareStore`, `OTAManager`, `OTASession` from `ota`
- `__init__`: Create `FirmwareStore` + `OTAManager` when `firmware_dir` is configured
- `_on_mesh_message()`: Route OTA message types (ACCEPT, REJECT, CHUNK_ACK, VERIFY, ABORT) to `ota.handle_ota_message()`
- New convenience methods: `start_ota_update()`, `abort_ota_update()`, `get_ota_status()`

## Key Design Decisions

1. **Hub-initiated push**: Hub decides when to update, not device poll
2. **Chunked transfer**: 4KB default, base64-encoded in JSON envelope payload
3. **Disk-streamed**: Firmware read chunk-by-chunk from disk, not loaded into memory
4. **Per-device concurrency**: Multiple devices can update simultaneously
5. **SHA-256 integrity**: Full file hash verified by device after reassembly
6. **No code signing**: Firmware integrity only (SHA-256), not authenticity. Future task could add Ed25519 signatures.

## Documentation Freshness Check
- architecture.md: OK — mesh module already documented, OTA is internal
- configuration.md: Updated — added firmware_dir, ota_chunk_size, ota_chunk_timeout fields
- customization.md: OK — no new extension points
- PRD.md: OK — DM-06 (OTA firmware update) addressed
- agent.md: OK — no upstream convention changes

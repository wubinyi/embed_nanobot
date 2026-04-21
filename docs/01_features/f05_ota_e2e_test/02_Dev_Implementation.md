# f05: End-to-End OTA WiFi Test — Dev Implementation

**Task**: 5.4.1  
**Branch**: `copilot/ota-e2e-test`  
**Date**: 2026-04-21  
**Status**: Complete  

---

## Files Created

### 1. `tests/test_ota_e2e.py` (52 tests)

Automated E2E simulation tests. No hardware or network required.

**Core components**:

#### `FakeESP32`
Simulates the MicroPython OTA handlers from `esp32/mesh_client/main.py`:

```python
class FakeESP32:
    def __init__(self, node_id, *, tamper_hash=False, anti_rollback_min=0, abort_after_seq=None)
    def handle(self, env: MeshEnvelope) -> list[MeshEnvelope]
```

Configurable failure modes:
- `tamper_hash=True` — sends wrong SHA-256 in `OTA_VERIFY`
- `anti_rollback_min=N` — rejects `OTA_OFFER` if `version_counter < N`
- `abort_after_seq=N` — device sends `OTA_ABORT` (reason: `low_battery`) on chunk N

After `OTA_COMPLETE` is received, `esp32.app_py_content` contains the
reassembled firmware bytes, verifiable against the original.

#### `drive_session(mgr, esp32, node_id, firmware_id)`
Wires `OTAManager` to `FakeESP32` via an in-memory `pending` list:

```python
async def drive_session(mgr, esp32, node_id, firmware_id, *, max_rounds=100_000) -> OTASession
```

Temporarily overrides `mgr._send` to capture outbound messages, routes them
through `FakeESP32.handle()`, and feeds responses back via
`mgr.handle_ota_message()`. Loops until `pending` is empty or `max_rounds`
is reached.

### 2. `esp32/tools/test_ota_wifi.py`

Manual hardware validation script for Radxa 5T. Usage:

```bash
# Basic run (generates test firmware, pushes to esp32-01)
python esp32/tools/test_ota_wifi.py

# With specific firmware and node
python esp32/tools/test_ota_wifi.py --firmware path/to/app.py --node-id esp32-01

# Dry run (verify setup only, no OTA push)
python esp32/tools/test_ota_wifi.py --dry-run

# Full options
python esp32/tools/test_ota_wifi.py --help
```

The script:
1. Starts `MeshChannel` with PSK auth  
2. Waits for the ESP32 to appear in the device registry  
3. Generates or loads a test firmware (Python source with version header)  
4. Stores it in `FirmwareStore` and calls `start_ota_update()`  
5. Monitors progress via `on_progress()` callbacks  
6. Pings the device post-reset to confirm reconnect  
7. Exits 0 (pass) or 1 (fail)

---

## Known Implementation Gap

**Hub OTA_OFFER missing `version_counter` and `firmware_hmac`**:

`OTAManager.start_update()` builds the `OTA_OFFER` payload without these fields:

```python
payload={
    "firmware_id": firmware.firmware_id,
    "version": firmware.version,
    "device_type": firmware.device_type,
    "size": firmware.size,
    "sha256": firmware.sha256,
    "chunk_size": cs,
    "total_chunks": session.total_chunks,
    # ← version_counter and firmware_hmac NOT sent
}
```

The ESP32 handles this gracefully:
- `version_counter = payload.get("version_counter", 0)` → anti-rollback passes
- `firmware_hmac = payload.get("firmware_hmac", "")` → HMAC skip (empty string)

This means the anti-rollback and HMAC features are **present on the ESP32 but
not exercisable without the hub sending the fields**. Tracked as TD-02 in the
design log.

---

## Documentation Freshness Check

- `architecture.md`: OK — no new modules added
- `configuration.md`: OK — no new config fields
- `customization.md`: OK — no new extension points
- `PRD.md`: OK — 5.4.1 was already in roadmap; update via roadmap update
- `agent.md`: OK — no upstream convention changes

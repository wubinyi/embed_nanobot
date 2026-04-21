# f05: End-to-End OTA WiFi Test — Design Log

**Task**: 5.4.1  
**Feature**: End-to-end OTA WiFi test on Radxa 5T  
**Branch**: `copilot/ota-e2e-test`  
**Date**: 2026-04-21  

---

## 1. Context & Scope

**Scope**: The OTA protocol (task 3.3) and boot-manager (task 5.2) are already
implemented on both sides. Task 5.4.1 is purely a testing task: write a
comprehensive automated test suite for the OTA WiFi flow, plus a live hardware
validation script.

**What already exists**:
| Component | File | Status |
|-----------|------|--------|
| Hub OTA manager | `nanobot/mesh/ota.py` | Done (990 lines) |
| Hub OTA channel integration | `nanobot/mesh/channel.py` | Done |
| ESP32 OTA handlers | `esp32/mesh_client/main.py` | Done |
| Unit tests (mock) | `tests/test_ota.py` | Done (49 tests) |

**Gap before this task**: All 49 existing OTA tests exercise each component in
isolation (unit-level). No test drives the full hub ↔ ESP32 *protocol hand-shake*
end-to-end. Edge cases like concurrent devices, retry-after-failure, and hash
mismatch were not covered.

---

## 2. Architecture Design

### [Architect] Design Proposal

#### Two deliverables

**Deliverable 1 — `tests/test_ota_e2e.py`**  
Automated pytest tests, no hardware required.  
Design: `FakeESP32` class mirrors `main.py` OTA handlers in Python, paired with
`drive_session()` which wires hub `OTAManager` to `FakeESP32` via an in-memory
message queue.

```
               pending: list[MeshEnvelope]
               ┌──────────────────────────┐
OTAManager     │  intercept_send(env)     │  FakeESP32
   .start_update() ──► OFFER ──────────────────► _on_offer()
   .handle_ota_message() ◄─ ACCEPT ◄────────────  → OTA_ACCEPT
   _on_accept() ──► CHUNK0 ─────────────────────► _on_chunk()
   _on_chunk_ack() ◄─ CHUNK_ACK0 ◄──────────────  → OTA_CHUNK_ACK
   ...                                              (all seqs)
   _on_verify() ◄─ OTA_VERIFY ◄────────────────  (final chunk → verify)
   → OTA_COMPLETE ──────────────────────────────► _on_complete()
                                                   → app_py_content set
```

**Deliverable 2 — `esp32/tools/test_ota_wifi.py`**  
Manual hardware validation script for Radxa 5T. Uses `nanobot` Python API
directly (no subprocess). Generates a minimal test firmware, stores it in
`FirmwareStore`, starts OTA, monitors progress events, and verifies ESP32
resets and reconnects.

#### `FakeESP32` design

Mirrors every OTA message handler from `main.py` one-to-one:

| Message received | main.py function | FakeESP32 method |
|------------------|-----------------|------------------|
| `OTA_OFFER` | `_handle_ota_offer()` | `_on_offer()` |
| `OTA_CHUNK` | `_handle_ota_chunk()` | `_on_chunk()` |
| `OTA_COMPLETE` | `_handle_ota_complete()` | `_on_complete()` |
| `OTA_ABORT` | `_handle_ota_abort()` | `_on_abort()` |

Configurable failure modes:
- `tamper_hash=True` → sends wrong SHA-256 in OTA_VERIFY
- `anti_rollback_min=N` → rejects OFFER if version_counter < N
- `abort_after_seq=N` → sends device-side OTA_ABORT on chunk N

### [Reviewer] Challenge & Gaps Identified

**Gap 1**: Hub `OTA_OFFER` does NOT include `version_counter` or `firmware_hmac`
fields expected by the ESP32 (see `_handle_ota_offer` in `main.py`). The ESP32
uses `payload.get("version_counter", 0)` and `payload.get("firmware_hmac", "")`,
so defaults are safe:
- `version_counter=0` → anti-rollback check passes (0 >= 0)
- `firmware_hmac=""` → HMAC verification skipped

**Decision**: Document this as a known limitation in the test report. Add a test
that explicitly covers this behavior (`test_offer_without_version_counter_accepted`).
Fixing the hub to send these fields is a follow-up task (not in scope for 5.4.1).

**Gap 2**: `check_timeouts()` in `ota.py` has a minor message clarity bug:
```python
session.state = UpdateState.FAILED
session.error = f"timeout in {session.state.value} state"  # always "failed"
```
The error message always says "timeout in failed state" regardless of which
phase timed out. The FAILED state transition is correct; only the message is
misleading. Tests check `"timeout" in session.error` rather than the state name,
making them robust against this. **Not fixed** (out of scope for 5.4.1; tracked
as tech debt below).

### Implementation Plan

| # | File | Action |
|---|------|--------|
| 1 | `tests/test_ota_e2e.py` | Create — 52 tests in 10 classes |
| 2 | `esp32/tools/test_ota_wifi.py` | Create — hardware validation script |
| 3 | `docs/01_features/f05_ota_e2e_test/01_Design_Log.md` | Create (this file) |
| 4 | `docs/01_features/f05_ota_e2e_test/02_Dev_Implementation.md` | Create |
| 5 | `docs/01_features/f05_ota_e2e_test/03_Test_Report.md` | Create |
| 6 | `docs/00_system/Project_Roadmap.md` | Mark 5.4.1 Done |

**No existing files modified** (no conflict surface increase).

---

## 3. Tech Debt Identified

| ID | Description | Priority | Location |
|----|-------------|----------|----------|
| TD-01 | `check_timeouts()` error message always says "failed state" | Low | `nanobot/mesh/ota.py:432` |
| TD-02 | Hub `OTA_OFFER` doesn't include `version_counter` / `firmware_hmac` | Medium | `nanobot/mesh/ota.py:start_update()` |
| TD-03 | No live hardware test of hash mismatch & abort scenarios | Low | Manual testing |

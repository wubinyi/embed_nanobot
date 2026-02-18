# f04: Device Enrollment Flow — Dev Implementation

**Task**: 1.10
**Date**: 2026-02-18
**Branch**: `copilot/device-enrollment`

---

## Implementation Summary

Implemented a PIN-based device enrollment protocol that allows new IoT devices
to securely obtain a PSK from the mesh Hub. The protocol uses HMAC-SHA256 PIN
proofs and PBKDF2-derived XOR encryption for secure PSK transfer on untrusted
LANs.

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/enrollment.py` | ~240 | `EnrollmentService` class, `PendingEnrollment` state, crypto helpers |
| `docs/01_features/f04_device_enrollment/01_Design_Log.md` | — | Architect/Reviewer design debate |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Added `ENROLL_REQUEST`, `ENROLL_RESPONSE` to `MsgType` enum |
| `nanobot/mesh/transport.py` | Added `enrollment_service` attribute, auth bypass for `ENROLL_REQUEST` in `_verify_inbound()` |
| `nanobot/mesh/channel.py` | Imports `EnrollmentService`, creates it in `__init__`, routes `ENROLL_REQUEST` in `_on_mesh_message()`, exposes `create_enrollment_pin()` / `cancel_enrollment_pin()` |
| `nanobot/config/schema.py` | Added 3 fields to `MeshConfig`: `enrollment_pin_length`, `enrollment_pin_timeout`, `enrollment_max_attempts` |
| `tests/test_mesh.py` | Added 35 new tests (7 test classes) |

## Key Design Decisions

### 1. PIN Proof (not raw PIN)
Device sends `HMAC-SHA256(key=pin, msg=node_id)` instead of the PIN itself.
This prevents passive sniffing from revealing the PIN.

### 2. PBKDF2 + XOR One-Time Pad
The PSK is encrypted with `XOR(psk, PBKDF2(pin, salt, 100K))`.
Since both the key and message are exactly 32 bytes, this is an information-
theoretically secure one-time pad. The PBKDF2 iterations make brute-forcing
the PIN expensive.

### 3. Transport-Level Auth Bypass
The `_verify_inbound()` method has a narrow exception: `ENROLL_REQUEST`
messages are allowed through ONLY when `enrollment_service.is_enrollment_active`
is True. This keeps the auth bypass minimal and time-bounded.

### 4. Single-Use PIN
After a successful enrollment, the PIN is marked `used=True` and cannot be
reused. A new `create_pin()` call is required for each device.

## Deviations from Plan

None. Implementation follows the Design Log exactly.

## Dependencies

- **Zero new dependencies** — uses only stdlib (`hashlib.pbkdf2_hmac`, `hmac`, `secrets`)
- Uses existing `KeyStore.add_device()` for PSK generation and storage

## Documentation Freshness Check
- architecture.md: Updated — added enrollment layer to mesh security section
- configuration.md: Updated — added enrollment config fields and enrollment section
- customization.md: OK — no changes needed (enrollment is internal to mesh)
- PRD.md: OK — updated status in roadmap
- agent.md: OK — no convention changes

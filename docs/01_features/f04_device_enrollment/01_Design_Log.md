# f04: Device Enrollment Flow (PIN-based Pairing) — Design Log

**Task**: 1.10
**Date**: 2026-02-18
**Status**: Design complete

---

## Problem Statement

Task 1.9 established HMAC-PSK authentication for the mesh transport, but new
devices have no automated way to obtain their PSK. Currently, an admin must
manually call `KeyStore.add_device()` and copy the PSK to the device — not
viable for real IoT deployments.

## Design

### Overview

A time-limited, single-use **PIN-based pairing protocol** that runs over the
existing mesh transport with a narrow authentication bypass for enrollment
messages only.

### Protocol Flow

```
  Hub Admin                  Hub                      New Device
  ─────────                  ───                      ──────────
  1. create_pin() ──────────►│                        │
     ◄── PIN "482917" ───────│                        │
  2. tell device the PIN     │                        │
                              │ ◄── ENROLL_REQUEST ────│
                              │     source: "esp32-k"  │
                              │     pin_proof: HMAC()  │
  3. Hub validates PIN        │                        │
     Hub generates PSK        │                        │
     Hub encrypts PSK         │                        │
                              │── ENROLL_RESPONSE ────►│
                              │    encrypted_psk       │
                              │    salt                │
  4. Device decrypts PSK      │                        │
     Stores it locally        │                        │
                              │ ◄── authenticated ─────│
                              │     messages now OK     │
```

### Security Measures

| Measure | Detail |
|---------|--------|
| Single-use PIN | Invalidated after successful enrollment |
| Auto-expiry | PIN expires after `enrollment_pin_timeout` seconds (default 300) |
| Rate limiting | `enrollment_max_attempts` failures (default 3) before PIN is locked |
| Key derivation | PBKDF2-HMAC-SHA256, 100K iterations, random 16-byte salt |
| PSK encryption | XOR one-time pad (32-byte PSK ⊕ 32-byte derived key = perfect secrecy) |
| PIN proof | `HMAC-SHA256(key=pin, msg=node_id)` — proves PIN knowledge without exposing it |
| Auth bypass | Transport only allows `ENROLL_REQUEST` through when enrollment is explicitly active |

### PIN Brute-Force Analysis

- 6-digit PIN = 10^6 possibilities
- 100K PBKDF2 iterations per attempt = 10^11 total iterations to exhaust
- At ~10K iterations/sec (Raspberry Pi 4): ~10^7 seconds = ~115 days
- Combined with 3-attempt limit: effectively impossible during 5-min window

### Message Formats

**ENROLL_REQUEST**:
```json
{
  "type": "enroll_request",
  "source": "esp32-kitchen",
  "target": "*",
  "payload": {
    "name": "Kitchen Sensor",
    "pin_proof": "<HMAC-SHA256 hex>"
  },
  "ts": 1700000000.0
}
```

**ENROLL_RESPONSE** (success):
```json
{
  "type": "enroll_response",
  "source": "nanobot-hub",
  "target": "esp32-kitchen",
  "payload": {
    "status": "ok",
    "encrypted_psk": "<hex>",
    "salt": "<hex>"
  },
  "ts": 1700000001.0
}
```

**ENROLL_RESPONSE** (failure):
```json
{
  "type": "enroll_response",
  "source": "nanobot-hub",
  "target": "esp32-kitchen",
  "payload": {
    "status": "error",
    "reason": "invalid_pin | expired | locked"
  }
}
```

## Architect–Reviewer Debate

**[Reviewer]**: The PIN is only 6 digits. Could a GPU attacker on the same LAN
brute-force the PBKDF2 in real time?

**[Architect]**: With 100K iterations, a desktop GPU (~1M iter/sec) would need
~10^6 × 10^5 / 10^6 = 10^5 seconds ≈ 27 hours. Combined with the 3-attempt
lockout at the transport level and the 5-minute expiry, the attacker would need
to passively sniff the ENROLL_REQUEST and then brute-force the PIN offline.
However, they still can't get the PSK without also sniffing the ENROLL_RESPONSE.
For a LAN-only Phase 1 deployment, this is acceptable.

**[Reviewer]**: What if enrollment is accidentally left active?

**[Architect]**: PINs auto-expire after `pin_timeout` seconds. The
`PendingEnrollment` object tracks `expires_at` and `is_active` checks the clock.
No perpetual enrollment windows.

**[Reviewer]**: ESP32 compatibility for PBKDF2?

**[Architect]**: CPython's `hashlib.pbkdf2_hmac` is C-accelerated.
MicroPython can use a pure-Python implementation with fewer iterations (e.g., 10K).
The ESP32 SDK (task 2.5) will handle this; for now we optimize for correctness.

**Consensus**: Design approved. Proceed with implementation.

## Implementation Plan

### New Files
| File | Purpose |
|------|---------|
| `nanobot/mesh/enrollment.py` | `EnrollmentService` class + `PendingEnrollment` dataclass |

### Modified Files
| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Add `ENROLL_REQUEST`, `ENROLL_RESPONSE` to `MsgType` |
| `nanobot/mesh/transport.py` | Allow ENROLL_REQUEST bypass in `_verify_inbound()` |
| `nanobot/mesh/channel.py` | Instantiate `EnrollmentService`, route enrollment messages |
| `nanobot/config/schema.py` | Add 3 enrollment fields to `MeshConfig` |
| `tests/test_mesh.py` | ~15 new enrollment tests |

### Dependencies
- None — uses only stdlib (`hashlib.pbkdf2_hmac`, `hmac`, `secrets`)

### Test Plan
- PIN lifecycle (create, cancel, expiry, single-use)
- PIN proof verification (correct, wrong, empty)
- PSK encryption/decryption roundtrip
- PBKDF2 key derivation determinism
- Full enrollment flow (request → response → device can authenticate)
- Rate limiting (max attempts exceeded)
- Transport auth bypass only during active enrollment
- Edge cases: expired PIN, already-enrolled device re-enrollment

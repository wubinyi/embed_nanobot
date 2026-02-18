# f04: Device Enrollment Flow — Test Report

**Task**: 1.10
**Date**: 2026-02-18
**Total tests**: 146 (111 existing + 35 new)

---

## New Test Classes

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestPendingEnrollment` | 4 | PIN state lifecycle: active, expired, locked, used |
| `TestEnrollmentCrypto` | 8 | PIN proof generation, PBKDF2 key derivation, PSK encrypt/decrypt |
| `TestEnrollmentService` | 10 | Full enrollment flow, wrong PIN, lockout, expiry, re-enrollment |
| `TestMsgTypeEnrollment` | 3 | ENROLL_REQUEST/RESPONSE type values and roundtrip serialisation |
| `TestTransportEnrollmentBypass` | 3 | Auth bypass when enrollment active/inactive/expired |
| `TestChannelEnrollment` | 4 | Channel creates/skips enrollment service, PIN creation, unavailable |
| `TestEnrollmentConfig` | 2 | Config defaults and custom values for enrollment fields |

**Total new tests**: 34 (+ 1 existing test class update for import)

## Edge Cases Covered

- **Expired PIN**: Force-expire PIN by setting `expires_at` to past; verify rejection with "expired" reason
- **Max attempts lockout**: 2-attempt limit; verify 2 wrong PINs → "locked" reason
- **Already-used PIN**: Successful enrollment invalidates PIN; second device gets "already_used"
- **No active enrollment**: Request without any `create_pin()` → "no_active_enrollment"
- **PIN replacement**: Second `create_pin()` replaces first; service stays active
- **Re-enrollment**: Already-enrolled device gets new PSK (rotation)
- **Wrong PIN proof**: Incorrect HMAC → attempts counter incremented, "invalid_pin" response
- **PSK encryption roundtrip**: XOR encrypt → XOR decrypt recovers original PSK
- **Wrong-length PSK**: ValueError for non-32-byte inputs
- **PBKDF2 determinism**: Same pin + salt → same key
- **PBKDF2 sensitivity**: Different pin or different salt → different key
- **Transport bypass active**: ENROLL_REQUEST passes auth when enrollment is active
- **Transport bypass inactive**: ENROLL_REQUEST blocked when no enrollment service or inactive
- **Transport bypass expired**: ENROLL_REQUEST blocked when enrollment exists but is inactive/expired
- **Channel integration**: PSK-enabled channel creates EnrollmentService; PSK-disabled does not
- **Config defaults**: MeshConfig enrollment fields have correct defaults (6 digits, 300s, 3 attempts)

## Known Gaps

- **No integration test with real TCP transport**: The enrollment flow is tested at the service level with mock transport. A full TCP integration test (like `TestTransportAuth` tests) would require both sides connected. Deferred to when ESP32 SDK work begins (task 2.5).
- **Network-level attack simulation**: MITM and replay attacks not tested at the test level; security analysis is in the Design Log.
- **Concurrent enrollment requests**: Not tested. Current design is single-PIN, so concurrent requests from different devices would race. This is acceptable since enrollment is admin-initiated one-at-a-time.

## Test Execution

```
============================= 146 passed in 11.50s =============================
```

All 146 tests pass, zero failures, zero warnings.

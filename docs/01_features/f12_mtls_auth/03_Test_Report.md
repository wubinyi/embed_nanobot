# f12: mTLS Device Authentication — Test Report

**Task**: 3.1 — mTLS for device authentication (local CA)  
**Test file**: `tests/test_mtls.py`  
**Date**: 2025-02-25  
**Result**: 49 passed, 0 failed  
**Full suite**: 487 passed (438 existing + 49 new), 0 regressions  

---

## Test Coverage Summary

| Test Class | Tests | Focus |
|------------|-------|-------|
| `TestCAInitialization` | 8 | CA key/cert generation, idempotent reload, permissions, X.509 validity, EC P-256 |
| `TestDeviceCertIssuance` | 13 | Device cert generation, CN, issuer, validity, permissions, extensions, errors |
| `TestCACertPEM` | 2 | CA cert PEM distribution, uninitialized error |
| `TestSSLContext` | 7 | Server/client context creation, hub cert auto-issue, TLS 1.2+ minimum |
| `TestTLSHandshake` | 3 | Real TLS handshake, wrong-CA rejection, peer node_id extraction |
| `TestTransportMTLS` | 2 | Message send/receive over mTLS, HMAC/AES-GCM skip flag |
| `TestEnrollmentMTLS` | 3 | Cert in enrollment response, no-CA fallback, correct device cert |
| `TestListDeviceCerts` | 3 | Empty list, populated list, field contents |
| `TestConfigIntegration` | 2 | Default values, serialization round-trip |
| `TestChannelMTLS` | 3 | Channel without mTLS, channel with mTLS, enrollment CA wiring |
| `TestGetPeerNodeId` | 3 | No SSL, no peer cert, CN extraction |

## Edge Cases Covered

1. **CA idempotent initialization**: Calling `initialize()` twice loads existing CA rather than regenerating
2. **Uninitialized CA errors**: `issue_device_cert()`, `get_ca_cert_pem()`, `create_server_ssl_context()` all raise `RuntimeError`
3. **Missing device cert**: `create_client_ssl_context()` raises `FileNotFoundError`
4. **Wrong CA rejection**: Device cert from different CA fails TLS handshake (raises `SSLError`)
5. **Key permissions**: Both CA and device private keys have `0o600` permissions
6. **Hub cert auto-issuance**: Server SSL context auto-issues hub cert if missing
7. **Hub cert reuse**: If hub cert exists, it's not re-issued
8. **Custom validity period**: `device_cert_validity_days=30` produces 28-32 day cert
9. **MagicMock truthiness**: Config with `mtls_enabled=False` doesn't trigger CA init (guarded by `is True`)
10. **Enrollment without CA**: Still works, PSK-only, no cert fields in response
11. **No SSL transport**: `get_peer_node_id()` returns `None` for plain TCP

## Known Gaps

1. **Certificate revocation (CRL)**: Not tested — intentionally deferred to task 3.2
2. **Expired certificate handling**: Not tested at runtime (would require time mocking for TLS layer)
3. **Concurrent enrollment**: Not tested for race conditions during simultaneous cert issuance
4. **ESP32/mbedTLS interop**: Cannot test in Python — requires hardware or firmware emulation
5. **Performance benchmarks**: No profiling of cert issuance or TLS handshake latency

## Regression Analysis

All 438 pre-existing tests pass without modification. The `is True` guard in `channel.py` prevents MagicMock truthiness issues in tests that don't explicitly set mTLS config fields.

# f03 — PSK Authentication: Test Report

**Task**: 1.9 — PSK-based device authentication (HMAC signing)  
**Date**: 2026-02-17  
**Status**: All tests passing  

---

## Test Summary

| Category | Tests | Status |
|----------|-------|--------|
| KeyStore management | 6 | ✅ All pass |
| HMAC sign/verify | 6 | ✅ All pass |
| Nonce tracking / replay | 5 | ✅ All pass |
| Envelope auth fields | 4 | ✅ All pass |
| Transport-level auth integration | 4 | ✅ All pass |
| **Total new** | **25** | ✅ |
| Existing mesh tests (regression) | 20 | ✅ All pass |
| Full test suite | 111 | ✅ All pass |

---

## Test Cases

### KeyStore (`TestKeyStore`)
1. **test_add_and_get_device** — Enroll device, verify PSK stored and retrievable
2. **test_remove_device** — Revoke and verify removal
3. **test_list_devices** — List all enrolled devices
4. **test_persistence** — Save → load from disk, verify data survives
5. **test_load_nonexistent** — Loading missing file is silent no-op
6. **test_psk_rotation** — Re-enrolling a device rotates its PSK

### HMAC (`TestHMAC`)
7. **test_sign_and_verify** — Round-trip sign/verify with correct PSK
8. **test_verify_fails_wrong_psk** — Different PSK → verification fails
9. **test_verify_fails_wrong_nonce** — Different nonce → verification fails
10. **test_verify_fails_tampered_body** — Modified body → verification fails
11. **test_canonical_bytes_excludes_hmac_nonce** — hmac/nonce excluded from canonical form
12. **test_canonical_bytes_sorted_keys** — Different key order → same canonical bytes

### Nonce Tracking (`TestNonceTracking`)
13. **test_fresh_nonce_accepted** — First-seen nonce passes
14. **test_duplicate_nonce_rejected** — Same nonce rejected (replay)
15. **test_different_nonces_accepted** — Distinct nonces both pass
16. **test_stale_nonce_pruned** — Expired nonces are pruned and re-accepted
17. **test_timestamp_validation** — Within window = OK, outside = rejected

### Envelope Auth (`TestEnvelopeAuth`)
18. **test_envelope_with_auth_fields_roundtrip** — Serialize/deserialize with hmac/nonce
19. **test_envelope_without_auth_backward_compatible** — Old-format messages still parse
20. **test_canonical_bytes_deterministic** — Same envelope → same canonical bytes
21. **test_sign_verify_envelope_end_to_end** — Full sign/verify cycle on MeshEnvelope

### Transport Auth Integration (`TestTransportAuth`)
22. **test_authenticated_send_receive** — Two nodes with shared PSK exchange messages over real TCP
23. **test_unauthenticated_message_rejected** — Unsigned message dropped when auth enabled
24. **test_unknown_node_rejected** — Rogue node with valid HMAC but not enrolled → rejected
25. **test_allow_unauthenticated_mode** — Unsigned messages pass when `allow_unauthenticated=True`

---

## Edge Cases Covered

- **Empty/missing auth fields**: Backward compatible parsing
- **PSK rotation**: Old PSK invalidated, new one stored
- **Nonce replay**: Duplicate nonce within window rejected
- **Stale nonce pruning**: Memory doesn't grow unbounded
- **Timestamp drift**: Messages outside window rejected
- **Unknown node**: Signed messages from unenrolled nodes rejected
- **Development mode**: `allow_unauthenticated=True` logs warning but processes

## Known Gaps (Future Work)

- **Network-level replay**: A sophisticated attacker could replay within the nonce window
  if they can intercept + resend within seconds. Phase 2 mTLS will close this gap.
- **Concurrent key store access**: No file locking. Acceptable for single-Hub deployment.
- **Key store encryption**: Plain JSON on disk. Phase 2 can add OS keyring or encrypted storage.

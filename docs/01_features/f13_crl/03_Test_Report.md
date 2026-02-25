# f13: Certificate Revocation (CRL) — Test Report

**Task**: 3.2 — Certificate revocation list  
**Branch**: `copilot/crl-revocation`  
**Date**: 2026-02-25  
**Test file**: `tests/test_crl.py`  

---

## Summary

36 tests covering CRL revocation logic, file persistence, transport-level enforcement, channel integration, and re-enrollment after revocation. All tests pass.

## Test Results

```
tests/test_crl.py — 36 passed in 1.21s
Full suite: 523 passed in 13.20s (487 baseline + 36 new)
```

## Test Classes

### TestRevocationLifecycle (11 tests)
| Test | Covers |
|------|--------|
| `test_revoke_returns_true` | Successful revocation returns True |
| `test_revoke_nonexistent_returns_false` | Revoking unknown node returns False |
| `test_revoke_already_revoked_returns_false` | Double revocation returns False |
| `test_is_revoked_before_and_after` | `is_revoked()` state transition |
| `test_revoke_deletes_cert_and_key` | Cert+key files removed after revocation |
| `test_list_revoked` | `list_revoked()` returns correct entries |
| `test_revocation_persists_across_reload` | Revocation state survives CA reload from disk |
| `test_multiple_revocations` | Sequential revocations all tracked correctly |
| `test_revoked_not_in_device_certs_active` | Revoked device excluded from active cert list |
| `test_revoked_appears_in_device_certs_with_flag` | Revoked device shows `revoked: True` |
| `test_list_device_certs_mixed` | Mixed active/revoked correctly flagged |

### TestCRLFile (6 tests)
| Test | Covers |
|------|--------|
| `test_crl_pem_created_on_revocation` | `crl.pem` file exists after revocation |
| `test_crl_pem_is_valid_x509` | CRL PEM parses as valid X.509 CRL |
| `test_crl_contains_revoked_serial` | CRL contains correct serial number |
| `test_crl_signed_by_ca` | CRL signature verifiable with CA public key |
| `test_crl_next_update` | CRL `next_update` is ~30 days from `last_update` |
| `test_revoked_json_matches_crl` | JSON and CRL have same revocation entries |

### TestCRLRebuild (4 tests)
| Test | Covers |
|------|--------|
| `test_rebuild_crl_from_json` | `rebuild_crl()` regenerates CRL from `revoked.json` |
| `test_rebuild_crl_no_revocations` | Rebuild with no revocations produces empty CRL |
| `test_rebuild_crl_after_manual_delete` | CRL recoverable after manual deletion |
| `test_rebuild_preserves_serials` | Rebuilt CRL has same serial numbers |

### TestSSLContextWithCRL (3 tests)
| Test | Covers |
|------|--------|
| `test_server_context_valid_with_revocations` | Server SSL context still works after revocations |
| `test_revoked_device_rejected_by_transport` | **Key test**: Real TLS connection from revoked device is dropped at transport layer |
| `test_non_revoked_device_accepted_by_transport` | Non-revoked device messages processed normally |

### TestListDeviceCertsWithCRL (3 tests)
| Test | Covers |
|------|--------|
| `test_empty_after_all_revoked` | No active certs when all revoked |
| `test_mixed_active_and_revoked` | Correct counts with mixed state |
| `test_revoked_entry_has_metadata` | Revoked entries include serial and date |

### TestTransportSSLHotReload (2 tests)
| Test | Covers |
|------|--------|
| `test_update_server_ssl_context` | Hot-reload replaces SSL context |
| `test_update_server_ssl_context_none` | Hot-reload with None keeps original |

### TestChannelRevokeDevice (5 tests)
| Test | Covers |
|------|--------|
| `test_revoke_device_calls_ca` | Channel delegates to CA correctly |
| `test_revoke_device_with_registry_removal` | Registry removal when flag set |
| `test_revoke_device_no_ca` | Graceful failure when CA not configured |
| `test_revoke_wires_revocation_check_fn` | Transport's revocation_check_fn wired to ca.is_revoked |
| `test_revoke_device_returns_false_for_unknown` | Unknown device returns False |

### TestReEnrollmentAfterRevocation (2 tests)
| Test | Covers |
|------|--------|
| `test_re_enroll_after_revocation` | New cert issued after revocation has different serial |
| `test_re_enrolled_cert_accepted_by_transport` | Re-enrolled device accepted, old revocation doesn't block new cert |

## Edge Cases Covered

- **Double revocation**: Returns False, does not corrupt state
- **Non-existent device**: Graceful failure, no side effects
- **CRL file manually deleted**: Recoverable via `rebuild_crl()`
- **Mixed active/revoked state**: Correctly partitioned in listings
- **CA reload from disk**: Revocation state persists via `revoked.json`
- **Re-enrollment after revocation**: New cert works, old serial stays revoked
- **No CA configured**: Channel gracefully returns False
- **Real TLS + transport handler**: End-to-end test with actual SSL connections

## Known Gaps

- **Concurrent revocation**: No lock on `_revoked` dict — safe for single-threaded asyncio but could race under multi-threaded use. Acceptable for current architecture.
- **CRL distribution to ESP32**: CRL PEM generated but distribution mechanism not yet implemented (future OTA task).
- **Connection kill for already-connected revoked device**: Current connections from a revoked device continue until they naturally close. Only new connections are rejected.

# f14: OTA Firmware Update Protocol — Test Report

**Task**: 3.3 — OTA firmware update protocol  
**Branch**: `copilot/ota-firmware`  
**Date**: 2026-02-25  
**Test file**: `tests/test_ota.py`  

---

## Summary

49 tests covering firmware storage, OTA session state machine, full protocol flow, chunk data integrity, progress callbacks, edge cases, and MeshChannel integration. All tests pass.

## Test Results

```
tests/test_ota.py — 49 passed in 1.03s
Full suite: 572 passed in 12.01s (523 baseline + 49 new)
```

## Test Classes

### TestFirmwareInfo (2 tests)
| Test | Covers |
|------|--------|
| `test_to_dict_roundtrip` | Serialize/deserialize FirmwareInfo |
| `test_from_dict_ignores_extra_keys` | Graceful handling of unknown fields |

### TestFirmwareStore (10 tests)
| Test | Covers |
|------|--------|
| `test_add_and_list` | Add firmware, verify size/sha256/list |
| `test_remove` | Remove firmware, verify gone |
| `test_remove_nonexistent` | Remove unknown returns False |
| `test_get_firmware` | Lookup by ID |
| `test_read_chunk` | Read specific offset/size from binary |
| `test_read_chunk_unknown` | Read from unknown firmware returns empty |
| `test_read_chunk_beyond_end` | Read past EOF returns remaining bytes |
| `test_manifest_persistence` | Reload manifest from disk |
| `test_binary_file_written` | Verify .bin file contents |
| `test_remove_deletes_binary` | Binary file deleted on remove |

### TestOTASession (7 tests)
| Test | Covers |
|------|--------|
| `test_total_chunks_exact` | Exact division |
| `test_total_chunks_remainder` | Ceiling division |
| `test_total_chunks_single` | Small firmware = 1 chunk |
| `test_progress_initial` | Progress 0.0 at start |
| `test_progress_partial` | Partial progress |
| `test_progress_complete` | Progress 1.0 when all ACK'd |
| `test_to_status` | Status dict format |

### TestOTAManagerStart (4 tests)
| Test | Covers |
|------|--------|
| `test_start_sends_offer` | OTA_OFFER sent with correct payload |
| `test_start_unknown_firmware` | Unknown firmware returns None |
| `test_start_duplicate_rejected` | Can't start two sessions for same device |
| `test_start_after_complete_allowed` | Re-update after completion allowed |

### TestOTAManagerFlow (6 tests)
| Test | Covers |
|------|--------|
| `test_accept_starts_transfer` | ACCEPT → TRANSFERRING + first chunk sent |
| `test_reject` | REJECT → REJECTED state + reason captured |
| `test_chunk_ack_sends_next` | ACK triggers next chunk |
| `test_full_transfer_completes` | Full flow: offer → accept → chunks → verify → complete |
| `test_verify_hash_mismatch` | Wrong hash → FAILED + OTA_ABORT sent |
| `test_device_abort` | Device OTA_ABORT → FAILED state |

### TestOTAManagerAbort (3 tests)
| Test | Covers |
|------|--------|
| `test_abort_active_session` | Hub-initiated abort sends OTA_ABORT |
| `test_abort_no_session` | Abort unknown device returns False |
| `test_abort_completed_session` | Can't abort completed session |

### TestOTAManagerStatus (3 tests)
| Test | Covers |
|------|--------|
| `test_get_status` | Session status dict |
| `test_get_status_none` | No session returns None |
| `test_list_sessions` | List all active sessions |

### TestOTAManagerChunkData (1 test)
| Test | Covers |
|------|--------|
| `test_reassembled_data_matches` | **Key test**: Reassemble all chunks, verify == original firmware |

### TestOTAManagerProgress (2 tests)
| Test | Covers |
|------|--------|
| `test_progress_callback_called` | Callback invoked on start |
| `test_progress_on_accept` | Callback invoked on state transition |

### TestOTAManagerEdgeCases (4 tests)
| Test | Covers |
|------|--------|
| `test_message_from_unknown_device` | Message from non-session device ignored |
| `test_firmware_id_mismatch` | Wrong firmware_id in message ignored |
| `test_accept_when_not_offered` | Accept in wrong state ignored |
| `test_concurrent_devices` | Two devices update simultaneously |

### TestChannelOTAIntegration (7 tests)
| Test | Covers |
|------|--------|
| `test_ota_manager_created_when_firmware_dir_set` | OTA manager created |
| `test_ota_manager_none_when_no_firmware_dir` | No OTA when unconfigured |
| `test_start_ota_update_convenience` | Channel convenience method works |
| `test_start_ota_no_ota_manager` | Graceful failure when OTA disabled |
| `test_ota_message_routing` | OTA messages routed to OTAManager |
| `test_get_ota_status` | Status lookup |
| `test_abort_ota_convenience` | Abort convenience method |

## Edge Cases Covered

- Unknown firmware ID
- Duplicate session for same device
- Device sending message with wrong firmware_id
- State machine transition out of order (ACCEPT when not OFFERED)
- Concurrent updates to different devices
- Chunk reassembly integrity (SHA-256 verification)
- Hash mismatch on verification
- Hub-initiated and device-initiated abort
- Read past end of firmware file
- Empty firmware directory on startup

## Known Gaps

- **Chunk retry/timeout**: No automatic retry on chunk ACK timeout (device must re-request or Hub must detect timeout). Timer-based retry deferred.
- **Firmware code signing**: SHA-256 integrity only. No Ed25519/RSA signature verification (future task).
- **Large firmware files**: Tested with small files (600–1024 bytes). Real ESP32 firmware (~1–4MB) would have many more chunks but the logic is identical.
- **Network interruption resume**: Session tracks ACK watermark but there's no explicit "resume from seq N" message. Device would need to reconnect and Hub would need to detect the gap.

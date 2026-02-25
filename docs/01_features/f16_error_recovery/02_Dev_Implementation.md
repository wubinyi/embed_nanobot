# f16: Error Recovery and Fault Tolerance — Dev Implementation

**Task**: 3.5 — Error recovery and fault tolerance  
**Branch**: `copilot/error-recovery`  
**Date**: 2026-02-25  

---

## Summary

Addressed all critical and high-priority resilience gaps across the mesh network stack with a new cross-cutting `resilience.py` module and targeted fixes in 5 existing files.

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/resilience.py` | ~170 | RetryPolicy, retry_send (exp backoff), Watchdog (periodic loop), supervised_task (error-logging create_task) |
| `tests/test_resilience.py` | ~370 | 36 tests covering all new resilience features |
| `docs/01_features/f16_error_recovery/01_Design_Log.md` | Design decisions & gap analysis |
| `docs/01_features/f16_error_recovery/02_Dev_Implementation.md` | This file |
| `docs/01_features/f16_error_recovery/03_Test_Report.md` | Test results |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/discovery.py` | Added Watchdog import, `_prune_watchdog` in `__init__`, auto-start in `start()`, auto-stop in `stop()` |
| `nanobot/mesh/transport.py` | Added resilience imports, `send_with_retry()` method using RetryPolicy |
| `nanobot/mesh/channel.py` | Added `supervised_task` import, wrapped `start()`/`stop()` with try/except for error isolation, replaced bare `create_task` with `supervised_task` in `_on_peer_seen` |
| `nanobot/mesh/ota.py` | Added `check_timeouts()` (enforce OFFER/CHUNK_ACK/VERIFY timeouts), `cleanup_completed()` (remove terminal sessions older than max_age) |
| `nanobot/mesh/protocol.py` | Wrapped `read_envelope()` with try/except for json.JSONDecodeError, UnicodeDecodeError, struct.error |

## Key Implementation Details

### Resilience Module (`resilience.py`)

- **RetryPolicy**: Configurable exponential backoff (defaults: 3 retries, 0.5s base, 10s max, 2x factor)
- **retry_send()**: Wraps any async send callable with retries. Catches both False returns and exceptions. Logs attempt progress.
- **Watchdog**: Reusable periodic async loop. Supports both sync and async callbacks. Exception-safe (continues after callback errors). Used for discovery prune (interval = peer_timeout / 2).
- **supervised_task()**: Wraps `asyncio.create_task()` with a done callback that logs exceptions. Prevents silent task failures.

### Critical Fixes

1. **Discovery auto-prune**: `prune()` was defined but never called. Now a Watchdog calls it at `peer_timeout / 2` interval. Peer-lost callbacks fire properly.
2. **Transport retry**: New `send_with_retry()` method for critical sends (automation actions, OTA).
3. **Channel error isolation**: `start()` catches transport failure and stops discovery. `stop()` catches errors in each component independently.
4. **OTA timeouts**: `check_timeouts()` enforces OFFER_TIMEOUT (60s), CHUNK_ACK_TIMEOUT (30s), VERIFY_TIMEOUT (60s). `cleanup_completed()` removes terminal sessions after 5 min.
5. **Protocol safety**: `read_envelope()` now catches JSON/struct errors and returns None.

### Deviations from Design

None. All planned changes implemented.

## Documentation Freshness Check

- architecture.md: OK (resilience.py is in mesh/ which is already documented)
- configuration.md: OK (no new config fields)
- customization.md: OK
- PRD.md: OK (will be updated at roadmap phase)
- agent.md: OK — no upstream convention changes

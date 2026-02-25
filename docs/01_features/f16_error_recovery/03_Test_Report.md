# f16: Error Recovery and Fault Tolerance — Test Report

**Task**: 3.5 — Error recovery and fault tolerance  
**Date**: 2026-02-25  

---

## Test File

`tests/test_resilience.py` — 36 tests

## Test Results

```
36 passed in 1.30s
Full regression: 643 passed in 13.39s (607 baseline + 36 new)
```

## Test Coverage

### TestRetryPolicy (3 tests)
- `test_defaults` — verify default values
- `test_delay_for` — exponential backoff calculation with cap
- `test_delay_respects_max` — delay never exceeds max_delay

### TestRetrySend (7 tests)
- `test_success_on_first_try` — no retries needed
- `test_success_after_retry` — succeeds on 3rd attempt
- `test_all_retries_fail` — returns False after max attempts
- `test_exception_in_send` — recovers from exception, succeeds on retry
- `test_all_exceptions` — returns False when all attempts raise
- `test_passes_args_through` — args/kwargs forwarded to send_fn
- `test_no_retries` — max_retries=0 means one attempt only

### TestWatchdog (4 tests)
- `test_callback_invoked` — sync callback runs periodically
- `test_async_callback` — async callback runs periodically
- `test_callback_exception_does_not_stop` — continues after error
- `test_stop_idempotent` — double-stop and stop-before-start safe

### TestSupervisedTask (3 tests)
- `test_normal_completion` — returns result normally
- `test_exception_logged` — exception propagated but logged
- `test_cancelled_no_error` — CancelledError is clean

### TestDiscoveryAutoPrune (4 tests)
- `test_prune_watchdog_exists` — Watchdog created in __init__
- `test_prune_watchdog_interval` — interval = peer_timeout / 2
- `test_prune_removes_stale_peers` — stale peers removed, fresh kept
- `test_prune_fires_peer_lost_callback` — callbacks notified

### TestTransportSendWithRetry (3 tests)
- `test_send_with_retry_success` — succeeds first try
- `test_send_with_retry_eventual_success` — succeeds on retry
- `test_send_with_retry_all_fail` — returns False after exhausting retries

### TestOTATimeoutAndCleanup (6 tests)
- `test_check_timeouts_no_sessions` — empty list when no sessions
- `test_check_timeouts_stale_offered` — offered session timed out
- `test_check_timeouts_fresh_session_not_affected` — recent sessions untouched
- `test_check_timeouts_skips_terminal` — completed/failed sessions ignored
- `test_cleanup_completed` — old terminal sessions removed, recent and active kept
- `test_cleanup_completed_no_sessions` — returns 0 when empty

### TestChannelStartStopSafety (3 tests)
- `test_stop_transport_error_doesnt_break_discovery_stop` — discovery still stopped despite transport error
- `test_start_transport_failure_stops_discovery` — discovery cleaned up on transport bind failure
- `test_start_discovery_failure_doesnt_start_transport` — transport never started if discovery fails

### TestReadEnvelopeSafety (3 tests)
- `test_malformed_json` — returns None instead of raising
- `test_valid_envelope` — normal operation still works
- `test_invalid_struct` — struct.error returns None

## Edge Cases Covered
- Zero retries (max_retries=0)
- Exception vs False return in send functions
- Watchdog callback exceptions
- Double stop / stop-before-start
- Cascading component failures in channel start/stop
- Stale vs fresh OTA sessions
- Terminal vs active OTA sessions for cleanup

## Known Gaps
- No integration test for Watchdog + discovery prune loop running together (unit-tested separately)
- No circuit breaker tests (circuit breaker deferred to future work)
- OTA check_timeouts/cleanup not yet wired to a Watchdog in channel (callers can invoke directly or wire later)

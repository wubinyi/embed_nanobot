# f11: Cloud API Fallback — Test Report

**Task**: 2.7  
**Date**: 2026-02-18  

---

## Test Summary

| Metric | Value |
|--------|-------|
| New tests | 11 |
| Total tests (project) | 414 |
| Regressions | 0 |
| Test file | `tests/test_hybrid_router.py` |

## New Tests

| Test | Coverage |
|------|----------|
| `test_api_failure_falls_back_to_local` | ConnectionError → local fallback |
| `test_api_failure_no_fallback_re_raises` | fallback_to_local=False → exception propagates |
| `test_api_failure_timeout_error` | TimeoutError → local fallback |
| `test_api_success_resets_failure_count` | Success after failure resets counter |
| `test_circuit_breaker_opens_after_threshold` | 3 consecutive failures → breaker opens |
| `test_circuit_breaker_routes_to_local` | Open breaker → direct local (no judge) |
| `test_circuit_breaker_half_open_success` | Expired timer + success → breaker closes |
| `test_circuit_breaker_half_open_failure` | Expired timer + failure → breaker reopens |
| `test_circuit_breaker_closed_by_default` | Initial state is closed |
| `test_circuit_is_open_logic` | Closed/open/expired edge cases |
| `test_fallback_uses_original_messages_not_sanitised` | Fallback gets original, not PII-stripped |

## Helper Classes Added

- `FailingProvider`: Always raises a configurable exception
- `SometimesFailingProvider`: Fails N times, then succeeds

## Edge Cases Covered

1. Different exception types (ConnectionError, TimeoutError)
2. Fallback disabled → exception propagates
3. Half-open state: success closes, failure reopens
4. Fallback messages are unsanitised (original user content)
5. Circuit breaker default state (closed, 0 failures)

## Known Gaps

1. No real network integration test (would require actual API endpoint)
2. No concurrency test for circuit breaker state under parallel requests

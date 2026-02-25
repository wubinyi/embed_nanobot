# f16: Error Recovery and Fault Tolerance — Design Log

**Task**: 3.5 — Error recovery and fault tolerance  
**Branch**: `copilot/error-recovery`  
**Date**: 2026-02-25  

---

## Motivation

The mesh network currently has numerous resilience gaps identified through audit:

| Priority | Component | Gap |
|----------|-----------|-----|
| **Critical** | discovery | `prune()` never called — stale peers accumulate, `on_peer_lost` never fires |
| **Critical** | ota | Timeout constants unused — zombie sessions possible |
| **High** | transport | No send retry — messages silently lost on first failure |
| **High** | channel | No startup/shutdown error isolation (partial failure leaves broken state) |
| **High** | channel | Fire-and-forget tasks have no error handler |
| **Medium** | transport | No proactive health monitoring (PING/PONG unused) |
| **Medium** | protocol | `read_envelope` not exception-safe |

## Architecture

### New Module: `nanobot/mesh/resilience.py`

Cross-cutting resilience utilities:

1. **RetryPolicy** dataclass: configurable retry parameters (max_retries, base_delay, max_delay, backoff_factor)
2. **retry_send()** async function: wraps a send callable with exponential backoff
3. **Watchdog** class: periodic async loop that calls a check function on interval (for prune, OTA timeout, health)
4. **supervised_task()** helper: wraps an async coroutine with error logging and optional restart

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/transport.py` | Add `send_with_retry()` method wrapping `send()` with RetryPolicy |
| `nanobot/mesh/discovery.py` | Add `_prune_loop()` auto-started in `start()`, stopped in `stop()` |
| `nanobot/mesh/channel.py` | Wrap `start()`/`stop()` with try/except, use supervised tasks, safe auto-registration |
| `nanobot/mesh/ota.py` | Add session timeout watchdog, session cleanup for completed/failed sessions |
| `nanobot/mesh/protocol.py` | Make `read_envelope()` exception-safe (catch json.JSONDecodeError) |

## Key Decisions

1. **Retry at transport layer**: `send_with_retry()` is a new method alongside the original `send()` — callers choose which to use. Critical sends (automation actions, OTA chunks) use retry; non-critical (beacons, info messages) use plain send.

2. **Watchdog pattern**: A reusable `Watchdog` class runs a callback at a fixed interval. Used for:
   - Discovery prune (every 15s)
   - OTA session timeout check (every 10s)

3. **Supervised tasks**: `supervised_task()` wraps `asyncio.create_task()` with an exception callback that logs the error. No auto-restart — just clean error visibility.

4. **Graceful degradation in channel.start()**: If transport fails to start, discovery is stopped. If discovery fails, nothing is left dangling.

5. **OTA session cleanup**: Sessions in terminal states (COMPLETE, FAILED, REJECTED) older than 5 minutes are purged.

## Reviewer Notes

- Retry backoff defaults: 3 retries, 0.5s base, 10s max, factor 2.0 — suitable for LAN where failures are brief
- Prune interval 15s matches the discovery beacon interval (10s) + tolerance
- No circuit breaker in this iteration — added to future work if needed

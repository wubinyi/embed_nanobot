# f11: Cloud API Fallback — Dev Implementation

**Task**: 2.7  
**Status**: Done  
**Date**: 2026-02-18  

---

## What Was Built

### Modified Files

| File | Change |
|------|--------|
| `nanobot/providers/hybrid_router.py` | +3 constructor params (`fallback_to_local`, `circuit_breaker_threshold`, `circuit_breaker_timeout`), +4 instance vars, +3 methods (`_circuit_is_open`, `_record_api_success`, `_record_api_failure`), circuit breaker check before difficulty judge, try/except on API call with local fallback |
| `nanobot/config/schema.py` | +3 fields appended to `HybridRouterConfig` |
| `nanobot/cli/commands.py` | Pass 3 new config fields to `HybridRouterProvider()` constructor |
| `tests/test_hybrid_router.py` | +2 helper classes (`FailingProvider`, `SometimesFailingProvider`), +11 new tests |

## Key Implementation Details

### API Call Fallback
```python
try:
    result = await self.api.chat(sanitised_messages, ...)
    self._record_api_success()
    return result
except Exception as e:
    self._record_api_failure()
    if self.fallback_to_local:
        return await self.local.chat(messages, ...)  # original messages
    raise
```

### Circuit Breaker
```python
def _circuit_is_open(self) -> bool:
    if self._cb_open_until <= 0:
        return False
    return time.time() < self._cb_open_until

def _record_api_failure(self):
    self._cb_consecutive_failures += 1
    if self._cb_consecutive_failures >= self._cb_threshold:
        self._cb_open_until = time.time() + self._cb_timeout

def _record_api_success(self):
    self._cb_consecutive_failures = 0
    self._cb_open_until = 0.0
```

### Fallback Uses Original Messages
When falling back after API failure, the local model receives the original (unsanitised) messages. Rationale: local model is trusted (on-premises), and the user's full context produces better answers.

## Deviations from Design

None.

### Documentation Freshness Check
- architecture.md: OK — HybridRouter section already documents the routing workflow; fallback is internal behavior, not architectural
- configuration.md: Updated — added 3 new HybridRouter config fields
- customization.md: OK — no new extension patterns
- PRD.md: OK — HR-02 (graceful degradation) progress
- agent.md: OK — no upstream convention changes

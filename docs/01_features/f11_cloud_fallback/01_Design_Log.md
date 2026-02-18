# f11: Cloud API Fallback — Design Log

**Task**: 2.7  
**Status**: Done  
**Date**: 2026-02-18  

---

## Problem Statement

When the cloud API provider is unreachable (network error, timeout, 5xx response), the Hybrid Router fails completely. In smart home/factory scenarios, the hub must remain functional even without internet access. The router should automatically fall back to the local model for degraded-but-functional service.

## Architect Proposal

### Design

Two complementary mechanisms:

1. **Try/Except Fallback**: Wrap the API call in `chat()`. On any exception, log a warning and route to the local model using the original (unsanitised) messages.

2. **Circuit Breaker**: Track consecutive API failures. After N failures (`circuit_breaker_threshold`, default 3), open the circuit for M seconds (`circuit_breaker_timeout`, default 300). While open, bypass the difficulty judge entirely and route all traffic to local. After timeout, enter half-open state: allow one API attempt. Success → close breaker. Failure → reopen.

```
                ┌──────────────────────────────────────────┐
                │               HybridRouter.chat()        │
                │                                          │
                │  ┌─ force_local_fn? → LOCAL              │
                │  │                                       │
                │  ├─ circuit breaker OPEN? → LOCAL         │
                │  │                                       │
                │  ├─ judge difficulty                      │
                │  │  └─ easy (score ≤ threshold) → LOCAL   │
                │  │                                       │
                │  └─ hard → sanitise PII → try API        │
                │           ├─ success → return + reset CB  │
                │           └─ failure → record failure     │
                │                ├─ fallback=true → LOCAL   │
                │                └─ fallback=false → raise  │
                └──────────────────────────────────────────┘
```

### Circuit Breaker States

```
    CLOSED ──(N failures)──→ OPEN ──(timeout)──→ HALF-OPEN
      ↑                       ↑                      │
      │                       │                      ├─ success → CLOSED
      └──── success ──────────┘←── failure ──────────┘
```

### Key Decisions

1. **Fallback uses original messages, not sanitised**: The local model is trusted (runs on-premises). No need for PII sanitisation when falling back.

2. **Circuit breaker skips difficulty judge**: When the breaker is open, there's no point evaluating difficulty — everything goes local. This saves one local model call per request.

3. **Default threshold = 3**: Three consecutive failures is a strong signal. One failure could be transient.

4. **Default timeout = 300s (5 min)**: Long enough to avoid hammering a recovering API, short enough to detect recovery reasonably quickly.

5. **Configurable**: All three parameters (`fallback_to_local`, `circuit_breaker_threshold`, `circuit_breaker_timeout`) are in `HybridRouterConfig`.

## Reviewer Challenge

### Concern 1: Should fallback be on by default?
**Answer**: Yes. The primary use case (smart home hub) requires always-on functionality. Users who want strict API-only can set `fallback_to_local: false`.

### Concern 2: Quality degradation when falling back
**Answer**: Acknowledged. The local model handles "hard" tasks less well. But degraded service is better than no service. Users can see "[HybridRouter] API failed... falling back to LOCAL" in logs.

### Concern 3: Silent failures
**Answer**: Circuit breaker state is logged (OPEN/CLOSED), and each fallback is individually logged. No silent degradation.

## Consensus

Design approved. Clean, small scope, no new files needed.

## File Plan

| File | Type | Change |
|------|------|--------|
| `nanobot/providers/hybrid_router.py` | MODIFIED | +3 constructor params, +40 LOC (circuit breaker methods + try/except + breaker check) |
| `nanobot/config/schema.py` | MODIFIED | +3 fields appended to `HybridRouterConfig` |
| `nanobot/cli/commands.py` | MODIFIED | Pass 3 new config fields to constructor |
| `tests/test_hybrid_router.py` | MODIFIED | +11 new tests (helpers + fallback + circuit breaker) |

# f26 — KleidiAI Provider: Test Report

**Feature**: `f26_hybrid_npu_inference` — Phase 1 (KleidiAI-optimized llama.cpp)
**Branch**: `copilot/f26-hybrid-npu-inference`
**Date**: 2025-01-28
**Validation class**: `real-hardware required`
**Hardware**: Radxa Rock 5T (RK3588), Armbian 26.2.1 / Debian 13 Trixie

> **Status**: Pre-run template. Benchmark cells marked `[TBD]` must be filled in
> after the first hardware run. This document is the reference for validating
> that the KleidiAI build delivers the expected throughput improvement.

---

## 1. Test Scope

| Test | Type | Automated? |
|------|------|-----------|
| Build succeeds with KleidiAI flags | manual / build | No (run once per source update) |
| `GGML_USE_KLEIDIAI` active at runtime | manual / log inspection | No |
| No `SIGILL` on first token | smoke / runtime | Indirectly via smoke test |
| Token generation t/s ≥ baseline | benchmark / `llama-bench` | Manual |
| Prompt processing t/s ≥ baseline | benchmark / `llama-bench` | Manual |
| Health endpoint responds `200 OK` | smoke / curl | Manual |
| `/v1/models` returns `qwen3.5-9b-kleidiai` | smoke / curl | Manual |
| `/v1/chat/completions` returns correct response | smoke / curl | Manual |
| Nanobot smoke test passes | integration / `run_agent_smoke.sh` | Manual |
| Full nanobot agent session works | integration / `nanobot agent` | Manual |
| Simultaneous operation with baseline provider | manual | No |

---

## 2. Build Test

### 2.1 Commands

```bash
# Ensure source is available (run baseline build first if needed)
ls local_llm/local_provider_llamacpp/llama.cpp-src/.git || \
  bash local_llm/local_provider_llamacpp/build_llamacpp.sh

# Build KleidiAI binary
bash local_llm/local_provider_llamacpp_kleidiai/build_llamacpp_kleidiai.sh 2>&1 | tee /tmp/kleidiai_build.log

# Check the binary exists
ls -lh local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin/llama-server
```

### 2.2 Expected cmake configure output

The configure step should include lines like:
```
-- GGML_USE_KLEIDIAI     : ON
-- KleidiAI sources found at ...
```

If `GGML_USE_KLEIDIAI` is `OFF` in the cmake output, the kernel library was
not found — check that the llama.cpp source includes `ggml/src/ggml-cpu/kleidiai/`.

### 2.3 Result

| Check | Result |
|-------|--------|
| Build completes without errors | [TBD] |
| `GGML_USE_KLEIDIAI: ON` in cmake output | [TBD] |
| Binary size (rough, for regression detection) | [TBD] |
| Build time | [TBD] |

---

## 3. Benchmark: KleidiAI vs Baseline

### 3.1 Commands

Both builds must be available. Run from the workspace root:

```bash
MODEL="$PWD/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf"

# --- KleidiAI build ---
KLEIDIAI_BIN="$PWD/local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin"
echo "=== KleidiAI llama-bench ==="
taskset -c 4-7 "$KLEIDIAI_BIN/llama-bench" \
  --model "$MODEL" \
  --n-gen 64 \
  --n-prompt 512 \
  --threads 4 \
  2>&1 | tee /tmp/bench_kleidiai.log

# --- Baseline build ---
BASE_BIN="$PWD/local_llm/local_provider_llamacpp/runtime/build/bin"
echo "=== Baseline llama-bench ==="
taskset -c 4-7 "$BASE_BIN/llama-bench" \
  --model "$MODEL" \
  --n-gen 64 \
  --n-prompt 512 \
  --threads 4 \
  2>&1 | tee /tmp/bench_baseline.log
```

### 3.2 Additional quantization sweep (optional)

```bash
# Test across quantization levels to find the KleidiAI sweet spot
for quant in Q4_0 Q4_K_M Q5_K_M Q8_0; do
  model_path="$PWD/local_llm/models/gguf/Qwen3.5-9B-${quant}.gguf"
  [[ -f "$model_path" ]] || continue
  echo "=== $quant ==="
  taskset -c 4-7 "$KLEIDIAI_BIN/llama-bench" --model "$model_path" \
    --n-gen 64 --n-prompt 512 --threads 4
done
```

### 3.3 Results table

| Metric | Baseline | KleidiAI | Actual speedup | Expected |
|--------|----------|----------|----------------|---------|
| Token gen (t/s) | 3.58 | [TBD] | [TBD] | ~5–7 t/s (1.5–2×) |
| Prompt proc (t/s) | 8.45 | [TBD] | [TBD] | ~12–18 t/s |
| TTFT (ms, 512 tok prompt) | [TBD] | [TBD] | [TBD] | — |
| Peak RSS (GB) | [TBD] | [TBD] | — | ≈ same (same model) |

> Baseline values (3.58 / 8.45 t/s) are from the measured run documented in
> the design log (01_Design_Log.md §1.1).

---

## 4. Functional Smoke Tests

### 4.1 Start the KleidiAI provider

```bash
bash local_llm/local_provider_llamacpp_kleidiai/start_local_provider.sh &
# Wait ~30s for model load
sleep 30
```

### 4.2 Health and model check

```bash
# Health
curl -sS http://127.0.0.1:19100/health
# Expected: {"status":"ok"} or similar 200 response

# Model list — must show qwen3.5-9b-kleidiai
curl -sS http://127.0.0.1:19100/v1/models | python3 -m json.tool
# Expected: "id": "qwen3.5-9b-kleidiai"

# Quick inference
curl -sS http://127.0.0.1:19100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-9b-kleidiai","messages":[{"role":"user","content":"Say KLEIDIAI_OK"}],"stream":false,"max_tokens":10}'
# Expected: response containing KLEIDIAI_OK
```

### 4.3 Nanobot smoke test

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp_kleidiai
# Expected: PASS: found KLEIDIAI_OK
```

### 4.4 Results

| Test | Expected | Result |
|------|----------|--------|
| Health endpoint 200 | ✅ | [TBD] |
| `/v1/models` shows kleidiai alias | ✅ | [TBD] |
| Non-streaming chat completion | ✅ | [TBD] |
| Smoke test: KLEIDIAI_OK | PASS | [TBD] |

---

## 5. Simultaneous Operation Test

Both providers can run at the same time (different ports). This test verifies
no port conflicts or interference:

```bash
# Start baseline (if not already running)
bash local_llm/local_provider_llamacpp/start_local_provider.sh &
sleep 30

# Start KleidiAI
bash local_llm/local_provider_llamacpp_kleidiai/start_local_provider.sh &
sleep 30

# Query both
curl -sS http://127.0.0.1:19000/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print('baseline:', d['data'][0]['id'])"
curl -sS http://127.0.0.1:19100/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print('kleidiai:', d['data'][0]['id'])"
```

### Result

| Check | Result |
|-------|--------|
| Both providers start without error | [TBD] |
| No port conflict (ss -tlnp shows both 19000 and 19100) | [TBD] |
| Each returns correct model alias | [TBD] |

---

## 6. Real Hardware Validation

**Classification**: `real-hardware required`
(This provider changes llama-server build flags, which requires a real inference
run to confirm the KleidiAI kernel is active and performance is as expected.)

### Mandatory validation steps

1. Build completes with `GGML_USE_KLEIDIAI: ON` ← _required_
2. First inference completes without `SIGILL` ← _required_
3. `llama-bench` t/s ≥ 4.5 t/s (≥ 1.25× baseline) ← _success threshold_
4. Nanobot smoke test PASS ← _required for nanobot integration_

### Validation session log

```
Date         : [TBD]
Platform     : Radxa Rock 5T (RK3588), Armbian 26.2.1
llama.cpp rev: [TBD — git rev-parse HEAD in llama.cpp-src/]
KleidiAI rev : [same — vendored inside llama.cpp]
Model        : Qwen3.5-9B-Q4_K_M (5.28 GB GGUF)
Result       : [TBD]
Notes        : [TBD]
```

---

## 7. Known Gaps

| Gap | Priority | Plan |
|-----|----------|------|
| Streaming latency (TTFT) not measured | Medium | Add to next benchmark run |
| Quantization sweep not yet run | Low | Run when Q4_0/Q5_K_M models available |
| Long-context performance (≥32K tokens) | Medium | Run once basic bench is complete |
| Phase 2 (RKNN hybrid) validation | Future | Separate roadmap task |

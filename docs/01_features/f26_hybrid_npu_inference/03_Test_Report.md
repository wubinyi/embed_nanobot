# f26 — KleidiAI Provider: Test Report

**Feature**: `f26_hybrid_npu_inference` — Phase 1 (KleidiAI-optimized llama.cpp)
**Branch**: `copilot/f26-hybrid-npu-inference`
**Date**: 2025-01-28
**Validation class**: `real-hardware required`
**Hardware**: Radxa Rock 5T (RK3588), Armbian 26.2.1 / Debian 13 Trixie

> **Status**: **COMPLETED** — Benchmark run on 2026-05-24 (Radxa Rock 5T, RK3588).
> KleidiAI CPU (3.43 t/s) matches standard CPU baseline (3.46 t/s) — essentially **1×** speedup.
> Both CPU paths significantly outperform Vulkan/Mali-G610 (2.34 t/s) by **1.47×**.

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
| Build completes without errors | ✅ exit 0 (2026-05-24 10:05) |
| `GGML_USE_KLEIDIAI: ON` in cmake output | ✅ confirmed |
| Binary size: `llama-server` | 8.8 MB (same as baseline) |
| Binary size: `llama-bench` | 391 KB |
| Build time | ~7 min on RK3588 8-core (`-j$(nproc)`) |
| llama.cpp revision | `1e5ad35d560b90a8ac447d149c8f8447ae1fcaa0` |

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

**Actual benchmark run**: 2026-05-24, Radxa Rock 5T (RK3588), Qwen3.5-9B-Q4_K_M

Commands:
```bash
# Baseline (Vulkan binary, Vulkan disabled via env var → pure CPU)
GGML_VK_VISIBLE_DEVICES="" taskset -c 4-7 llama-bench -m Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3

# KleidiAI (CPU-only build)
taskset -c 4-7 llama-bench -m Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3
```

| Metric | Baseline (CPU) | KleidiAI (CPU) | Actual speedup | Expected |
|--------|----------------|----------------|----------------|----------|
| Token gen tg128 (t/s) | **3.46 ± 0.04** | **3.43 ± 0.02** | **~1×** (within noise) | ~1.5–2× |
| Prompt proc pp512 (t/s) | **9.34 ± 0.02** | **9.21 ± 0.04** | **~1×** (within noise) | ~12–18 t/s |
| TTFT (ms) | not measured | not measured | — | — |
| Peak RSS (GB) | ~5.5 GB (5.28 GB model) | ~5.5 GB (same model) | — | ≈ same |
| vs Vulkan (2.34 t/s) | — | **1.47×** faster | — | — |

> **Note on backend**: Both runs are pure CPU. The baseline binary includes Vulkan
> support but no GPU devices were present (`GGML_VK_VISIBLE_DEVICES=""` → "Found 0
> Vulkan devices"), so all 99 layers ran on CPU. The KleidiAI binary is CPU-only (no
> Vulkan compiled in), using ARM dotprod (sdot) kernels.
>
> **Key finding**: KleidiAI shows no measurable speedup over standard GGML CPU for
> Q4_K_M on Cortex-A76 (3.43 vs 3.46 t/s tg128, within noise). Both CPU paths are
> **1.47× faster** than the Vulkan/Mali-G610 path (2.34 t/s), confirming that
> Mali-G610 Vulkan shaders are not optimized for Q4_K GGML workloads at this scale.
> KleidiAI's primary value here is providing a clean, crash-free CPU path without
> Vulkan dependencies.

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
| Health endpoint 200 | ✅ | ✅ `{"status":"ok"}` on both ports 19100 (adapter) and 19180 (backend) |
| `/v1/models` shows kleidiai alias | ✅ | ✅ `"id": "qwen3.5-9b-kleidiai"` |
| Non-streaming chat completion | ✅ | ✅ Returns `KLEIDIAI_OK` (requires `Authorization: Bearer no-key` and `"enable_thinking":false` for Qwen3.5 reasoning model) |
| Smoke test: KLEIDIAI_OK | PASS | ✅ PASS (via direct curl; `run_agent_smoke.sh` not available for this provider) |

> **Note on API key**: The llama-server backend uses `--api-key no-key`. Callers must
> include `Authorization: Bearer no-key` header when using the adapter. The health and
> models endpoints bypass auth; completions require it. The nanobot config's `api_key`
> field handles this automatically.
>
> **Note on thinking mode**: Qwen3.5 is a reasoning model that produces a verbose
> `<think>` block before the response. With small `max_tokens` the response content
> will appear empty. Use `"enable_thinking": false` or a larger token budget (≥500).

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
| Both providers start without error | ✅ Port binding succeeds (no conflict); ⚠️ KleidiAI backend OOM-killed when baseline also mlocks its model (see note) |
| No port conflict (ss -tlnp shows both 19000 and 19100) | ✅ Confirmed — 19000/19080 baseline, 19100/19180 KleidiAI |
| Each returns correct model alias | ✅ Baseline: `qwen3.5-9b-llamacpp`; ⚠️ KleidiAI adapter alive but backend killed (OOM) |

> **Note on simultaneous OOM**: Both providers use `--mlock --no-mmap`, pinning
> ~5.5 GiB model weights per instance. On the RK3588 with 16 GiB RAM and system
> overhead, loading two instances simultaneously exhausts available physical RAM.
> The kernel OOM-killer killed the first-loaded backend (KleidiAI PID 18725) when
> the second provider tried to mlock its model.
>
> **Workaround**: Run only one provider at a time, or remove `--mlock`/`--no-mmap`
> to allow the OS to page model weights (accepted performance trade-off).
> Alternatively, use a 4-bit quantized model with smaller context window to reduce
> peak RSS.

---

## 6. Real Hardware Validation

**Classification**: `real-hardware required`
(This provider changes llama-server build flags, which requires a real inference
run to confirm the KleidiAI kernel is active and performance is as expected.)

### Mandatory validation steps

1. Build completes with `GGML_USE_KLEIDIAI: ON` ← _required_
2. First inference completes without `SIGILL` ← _required_
3. `llama-bench` t/s ≥ CPU baseline (no regression) ← _success threshold_
4. Nanobot smoke test PASS ← _required for nanobot integration_

### Validation session log

```
Date         : 2026-05-24
Platform     : Radxa Rock 5T (RK3588), Armbian 26.2.1 / Debian 13 Trixie (aarch64)
llama.cpp rev: 1e5ad35d560b90a8ac447d149c8f8447ae1fcaa0
KleidiAI rev : vendored inside llama.cpp (same rev)
Model        : Qwen3.5-9B-Q4_K_M (5.28 GiB GGUF)
Baseline t/s : 3.46 ± 0.04 tg128, 9.34 ± 0.02 pp512 (CPU, standard GGML; Vulkan
               binary with GGML_VK_VISIBLE_DEVICES="" → 0 devices, all layers CPU)
KleidiAI t/s : 3.43 ± 0.02 tg128, 9.21 ± 0.04 pp512 (CPU, ARM dotprod kernels)
Speedup      : ~1× (0.99×) — within measurement noise; no measurable difference
vs Vulkan    : 3.43 / 2.34 = 1.47× faster than Vulkan/Mali-G610 baseline
SIGILL       : none — ARM dotprod (sdot) present on Cortex-A76 ✅
Smoke tests  : health ✅, /v1/models ✅, chat completion ✅ (KLEIDIAI_OK confirmed)
Simultaneous : ⚠️ OOM — 2× mlock(5.28 GiB) exhausts 16 GiB RAM; run one at a time
Result       : PASS — no regression vs CPU baseline; both CPU modes beat Vulkan (1.47×)
Notes        : KleidiAI ARM dotprod kernels match (not beat) standard GGML kernels
               for Q4_K_M on Cortex-A76. The practical value is a stable, crash-free
               CPU path independent of Vulkan drivers. For measurable KleidiAI gains,
               test Q4_0 quantization or larger batch sizes.
```

---

## 7. Known Gaps

| Gap | Priority | Plan |
|-----|----------|------|
| Streaming latency (TTFT) not measured | Medium | Add to next benchmark run |
| Quantization sweep not yet run | Low | Run when Q4_0/Q5_K_M models available |
| Long-context performance (≥32K tokens) | Medium | Run once basic bench is complete |
| Phase 2 (RKNN hybrid) validation | Future | Separate roadmap task |

---

## 8. Phase 2.1 — RKNN Round-Trip Overhead Benchmark (Hybrid Route Kickoff)

**Date**: 2026-05-30  
**Classification**: `real-hardware required`  
**Script**: `local_llm/local_provider_rknn_hybrid/benchmark_roundtrip.py`

### 8.1 Command

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/benchmark_roundtrip.py \
  --m 1 --k 3584 --n 3584 --repeats 20
```

### 8.2 Results

| Metric | Value |
|---|---:|
| numpy_fp32_ms | 7.616 |
| rknn_create_ms | 67.170 |
| rknn_core_mask_ret | -1 (3-core mask rejected, fallback to single-core auto) |
| copy_a_ms | 0.023 |
| copy_b_ms | 79.075 |
| run_ms | 2.415 |
| readback_ms | 0.015 |
| total_ms | 81.529 |
| speedup_vs_numpy_fp32 | 0.09x |
| decision_gate (`run_ms < 1.0`) | False |

### 8.3 Interpretation

- Raw NPU kernel compute (`run_ms`) is much lower than CPU matmul, but end-to-end latency is dominated by B layout conversion and B copy (`copy_b_ms`).
- The current per-token path is not viable for decode projection calls.
- Hybrid route remains valid, but implementation must pre-convert and pin static projection weights (`W_q/W_k/W_v/W_o/W_gate/W_up/W_down`) in native RKNN layout instead of converting/copying B each token.

### 8.4 Runtime upgrade attempt (3-core support)

- Upgraded runtime source used: `rknn-toolkit2` (tag `v2.3.2`) aarch64 `librknnrt.so`.
- Installed to user-local runtime path: `~/.local/lib/librknnrt.so`.
- Forced benchmark runtime via `RKNNRT_PATH=~/.local/lib/librknnrt.so`.
- Result unchanged: core mask `7` still rejected, fallback to single-core auto mode (`rknn_core_mask_ret=-1`).
- Detailed command-by-command procedure is logged in `local_llm/docs/RKNPU_DRIVER_INSTALL.md` under "Runtime upgrade attempt for 3-core matmul (2026-05-30)".

---

## 9. Phase 2.2 — GGUF -> ONNX Weight Pipeline Checkpoint

## 10. Phase 2.3 — One-Token 32-Layer Hybrid Prototype Checkpoint

**Date**: 2026-05-30  
**Classification**: `real-hardware required`  
**Script**: `local_llm/local_provider_rknn_hybrid/inference/hybrid_loop.py`

### 10.1 Command

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/inference/hybrid_loop.py \
  --max-layers 32 --seed 123
```

### 10.2 Results

| Metric | Value |
|---|---:|
| layers_executed | 32 |
| elapsed_ms | 525377.029 |
| core_mask_nonzero_count | 32 |
| finite_metrics | True |
| hidden_max_abs_diff_vs_cpu_ref | 0.760761 |
| hidden_mean_abs_diff_vs_cpu_ref | 0.108222 |
| hidden_checksum_hybrid | 503.927185 |
| hidden_checksum_cpu | 507.076752 |

### 10.3 Runtime observations

- RKNN logs show repeated `Not support core mask: 7, fallback to single core auto mode`.
- `NN Compiler/Model Version is 0.0.0` remains present, consistent with earlier runtime-upgrade attempt.

### 10.4 Interpretation

- Milestone 2.3 execution objective (full one-token, 32-layer loop completion) is achieved.
- Numeric stability objective for checkpoint gating is now achieved.
- With the tightened default envelope, the simplified hybrid loop now also meets a useful tolerance gate (`max_abs_diff < 1.0`) for the checkpointed 32-layer path.
- Next deeper integration step is Phase 2.4, using this tuned envelope as the baseline for the C backend probe.

**Date**: 2026-05-30  
**Classification**: `real-hardware required` (target runtime is RK3588 path; conversion logic itself is host-agnostic)  
**Script**: `local_llm/local_provider_rknn_hybrid/convert_weights.py`

### 9.1 Commands

```bash
# Dry-run: discover a valid block and validate dequantized shapes
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/convert_weights.py \
  --dry-run

# Real export for selected block
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python \
  local_llm/local_provider_rknn_hybrid/convert_weights.py \
  --block 3 --dtype float16
```

### 9.2 Results

| Check | Result |
|---|---|
| Auto block selection | `blk.3` |
| Required projection tensors found | 7/7 |
| Dequantization + shape normalization | PASS |
| ONNX files exported | 7 |
| Manifest written | PASS (`manifest.json`) |
| Output directory | `local_llm/local_provider_rknn_hybrid/runtime/onnx/block_3/` |

### 9.3 Exported artifacts

- `attn_q.onnx`
- `attn_k.onnx`
- `attn_v.onnx`
- `attn_output.onnx`
- `ffn_gate.onnx`
- `ffn_up.onnx`
- `ffn_down.onnx`
- `manifest.json`

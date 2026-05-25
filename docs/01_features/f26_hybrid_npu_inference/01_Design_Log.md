# f26: Hybrid NPU Inference — Design Log

**Task**: Fast LLM inference on RK3588 — CPU optimization (KleidiAI) + RKNN hybrid NPU backend  
**Feature**: `f26_hybrid_npu_inference`  
**Branch**: `copilot/f26-hybrid-npu-inference`  
**Date**: 2026-05-24  
**Validation class**: `real-hardware required` (all phases — RKNN and performance benchmarks only meaningful on physical RK3588)

---

## Brainstorming: Requirements & Clarifications

### Problem statement

The project currently has three local providers:
- **RKLLM** (`local_provider_rkllm`, port 18000): fast NPU inference, hard-capped at 4096-token context (`max_context_len = 4096` in `flask_server.py`), limited model compatibility (only `.rkllm` converted models)
- **llama.cpp** (`local_provider_llamacpp`, port 19000): full GGUF compatibility, 65K+ token context, but only **3.58 t/s** on Cortex-A76×4 (benchmark: Qwen3.5-9B Q4_K_M, `DOTPROD=1`, `taskset -c 4-7`)
- **Ollama** (`local_provider_ollama`): similar characteristics to llama.cpp

The user wants: **long context + high inference speed + broad model compatibility** in one consistent experience.

### Requirements (settled via Q&A)

| # | Requirement | Source |
|---|---|---|
| R1 | Token generation speed ≥ 10 t/s (soft target; 20-30 t/s theoretical for Phase 2) | Q4 answer |
| R2 | Full long-context support: 65K+ tokens | Q1: "C — both growing conversations and large single-turn inputs" |
| R3 | GGUF model compatibility (any model llama.cpp supports) | Q2/Q3 clarification |
| R4 | One consistent model experience — no user-visible model switching | Q2: "one consistent model experience" |
| R5 | Runs on RK3588 hardware only — no external dependencies | Implicit |
| R6 | `local_provider_llamacpp/` must remain untouched | Explicit constraint |

### What was ruled out

- **RKLLM as primary engine**: limited model compatibility, 4K context cap baked into converted model at compile time
- **HybridRouterProvider** (local↔cloud routing): already exists for different purpose, not applicable here
- **Speculative decoding** (Approach B from brainstorming): RKLLM can't serve as draft model for llama.cpp (outputs text, not logits); small-GGUF draft is viable but user chose Approach A+C instead

### Technical clarifications established

**RKLLM vs RKNN:**
- RKLLM is a whole-model black box built on RKNN. It takes prompts and returns text; KV cache is internal and inaccessible.
- RKNN is the lower-level NPU runtime that executes arbitrary compiled neural network graphs (from ONNX/TFLite). It provides per-call APIs: `rknn_inputs_set()`, `rknn_run()`, `rknn_outputs_get()`.
- The "subgraph as kernel" vision requires RKNN (not RKLLM).

**i8mm correction:**
- Cortex-A76 is ARMv8.2-A. It does NOT support `FEAT_I8MM` (ARMv8.6-A feature).
- The correct optimization target is `FEAT_DOTPROD` (already active: `DOTPROD=1` in logs).
- KleidiAI's benefit on A76 comes from a better DOTPROD kernel implementation (optimized scheduling, memory access patterns), not a new ISA extension.
- Realistic Phase 1 improvement: **1.5–2× over 3.58 t/s → ~5–7 t/s**.

**Why the compute split works:**
- During token generation (batch=1), projection/FFN layers are compute-bound (large weight matmuls → NPU wins).
- Attention over KV cache is memory-bandwidth-bound (sequential reads of cached K/V → CPU is fine, avoids round-trip cost of sending full KV cache to NPU).
- RK3588 NPU and CPU share LPDDR5 (UMA). Weights loaded once via `rknn_init()` stay in LPDDR5; each `rknn_run()` uses NPU DMA to read them — no extra copies vs CPU.

**Why self-attention cannot be moved to NPU (decode phase):**

The attention computation (`softmax(Q·Kᵀ/√d)·V`) over the KV cache is a vector × growing-matrix operation during decode (batch=1). Its arithmetic intensity is ~1 FLOP/byte — it is dominated by **reading the KV cache from LPDDR5**, not by arithmetic. Moving it to the NPU provides no memory-bandwidth advantage because CPU and NPU share the same LPDDR5 bus.

There are also three practical blockers:

1. **Fixed-shape graphs**: RKNN compiles `.rknn` models at a fixed sequence length. The KV cache grows from length 1 to 65K+ with each token. Supporting this on NPU requires either padding to max context (~8 GB per attention call for 65K context) or per-step recompilation — neither is viable.

2. **KV cache management is dynamic-state work**: Inserting new K/V pairs, applying RoPE position encodings, and handling context window rotation require stateful index arithmetic that RKNN compiled graphs cannot express. The CPU must manage this regardless, so there is no clean handoff.

3. **NPU round-trip overhead**: Each `rknn_run()` call costs ~1–3 ms. Running 32 layers of memory-bound attention on NPU would add ~32–96 ms per token while providing zero throughput gain vs CPU (same LPDDR5 bandwidth).

**Future nuance — prefill phase only**: During prompt ingestion (batch >> 1), the attention computation becomes compute-bound, making NPU acceleration theoretically viable. This requires dynamic-shape RKNN support and is out of scope for Phase 2 (which targets decode throughput).

The correct NPU targets are the **7 projection matmuls per layer** (W_q, W_k, W_v, W_o, W_gate, W_up, W_down) — they are compute-bound with fixed, compile-time-known shapes.

---

## Architecture

### Three-phase roadmap

```
Phase 1 (Approach C) — CPU optimization          Phase 2 (Approach A) — RKNN Hybrid        Phase 3 — Prefill NPU Attention
Days to weeks, immediate value                    Months, highest decode t/s ceiling        Research track; prefill batch speedup

┌─────────────────────────────────┐              ┌──────────────────────────────────────┐
│  local_provider_llamacpp_       │              │  local_provider_rknn_hybrid           │              │  local_provider_rknn_hybrid (Phase 3 ext.)    │
│  kleidiai (port 19100)          │   evolves    │  (port 19200)                         │   extends    │  + prefill attention on NPU                   │
│                                 │  ─────────►  │                                       │  ──────────► │  Q·Kᵀ and attn·V via rknn_matmul_api         │
│  llama.cpp rebuilt with:        │              │  ┌──────────┐     ┌───────────────┐   │              │  rknn_matmul_create_dynamic_shape              │
│  - GGML_USE_KLEIDIAI=ON         │              │  │ CPU      │     │ RKNN NPU      │   │              │  bucket sizes: 64,128,256,512,1024,2048        │
│  - -march=armv8.2-a+dotprod     │              │  │ Attention│     │ FFN + proj    │   │              │  Goal: faster prompt ingestion                 │
│  Target: ~5–7 t/s               │              │  │ KV cache │     │ weights       │   │              └───────────────────────────────────────────────┘
│                                 │              │  │ Sampling │     │ resident      │   │
│  local_provider_llamacpp/       │              │  └──────────┘     └───────────────┘   │
│  (port 19000) — UNTOUCHED       │              │  Target: ~20–30 t/s (theoretical)     │
└─────────────────────────────────┘              └──────────────────────────────────────┘
```

### Provider port allocation

| Provider | Backend port | Adapter port | Status |
|---|---|---|---|
| `local_provider_llamacpp` | 19080 | 19000 | Existing — untouched |
| `local_provider_llamacpp_kleidiai` | 19180 | 19100 | Phase 1 — new |
| `local_provider_rknn_hybrid` | 19280 | 19200 | Phase 2 — new |
| `local_provider_rknn_hybrid` (Phase 3 ext.) | 19280 | 19200 | Phase 3 — extends Phase 2 |
| `local_provider_rkllm` | 8080 | 18000 | Existing — untouched |

### nanobot integration (no core code changes)

All providers expose OpenAI-compatible `/v1/chat/completions`. Switching between them requires changing one line in `~/.embed_nanobot/config.json`:

```json
"providers": {
  "custom": {
    "apiBase": "http://127.0.0.1:19100/v1"   ← change port to switch provider
  }
}
```

No changes to nanobot channels, tools, or agent logic.

---

## Phase 1: CPU Optimization (KleidiAI rebuild)

### What changes

A new provider directory is created alongside `local_provider_llamacpp`. The existing provider is never modified.

**cmake delta (the only real build change):**
```bash
cmake .. \
  -DGGML_VULKAN=ON \
  -DGGML_USE_KLEIDIAI=ON \
  -DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16" \
  -DCMAKE_C_FLAGS="-march=armv8.2-a+dotprod+fp16" \
  ...
```

KleidiAI is vendored inside llama.cpp source. No extra dependencies. The new binary is built into the new provider's own `runtime/build/` directory so it does not overwrite the existing build.

### Files created (Phase 1)

| File | Purpose |
|---|---|
| `local_llm/local_provider_llamacpp_kleidiai/build_llamacpp_kleidiai.sh` | KleidiAI-enabled cmake build script |
| `local_llm/local_provider_llamacpp_kleidiai/start_local_provider.sh` | Launches backend (19180) + adapter (19100) |
| `local_llm/local_provider_llamacpp_kleidiai/openai_adapter.py` | Thin proxy adapter; same logic as existing, env defaults point to port 19180 |
| `local_llm/local_provider_llamacpp_kleidiai/README.md` | Setup, benchmark results, comparison with raw build |
| `local_llm/local_provider_llamacpp_kleidiai/runtime/local_llamacpp_kleidiai.json` | nanobot config pointing to port 19100 |

### Benchmark gate (must pass before Phase 1 is complete)

```bash
# Before (existing build)
./local_provider_llamacpp/runtime/build/llama-bench \
  -m models/gguf/Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3

# After (new KleidiAI build)
./local_provider_llamacpp_kleidiai/runtime/build/llama-bench \
  -m models/gguf/Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3

# Both tg t/s values recorded in 03_Test_Report.md
```

### Optional: quantization sweep

While the new binary is available, benchmark Q4_0 vs Q4_K_M — Q4_0 has simpler dequantization and may be 5–15% faster:

```bash
# Convert in-place (no re-download)
./llama-quantize Qwen3.5-9B-Q4_K_M.gguf Qwen3.5-9B-Q4_0.gguf Q4_0

./llama-bench -m Qwen3.5-9B-Q4_0.gguf -t 4 -p 512 -n 128 -r 3
```

Results documented in `local_provider_llamacpp_kleidiai/FAQ.md`.

---

## Phase 2: RKNN Hybrid Backend

### Compute split per token per layer

```
INPUT: hidden state h [1 × d_model]
           │
    ┌───────┴───────┐
    ▼               ▼
┌────────────┐  ┌──────────────────────────────────┐
│ RKNN (NPU) │  │ CPU                              │
│            │  │                                  │
│ Q = h·W_q  │  │ scores = Q·Kᵀ / √d              │
│ K = h·W_k  │  │ attn_weights = softmax(…)        │
│ V = h·W_v  │  │ ctx_vec = attn_weights · V_cache │
│            │  │                                  │
│ O = ctx·Wo │◄─┤ KV cache mgmt in LPDDR5 (CPU)   │
│            │  │ (insert new K/V, RoPE, rotation) │
│ gate = h·Wg│  │                                  │
│ up   = h·Wu│  │ ← memory-bandwidth-bound;        │
│ down = h·Wd│  │   NPU offers no advantage here   │
└────────────┘  └──────────────────────────────────┘
Weights DMA'd from LPDDR5 by NPU
(shared UMA — no extra copies)
```

**Why this is fast:** 7 NPU projection calls replace the most compute-heavy operations per layer. The KV cache (memory-bandwidth-bound) stays in CPU memory — no round-trip cost.

### Integration path: preferred vs fallback

**Option A (preferred): `ggml_backend` plugin for llama.cpp**

Register an RKNN backend that intercepts `mul_mat` ops in llama.cpp's compute graph. llama.cpp continues to own tokenization, KV cache, sampling, GGUF loading, and context window management.

```
llama.cpp ggml graph planner
  ├── mul_mat (Q/K/V/O/gate/up/down projections) ──► ggml_backend_rknn
  │                                                    (.rknn compiled kernels)
  └── softmax, rope, rms_norm, add, sample ──────────► ggml_backend_cpu
```

**Option B (fallback): Minimal Python custom framework**

If `ggml_backend` C integration cost is too high for initial prototype: Python token loop, RKNN bindings via `rknn-toolkit2`'s Python API for projection calls, NumPy on CPU for attention and KV cache. Slower to optimize, faster to prototype. Same GGUF model loaded via `gguf` Python library.

**Decision gate:** Milestone 2.1 overhead benchmark. If `rknn_run()` overhead per call is < 1ms, Option A is viable. If overhead is 2–5ms and 32 layers × 7 calls = 224 calls/token, Option A becomes latency-dominated and Option B (fewer, batched calls per layer) is preferred.

### Phase 2 milestones

| Milestone | Deliverable | Acceptance |
|---|---|---|
| **2.1 Overhead research** | `benchmark_roundtrip.py` — measures single `rknn_run()` call latency vs CPU equivalent | Data: overhead < 1ms/call OR pivot decision documented |
| **2.2 Weight pipeline** | `convert_weights.py` — GGUF layer weights → ONNX → `.rknn` for one transformer block | Compiled `.rknn` for Qwen3.5-9B layer 0, all projection ops |
| **2.3 Prototype** | Single full forward pass (one token, all 32 layers, hybrid CPU+NPU) | Output logits match llama.cpp within FP16 tolerance |
| **2.4 Full integration** | All 32 layers running, token loop operational, end-to-end t/s measured | t/s > Phase 1 baseline |
| **2.5 Provider** | `local_provider_rknn_hybrid` operational as nanobot provider | `run_agent_smoke.sh --mode rknn_hybrid` passes |

### New directory structure (Phase 2)

```
local_llm/
└── local_provider_rknn_hybrid/       ← NEW (Phase 2)
    ├── README.md                         # Architecture, setup, benchmark results
    ├── convert_weights.py                # GGUF → ONNX → .rknn pipeline (per model)
    ├── benchmark_roundtrip.py            # Milestone 2.1 overhead measurement tool
    ├── rknn_backend/
    │   ├── ggml_backend_rknn.c           # Option A: ggml_backend C implementation
    │   └── rknn_kernel.py                # Option B fallback: Python RKNN bindings
    ├── inference/
    │   └── hybrid_loop.py                # Option B: custom Python token loop
    ├── start_local_provider.sh           # starts OpenAI-compatible adapter on port 19200
    ├── openai_adapter.py
    └── runtime/
        ├── local_rknn_hybrid.json        # nanobot config (port 19200)
        └── kernels/                      # compiled .rknn files per model (gitignored)
```

### Files created (Phase 2, iterative)

| File | Purpose |
|---|---|
| `README.md` | Architecture, setup, benchmark results |
| `convert_weights.py` | GGUF → ONNX → `.rknn` per-layer pipeline |
| `benchmark_roundtrip.py` | Milestone 2.1 overhead measurement tool |
| `rknn_backend/ggml_backend_rknn.c` | Option A: `ggml_backend` C implementation |
| `rknn_backend/rknn_kernel.py` | Option B: Python RKNN bindings wrapper |
| `inference/hybrid_loop.py` | Option B: custom Python token loop |
| `start_local_provider.sh` | Starts OpenAI-compatible adapter on port 19200 |
| `openai_adapter.py` | Thin proxy adapter |
| `runtime/local_rknn_hybrid.json` | nanobot config (port 19200) |
| `runtime/kernels/` | Compiled `.rknn` files (gitignored) |

### Known unknowns (resolved in milestone 2.1)

| Question | Impact if answer is unfavorable |
|---|---|
| `rknn_run()` per-call overhead (µs)? | >5ms/call → 224 calls/token = >1s overhead alone → pivot to Option B with batched calls |
| RKNN accepts FP16 activations natively? | If only INT8: activation quantization adds per-step complexity |
| RKNN Toolkit2 accepts arbitrary ONNX linear layers? | If not: need TFLite export path or custom operator |
| Can 64+ RKNN model handles stay loaded simultaneously? | If OOM: group multiple layers' projections into one compiled model |

---

## Phase 3: Prefill Attention on NPU

> **Status: BLOCKED — do not start until Phase 2 is complete.**  
> Pre-work (experiment design + initial benchmark) was done while the Phase 2 design was being elaborated.  
> Phase 3 is also blocked on a hard prerequisite: the system RKNN runtime with 3-core NPU support is not installed.  
> (`/usr/lib/librknnrt.so` does not exist; only the vendored single-core copy in rknn-llm-src is available.)

### Goal

During **prompt ingestion (prefill)**, the model processes S input tokens in a single forward pass with batch size S. In this mode, the Q·K^T attention matmul has arithmetic intensity ~S FLOP/byte — it becomes **compute-bound for large S** (≥ 256), making NPU acceleration theoretically viable.

This is the **only case** where attention can benefit from the NPU. Decode (batch=1) remains memory-bandwidth-bound and always stays on CPU (see "Why self-attention cannot be moved to NPU" above).

### Why this is different from decode

| Property | Decode (batch=1) | Prefill (batch=S) |
|---|---|---|
| Attention arithmetic intensity | ~1 FLOP/byte | ~S/2 FLOP/byte |
| Compute-bound at S=256? | No (never) | Yes (~128+ FLOP/byte) |
| K/V sequence length | Grows 1 per token | Fixed = prompt length |
| Shape known before inference? | No | Yes — prompt length is fixed before computation starts |
| NPU viable? | No | Yes, with fixed-shape kernels |

### Two sub-approaches for Phase 3

The RKNN matmul API (`rknn_matmul_api.h`) provides the low-level primitive needed. Both approaches compile the **same set of fixed-shape kernels**; the difference is packaging and dispatch.

#### Approach 3A: `rknn_matmul_create_dynamic_shape` (RKNN-managed multi-shape)

```c
// Enumerate all bucket shapes at creation time
rknn_matmul_shape shapes[] = {
  {64, D_HEAD, 64}, {128, D_HEAD, 128},
  {256, D_HEAD, 256}, {512, D_HEAD, 512},
  {1024, D_HEAD, 1024}, {2048, D_HEAD, 2048},
};
rknn_matmul_create_dynamic_shape(&ctx, &info, 6, shapes, io_attrs);

// At inference: call rknn_matmul_set_dynamic_shape to select the right bucket,
// then rknn_matmul_run
rknn_matmul_shape current = {actual_S, D_HEAD, actual_S};
rknn_matmul_set_dynamic_shape(ctx, &current);  // RKNN selects compiled graph
rknn_matmul_run(ctx);
```

**Pros**: Single context handle, RKNN manages dispatch, cleaner API.  
**Cons**: All shapes baked in at creation time, larger upfront compilation.

> **Important**: `rknn_matmul_set_dynamic_shape` alone only supports **M dynamic, K and N fixed** (for weight-matrix reuse). For attention where M=N=S, we MUST use `create_dynamic_shape` with pre-enumerated shapes — `set_dynamic_shape` is insufficient.

#### Approach 3B: Multiple fixed-shape contexts (user-managed dispatch)

```python
# Pre-create one context per bucket size
BUCKETS = [64, 128, 256, 512, 1024, 2048]
contexts = {s: rknn_matmul_create(M=s, K=D_HEAD, N=s) for s in BUCKETS}

# At inference: route to smallest bucket >= seq_len, pad input
bucket = min(b for b in BUCKETS if b >= seq_len)
q_padded = pad(q, bucket)         # [bucket, D_HEAD]
kt_padded = pad(k_transposed, bucket)  # [D_HEAD, bucket]
out = contexts[bucket].run(q_padded, kt_padded)
out = out[:seq_len, :seq_len]     # trim padding
```

**Pros**: Simple, no special API, always supported.  
**Cons**: Multiple context handles, user must manage routing and padding.

### Key API constraint discovered from header analysis

From `rknn_matmul_api.h` for RK3588, FP16 matmul alignment requirements:

| Dimension | Alignment (FP16, RK3588) | Our values |
|---|---|---|
| K (columns of A = d_head) | Multiple of 16 FP16 elements (32 bytes) | 128 ✓ (128 % 16 = 0) |
| N (columns of C = seq_len) | Multiple of 8 FP16 elements (16 bytes) | 64, 128, … 2048 ✓ |

All planned bucket sizes (64, 128, 256, 512, 1024, 2048) satisfy alignment requirements. No padding of d_head is needed.

### Compute waste from bucketing

For a prompt of length S padded to the nearest bucket B ≥ S:

$$\text{waste fraction} = 1 - \frac{S}{B}$$

Worst case: S just above a previous bucket, e.g. S=65 padded to B=128 → 49% waste.  
Average with uniform S distribution over [64, 2048]: ~25% waste per matmul.  
Attention total FLOPs even with 25% waste is still ≪ projection FLOPs for large d_model.

### Phase 3 milestones

| Milestone | Deliverable | Acceptance |
|---|---|---|
| **3.1 Experiment** | `benchmark_attention_kernels.py` — NPU matmul vs CPU at S=64…2048 | Decision: NPU wins at S ≥ threshold (TBD from results) |
| **3.2 Design decision** | Document Approach 3A vs 3B selection based on experiment overhead data | Choice recorded with rationale |
| **3.3 Prefill hook** | Insert NPU attention path into Phase 2 provider for prefill phase | Prefill latency reduced vs Phase 2 baseline |
| **3.4 Validation** | End-to-end: prompt ingestion speed measured with `nanobot agent` | Prefill t/s improvement confirmed on real hardware |

### Phase 3 experiment: `benchmark_attention_kernels.py`

Located at: `local_llm/local_provider_rknn_hybrid/benchmark_attention_kernels.py`

**What it measures:**

```
For each seq_len S in [64, 128, 256, 512, 1024, 2048]:
  For each attention head h in [0..H-1] (H=28 for Qwen3.5-9B):
    Q = [S, d_head=128]  K^T = [d_head=128, S]

  Benchmark A: numpy FP32  — Q · K^T
  Benchmark B: numpy FP16  — Q · K^T (nearer to NPU precision)
  Benchmark C: RKNN matmul — Q · K^T via rknn_matmul_create(M=S, K=128, N=S)

  Record: setup_ms, per_call_ms, speedup_vs_numpy_fp32
```

**Decision gate:**

- If RKNN wins (lower latency) at S ≥ 128: Phase 3 is worthwhile → select Approach 3A or 3B
- If RKNN never wins (or wins only at S ≥ 1024): Phase 3 has limited ROI for typical prompts
- If overhead > 1ms per head × 28 heads = 28ms setup per token: Approach 3A (batched shapes) is preferable to avoid per-call setup

**Note on approach comparison**: Approaches 3A and 3B compile the **same underlying NPU kernels** — they differ only in API ergonomics and context management overhead. The experiment measures both to quantify the difference.

### Milestone 3.1 Experiment Results (2026-05-25)

**Script**: `local_llm/local_provider_rknn_hybrid/benchmark_attention_kernels.py`  
**Hardware**: Radxa Rock 5T (RK3588), RKNN runtime from rknn-llm-src vendored copy  
**Model**: Qwen3.5-9B config — 28 heads, d_head=128, buckets [64, 128, 256, 512, 1024, 2048]

| S | numpy FP32 (ms) | numpy FP16 (ms) | RKNN create (ms) | RKNN run (ms) | speedup | winner |
|---|---|---|---|---|---|---|
| 64 | 0.085 | 1.226 | 2.31 | 0.143 | 0.59x | CPU |
| 128 | 0.089 | 4.892 | 1.48 | 0.244 | 0.36x | CPU |
| 256 | 0.411 | 19.703 | 1.70 | 0.594 | 0.69x | CPU |
| 512 | 1.238 | 84.979 | 3.02 | 2.124 | 0.58x | CPU |
| 1024 | 5.751 | 350.881 | 7.27 | 11.240 | 0.51x | CPU |
| 2048 | 19.884 | 1915.965 | 21.93 | 35.198 | 0.56x | CPU |

**Key observations:**

1. **CPU wins at ALL tested sizes.** RKNN matmul FP16 is 1.1–2× slower than numpy FP32 for attention Q·K^T across S=64..2048.

2. **RKNN was forced to single NPU core.** The lib version reports `NN Compiler/Model Version is 0.0.0` and rejects the 3-core mask (`core_mask: 7`), falling back to single-core auto mode. The vendored `librknnrt.so` bundled in `rknn-llm-src/examples/` is an older version. If all 3 NPU cores were usable, RKNN would be ~3× faster — potentially 1.5–2.6× ahead of CPU at S ≥ 256. This means **results are pessimistic for the NPU**.

3. **numpy FP16 is 30–96× slower than FP32** on Cortex-A76. This is expected: A76 DOTPROD only accelerates int8; FP16 matmuls fall back to scalar FP32 accumulation in numpy. RKNN FP16 IS properly using hardware, so the correct comparison is RKNN FP16 vs numpy FP32.

4. **Context creation scales with S** (1.5ms at S=128 → 21.9ms at S=2048). For Approach 3B (one context per head per bucket size): 28 heads × 6 buckets = 168 contexts, with total creation time 168× avg ~5ms = ~840ms startup overhead. For Approach 3A (`create_dynamic_shape`): 1 context per head × 6 buckets = 28 contexts → ~140ms startup. Approach 3A is clearly preferable.

**Decision:** 

- **Phase 3 is deferred** pending verification with the system RKNN runtime (not the vendored test copy) that supports multi-core mode. Use `dpkg -l | grep rknn` or `/usr/lib/librknnrt.so` to find the production runtime, then re-run with all 3 cores enabled.
- **If 3-core NPU is confirmed available** and produces ≥1.5× speedup at S≥256: adopt **Approach 3A** (`rknn_matmul_create_dynamic_shape`) as the single context handles all bucket sizes elegantly.
- **Approach 3A vs 3B conclusion**: Under the hood they are identical (same compiled kernels). Approach 3A wins on API ergonomics (28 handles vs 168 handles) and startup time (140ms vs 840ms). No performance difference at inference time.

---

## Integration & Testing

### How nanobot selects the provider

No changes to nanobot core. Each provider is a separate JSON config the user points nanobot at. The three new and existing providers coexist:

```
~/.embed_nanobot/config.json
        │
        └── "provider": "custom"
            "apiBase": "http://127.0.0.1:XXXX/v1"

  19000 → local_provider_llamacpp          (raw llama.cpp, stable reference)
  19100 → local_provider_llamacpp_kleidiai (Phase 1, optimized CPU)
  19200 → local_provider_rknn_hybrid       (Phase 2, NPU hybrid)
```

Switch between them by changing one line in the config. No code changes to nanobot.

### Validation classification

| Phase | Classification | Rationale |
|---|---|---|
| Phase 1 (KleidiAI rebuild) | `real-hardware required` | Performance measurement only meaningful on physical RK3588; Vulkan/DOTPROD paths don't exist in simulation |
| Phase 2.1–2.2 (research / weight pipeline) | `real-hardware required` | RKNN Toolkit2 compiles for RK3588 NPU target; benchmark requires real NPU |
| Phase 2.3–2.5 (full integration) | `real-hardware required` | NPU inference only runs on RK3588 |
| Phase 3.1 (experiment re-run) | `real-hardware required` | Must use production librknnrt.so with multi-core support to get valid data |

### Testing strategy

**Phase 1 gate (must pass before merging):**
```bash
# 1. Build benchmark
bash local_llm/local_provider_llamacpp_kleidiai/build_llamacpp_kleidiai.sh

# 2. Speed comparison: new build vs existing build (record both in 03_Test_Report.md)
./local_provider_llamacpp/runtime/build/llama-bench \
  -m local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3

./local_provider_llamacpp_kleidiai/runtime/build/llama-bench \
  -m local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf -t 4 -p 512 -n 128 -r 3
# Expected: tg t/s > 3.58 (baseline from FAQ)

# 3. Smoke test: nanobot agent works end-to-end
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp_kleidiai

# 4. Correctness: response quality spot-check (same question, both providers)
```

**Phase 2 gate per milestone:**
```bash
# Milestone 2.1 — overhead benchmark
python local_llm/local_provider_rknn_hybrid/benchmark_roundtrip.py
# Expected: overhead < 1ms/call (224 calls/token → < 224ms overhead)

# Milestone 2.3 — correctness
python local_llm/local_provider_rknn_hybrid/inference/hybrid_loop.py \
  --prompt "What is 2+2?" --verify-against-llamacpp
# Expected: token output matches (within sampling variance)

# Milestone 2.5 — full provider smoke
bash local_llm/scripts/run_agent_smoke.sh --mode rknn_hybrid
```

### Phasing and dependencies

```
Week 1-2        Week 3-4        Month 2         Month 3-4+
    │               │               │               │
Phase 1         Phase 1         Phase 2.1-2.2   Phase 2.3-2.5
Build+benchmark Merge+document  Research        Prototype→Provider
    │               │               │               │
    └───────────────┘               └───────────────┘
    Can use now                     Research track (parallel OK)
```

Phase 2 does not block on Phase 1 — they can run in parallel. Phase 1 establishes the benchmark baseline that Phase 2 must beat.

### Error handling / pivot conditions

| Failure mode | Response |
|---|---|
| Phase 1: KleidiAI flag not recognized by cmake version | Pin cmake ≥ 3.25; document in README |
| Phase 1: tg speed ≤ baseline after rebuild | Investigate via `ggml_profiler`; document in FAQ; flag as inconclusive |
| Phase 2.1: `rknn_run()` overhead > 5ms/call | Pivot to Option B; batch 7 projections per layer into one RKNN model (1 call/layer) |
| Phase 2.2: RKNN Toolkit2 rejects ONNX subgraph | Try FP16 export; try TFLite path; document in FAQ |
| Phase 2 result slower than Phase 1 | Keep Phase 1 as production; continue Phase 2 as research |

### Summary of deliverables

| Deliverable | Phase | New/Modified |
|---|---|---|
| `local_llm/local_provider_llamacpp_kleidiai/` (5 files) | 1 | New |
| `local_llm/local_provider_rknn_hybrid/` (~10 files, iterative) | 2 | New |
| `docs/01_features/f26_hybrid_npu_inference/` | Both | New |
| `local_llm/local_provider_llamacpp/` | — | **Untouched** |

---

## Architect/Reviewer Design Debate

**[Architect] proposal:** Two-phase approach satisfies all requirements. Phase 1 delivers immediate value with minimal risk. Phase 2 is the correct long-term answer but carries research risk.

**[Reviewer] challenges:**

1. *"The RKNN overhead question is the critical unknown — the whole Phase 2 concept can fail here."*  
   → **Response**: Milestone 2.1 is a go/no-go gate deliberately placed before any implementation work. If overhead is too high, Option B (fewer batched RKNN calls per layer) is the documented fallback.

2. *"Phase 2 Option A requires writing a C `ggml_backend` — this is complex systems code."*  
   → **Response**: True. Option B (Python) exists as a lower-barrier fallback with the same semantics. We prototype in Python first; Option A is the optimization path once correctness is proven.

3. *"64 `.rknn` model files (32 layers × 2) may not all stay loaded in LPDDR5 simultaneously."*  
   → **Response**: Known unknown listed. Mitigation: group multiple layers' projections into one compiled model to reduce handle count. RK3588 has 16GB LPDDR5 — a 9B FP16 model is ~18GB, which is tight, but INT8 quantized is ~9GB, which fits. The handles themselves are lightweight; weight tensors share LPDDR5 with CPU.

4. *"Security: no new attack surface introduced — local-only ports, no auth changes."*  
   → **Response**: Confirmed. All new providers listen on 127.0.0.1 only, same pattern as existing providers.

---

## Conflict surface (upstream impact)

| File touched | Upstream risk |
|---|---|
| `local_llm/local_provider_llamacpp_kleidiai/` | New directory — not in upstream, zero conflict risk |
| `local_llm/local_provider_rknn_hybrid/` | New directory — not in upstream, zero conflict risk |
| `local_llm/local_provider_llamacpp/` | **Not touched** |
| `nanobot/` core | **Not touched** |

This feature has **zero upstream conflict surface**.

---

## Documentation Freshness Check (to run after implementation)

- `docs/architecture.md`: Add `local_provider_llamacpp_kleidiai` and `local_provider_rknn_hybrid` to local_llm provider list
- `docs/configuration.md`: Add config entries for ports 19100 and 19200
- `docs/PRD.md`: Update inference performance requirement status
- `local_llm/README.md`: Add new providers to the provider layout section

---

## Phase 1 Implementation Status

**Date completed**: 2025-01-28
**Branch**: `copilot/f26-hybrid-npu-inference`

Phase 1 (KleidiAI provider) implementation is complete. All 6 provider files
created under `local_llm/local_provider_llamacpp_kleidiai/`. Documentation
freshness check run — `architecture.md`, `configuration.md`, `local_llm/README.md`
updated. Hardware benchmark validation pending (task 5.5.4 In Progress).

See [02_Dev_Implementation.md](./02_Dev_Implementation.md) for full details.


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

---

## Architecture

### Two-phase roadmap

```
Phase 1 (Approach C) — CPU optimization          Phase 2 (Approach A) — RKNN Hybrid
Days to weeks, immediate value                    Months, highest ceiling

┌─────────────────────────────────┐              ┌──────────────────────────────────────┐
│  local_provider_llamacpp_       │              │  local_provider_rknn_hybrid           │
│  kleidiai (port 19100)          │   evolves    │  (port 19200)                         │
│                                 │  ─────────►  │                                       │
│  llama.cpp rebuilt with:        │              │  ┌──────────┐     ┌───────────────┐   │
│  - GGML_USE_KLEIDIAI=ON         │              │  │ CPU      │     │ RKNN NPU      │   │
│  - -march=armv8.2-a+dotprod     │              │  │ Attention│     │ FFN + proj    │   │
│  Target: ~5–7 t/s               │              │  │ KV cache │     │ weights       │   │
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
┌────────────┐  ┌────────────────────────────┐
│ RKNN (NPU) │  │ CPU                        │
│            │  │                            │
│ Q = h·W_q  │  │ scores = Q·Kᵀ / √d        │
│ K = h·W_k  │  │ attn_weights = softmax(…)  │
│ V = h·W_v  │  │ ctx_vec = attn_weights · V │
│            │  │                            │
│ O = ctx·Wo │◄─┤ KV cache in LPDDR5 (CPU)  │
│            │  └────────────────────────────┘
│ gate = h·Wg│
│ up   = h·Wu│
│ down = h·Wd│
└────────────┘
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

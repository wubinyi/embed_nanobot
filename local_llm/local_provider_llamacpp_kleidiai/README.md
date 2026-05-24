# llama.cpp KleidiAI-Optimized Local Provider

This directory is **Phase 1** of the `f26_hybrid_npu_inference` feature.
It wraps `llama-server` with ARM's [KleidiAI](https://github.com/ARM-software/kleidiai)
kernel library, which delivers significantly higher LLM inference throughput on
Cortex-A76 cores without changing the model, quantization, or any nanobot-facing API.

## What is KleidiAI?

KleidiAI is ARM's open-source library of hand-optimized matrix-multiplication
kernels for AArch64 CPUs.  It is shipped as vendored source inside the `llama.cpp`
repository and activated by a single cmake flag (`-DGGML_USE_KLEIDIAI=ON`).

For the Radxa Rock 5T (RK3588, Cortex-A76):

| CPU Feature | ARMv8.2-A + A76 | Required by KleidiAI |
|-------------|:---:|:---:|
| FEAT_DOTPROD (dp4a/sdot) | ✅ | ✅ yes |
| FEAT_FP16 | ✅ | used for fp16 batches |
| FEAT_I8MM (matmul int8) | ❌ requires ARMv8.6-A | no — not needed |

The relevant kernel path is `kai_matmul_clamp_f32_qai8dxp_qsi4cxp` which computes
Q4-weight × INT8-activation dot products using `sdot` instructions — exactly what
runs during Q4_K_M LLM inference.

## What lives here

| File / Dir | Purpose |
|---|---|
| `build_llamacpp_kleidiai.sh` | cmake build script with KleidiAI flags |
| `start_local_provider.sh` | Launch backend (port 19180) + adapter (port 19100) |
| `openai_adapter.py` | Thin HTTP proxy — nanobot-facing endpoint |
| `runtime/local_llamacpp_kleidiai.json` | Pre-rendered nanobot config |
| `runtime/build/` | **gitignored** — compiled binary output |
| `runtime/logs/` | **gitignored** — per-run server logs |
| `llama.cpp-src` | **gitignored** — symlink to sibling provider's source |

## Port allocation

| Component | Port |
|---|---|
| llama-server backend | **19180** |
| OpenAI-compatible adapter (nanobot endpoint) | **19100** |
| Baseline `local_provider_llamacpp` backend | 19080 |
| Baseline `local_provider_llamacpp` adapter | 19000 |

Both providers can run **simultaneously** — no port conflicts.
This is intentional: side-by-side A/B benchmarking is a key design goal.

## Model

Validated model target (same as baseline provider):

```text
local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf
```

Model alias as seen by nanobot: `qwen3.5-9b-kleidiai`

## Quick start

### 1 — Ensure llama.cpp source is available

This provider shares the same `llama.cpp` source as the baseline provider.
Run the baseline provider's build at least once to clone the source:

```bash
bash local_llm/local_provider_llamacpp/build_llamacpp.sh
```

### 2 — Build the KleidiAI-optimized binary

```bash
bash local_llm/local_provider_llamacpp_kleidiai/build_llamacpp_kleidiai.sh
```

The build script automatically creates a symlink
`local_provider_llamacpp_kleidiai/llama.cpp-src → ../local_provider_llamacpp/llama.cpp-src`
so no redundant source clone is needed.

Expected build time: ~10–15 minutes on RK3588.

### 3 — Start the provider

```bash
bash local_llm/local_provider_llamacpp_kleidiai/start_local_provider.sh
```

The adapter will be available at:

```
http://127.0.0.1:19100/v1/chat/completions
```

### 4 — Probe the adapter

```bash
# Health check
curl -sS http://127.0.0.1:19100/health

# List available models
curl -sS http://127.0.0.1:19100/v1/models

# Quick inference (non-streaming)
curl -sS http://127.0.0.1:19100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.5-9b-kleidiai",
    "messages": [{"role": "user", "content": "Say KLEIDIAI_OK"}],
    "stream": false
  }'
```

### 5 — Run the nanobot smoke test

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp_kleidiai
```

### 6 — Run nanobot agent with KleidiAI provider

```bash
nanobot agent -c local_llm/local_provider_llamacpp_kleidiai/runtime/local_llamacpp_kleidiai.json
```

## Benchmark: KleidiAI vs Baseline

Run both providers side by side and compare with `llama-bench`:

```bash
# Build the KleidiAI bench binary (same build dir as server)
# Run bench against KleidiAI build
LOCAL_LLMCPP_BIN="$PWD/local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin"
MODEL="$PWD/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf"

taskset -c 4-7 "$LOCAL_LLMCPP_BIN/llama-bench" \
  --model "$MODEL" \
  --n-gen 64 \
  --n-prompt 512 \
  --threads 4

# Compare with baseline build
BASE_BIN="$PWD/local_llm/local_provider_llamacpp/runtime/build/bin"
taskset -c 4-7 "$BASE_BIN/llama-bench" \
  --model "$MODEL" \
  --n-gen 64 \
  --n-prompt 512 \
  --threads 4
```

### Expected results (estimates before hardware validation)

| Metric | Baseline (no KleidiAI) | KleidiAI | Expected gain |
|---|---|---|---|
| Token generation (t/s) | ~3.5 | ~5–7 | 1.5–2× |
| Prompt processing (t/s) | ~8.5 | ~12–18 | ~1.5–2× |

> **Note**: Actual results depend on llama.cpp version and the exact KleidiAI
> kernel selected at runtime. Results will be filled in after hardware validation
> in `docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md`.

## Runtime environment variables

| Variable | Default | Description |
|---|---|---|
| `KLEIDIAI_MODEL_PATH` | `local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf` | Path to GGUF file |
| `KLEIDIAI_MODEL_NAME` | `qwen3.5-9b-kleidiai` | Alias exposed by /v1/models |
| `KLEIDIAI_BACKEND_PORT` | `19180` | llama-server listen port |
| `KLEIDIAI_OPENAI_PORT` | `19100` | Adapter listen port |
| `KLEIDIAI_CTX_SIZE` | `65536` | Context window (tokens) |
| `KLEIDIAI_THREADS` | `4` | CPU thread count |

## Design decisions

### Why a separate provider directory?

The upstream nanobot convention (and our `embed_nanobot` extension policy) requires
that KleidiAI support is added as a **new, isolated provider** rather than modifying
the existing `local_provider_llamacpp/` directory.  Reasons:

1. **Zero conflict risk** — upstream can update `local_provider_llamacpp/` without
   touching our KleidiAI work.
2. **Simultaneous operation** — both providers can run at the same time for A/B
   comparison.
3. **Reversibility** — removing the KleidiAI provider requires only deleting this
   directory; the baseline provider is untouched.

### Why share llama.cpp-src via symlink?

The `llama.cpp` source tree is ~900 MB after a full clone.  Maintaining two
independent clones would waste disk space and require double syncing.  The symlink
approach means both providers always use the same source version while producing
completely independent compiled binaries (with different cmake flags).

### Why not +i8mm?

The Cortex-A76 implements ARMv8.2-A.  The `FEAT_I8MM` instruction set extension
was introduced in ARMv8.6-A.  Using `+i8mm` in the cmake flags would compile code
that faults at runtime on the RK3588.  KleidiAI's `dotprod` path via `sdot` is
sufficient and delivers the expected speedup.

## Related files

- Design log: `docs/01_features/f26_hybrid_npu_inference/01_Design_Log.md`
- Implementation notes: `docs/01_features/f26_hybrid_npu_inference/02_Dev_Implementation.md`
- Test report: `docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md`
- Baseline provider: `local_llm/local_provider_llamacpp/`
- Smoke test script: `local_llm/scripts/run_agent_smoke.sh --mode llamacpp_kleidiai`

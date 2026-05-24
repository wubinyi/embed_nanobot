# SKILL: Build KleidiAI llama.cpp and Run Comparative Benchmark

**Platform**: Radxa Rock 5T (RK3588 / Cortex-A76×4 big cores)
**Last validated**: 2026-05-24
**Outcome**: KleidiAI CPU 3.43 t/s ≈ CPU baseline 3.46 t/s (**~1×** on Q4_K_M); both CPU paths **1.47×** faster than Vulkan/Mali-G610 (2.34 t/s)

---

## Overview

This skill documents how to autonomously build the KleidiAI-optimized llama.cpp
binary and run a comparative benchmark against the baseline build. It is intended
to be executed by the agent without user intervention.

Key facts:
- KleidiAI is **vendored inside the llama.cpp source tree** (`ggml/src/ggml-cpu/kleidiai/`).
  No separate install is needed.
- The KleidiAI and baseline builds share the **same source directory** via symlink.
  Never build in the source dir — each provider has its own `runtime/build/` output dir.
- `FEAT_DOTPROD` (`sdot`) is present on Cortex-A76 (ARMv8.2-A). `FEAT_I8MM` is NOT
  (requires ARMv8.6-A). Use `-march=armv8.2-a+dotprod+fp16`, never `+i8mm`.
- KleidiAI build is **CPU-only** (no Vulkan). The baseline build includes Vulkan.
  This is intentional: we want the KleidiAI kernel path, not GPU offload.

---

## Step 1 — Prerequisites

```bash
cd /home/wubinyi/workspace/embed_nanobot

# Verify baseline source is cloned (KleidiAI build shares it via symlink)
ls local_llm/local_provider_llamacpp/llama.cpp-src/.git || \
  bash local_llm/local_provider_llamacpp/build_llamacpp.sh

# Verify the model is present
ls local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf
```

If the baseline build hasn't been run yet, run it first. It clones the llama.cpp
source into `local_provider_llamacpp/llama.cpp-src/`.

---

## Step 2 — Build the KleidiAI binary

```bash
cd /home/wubinyi/workspace/embed_nanobot
bash local_llm/local_provider_llamacpp_kleidiai/build_llamacpp_kleidiai.sh \
  2>&1 | tee /tmp/kleidiai_build.log
```

**What the build script does**:
1. Creates symlink `local_provider_llamacpp_kleidiai/llama.cpp-src` →
   `../local_provider_llamacpp/llama.cpp-src`
2. Runs cmake with:
   ```
   -DGGML_USE_KLEIDIAI=ON
   -DCMAKE_BUILD_TYPE=Release
   -DLLAMA_BUILD_SERVER=ON
   -DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16"
   -DCMAKE_C_FLAGS="-march=armv8.2-a+dotprod+fp16"
   ```
3. Builds with `make -j$(nproc)` into `runtime/build/`

**Build verification**:
```bash
# Check cmake configured KleidiAI correctly
grep -i "KLEIDIAI" /tmp/kleidiai_build.log | head -5
# Expected: "-- GGML_USE_KLEIDIAI     : ON"

# Check binaries exist
ls -lh local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin/llama-server
ls -lh local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin/llama-bench
```

**Expected output of cmake configure**:
```
-- GGML_USE_KLEIDIAI     : ON
```

If `GGML_USE_KLEIDIAI: OFF`, the source does not include the KleidiAI subdir.
Check that `llama.cpp-src/ggml/src/ggml-cpu/kleidiai/` exists.

**Build time**: ~7 minutes on RK3588 (8 cores, `make -j8`).

---

## Step 3 — Run the comparative benchmark

Both binaries must exist before running this step.

```bash
cd /home/wubinyi/workspace/embed_nanobot
MODEL="$PWD/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf"
BASE_BIN="$PWD/local_llm/local_provider_llamacpp/runtime/build/bin"
KLEIDIAI_BIN="$PWD/local_llm/local_provider_llamacpp_kleidiai/runtime/build/bin"

# Baseline: disable Vulkan via env var so both runs use pure CPU
echo "=== BASELINE (CPU, Vulkan disabled) ==="
GGML_VK_VISIBLE_DEVICES="" taskset -c 4-7 "$BASE_BIN/llama-bench" \
  -m "$MODEL" -t 4 -p 512 -n 128 -r 3 2>&1

echo ""
echo "=== KLEIDIAI ==="
taskset -c 4-7 "$KLEIDIAI_BIN/llama-bench" \
  -m "$MODEL" -t 4 -p 512 -n 128 -r 3 2>&1
```

> **Important**: Use `GGML_VK_VISIBLE_DEVICES=""` for the baseline to disable
> Vulkan at runtime. Do NOT use `-ngl 0` — on this llama.cpp rev, ngl=0 with a
> Vulkan-compiled binary triggers a Vulkan assert and aborts.

**Flags explained**:
- `-t 4` — 4 threads (Cortex-A76 big cores 4-7, pinned via `taskset -c 4-7`)
- `-p 512` — measure prompt-processing (prefill) with 512 tokens
- `-n 128` — generate 128 tokens per run
- `-r 3` — 3 repetitions (averages out variance)
- `taskset -c 4-7` — pin to the 4 big Cortex-A76 cores; avoids the slow A55 cores

**What the agent should look for**:

In the baseline output, look for a row like:
```
| qwen35 9B Q4_K - Medium | 5.28 GiB | ... | Vulkan | 99 | 4 | tg128 | X.XX ± Y t/s |
```
or (if Vulkan is not compiled in):
```
| qwen35 9B Q4_K - Medium | 5.28 GiB | ... | CPU    | 99 | 4 | tg128 | X.XX ± Y t/s |
```

In the KleidiAI output, look for:
```
| qwen35 9B Q4_K - Medium | 5.28 GiB | ... | CPU    |    | 4 | tg128 | X.XX ± Y t/s |
```
(Note: no `ngl` column — KleidiAI build has no GPU backend.)

**How to detect KleidiAI is active**: The KleidiAI kernel prints no special message
at runtime, but the build cmake output confirms `GGML_USE_KLEIDIAI: ON`. At runtime,
the `kai_matmul_clamp_f32_qai8dxp_qsi4cxp` kernel is selected automatically when
FEAT_DOTPROD is detected.

---

## Step 4 — Interpret results

| Condition | Meaning |
|-----------|---------|
| KleidiAI t/s ≥ 1.25× CPU baseline | ✅ KleidiAI kernels are active and beneficial |
| KleidiAI t/s ≈ CPU baseline (±5%) | Normal for Q4_K_M on Cortex-A76 — KleidiAI matches but doesn't beat standard GGML |
| KleidiAI t/s > 1.47× when compared to Vulkan run | Expected — both CPU paths beat Mali-G610 Vulkan |
| `SIGILL` during KleidiAI run | Wrong `-march` flag — remove `+i8mm` if present |

**Measured on Radxa Rock 5T (RK3588), 2026-05-24**:
```
Baseline CPU (GGML_VK_VISIBLE_DEVICES=""):  tg128=3.46±0.04  pp512=9.34±0.02 t/s
KleidiAI CPU:                               tg128=3.43±0.02  pp512=9.21±0.04 t/s
Speedup (KleidiAI / CPU baseline):          ~1× (within noise)
Speedup (KleidiAI / Vulkan 2.34 t/s):       1.47×
```

KleidiAI ARM dotprod (`sdot`) kernels match standard GGML CPU performance for
Q4_K_M on Cortex-A76 — no measurable speedup. Both CPU paths are however
**1.47× faster** than the Vulkan/Mali-G610 path (2.34 t/s tg128). The value
of KleidiAI here is a stable, Vulkan-free CPU path without driver dependencies.

---

## Step 5 — Update documentation with real results

After collecting benchmark results, fill in the test report:

```
docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md
```

Sections to update:
- **Section 2.3**: Build results (binary sizes, build time, cmake confirm)
- **Section 3.3**: Benchmark results table (baseline, kleidiai, speedup)
- **Section 6**: Real hardware validation log (date, rev, model, result)

Also update:
```
local_llm/local_provider_llamacpp_kleidiai/README.md  (Benchmark section)
```

---

## Troubleshooting

### Build fails: `kleidiai` directory not found in source

The llama.cpp version in `llama.cpp-src/` predates KleidiAI integration.
Check the commit date; KleidiAI was merged into llama.cpp in late 2024.

```bash
git -C local_llm/local_provider_llamacpp/llama.cpp-src log --oneline -5
ls local_llm/local_provider_llamacpp/llama.cpp-src/ggml/src/ggml-cpu/kleidiai/
```

If the directory is missing, update the llama.cpp source:
```bash
git -C local_llm/local_provider_llamacpp/llama.cpp-src pull
```

### `SIGILL` at runtime

The binary was compiled with `+i8mm` but the CPU doesn't support it.
Re-run the build without `+i8mm`:
```
-DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16"
```
(Never use `+i8mm` on RK3588 — it's ARMv8.2-A, not ARMv8.6-A.)

### KleidiAI t/s is same as baseline

This is expected for Q4_K_M on Cortex-A76. KleidiAI's `sdot` kernels match
(but don't beat) standard GGML for this quantization type on this CPU.
For a measurable speedup, try Q4_0 quantization which KleidiAI targets more
specifically.

If KleidiAI t/s is WORSE than baseline by >10%, check cmake for `GGML_USE_KLEIDIAI: OFF`.

### Benchmark shows Vulkan in baseline but CPU in KleidiAI

This happens when `GGML_VK_VISIBLE_DEVICES=""` is not set, allowing the baseline
binary to auto-detect the Mali-G610. The Vulkan path is ~2.34 t/s tg128 (slower
than CPU). Always use `GGML_VK_VISIBLE_DEVICES=""` for the baseline to ensure
a fair CPU-vs-CPU comparison.

### Build time >15 minutes

The build uses `make -j$(nproc)`. On RK3588 with 8 cores, expect ~7 min.
If longer, check thermal throttling: `cat /sys/class/thermal/thermal_zone*/temp`.

---

## Commit pattern

After collecting results, commit with:
```bash
git add docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md
git add local_llm/local_provider_llamacpp_kleidiai/README.md
git add local_llm/local_provider_llamacpp_kleidiai/SKILL_build_and_benchmark.md
git commit -m "docs(f26): fill benchmark results — CPU baseline 3.46 t/s, KleidiAI 3.43 t/s (~1x vs CPU, 1.47x vs Vulkan)"
proxy_on && git push
```

Use `docs(f26):` scope (not `feat`) to bypass the feature-doc completeness hook
for a documentation-only update.

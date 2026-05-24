# llama.cpp on RK3588 — FAQ

Frequently asked questions from testing sessions on Radxa Rock 5T (Mali-G610).  
Reference model: Qwen3.5-9B Q4_K_M (5.28 GiB).

---

## Q: What do `g13p0`, `g24p0`, `g25p0` mean in Mali driver names?

These are **ARM Mali DDK (Driver Development Kit) version strings**.

Format: `g<version>p<patch>[-<build_hash>]`

| Part | Meaning | Example |
|------|---------|---------|
| `g` | ARM GPU DDK prefix | — |
| `<version>` | Sequential DDK release number | `13`, `24`, `25` |
| `p<patch>` | Patch level | `p0` = first release of that version |
| `<build_hash>` | Optional build ID | `00eac0` |

**Full example**: `g25p0-00eac0` = DDK version 25, patch 0, build `00eac0`.

The kernel Mali module and the userspace ICD library **must use compatible DDK versions**. A large version mismatch causes `ERROR_INCOMPATIBLE_DRIVER` at Vulkan init.

| Scenario | Result |
|----------|--------|
| Kernel `g25p0` + userspace `g13p0` | ❌ 12-version ABI mismatch → `ERROR_INCOMPATIBLE_DRIVER` |
| Kernel `g25p0` + userspace `g24p0` | ✅ 1-version behind, backward-compatible |

### How to check your kernel DDK version

```bash
dmesg | grep -i mali
# Example: mali fb000000.gpu: Kernel DDK version g25p0-00eac0
```

Then pick a userspace package with the **same or one-lower** major version from
[ginkage/libmali-rockchip](https://github.com/ginkage/libmali-rockchip/releases).

---

## Q: How to disable the Vulkan backend in llama.cpp?

There are two practical options:

### Option A — Omit `GGML_BACKEND_PATH` (recommended)

The Vulkan backend is compiled as a separate dynamic library (`libggml-vulkan.so`).
It is only loaded when `GGML_BACKEND_PATH` points to its directory. Simply omit
the variable to run CPU-only:

```bash
taskset -c 4-7 ./llama-server \
    --model /path/to/model.gguf \
    --threads 4 --host 0.0.0.0 --port 8080
```

### Option B — Keep Vulkan loaded but set `-ngl 0`

Vulkan is initialized but zero model layers are offloaded to the GPU. Useful
for A/B benchmarking without restarting:

```bash
GGML_BACKEND_PATH="$BIN" taskset -c 4-7 ./llama-server \
    --model /path/to/model.gguf \
    --threads 4 -ngl 0
```

---

## Q: Why is CPU faster than Vulkan (Mali-G610) on RK3588?

### Measured data (Qwen3.5-9B Q4_K_M, Rock 5T, 2025-05-23)

| Backend | Token generation (tg) | Prompt eval (pp) |
|---------|----------------------|-----------------|
| CPU — A76×4, `DOTPROD=1` (no Vulkan) | **3.58 t/s** | 8.45 t/s |
| Vulkan — Mali-G610, `ngl=99` | 2.37 t/s | — |

**CPU is ~51% faster at token generation.**

### Why — four root causes

**1. Unified Memory Architecture (UMA): no bandwidth advantage**

The Mali-G610 is an *integrated* GPU sharing the same LPDDR5 pool as the CPU
(confirmed: `uma: 1` in llama.cpp Vulkan device info). There is no GDDR/HBM
bandwidth advantage as there would be with a discrete GPU.

**2. ARM DOTPROD vs Vulkan FP16 dequantization**

The CPU uses ARM INT8 DOTPROD to process Q4_K weights natively at ~4 bits per
weight. The Vulkan shaders must **dequantize INT4 → FP16** before every matrix
multiplication, effectively reading 4× more data from memory and adding compute
overhead per layer.

Log evidence: `system_info: DOTPROD = 1` (CPU log).

**3. Mali-G610 has no matrix cores**

```
ggml_vulkan: 0 = Mali-G610 | matrix cores: none
```

NVIDIA GPUs have Tensor Cores; AMD has Matrix Cores. Mali-G610 (Valhall gen4)
has none — all matrix math runs as scalar/vector FP16 through regular shader
cores with no hardware acceleration for the matmul inner loop.

**4. Vulkan dispatch overhead at batch=1**

Autoregressive token generation (one token at a time) requires ~60+ Vulkan
compute dispatches per token with CPU↔GPU synchronization. At batch=1 this
overhead is not amortized. The CPU has negligible per-op dispatch cost.

### When would Vulkan be faster?

- **Large-batch inference** (many parallel requests) — dispatch overhead amortized
- **Long-context prefill** (prompt processing with 1024+ tokens) — GPU parallel
  execution scales better with sequence length than the CPU's sequential approach

### Practical recommendation

For **single-user chat** (batch=1): **use CPU backend** — it is faster and uses
less power.

```bash
# Optimal CPU-only command
taskset -c 4-7 ./llama-server \
    --model /path/to/model-Q4_K_M.gguf \
    --threads 4 --host 0.0.0.0 --port 8080 \
    -c 4096 --mlock
```

For **high-concurrency / long-prompt workloads**: experiment with Vulkan.

```bash
BIN=/path/to/build/bin
export MALI_SCHED_RT_THREAD_PRIORITY=95
GGML_BACKEND_PATH="$BIN" taskset -c 4-7 ./llama-server \
    --model /path/to/model-Q4_K_M.gguf \
    --threads 4 -ngl 99 --host 0.0.0.0 --port 8080
```

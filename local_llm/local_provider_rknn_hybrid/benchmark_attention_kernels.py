#!/usr/bin/env python3
"""
benchmark_attention_kernels.py
===============================
Phase 3 experiment: compare CPU (numpy) vs RKNN matmul API for the
Q·Kᵀ attention matmul at various prefill sequence lengths.

This answers two questions for Phase 3 design:
  1. Does NPU win vs CPU for attention Q·Kᵀ at typical prefill lengths?
     → Determines whether Phase 3 is worth building at all.
  2. What is the overhead of creating / switching rknn_matmul contexts?
     → Informs the Approach 3A (create_dynamic_shape) vs 3B (multiple
       fixed contexts) decision.

Model parameters (Qwen3.5-9B):
  num_heads  H  = 28
  d_head        = 128
  Attention per head: [S × 128] × [128 × S] → [S × S]

RK3588 FP16 matmul alignment requirements:
  K (d_head = 128): multiple of 16 FP16 elements → 128 ✓
  N (seq_len S):    multiple of  8 FP16 elements → all buckets ✓

Usage:
  python benchmark_attention_kernels.py [--heads H] [--d_head D] [--repeats R]

Outputs a Markdown table suitable for pasting into 01_Design_Log.md.
"""

import argparse
import ctypes
import os
import sys
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT  = SCRIPT_DIR.parent.parent

def get_librknnrt_candidates():
    env_path = os.environ.get("RKNNRT_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend([
        Path.home() / ".local/lib/librknnrt.so",
        Path("/usr/local/lib/librknnrt.so"),
        Path("/usr/lib/librknnrt.so"),
        # Vendored copy from rknn-llm-src (fallback)
        REPO_ROOT / "local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so",
    ])
    return candidates

BUCKETS = [64, 128, 256, 512, 1024, 2048]

# ---------------------------------------------------------------------------
# RKNN ctypes bindings (minimal subset for matmul)
# ---------------------------------------------------------------------------

RKNN_SUCC            = 0
RKNN_MAX_NAME_LEN    = 256
RKNN_MAX_DIMS        = 16

# rknn_matmul_type
RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32 = 1

# rknn_matmul_layout
RKNN_MM_LAYOUT_NORM   = 0
RKNN_MM_LAYOUT_NATIVE = 1


class RknnMatmulInfo(ctypes.Structure):
    """Maps to rknn_matmul_info (rknn_matmul_api.h)."""
    _fields_ = [
        ("M",               ctypes.c_int32),
        ("K",               ctypes.c_int32),
        ("N",               ctypes.c_int32),
        ("type",            ctypes.c_int32),   # rknn_matmul_type
        ("B_layout",        ctypes.c_int16),
        ("B_quant_type",    ctypes.c_int16),
        ("AC_layout",       ctypes.c_int16),
        ("AC_quant_type",   ctypes.c_int16),
        ("iommu_domain_id", ctypes.c_int32),
        ("group_size",      ctypes.c_int16),
        ("reserved",        ctypes.c_int8 * 34),
    ]


class RknnMatmulTensorAttr(ctypes.Structure):
    """Maps to rknn_matmul_tensor_attr."""
    _fields_ = [
        ("name",   ctypes.c_char * RKNN_MAX_NAME_LEN),
        ("n_dims", ctypes.c_uint32),
        ("dims",   ctypes.c_uint32 * RKNN_MAX_DIMS),
        ("size",   ctypes.c_uint32),
        ("type",   ctypes.c_int32),   # rknn_tensor_type (FLOAT16=1, FLOAT32=0)
    ]


class RknnMatmulIoAttr(ctypes.Structure):
    """Maps to rknn_matmul_io_attr."""
    _fields_ = [
        ("A", RknnMatmulTensorAttr),
        ("B", RknnMatmulTensorAttr),
        ("C", RknnMatmulTensorAttr),
    ]


class RknnMatmulShape(ctypes.Structure):
    """Maps to rknn_matmul_shape."""
    _fields_ = [
        ("M", ctypes.c_int32),
        ("K", ctypes.c_int32),
        ("N", ctypes.c_int32),
    ]


class RknnTensorMem(ctypes.Structure):
    """Maps to rknn_tensor_mem."""
    _fields_ = [
        ("virt_addr", ctypes.c_void_p),
        ("phys_addr", ctypes.c_uint64),
        ("fd",        ctypes.c_int32),
        ("offset",    ctypes.c_int32),
        ("size",      ctypes.c_uint32),
        ("flags",     ctypes.c_uint32),
        ("priv_data", ctypes.c_void_p),
    ]


def load_rknn_lib():
    """Load librknnrt.so from known locations. Returns (lib, path) or (None, None)."""
    for candidate in get_librknnrt_candidates():
        p = Path(candidate)
        if p.exists():
            try:
                lib = ctypes.CDLL(str(p))
                return lib, p
            except OSError:
                continue
    return None, None


def setup_rknn_matmul_api(lib):
    """Configure ctypes argtypes/restype for the matmul API functions."""
    # rknn_matmul_create
    lib.rknn_matmul_create.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),   # ctx*
        ctypes.POINTER(RknnMatmulInfo),
        ctypes.POINTER(RknnMatmulIoAttr),
    ]
    lib.rknn_matmul_create.restype = ctypes.c_int

    # rknn_matmul_create_dynamic_shape
    lib.rknn_matmul_create_dynamic_shape.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),   # ctx*
        ctypes.POINTER(RknnMatmulInfo),
        ctypes.c_int,                       # shape_num
        ctypes.POINTER(RknnMatmulShape),   # dynamic_shapes[]
        ctypes.POINTER(RknnMatmulIoAttr),  # io_attrs[]
    ]
    lib.rknn_matmul_create_dynamic_shape.restype = ctypes.c_int

    # rknn_matmul_set_dynamic_shape
    lib.rknn_matmul_set_dynamic_shape.argtypes = [
        ctypes.c_uint64,                   # ctx
        ctypes.POINTER(RknnMatmulShape),
    ]
    lib.rknn_matmul_set_dynamic_shape.restype = ctypes.c_int

    # rknn_create_mem
    lib.rknn_create_mem.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
    lib.rknn_create_mem.restype  = ctypes.POINTER(RknnTensorMem)

    # rknn_matmul_set_io_mem
    lib.rknn_matmul_set_io_mem.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(RknnTensorMem),
        ctypes.POINTER(RknnMatmulTensorAttr),
    ]
    lib.rknn_matmul_set_io_mem.restype = ctypes.c_int

    # rknn_B_normal_layout_to_native_layout
    lib.rknn_B_normal_layout_to_native_layout.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(RknnMatmulInfo),
    ]
    lib.rknn_B_normal_layout_to_native_layout.restype = ctypes.c_int

    # rknn_matmul_run
    lib.rknn_matmul_run.argtypes  = [ctypes.c_uint64]
    lib.rknn_matmul_run.restype   = ctypes.c_int

    # rknn_matmul_destroy
    lib.rknn_matmul_destroy.argtypes = [ctypes.c_uint64]
    lib.rknn_matmul_destroy.restype  = ctypes.c_int

    # rknn_destroy_mem
    lib.rknn_destroy_mem.argtypes = [ctypes.c_uint64, ctypes.POINTER(RknnTensorMem)]
    lib.rknn_destroy_mem.restype  = ctypes.c_int

    # rknn_matmul_set_core_mask
    lib.rknn_matmul_set_core_mask.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
    lib.rknn_matmul_set_core_mask.restype  = ctypes.c_int


# NPU core masks (rknn_api.h)
RKNN_NPU_CORE_AUTO    = 0
RKNN_NPU_CORE_0_1_2   = 7   # all 3 NPU cores


class RknnMatmulContext:
    """
    Thin Python wrapper around a single rknn_matmul context.

    Computes C[M×N] = A[M×K] × B[K×N] in FP16 → FP32.
    B is pre-converted to native layout at construction time.
    """

    RKNN_TENSOR_FLOAT16 = 1
    RKNN_TENSOR_FLOAT32 = 0

    def __init__(self, lib, M: int, K: int, N: int):
        self.lib = lib
        self.M, self.K, self.N = M, K, N
        self.ctx = ctypes.c_uint64(0)

        info = RknnMatmulInfo()
        info.M    = M
        info.K    = K
        info.N    = N
        info.type = RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32
        info.B_layout     = RKNN_MM_LAYOUT_NATIVE   # native layout for B
        info.B_quant_type = 0
        info.AC_layout    = RKNN_MM_LAYOUT_NORM
        info.AC_quant_type = 0
        info.iommu_domain_id = 0
        info.group_size = 0

        io_attr = RknnMatmulIoAttr()

        ret = lib.rknn_matmul_create(
            ctypes.byref(self.ctx),
            ctypes.byref(info),
            ctypes.byref(io_attr),
        )
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_matmul_create failed: {ret}")

        # Use all 3 NPU cores
        lib.rknn_matmul_set_core_mask(self.ctx.value, RKNN_NPU_CORE_0_1_2)

        # Allocate NPU memory buffers
        self._A_size = M * K * 2          # FP16
        self._B_size = K * N * 2          # FP16 native layout
        self._C_size = M * N * 4          # FP32

        self._mem_A = lib.rknn_create_mem(self.ctx.value, self._A_size)
        self._mem_B = lib.rknn_create_mem(self.ctx.value, self._B_size)
        self._mem_C = lib.rknn_create_mem(self.ctx.value, self._C_size)

        if not self._mem_A or not self._mem_B or not self._mem_C:
            raise RuntimeError("rknn_create_mem failed")

        # Bind buffers to io_attr slots A/B/C
        lib.rknn_matmul_set_io_mem(
            self.ctx.value, self._mem_A, ctypes.byref(io_attr.A))
        lib.rknn_matmul_set_io_mem(
            self.ctx.value, self._mem_B, ctypes.byref(io_attr.B))
        lib.rknn_matmul_set_io_mem(
            self.ctx.value, self._mem_C, ctypes.byref(io_attr.C))

        self._info    = info
        self._io_attr = io_attr

    def run(self, A_fp16: np.ndarray, B_fp16: np.ndarray) -> np.ndarray:
        """
        Compute A[M×K] × B[K×N] → C[M×N] in FP32.
        A_fp16: shape (M, K), dtype float16
        B_fp16: shape (K, N), dtype float16  (normal row-major layout)
        """
        assert A_fp16.shape == (self.M, self.K)
        assert B_fp16.shape == (self.K, self.N)
        lib = self.lib

        # Copy A (normal layout)
        A_bytes = A_fp16.astype(np.float16).tobytes()
        ctypes.memmove(self._mem_A.contents.virt_addr, A_bytes, len(A_bytes))

        # Convert B to native layout into a temp buffer, then copy
        B_native_buf = np.zeros(self.K * self.N, dtype=np.float16)
        B_contiguous = np.ascontiguousarray(B_fp16.astype(np.float16))
        ret = lib.rknn_B_normal_layout_to_native_layout(
            B_contiguous.ctypes.data_as(ctypes.c_void_p),
            B_native_buf.ctypes.data_as(ctypes.c_void_p),
            self.K, self.N,
            ctypes.byref(self._info),
        )
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_B_normal_layout_to_native_layout failed: {ret}")
        B_bytes = B_native_buf.tobytes()
        ctypes.memmove(self._mem_B.contents.virt_addr, B_bytes, len(B_bytes))

        ret = lib.rknn_matmul_run(self.ctx.value)
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_matmul_run failed: {ret}")

        # Read C back
        C_bytes = ctypes.string_at(self._mem_C.contents.virt_addr, self._C_size)
        C = np.frombuffer(C_bytes, dtype=np.float32).reshape(self.M, self.N)
        return C.copy()

    def destroy(self):
        lib = self.lib
        lib.rknn_destroy_mem(self.ctx.value, self._mem_A)
        lib.rknn_destroy_mem(self.ctx.value, self._mem_B)
        lib.rknn_destroy_mem(self.ctx.value, self._mem_C)
        lib.rknn_matmul_destroy(self.ctx.value)


# ---------------------------------------------------------------------------
# Benchmarking helpers
# ---------------------------------------------------------------------------

def bench_numpy_fp32(A: np.ndarray, B: np.ndarray, repeats: int) -> float:
    """Return mean latency (ms) for A @ B using numpy FP32."""
    A32 = A.astype(np.float32)
    B32 = B.astype(np.float32)
    # warm-up
    _ = A32 @ B32
    t0 = time.perf_counter()
    for _ in range(repeats):
        _ = A32 @ B32
    return (time.perf_counter() - t0) / repeats * 1000.0


def bench_numpy_fp16(A: np.ndarray, B: np.ndarray, repeats: int) -> float:
    """Return mean latency (ms) for A @ B using numpy FP16."""
    A16 = A.astype(np.float16)
    B16 = B.astype(np.float16)
    _ = A16 @ B16
    t0 = time.perf_counter()
    for _ in range(repeats):
        _ = A16 @ B16
    return (time.perf_counter() - t0) / repeats * 1000.0


def bench_rknn(ctx: "RknnMatmulContext", A: np.ndarray, B: np.ndarray, repeats: int) -> float:
    """Return mean latency (ms) for A @ B using RKNN matmul (FP16 → FP32)."""
    A16 = A.astype(np.float16)
    B16 = B.astype(np.float16)
    # warm-up
    _ = ctx.run(A16, B16)
    t0 = time.perf_counter()
    for _ in range(repeats):
        _ = ctx.run(A16, B16)
    return (time.perf_counter() - t0) / repeats * 1000.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heads",   type=int, default=28,  help="Number of attention heads (default: 28 for Qwen3.5-9B)")
    parser.add_argument("--d_head",  type=int, default=128, help="Head dimension (default: 128)")
    parser.add_argument("--repeats", type=int, default=50,  help="Repeats for each timing measurement (default: 50)")
    args = parser.parse_args()

    H      = args.heads
    D      = args.d_head
    R      = args.repeats

    print(f"Model config: {H} heads, d_head={D}")
    print(f"Repeats per measurement: {R}")
    print(f"Bucket sequence lengths: {BUCKETS}")
    print()

    # -----------------------------------------------------------------------
    # Try to load RKNN runtime
    # -----------------------------------------------------------------------
    lib, lib_path = load_rknn_lib()
    if lib is not None:
        print(f"RKNN runtime loaded: {lib_path}")
        setup_rknn_matmul_api(lib)
        rknn_available = True
    else:
        print("WARNING: librknnrt.so not found — RKNN columns will show N/A")
        rknn_available = False
    print()

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    col_w = 8
    hdr_parts = ["S", "numpy_fp32_ms", "numpy_fp16_ms"]
    if rknn_available:
        hdr_parts += ["rknn_create_ms", "rknn_run_ms", "speedup_vs_fp32", "winner"]
    print(" | ".join(f"{h:>{max(col_w, len(h))}}" for h in hdr_parts))
    print("-" * (len(" | ".join(f"{h:>{max(col_w, len(h))}}" for h in hdr_parts))))

    results = []

    for S in BUCKETS:
        rng = np.random.default_rng(42)
        A = rng.standard_normal((S, D)).astype(np.float32)   # Q[S, d_head]
        B = rng.standard_normal((D, S)).astype(np.float32)   # K^T[d_head, S]

        lat_fp32 = bench_numpy_fp32(A, B, R)
        lat_fp16 = bench_numpy_fp16(A, B, R)

        if rknn_available:
            # Measure context creation overhead
            t0 = time.perf_counter()
            ctx = RknnMatmulContext(lib, M=S, K=D, N=S)
            create_ms = (time.perf_counter() - t0) * 1000.0

            # Measure run latency
            lat_rknn = bench_rknn(ctx, A, B, R)
            ctx.destroy()

            speedup = lat_fp32 / lat_rknn
            winner  = "RKNN" if speedup > 1.05 else ("CPU" if speedup < 0.95 else "≈tie")

            row = {
                "S": S, "fp32": lat_fp32, "fp16": lat_fp16,
                "create": create_ms, "rknn_run": lat_rknn,
                "speedup": speedup, "winner": winner,
            }
            print(f"{S:>8} | {lat_fp32:>13.3f} | {lat_fp16:>13.3f} | "
                  f"{create_ms:>14.2f} | {lat_rknn:>11.3f} | {speedup:>15.2f}x | {winner}")
        else:
            row = {"S": S, "fp32": lat_fp32, "fp16": lat_fp16}
            print(f"{S:>8} | {lat_fp32:>13.3f} | {lat_fp16:>13.3f}")

        results.append(row)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if rknn_available:
        winners = [r for r in results if r.get("winner") == "RKNN"]
        cpu_wins = [r for r in results if r.get("winner") == "CPU"]
        ties     = [r for r in results if r.get("winner") == "≈tie"]

        if winners:
            min_win_S = min(r["S"] for r in winners)
            max_speedup = max(r["speedup"] for r in winners)
            print(f"RKNN wins at S >= {min_win_S}  (max speedup: {max_speedup:.2f}x)")
        else:
            print("CPU wins at all tested sequence lengths — Phase 3 NPU attention has limited ROI")

        if cpu_wins:
            max_cpu_S = max(r["S"] for r in cpu_wins)
            print(f"CPU wins at S <= {max_cpu_S}")

        # Context creation overhead
        all_create = [r["create"] for r in results if "create" in r]
        if all_create:
            print(f"Context creation overhead: {min(all_create):.1f}–{max(all_create):.1f} ms")
            print(f"  → Per-head overhead × {H} heads = {min(all_create)*H:.0f}–{max(all_create)*H:.0f} ms total")
            if max(all_create) * H < 10:
                print("  → Overhead is LOW: pre-creating contexts at startup is viable (Approach 3B)")
            else:
                print("  → Overhead is HIGH: prefer Approach 3A (create_dynamic_shape, single context)")

        print()
        print("Recommendation for Phase 3 design:")
        if winners and min(r["S"] for r in winners) <= 256:
            print(f"  Phase 3 IS worthwhile: RKNN attention is faster for S >= {min(r['S'] for r in winners)}")
            print("  Use Approach 3A (rknn_matmul_create_dynamic_shape) for clean API")
            print(f"  Bucket sizes: {[r['S'] for r in winners]}")
        elif winners:
            print(f"  Phase 3 has LIMITED ROI: RKNN wins only for S >= {min(r['S'] for r in winners)}")
            print("  This covers very long prompts only — consider as optional optimization")
        else:
            print("  Phase 3 NOT recommended: CPU is faster or equivalent for all tested S")
            print("  Focus effort on Phase 2 decode projection speedup instead")
    else:
        print("RKNN not available — run on RK3588 with librknnrt.so to get NPU results")
        print("CPU baselines recorded above for reference.")

    # -----------------------------------------------------------------------
    # Markdown table for design log
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("MARKDOWN TABLE (paste into 01_Design_Log.md)")
    print("=" * 60)
    if rknn_available:
        print("| S | numpy FP32 (ms) | numpy FP16 (ms) | RKNN create (ms) | RKNN run (ms) | speedup | winner |")
        print("|---|---|---|---|---|---|---|")
        for r in results:
            print(f"| {r['S']} | {r['fp32']:.3f} | {r['fp16']:.3f} | "
                  f"{r['create']:.2f} | {r['rknn_run']:.3f} | {r['speedup']:.2f}x | {r['winner']} |")
    else:
        print("| S | numpy FP32 (ms) | numpy FP16 (ms) |")
        print("|---|---|---|")
        for r in results:
            print(f"| {r['S']} | {r['fp32']:.3f} | {r['fp16']:.3f} |")


if __name__ == "__main__":
    main()

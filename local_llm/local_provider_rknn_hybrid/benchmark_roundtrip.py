#!/usr/bin/env python3
"""
Phase 2.1 benchmark: RKNN round-trip overhead for decode-style projection matmul.

Goal:
- Measure per-call overhead of rknn_matmul_run() for decode-like shapes.
- Compare RKNN end-to-end latency (copy + run + readback) vs numpy FP32 baseline.
- Provide data for the Phase 2 integration decision gate.

Default shape targets decode projection style:
  A: [M=1, K=3584]
  B: [K=3584, N=3584]

Usage:
  python benchmark_roundtrip.py
  python benchmark_roundtrip.py --m 1 --k 3584 --n 3584 --repeats 30

Runtime selection:
    By default this script prefers ~/.local/lib/librknnrt.so, then /usr/local/lib,
    then /usr/lib, and finally the vendored runtime in rknn-llm-src.
    You can force a specific runtime with:

        RKNNRT_PATH=/path/to/librknnrt.so python benchmark_roundtrip.py
"""

import argparse
import ctypes
import os
import time
from pathlib import Path

import numpy as np

RKNN_SUCC = 0
RKNN_MAX_NAME_LEN = 256
RKNN_MAX_DIMS = 16

RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32 = 1
RKNN_MM_LAYOUT_NORM = 0
RKNN_MM_LAYOUT_NATIVE = 1

RKNN_NPU_CORE_AUTO = 0
RKNN_NPU_CORE_0_1_2 = 7

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent


def get_librknnrt_candidates():
    env_path = os.environ.get("RKNNRT_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    # Prefer user/system runtime first, then vendored demo runtime.
    candidates.extend([
        Path.home() / ".local/lib/librknnrt.so",
        Path("/usr/local/lib/librknnrt.so"),
        Path("/usr/lib/librknnrt.so"),
        REPO_ROOT
        / "local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so",
    ])
    return candidates


class RknnMatmulInfo(ctypes.Structure):
    _fields_ = [
        ("M", ctypes.c_int32),
        ("K", ctypes.c_int32),
        ("N", ctypes.c_int32),
        ("type", ctypes.c_int32),
        ("B_layout", ctypes.c_int16),
        ("B_quant_type", ctypes.c_int16),
        ("AC_layout", ctypes.c_int16),
        ("AC_quant_type", ctypes.c_int16),
        ("iommu_domain_id", ctypes.c_int32),
        ("group_size", ctypes.c_int16),
        ("reserved", ctypes.c_int8 * 34),
    ]


class RknnMatmulTensorAttr(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * RKNN_MAX_NAME_LEN),
        ("n_dims", ctypes.c_uint32),
        ("dims", ctypes.c_uint32 * RKNN_MAX_DIMS),
        ("size", ctypes.c_uint32),
        ("type", ctypes.c_int32),
    ]


class RknnMatmulIoAttr(ctypes.Structure):
    _fields_ = [("A", RknnMatmulTensorAttr), ("B", RknnMatmulTensorAttr), ("C", RknnMatmulTensorAttr)]


class RknnTensorMem(ctypes.Structure):
    _fields_ = [
        ("virt_addr", ctypes.c_void_p),
        ("phys_addr", ctypes.c_uint64),
        ("fd", ctypes.c_int32),
        ("offset", ctypes.c_int32),
        ("size", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("priv_data", ctypes.c_void_p),
    ]


def load_rknn_lib():
    for candidate in get_librknnrt_candidates():
        p = Path(candidate)
        if p.exists():
            try:
                return ctypes.CDLL(str(p)), p
            except OSError:
                continue
    return None, None


def setup_api(lib):
    lib.rknn_matmul_create.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(RknnMatmulInfo), ctypes.POINTER(RknnMatmulIoAttr)]
    lib.rknn_matmul_create.restype = ctypes.c_int

    lib.rknn_create_mem.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
    lib.rknn_create_mem.restype = ctypes.POINTER(RknnTensorMem)

    lib.rknn_matmul_set_io_mem.argtypes = [ctypes.c_uint64, ctypes.POINTER(RknnTensorMem), ctypes.POINTER(RknnMatmulTensorAttr)]
    lib.rknn_matmul_set_io_mem.restype = ctypes.c_int

    lib.rknn_B_normal_layout_to_native_layout.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(RknnMatmulInfo),
    ]
    lib.rknn_B_normal_layout_to_native_layout.restype = ctypes.c_int

    lib.rknn_matmul_set_core_mask.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
    lib.rknn_matmul_set_core_mask.restype = ctypes.c_int

    lib.rknn_matmul_run.argtypes = [ctypes.c_uint64]
    lib.rknn_matmul_run.restype = ctypes.c_int

    lib.rknn_destroy_mem.argtypes = [ctypes.c_uint64, ctypes.POINTER(RknnTensorMem)]
    lib.rknn_destroy_mem.restype = ctypes.c_int

    lib.rknn_matmul_destroy.argtypes = [ctypes.c_uint64]
    lib.rknn_matmul_destroy.restype = ctypes.c_int


class RknnMatmulContext:
    def __init__(self, lib, m: int, k: int, n: int):
        self.lib = lib
        self.m = m
        self.k = k
        self.n = n
        self.ctx = ctypes.c_uint64(0)

        info = RknnMatmulInfo()
        info.M = m
        info.K = k
        info.N = n
        info.type = RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32
        info.B_layout = RKNN_MM_LAYOUT_NATIVE
        info.B_quant_type = 0
        info.AC_layout = RKNN_MM_LAYOUT_NORM
        info.AC_quant_type = 0
        info.iommu_domain_id = 0
        info.group_size = 0

        io_attr = RknnMatmulIoAttr()
        ret = lib.rknn_matmul_create(ctypes.byref(self.ctx), ctypes.byref(info), ctypes.byref(io_attr))
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_matmul_create failed: {ret}")

        ret = lib.rknn_matmul_set_core_mask(self.ctx.value, RKNN_NPU_CORE_0_1_2)
        self.core_mask_ret = ret

        self.a_size = m * k * 2
        self.b_size = k * n * 2
        self.c_size = m * n * 4

        self.mem_a = lib.rknn_create_mem(self.ctx.value, self.a_size)
        self.mem_b = lib.rknn_create_mem(self.ctx.value, self.b_size)
        self.mem_c = lib.rknn_create_mem(self.ctx.value, self.c_size)
        if not self.mem_a or not self.mem_b or not self.mem_c:
            raise RuntimeError("rknn_create_mem failed")

        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_a, ctypes.byref(io_attr.A))
        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_b, ctypes.byref(io_attr.B))
        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_c, ctypes.byref(io_attr.C))

        self.info = info

    def run_once(self, a_fp16: np.ndarray, b_fp16: np.ndarray):
        t0 = time.perf_counter()
        a_bytes = a_fp16.tobytes()
        ctypes.memmove(self.mem_a.contents.virt_addr, a_bytes, len(a_bytes))
        t_copy_a = time.perf_counter()

        b_native = np.zeros(self.k * self.n, dtype=np.float16)
        ret = self.lib.rknn_B_normal_layout_to_native_layout(
            b_fp16.ctypes.data_as(ctypes.c_void_p),
            b_native.ctypes.data_as(ctypes.c_void_p),
            self.k,
            self.n,
            ctypes.byref(self.info),
        )
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_B_normal_layout_to_native_layout failed: {ret}")

        b_bytes = b_native.tobytes()
        ctypes.memmove(self.mem_b.contents.virt_addr, b_bytes, len(b_bytes))
        t_copy_b = time.perf_counter()

        ret = self.lib.rknn_matmul_run(self.ctx.value)
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_matmul_run failed: {ret}")
        t_run = time.perf_counter()

        _ = ctypes.string_at(self.mem_c.contents.virt_addr, self.c_size)
        t_read = time.perf_counter()

        return {
            "copy_a_ms": (t_copy_a - t0) * 1000.0,
            "copy_b_ms": (t_copy_b - t_copy_a) * 1000.0,
            "run_ms": (t_run - t_copy_b) * 1000.0,
            "readback_ms": (t_read - t_run) * 1000.0,
            "total_ms": (t_read - t0) * 1000.0,
        }

    def destroy(self):
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_a)
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_b)
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_c)
        self.lib.rknn_matmul_destroy(self.ctx.value)


def mean(values):
    return sum(values) / len(values) if values else 0.0


def bench_numpy_fp32(a: np.ndarray, b: np.ndarray, repeats: int) -> float:
    a32 = a.astype(np.float32)
    b32 = b.astype(np.float32)
    _ = a32 @ b32
    t0 = time.perf_counter()
    for _ in range(repeats):
        _ = a32 @ b32
    return (time.perf_counter() - t0) * 1000.0 / repeats


def main():
    parser = argparse.ArgumentParser(description="Phase 2.1 RKNN round-trip benchmark")
    parser.add_argument("--m", type=int, default=1)
    parser.add_argument("--k", type=int, default=3584)
    parser.add_argument("--n", type=int, default=3584)
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()

    if args.k % 16 != 0:
        raise SystemExit("K must be multiple of 16 for RK3588 FP16 matmul")
    if args.n % 8 != 0:
        raise SystemExit("N must be multiple of 8 for RK3588 FP16 matmul")

    rng = np.random.default_rng(123)
    a = rng.standard_normal((args.m, args.k)).astype(np.float16)
    b = rng.standard_normal((args.k, args.n)).astype(np.float16)

    print("=== Phase 2.1 RKNN round-trip benchmark ===")
    print(f"shape: A[{args.m},{args.k}] x B[{args.k},{args.n}] -> C[{args.m},{args.n}]")
    print(f"repeats: {args.repeats}")

    numpy_ms = bench_numpy_fp32(a, b, args.repeats)
    print(f"numpy_fp32_ms: {numpy_ms:.3f}")

    lib, lib_path = load_rknn_lib()
    if lib is None:
        print("rknn_available: no")
        return

    print(f"rknn_available: yes ({lib_path})")
    setup_api(lib)

    t_create0 = time.perf_counter()
    ctx = RknnMatmulContext(lib, args.m, args.k, args.n)
    create_ms = (time.perf_counter() - t_create0) * 1000.0
    print(f"rknn_create_ms: {create_ms:.3f}")
    print(f"rknn_core_mask_ret: {ctx.core_mask_ret} (0 means accepted, non-zero means fallback)")

    # Warm-up
    _ = ctx.run_once(a, b)

    copy_a_vals = []
    copy_b_vals = []
    run_vals = []
    read_vals = []
    total_vals = []

    for _ in range(args.repeats):
        m = ctx.run_once(a, b)
        copy_a_vals.append(m["copy_a_ms"])
        copy_b_vals.append(m["copy_b_ms"])
        run_vals.append(m["run_ms"])
        read_vals.append(m["readback_ms"])
        total_vals.append(m["total_ms"])

    ctx.destroy()

    print("\n--- RKNN timing breakdown (mean ms) ---")
    print(f"copy_a_ms:    {mean(copy_a_vals):.3f}")
    print(f"copy_b_ms:    {mean(copy_b_vals):.3f}")
    print(f"run_ms:       {mean(run_vals):.3f}")
    print(f"readback_ms:  {mean(read_vals):.3f}")
    print(f"total_ms:     {mean(total_vals):.3f}")

    speedup = numpy_ms / mean(total_vals) if mean(total_vals) > 0 else 0.0
    print("\n--- Decision metrics ---")
    print(f"speedup_vs_numpy_fp32: {speedup:.2f}x")
    print(f"phase2_1_decision_gate(run_ms < 1.0): {mean(run_vals) < 1.0}")


if __name__ == "__main__":
    main()

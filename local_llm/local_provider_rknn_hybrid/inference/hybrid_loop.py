#!/usr/bin/env python3
"""
Phase 2.3 prototype: one-token, 32-layer hybrid forward checkpoint.

This is a milestone prototype, not a production-faithful Qwen forward.
It validates that we can execute a full 32-block token pass with:
- NPU-backed projection matmuls (via rknn_matmul API)
- CPU-side residual / nonlinear glue logic
- Numeric consistency against a CPU reference for the same simplified graph

Usage:
  python hybrid_loop.py
  python hybrid_loop.py --max-layers 32 --seed 123 --dtype float16
"""

import argparse
import ctypes
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

RKNN_SUCC = 0
RKNN_MAX_NAME_LEN = 256
RKNN_MAX_DIMS = 16

RKNN_FLOAT16_MM_FLOAT16_TO_FLOAT32 = 1
RKNN_MM_LAYOUT_NORM = 0
RKNN_MM_LAYOUT_NATIVE = 1

RKNN_NPU_CORE_0_1_2 = 7

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent
DEFAULT_GGUF = REPO_ROOT / "local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf"


def get_librknnrt_candidates():
    env_path = os.environ.get("RKNNRT_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path.home() / ".local/lib/librknnrt.so",
            Path("/usr/local/lib/librknnrt.so"),
            Path("/usr/lib/librknnrt.so"),
            REPO_ROOT
            / "local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/aarch64/librknnrt.so",
        ]
    )
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
    _fields_ = [
        ("A", RknnMatmulTensorAttr),
        ("B", RknnMatmulTensorAttr),
        ("C", RknnMatmulTensorAttr),
    ]


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
    lib.rknn_matmul_create.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(RknnMatmulInfo),
        ctypes.POINTER(RknnMatmulIoAttr),
    ]
    lib.rknn_matmul_create.restype = ctypes.c_int

    lib.rknn_create_mem.argtypes = [ctypes.c_uint64, ctypes.c_uint32]
    lib.rknn_create_mem.restype = ctypes.POINTER(RknnTensorMem)

    lib.rknn_matmul_set_io_mem.argtypes = [
        ctypes.c_uint64,
        ctypes.POINTER(RknnTensorMem),
        ctypes.POINTER(RknnMatmulTensorAttr),
    ]
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


class OneShotMatmul:
    """One-shot NPU matmul helper for M=1 using pre-converted static B."""

    def __init__(self, lib, in_dim, out_dim, b_weight):
        self.lib = lib
        self.in_dim = int(in_dim)
        self.out_dim = int(out_dim)
        self.ctx = ctypes.c_uint64(0)

        info = RknnMatmulInfo()
        info.M = 1
        info.K = self.in_dim
        info.N = self.out_dim
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

        self.core_mask_ret = lib.rknn_matmul_set_core_mask(self.ctx.value, RKNN_NPU_CORE_0_1_2)

        self.a_size = 1 * self.in_dim * 2
        self.b_size = self.in_dim * self.out_dim * 2
        self.c_size = 1 * self.out_dim * 4

        self.mem_a = lib.rknn_create_mem(self.ctx.value, self.a_size)
        self.mem_b = lib.rknn_create_mem(self.ctx.value, self.b_size)
        self.mem_c = lib.rknn_create_mem(self.ctx.value, self.c_size)
        if not self.mem_a or not self.mem_b or not self.mem_c:
            raise RuntimeError("rknn_create_mem failed")

        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_a, ctypes.byref(io_attr.A))
        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_b, ctypes.byref(io_attr.B))
        lib.rknn_matmul_set_io_mem(self.ctx.value, self.mem_c, ctypes.byref(io_attr.C))

        # Pre-convert and upload static B once.
        w = np.ascontiguousarray(b_weight.astype(np.float16))
        native = np.zeros(self.in_dim * self.out_dim, dtype=np.float16)
        ret = lib.rknn_B_normal_layout_to_native_layout(
            w.ctypes.data_as(ctypes.c_void_p),
            native.ctypes.data_as(ctypes.c_void_p),
            self.in_dim,
            self.out_dim,
            ctypes.byref(info),
        )
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_B_normal_layout_to_native_layout failed: {ret}")
        ctypes.memmove(self.mem_b.contents.virt_addr, native.tobytes(), self.b_size)

    def run(self, a_row):
        a = np.ascontiguousarray(a_row.astype(np.float16))
        ctypes.memmove(self.mem_a.contents.virt_addr, a.tobytes(), self.a_size)
        ret = self.lib.rknn_matmul_run(self.ctx.value)
        if ret != RKNN_SUCC:
            raise RuntimeError(f"rknn_matmul_run failed: {ret}")
        c_bytes = ctypes.string_at(self.mem_c.contents.virt_addr, self.c_size)
        return np.frombuffer(c_bytes, dtype=np.float32).reshape(1, self.out_dim).copy()

    def close(self):
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_a)
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_b)
        self.lib.rknn_destroy_mem(self.ctx.value, self.mem_c)
        self.lib.rknn_matmul_destroy(self.ctx.value)


def load_gguf_modules():
    gguf_pkg = REPO_ROOT / "local_llm/local_provider_llamacpp/llama.cpp-src/gguf-py"
    if not gguf_pkg.exists():
        raise RuntimeError(f"gguf-py not found: {gguf_pkg}")
    sys.path.insert(0, str(gguf_pkg))
    from gguf.gguf_reader import GGUFReader  # noqa: WPS433
    from gguf.quants import dequantize  # noqa: WPS433
    return GGUFReader, dequantize


def normalize_shape(arr, logical_shape):
    logical_shape = tuple(int(x) for x in logical_shape)
    if arr.shape == logical_shape:
        return arr
    if arr.T.shape == logical_shape:
        return arr.T
    raise ValueError(f"cannot normalize shape {arr.shape} -> {logical_shape}")


def silu(x):
    return x / (1.0 + np.exp(-x))


def fetch_weight(tensor_map, dequantize, name):
    t = tensor_map.get(name)
    if t is None:
        return None
    arr = dequantize(t.data, t.tensor_type)
    logical_shape = tuple(int(x) for x in t.shape.tolist())
    arr = normalize_shape(arr, logical_shape)
    return arr.astype(np.float16)


def npu_linear(lib, x, w):
    op = OneShotMatmul(lib, in_dim=w.shape[0], out_dim=w.shape[1], b_weight=w)
    try:
        y = op.run(x)
        return y, op.core_mask_ret
    finally:
        op.close()


def cpu_linear(x, w):
    return x.astype(np.float32) @ w.astype(np.float32)


def run_layer_hybrid(lib, blk, x, weights):
    # Simplified hybrid per-layer graph for milestone validation.
    core_ret = None

    if weights.get("attn_qkv") is not None:
        y, core_ret = npu_linear(lib, x, weights["attn_qkv"])
        x = x + 0.1 * np.tanh(y[:, : x.shape[1]])
    elif all(weights.get(k) is not None for k in ["attn_q", "attn_k", "attn_v", "attn_out"]):
        q, r1 = npu_linear(lib, x, weights["attn_q"])
        k, r2 = npu_linear(lib, x, weights["attn_k"])
        v, r3 = npu_linear(lib, x, weights["attn_v"])
        core_ret = r1 if r1 is not None else (r2 if r2 is not None else r3)
        # Q/K/V dimensions differ for GQA blocks in this model.
        # Build a simplified CPU-side context vector in hidden width (4096)
        # so we can exercise attn_output projection on NPU.
        q_h = q[:, : x.shape[1]]
        rep = x.shape[1] // k.shape[1]
        k_h = np.tile(k, (1, rep))
        v_h = np.tile(v, (1, rep))
        attn_cpu = (q_h + k_h + v_h) / 3.0
        o, r4 = npu_linear(lib, attn_cpu, weights["attn_out"])
        if core_ret is None:
            core_ret = r4
        x = x + o

    if all(weights.get(k) is not None for k in ["ffn_gate", "ffn_up", "ffn_down"]):
        gate, rg = npu_linear(lib, x, weights["ffn_gate"])
        up, ru = npu_linear(lib, x, weights["ffn_up"])
        if core_ret is None:
            core_ret = rg if rg is not None else ru
        act = silu(gate) * up
        down, rd = npu_linear(lib, act, weights["ffn_down"])
        if core_ret is None:
            core_ret = rd
        x = x + down

    if weights.get("ssm_out") is not None:
        ssm, rs = npu_linear(lib, x, weights["ssm_out"])
        if core_ret is None:
            core_ret = rs
        x = x + 0.1 * ssm

    return x.astype(np.float32), core_ret


def run_layer_cpu(blk, x, weights):
    if weights.get("attn_qkv") is not None:
        y = cpu_linear(x, weights["attn_qkv"])
        x = x + 0.1 * np.tanh(y[:, : x.shape[1]])
    elif all(weights.get(k) is not None for k in ["attn_q", "attn_k", "attn_v", "attn_out"]):
        q = cpu_linear(x, weights["attn_q"])
        k = cpu_linear(x, weights["attn_k"])
        v = cpu_linear(x, weights["attn_v"])
        q_h = q[:, : x.shape[1]]
        rep = x.shape[1] // k.shape[1]
        k_h = np.tile(k, (1, rep))
        v_h = np.tile(v, (1, rep))
        attn_cpu = (q_h + k_h + v_h) / 3.0
        o = cpu_linear(attn_cpu, weights["attn_out"])
        x = x + o

    if all(weights.get(k) is not None for k in ["ffn_gate", "ffn_up", "ffn_down"]):
        gate = cpu_linear(x, weights["ffn_gate"])
        up = cpu_linear(x, weights["ffn_up"])
        act = silu(gate) * up
        down = cpu_linear(act, weights["ffn_down"])
        x = x + down

    if weights.get("ssm_out") is not None:
        ssm = cpu_linear(x, weights["ssm_out"])
        x = x + 0.1 * ssm

    return x.astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description="Phase 2.3 one-token 32-layer hybrid prototype")
    ap.add_argument("--gguf", type=Path, default=DEFAULT_GGUF)
    ap.add_argument("--max-layers", type=int, default=32)
    ap.add_argument("--seed", type=int, default=123)
    args = ap.parse_args()

    GGUFReader, dequantize = load_gguf_modules()
    lib, lib_path = load_rknn_lib()
    if lib is None:
        raise SystemExit("librknnrt.so not found")
    setup_api(lib)

    print(f"rknn_runtime: {lib_path}")
    print(f"gguf: {args.gguf}")

    reader = GGUFReader(str(args.gguf), "r")
    tensor_map = {t.name: t for t in reader.tensors}

    # Build layer list from GGUF.
    block_ids = sorted(
        {
            int(m.group(1))
            for name in tensor_map.keys()
            for m in [re.match(r"^blk\.(\d+)\.", name)]
            if m
        }
    )
    block_ids = block_ids[: args.max_layers]

    rng = np.random.default_rng(args.seed)
    x_h = rng.standard_normal((1, 4096)).astype(np.float32)
    x_c = x_h.copy()

    t0 = time.perf_counter()
    fallback_count = 0

    for blk in block_ids:
        p = f"blk.{blk}."
        weights = {
            "attn_qkv": fetch_weight(tensor_map, dequantize, p + "attn_qkv.weight"),
            "attn_q": fetch_weight(tensor_map, dequantize, p + "attn_q.weight"),
            "attn_k": fetch_weight(tensor_map, dequantize, p + "attn_k.weight"),
            "attn_v": fetch_weight(tensor_map, dequantize, p + "attn_v.weight"),
            "attn_out": fetch_weight(tensor_map, dequantize, p + "attn_output.weight"),
            "ffn_gate": fetch_weight(tensor_map, dequantize, p + "ffn_gate.weight"),
            "ffn_up": fetch_weight(tensor_map, dequantize, p + "ffn_up.weight"),
            "ffn_down": fetch_weight(tensor_map, dequantize, p + "ffn_down.weight"),
            "ssm_out": fetch_weight(tensor_map, dequantize, p + "ssm_out.weight"),
        }

        x_h, core_ret = run_layer_hybrid(lib, blk, x_h, weights)
        x_c = run_layer_cpu(blk, x_c, weights)

        if core_ret not in (None, 0):
            fallback_count += 1

    elapsed = (time.perf_counter() - t0) * 1000.0

    diff = np.abs(x_h - x_c)
    max_abs = float(diff.max())
    mean_abs = float(diff.mean())

    print("\n=== Phase 2.3 prototype result ===")
    print(f"layers_executed: {len(block_ids)}")
    print(f"elapsed_ms: {elapsed:.3f}")
    print(f"core_mask_nonzero_count: {fallback_count}")
    print(f"hidden_max_abs_diff_vs_cpu_ref: {max_abs:.6f}")
    print(f"hidden_mean_abs_diff_vs_cpu_ref: {mean_abs:.6f}")
    print(f"hidden_checksum_hybrid: {float(x_h.sum()):.6f}")
    print(f"hidden_checksum_cpu: {float(x_c.sum()):.6f}")


if __name__ == "__main__":
    main()

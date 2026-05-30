#!/usr/bin/env python3
"""
Phase 2.2: GGUF -> ONNX projection export for one transformer block.

This script extracts projection weights for one block from a GGUF model,
dequantizes them to float weights, and emits one ONNX MatMul model per
projection op.

Exports (if present in selected block):
- attn_q.weight
- attn_k.weight
- attn_v.weight
- attn_output.weight
- ffn_gate.weight
- ffn_up.weight
- ffn_down.weight

Usage:
  python convert_weights.py --dry-run
  python convert_weights.py --block 3 --dtype float16
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent

DEFAULT_GGUF = REPO_ROOT / "local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf"
DEFAULT_OUT_DIR = SCRIPT_DIR / "runtime/onnx"

# Required Phase 2 projection set for one block.
PROJECTION_SUFFIXES = [
    "attn_q.weight",
    "attn_k.weight",
    "attn_v.weight",
    "attn_output.weight",
    "ffn_gate.weight",
    "ffn_up.weight",
    "ffn_down.weight",
]


def _load_gguf_modules():
    gguf_pkg = REPO_ROOT / "local_llm/local_provider_llamacpp/llama.cpp-src/gguf-py"
    if not gguf_pkg.exists():
        raise RuntimeError(f"gguf-py not found: {gguf_pkg}")

    sys.path.insert(0, str(gguf_pkg))
    from gguf.gguf_reader import GGUFReader  # noqa: WPS433
    from gguf.quants import dequantize  # noqa: WPS433

    return GGUFReader, dequantize


def _scan_blocks(tensor_names):
    by_block = {}
    pat = re.compile(r"^blk\.(\d+)\.(.+)$")
    for name in tensor_names:
        m = pat.match(name)
        if not m:
            continue
        blk = int(m.group(1))
        suffix = m.group(2)
        by_block.setdefault(blk, set()).add(suffix)
    return by_block


def _pick_block(by_block, requested_block):
    if requested_block is not None:
        if requested_block not in by_block:
            raise ValueError(f"Requested block {requested_block} not found")
        return requested_block

    candidates = []
    required = set(PROJECTION_SUFFIXES)
    for blk, suffixes in by_block.items():
        if required.issubset(suffixes):
            candidates.append(blk)
    if not candidates:
        raise RuntimeError(
            "No block has all required projection tensors. "
            "Try --block <id> and inspect available suffixes first."
        )
    return min(candidates)


def _normalize_weight_shape(arr, logical_shape):
    logical_shape = tuple(int(x) for x in logical_shape)
    if arr.shape == logical_shape:
        return arr
    if arr.T.shape == logical_shape:
        return arr.T
    raise ValueError(f"Cannot normalize shape from {arr.shape} to {logical_shape}")


def _save_matmul_onnx(weight, model_path):
    in_dim, out_dim = weight.shape

    x = helper.make_tensor_value_info("X", TensorProto.FLOAT, ["M", int(in_dim)])
    y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, ["M", int(out_dim)])

    w_init = numpy_helper.from_array(weight.astype(np.float32), name="W")
    node = helper.make_node("MatMul", ["X", "W"], ["Y"])

    graph = helper.make_graph(
        [node],
        "projection_matmul",
        [x],
        [y],
        initializer=[w_init],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 17)])
    onnx.save(model, str(model_path))


def main():
    parser = argparse.ArgumentParser(description="Phase 2.2 GGUF -> ONNX projection exporter")
    parser.add_argument("--gguf", type=Path, default=DEFAULT_GGUF)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--block", type=int, default=None)
    parser.add_argument("--dtype", choices=["float32", "float16"], default="float16")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    GGUFReader, dequantize = _load_gguf_modules()

    if not args.gguf.exists():
        raise SystemExit(f"GGUF file not found: {args.gguf}")

    reader = GGUFReader(str(args.gguf), "r")
    tensor_by_name = {t.name: t for t in reader.tensors}
    by_block = _scan_blocks(tensor_by_name.keys())
    selected = _pick_block(by_block, args.block)

    block_prefix = f"blk.{selected}."
    names = [block_prefix + suffix for suffix in PROJECTION_SUFFIXES]

    print(f"Selected block: {selected}")
    print(f"GGUF: {args.gguf}")
    print(f"dtype: {args.dtype}")

    missing = [n for n in names if n not in tensor_by_name]
    if missing:
        raise SystemExit("Missing required tensors in selected block:\n" + "\n".join(missing))

    manifest = {
        "gguf": str(args.gguf),
        "block": selected,
        "dtype": args.dtype,
        "exports": [],
    }

    if args.dry_run:
        print("\nDry-run tensor check:")

    out_dir = args.out_dir / f"block_{selected}"
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    for suffix in PROJECTION_SUFFIXES:
        name = block_prefix + suffix
        t = tensor_by_name[name]

        logical_shape = tuple(int(x) for x in t.shape.tolist())
        deq = dequantize(t.data, t.tensor_type)
        deq = _normalize_weight_shape(deq, logical_shape)

        if args.dtype == "float16":
            weight = deq.astype(np.float16)
        else:
            weight = deq.astype(np.float32)

        if args.dry_run:
            print(
                f"- {name}: gguf_shape={logical_shape}, deq_shape={tuple(deq.shape)}, "
                f"dtype={weight.dtype}"
            )
        else:
            model_name = suffix.replace(".weight", "") + ".onnx"
            model_path = out_dir / model_name
            _save_matmul_onnx(weight, model_path)
            print(f"exported: {model_path}")

        manifest["exports"].append(
            {
                "tensor": name,
                "shape": list(weight.shape),
                "dtype": str(weight.dtype),
            }
        )

    if not args.dry_run:
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()

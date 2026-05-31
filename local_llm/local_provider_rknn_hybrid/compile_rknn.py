#!/usr/bin/env python3
"""Compile Phase 2.2 ONNX projection models to RKNN artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_MANIFEST = SCRIPT_DIR / "runtime/onnx/block_3/manifest.json"
DEFAULT_OUT_DIR = SCRIPT_DIR / "runtime/kernels/block_3"


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if "exports" not in data or not isinstance(data["exports"], list):
        raise ValueError(f"Invalid manifest format: {path}")
    return data


def _tensor_to_onnx_name(tensor_name: str) -> str:
    # blk.3.attn_q.weight -> attn_q.onnx
    suffix = tensor_name.split(".")[-2]
    return f"{suffix}.onnx"


def _compile_one(rknn_api, onnx_path: Path, out_path: Path, target: str, verbose: bool) -> tuple[bool, str]:
    rknn = rknn_api.RKNN(verbose=verbose)
    try:
        ret = rknn.config(target_platform=target)
        if ret != 0:
            return False, f"config failed ({ret})"

        ret = rknn.load_onnx(model=str(onnx_path))
        if ret != 0:
            return False, f"load_onnx failed ({ret})"

        ret = rknn.build(do_quantization=False)
        if ret != 0:
            return False, f"build failed ({ret})"

        ret = rknn.export_rknn(str(out_path))
        if ret != 0:
            return False, f"export_rknn failed ({ret})"

        return True, "ok"
    finally:
        try:
            rknn.release()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile ONNX projection models to RKNN")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--onnx-dir", type=Path, default=None, help="Defaults to manifest parent")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--target", type=str, default="rk3588")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    manifest = _load_manifest(args.manifest)
    onnx_dir = args.onnx_dir if args.onnx_dir else args.manifest.parent
    args.out_dir.mkdir(parents=True, exist_ok=True)

    compile_manifest: dict[str, object] = {
        "source_manifest": str(args.manifest),
        "onnx_dir": str(onnx_dir),
        "target": args.target,
        "artifacts": [],
    }

    try:
        from rknn import api as rknn_api  # type: ignore
    except Exception as exc:
        print("ERROR: rknn-toolkit2 is not importable in current Python environment.")
        print(f"Import error: {exc}")
        print("Install/activate toolkit env, then rerun compile_rknn.py.")

        for entry in manifest["exports"]:
            tensor_name = entry.get("tensor")
            if not tensor_name:
                continue
            onnx_name = _tensor_to_onnx_name(str(tensor_name))
            onnx_path = onnx_dir / onnx_name
            out_path = args.out_dir / onnx_name.replace(".onnx", ".rknn")
            compile_manifest["artifacts"].append(
                {
                    "tensor": tensor_name,
                    "onnx": str(onnx_path),
                    "rknn": str(out_path),
                    "status": "blocked",
                    "message": f"toolkit_import_failed: {exc}",
                }
            )

        compile_manifest_path = args.out_dir / "compile_manifest.json"
        compile_manifest_path.write_text(json.dumps(compile_manifest, indent=2) + "\n", encoding="utf-8")
        print(f"compile manifest: {compile_manifest_path}")
        return 2

    failures = 0
    for entry in manifest["exports"]:
        tensor_name = entry.get("tensor")
        if not tensor_name:
            continue

        onnx_name = _tensor_to_onnx_name(str(tensor_name))
        onnx_path = onnx_dir / onnx_name
        out_path = args.out_dir / onnx_name.replace(".onnx", ".rknn")

        if not onnx_path.exists():
            failures += 1
            msg = "missing onnx input"
            print(f"[FAIL] {onnx_name}: {msg}")
            compile_manifest["artifacts"].append(
                {
                    "tensor": tensor_name,
                    "onnx": str(onnx_path),
                    "rknn": str(out_path),
                    "status": "fail",
                    "message": msg,
                }
            )
            continue

        ok, message = _compile_one(rknn_api, onnx_path, out_path, args.target, args.verbose)
        if ok:
            print(f"[OK] {onnx_name} -> {out_path.name}")
            status = "ok"
        else:
            failures += 1
            print(f"[FAIL] {onnx_name}: {message}")
            status = "fail"

        compile_manifest["artifacts"].append(
            {
                "tensor": tensor_name,
                "onnx": str(onnx_path),
                "rknn": str(out_path),
                "status": status,
                "message": message,
            }
        )

    compile_manifest_path = args.out_dir / "compile_manifest.json"
    compile_manifest_path.write_text(json.dumps(compile_manifest, indent=2) + "\n", encoding="utf-8")
    print(f"compile manifest: {compile_manifest_path}")

    if failures:
        print(f"completed with failures: {failures}")
        return 1

    print("all projections compiled successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

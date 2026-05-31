# f26 RKNN Toolkit2 Install and Compile Prerequisites

This note documents how to enable `.rknn` compilation for the f26 hybrid NPU flow.

## 1. Required packages

- Runtime package: `rknn-toolkit-lite2` provides `rknnlite.api`.
- Compiler package: `rknn-toolkit2` provides `rknn.api`.

If `rknn.api` is missing, `compile_rknn.py` cannot export `.rknn` files.

## 2. Verification commands

```bash
conda run -n embed_nanobot python -c "import rknnlite.api as la; print('rknnlite ok')"
conda run -n embed_nanobot python -c "import rknn.api as ra; print('rknn toolkit2 ok')"
```

Expected:
- First command succeeds when runtime-lite is installed.
- Second command must succeed for compile capability.

## 3. Install attempt in embed_nanobot

```bash
conda run -n embed_nanobot python -m pip install rknn-toolkit2==2.3.2
```

If pip cannot resolve a compatible wheel for architecture and Python ABI,
compile must be done on a supported build host.

## 4. Recommended build-host workflow

1. Use a Linux x86_64 host with a Python version supported by Rockchip Toolkit2 wheel distribution.
2. Install `rknn-toolkit2` there.
3. Run:

```bash
python local_llm/local_provider_rknn_hybrid/compile_rknn.py \
  --manifest local_llm/local_provider_rknn_hybrid/runtime/onnx/block_3/manifest.json \
  --out-dir local_llm/local_provider_rknn_hybrid/runtime/kernels/block_3 \
  --target rk3588
```

4. Copy generated `.rknn` artifacts and `compile_manifest.json` back into:
   `local_llm/local_provider_rknn_hybrid/runtime/kernels/block_3/`.
5. Keep RK3588 runtime on `rknn-toolkit-lite2` for inference execution.

## 5. RK3588 status log (2026-05-31)

- Host: RK3588 (aarch64)
- Environment: `embed_nanobot` (Python 3.12.12)
- `rknnlite.api`: available
- `rknn.api`: unavailable (`No module named 'rknn'`)
- Result: runtime path available, compile path blocked in this environment

Evidence artifact:
- `local_llm/local_provider_rknn_hybrid/runtime/kernels/block_3/compile_manifest.json`

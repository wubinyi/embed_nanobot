#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider"
BACKEND_RUNTIME_DIR="$PROVIDER_DIR/runtime_backend"
UPSTREAM_SERVER_PY="$ROOT_DIR/local_llm/rknn-llm-src/examples/rkllm_server_demo/rkllm_server/flask_server.py"
RKLLM_LIB_SRC="$ROOT_DIR/local_llm/rknn-llm-src/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
EMBED_ENV_PY="/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python"
if [[ ! -x "$EMBED_ENV_PY" ]]; then
    EMBED_ENV_PY="$ROOT_DIR/.conda/bin/python"
fi

MODEL_PATH="${RKLLM_MODEL_PATH:-$ROOT_DIR/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm}"
TARGET_PLATFORM="${RKLLM_TARGET_PLATFORM:-rk3588}"
BACKEND_PORT="${RKLLM_BACKEND_PORT:-8080}"
ADAPTER_PORT="${RKLLM_OPENAI_PORT:-18000}"

mkdir -p "$BACKEND_RUNTIME_DIR/lib"
ln -sf "$RKLLM_LIB_SRC" "$BACKEND_RUNTIME_DIR/lib/librkllmrt.so"

UPSTREAM_SERVER_PY="$UPSTREAM_SERVER_PY" BACKEND_SERVER_COPY="$BACKEND_RUNTIME_DIR/flask_server.py" "$EMBED_ENV_PY" - <<'PY'
from pathlib import Path
import os

source = Path(os.environ["UPSTREAM_SERVER_PY"])
target = Path(os.environ["BACKEND_SERVER_COPY"])
text = source.read_text(encoding="utf-8")
text = text.replace("rkllm_param.max_context_len = 8192", "rkllm_param.max_context_len = 4096")
text = text.replace("rkllm_param.max_context_len = 4096", "rkllm_param.max_context_len = 4096")
text = text.replace("rkllm_param.max_new_tokens = 4096", "rkllm_param.max_new_tokens = 1024")
target.write_text(text, encoding="utf-8")
PY

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "RKLLM model not found: $MODEL_PATH" >&2
    exit 1
fi

cleanup() {
    local exit_code=$?
    if [[ -n "${ADAPTER_PID:-}" ]]; then
        kill "$ADAPTER_PID" >/dev/null 2>&1 || true
    fi
    if [[ -n "${BACKEND_PID:-}" ]]; then
        kill "$BACKEND_PID" >/dev/null 2>&1 || true
    fi
    wait >/dev/null 2>&1 || true
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

cd "$BACKEND_RUNTIME_DIR"
RKLLM_SKIP_FREQ_FIX=1 RKLLM_SERVER_PORT="$BACKEND_PORT" RKLLM_MODEL_PATH="$MODEL_PATH" RKLLM_TARGET_PLATFORM="$TARGET_PLATFORM" "$EMBED_ENV_PY" - <<'PY' &
from __future__ import annotations

import os
import runpy
import subprocess
import sys

port = os.environ.get("RKLLM_SERVER_PORT", "8080")
model_path = os.environ["RKLLM_MODEL_PATH"]
platform = os.environ.get("RKLLM_TARGET_PLATFORM", "rk3588")
script_path = os.path.join(os.getcwd(), "flask_server.py")

original_run = subprocess.run


def patched_run(command, *args, **kwargs):
    if isinstance(command, str) and command.startswith("sudo bash fix_freq_"):
        print(f"Skipping frequency fix command: {command}")
        return subprocess.CompletedProcess(command, 0)
    return original_run(command, *args, **kwargs)


subprocess.run = patched_run
sys.argv = [
    script_path,
    "--rkllm_model_path",
    model_path,
    "--target_platform",
    platform,
]
runpy.run_path(script_path, run_name="__main__")
PY
BACKEND_PID=$!

sleep 5

RKLLM_BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}/rkllm_chat" \
RKLLM_OPENAI_PORT="$ADAPTER_PORT" \
"$EMBED_ENV_PY" "$PROVIDER_DIR/openai_adapter.py" &
ADAPTER_PID=$!

echo "RKLLM backend pid: $BACKEND_PID"
echo "RKLLM OpenAI adapter pid: $ADAPTER_PID"
echo "OpenAI-compatible endpoint: http://127.0.0.1:${ADAPTER_PORT}/v1/chat/completions"
wait "$BACKEND_PID" "$ADAPTER_PID"
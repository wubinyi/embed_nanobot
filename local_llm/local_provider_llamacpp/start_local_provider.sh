#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_llamacpp"
RUNTIME_DIR="$PROVIDER_DIR/runtime"
BUILD_DIR="$RUNTIME_DIR/build"
BIN_PATH="$BUILD_DIR/bin/llama-server"
EMBED_ENV_PY="/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python"

if [[ ! -x "$EMBED_ENV_PY" ]]; then
    EMBED_ENV_PY="$ROOT_DIR/.conda/bin/python"
fi

MODEL_PATH="${LLAMACPP_MODEL_PATH:-$ROOT_DIR/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_NAME="${LLAMACPP_MODEL_NAME:-qwen3.5-9b-llamacpp}"
BACKEND_PORT="${LLAMACPP_BACKEND_PORT:-19080}"
ADAPTER_PORT="${LLAMACPP_OPENAI_PORT:-19000}"
CTX_SIZE="${LLAMACPP_CTX_SIZE:-65536}"
N_PREDICT="${LLAMACPP_N_PREDICT:-65536}"
# THREADS="${LLAMACPP_THREADS:-$(nproc)}"
THREADS="${LLAMACPP_THREADS:-4}"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "llama.cpp model not found: $MODEL_PATH" >&2
    exit 1
fi

if [[ ! -x "$BIN_PATH" ]]; then
    bash "$PROVIDER_DIR/build_llamacpp.sh"
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

mkdir -p "$RUNTIME_DIR/logs"

ulimit -l
echo ">>> 当前脚本的真实 mlock 限制为: $(ulimit -l) <<<"
# sudo cpupower frequency-set -g performance

# 1. 声明插件所在的绝对路径（这是动态加载的核心）
export GGML_BACKEND_PATH="/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_llamacpp/runtime/build/bin"
# 2. 绑核 + GPU 卸载 + 内存锁定 启动！
taskset -c 4-7 "$BIN_PATH" \
    --model "$MODEL_PATH" \
    --alias "$MODEL_NAME" \
    --host 127.0.0.1 \
    --port "$BACKEND_PORT" \
    --ctx-size "$CTX_SIZE" \
    --threads "$THREADS" \
    --n-predict "$N_PREDICT" \
    --api-key no-key \
    --mlock \
    --no-mmap \
    --flash-attn on \
    --no-webui \
    >"$RUNTIME_DIR/logs/llama_server.log" 2>&1 &
BACKEND_PID=$!

sleep 5

LLAMACPP_BACKEND_BASE="http://127.0.0.1:${BACKEND_PORT}" \
LLAMACPP_OPENAI_PORT="$ADAPTER_PORT" \
LLAMACPP_MODEL_NAME="$MODEL_NAME" \
"$EMBED_ENV_PY" "$PROVIDER_DIR/openai_adapter.py" &
ADAPTER_PID=$!

echo "llama.cpp backend pid: $BACKEND_PID"
echo "llama.cpp adapter pid: $ADAPTER_PID"
echo "Nanobot endpoint: http://127.0.0.1:${ADAPTER_PORT}/v1/chat/completions"
wait "$BACKEND_PID" "$ADAPTER_PID"
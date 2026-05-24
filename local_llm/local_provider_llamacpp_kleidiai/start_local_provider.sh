#!/usr/bin/env bash
# =============================================================================
# start_local_provider.sh — Start the KleidiAI-optimized llama.cpp provider
#
# This script starts two processes:
#   1. llama-server  — raw llama.cpp backend on BACKEND_PORT (default 19180)
#   2. openai_adapter.py — nanobot-facing OpenAI-compatible proxy on
#                          ADAPTER_PORT (default 19100)
#
# Port allocations for this provider (non-overlapping with baseline provider):
#   BACKEND_PORT  19180  — llama-server raw HTTP API
#   ADAPTER_PORT  19100  — nanobot-facing OpenAI-compatible endpoint
#
# The binary used is the KleidiAI build (from build_llamacpp_kleidiai.sh),
# stored under runtime/build/bin/ inside THIS provider directory.
#
# All other runtime flags are kept identical to the baseline provider so
# benchmark results are directly comparable:
#   --mlock --no-mmap --flash-attn on --ctx-size 65536 --threads 4
#   taskset -c 4-7 (big Cortex-A76 cores only, indices 4-7 on RK3588)
#
# Environment overrides (all optional):
#   KLEIDIAI_MODEL_PATH     — path to GGUF model file
#   KLEIDIAI_MODEL_NAME     — model alias exposed via /v1/models
#   KLEIDIAI_BACKEND_PORT   — llama-server listen port (default 19180)
#   KLEIDIAI_OPENAI_PORT    — adapter listen port (default 19100)
#   KLEIDIAI_CTX_SIZE       — context window in tokens (default 65536)
#   KLEIDIAI_THREADS        — number of threads (default 4)
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# This provider's own directory
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_llamacpp_kleidiai"
RUNTIME_DIR="$PROVIDER_DIR/runtime"
BUILD_DIR="$RUNTIME_DIR/build"
BIN_PATH="$BUILD_DIR/bin/llama-server"

# Resolve embed_nanobot conda env Python (same as baseline provider)
EMBED_ENV_PY="/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python"
if [[ ! -x "$EMBED_ENV_PY" ]]; then
    EMBED_ENV_PY="$ROOT_DIR/.conda/bin/python"
fi

# ---------------------------------------------------------------------------
# Runtime configuration — KleidiAI-specific defaults, all env-overridable
# ---------------------------------------------------------------------------
MODEL_PATH="${KLEIDIAI_MODEL_PATH:-$ROOT_DIR/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_NAME="${KLEIDIAI_MODEL_NAME:-qwen3.5-9b-kleidiai}"
BACKEND_PORT="${KLEIDIAI_BACKEND_PORT:-19180}"
ADAPTER_PORT="${KLEIDIAI_OPENAI_PORT:-19100}"
CTX_SIZE="${KLEIDIAI_CTX_SIZE:-65536}"
N_PREDICT="${KLEIDIAI_N_PREDICT:-65536}"
THREADS="${KLEIDIAI_THREADS:-4}"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ ! -f "$MODEL_PATH" ]]; then
    echo "ERROR: GGUF model not found: $MODEL_PATH" >&2
    echo "  → Set KLEIDIAI_MODEL_PATH or place the model at the default location." >&2
    exit 1
fi

# Auto-build if binary is missing
if [[ ! -x "$BIN_PATH" ]]; then
    echo "[start] llama-server (KleidiAI build) not found — running build first..."
    bash "$PROVIDER_DIR/build_llamacpp_kleidiai.sh"
fi

# ---------------------------------------------------------------------------
# Cleanup trap — kill both child processes on exit
# ---------------------------------------------------------------------------
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

# Print effective mlock limit for diagnostics
echo ">>> mlock limit: $(ulimit -l) <<<"

# ---------------------------------------------------------------------------
# 1. Start llama-server (KleidiAI build) on BACKEND_PORT
#    Flags are identical to the baseline provider to ensure fair benchmark:
#      --mlock      — pin model weights in RAM, no swap
#      --no-mmap    — disable memory-mapped I/O for more predictable latency
#      --flash-attn — enable FlashAttention for long-context performance
#      taskset -c 4-7 — bind to big Cortex-A76 cores (indices 4-7 on RK3588)
# ---------------------------------------------------------------------------

# Point llama.cpp to this provider's own build bin dir for dynamic backends
export GGML_BACKEND_PATH="$BUILD_DIR/bin"

echo "[start] Launching KleidiAI llama-server on port $BACKEND_PORT..."
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

# Wait for the backend to start accepting connections before launching adapter
sleep 5

# ---------------------------------------------------------------------------
# 2. Start the OpenAI-compatible adapter on ADAPTER_PORT
#    The adapter forwards all requests to the backend and exposes a stable
#    endpoint for nanobot at http://127.0.0.1:19100/v1
# ---------------------------------------------------------------------------
echo "[start] Launching OpenAI adapter on port $ADAPTER_PORT..."
LLAMACPP_BACKEND_BASE="http://127.0.0.1:${BACKEND_PORT}" \
LLAMACPP_OPENAI_PORT="$ADAPTER_PORT" \
LLAMACPP_MODEL_NAME="$MODEL_NAME" \
"$EMBED_ENV_PY" "$PROVIDER_DIR/openai_adapter.py" &
ADAPTER_PID=$!

echo ""
echo "[start] KleidiAI provider running:"
echo "  Backend PID : $BACKEND_PID  (port $BACKEND_PORT)"
echo "  Adapter PID : $ADAPTER_PID  (port $ADAPTER_PORT)"
echo "  Model alias : $MODEL_NAME"
echo "  Nanobot URL : http://127.0.0.1:${ADAPTER_PORT}/v1/chat/completions"
echo ""

wait "$BACKEND_PID" "$ADAPTER_PID"

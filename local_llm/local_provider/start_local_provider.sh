#!/usr/bin/env bash
set -euo pipefail

# 获取当前脚本所在目录的“上两级”父目录的绝对路径，并将其赋值给变量 ROOT_DIR
# 1. "${BASH_SOURCE[0]}" 获取当前脚本的路径
# 2. dirname 获取该路径的目录部分，即脚本所在目录
# 3. /../.. 向上两级目录
# 4. cd ... && pwd 获取该目录的绝对路径
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider"
BACKEND_RUNTIME_DIR="$PROVIDER_DIR/runtime_backend"
UPSTREAM_SERVER_PY="$ROOT_DIR/local_llm/rknn-llm-src/examples/rkllm_server_demo/rkllm_server/flask_server.py"
RKLLM_LIB_SRC="$ROOT_DIR/local_llm/rknn-llm-src/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
EMBED_ENV_PY="/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python"
# 如果 EMBED_ENV_PY 不可执行，则使用 ROOT_DIR/.conda/bin/python 作为 Python 解释器
if [[ ! -x "$EMBED_ENV_PY" ]]; then
    EMBED_ENV_PY="$ROOT_DIR/.conda/bin/python"
fi

# ${A:-B} --> 如果变量 A 已定义且非空，则结果为 A；否则结果为 B。
MODEL_PATH="${RKLLM_MODEL_PATH:-$ROOT_DIR/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm}"
TARGET_PLATFORM="${RKLLM_TARGET_PLATFORM:-rk3588}"
BACKEND_PORT="${RKLLM_BACKEND_PORT:-8080}"
ADAPTER_PORT="${RKLLM_OPENAI_PORT:-18000}"

mkdir -p "$BACKEND_RUNTIME_DIR/lib"
ln -sf "$RKLLM_LIB_SRC" "$BACKEND_RUNTIME_DIR/lib/librkllmrt.so"

# VAR="value" command  -->  这种格式表示仅在当前命令[command]执行期间设置环境变量[VAR]的值为[value]。
# 命令：Python -  <<'PY' ... PY  -->  这种格式表示将两个 PY 之间的内容作为标准输入传递给 Python 解释器执行。
#       "$EMBED_ENV_PY"：执行一个 Python 解释器或脚本。
#       -：这是一个特殊的参数，告诉 Python “从标准输入（stdin）读取代码来执行”，而不是执行某个 .py 文件。
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

# 确保后台启动的子进程（如 Adapter 和 Backend 服务）被彻底杀死
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
# trap cleanup EXIT  -->  这行代码设置了一个 trap（陷阱），当脚本接收到 EXIT 信号时（即脚本正常退出或被中断）, INT（中断信号，通常由 Ctrl+C 触发）或 TERM（终止信号）时，会调用 cleanup 函数来执行清理操作。
trap cleanup EXIT INT TERM

# 下面 'PY' ... PY 之间的内容是一个 Python 脚本，在正式运行 Flask 后端服务之前，先通过“欺骗”和“伪装”的手段，修改程序的运行环境（比如屏蔽掉需要 root 权限的硬件频率调整命令），然后以编程方式启动主程序。
# 这种写法通常用于解决权限问题或环境兼容性问题，让一个原本设计为直接运行的脚本，能在受限环境（如 Docker、普通用户权限）下顺利跑起来。
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
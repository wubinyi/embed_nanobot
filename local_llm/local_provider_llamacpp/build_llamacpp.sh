#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_llamacpp"
SRC_DIR="$PROVIDER_DIR/llama.cpp-src"
BUILD_DIR="$PROVIDER_DIR/runtime/build"
TARGET="${LLAMACPP_BUILD_TARGET:-llama-server}"
REPO_URL="${LLAMACPP_REPO_URL:-https://github.com/ggml-org/llama.cpp.git}"

mkdir -p "$PROVIDER_DIR/runtime"

# if [[ ! -d "$SRC_DIR/.git" ]]; then
#     git clone --depth 1 "$REPO_URL" "$SRC_DIR"
# else
#     git -C "$SRC_DIR" fetch --depth 1 origin
#     git -C "$SRC_DIR" pull --ff-only
# fi

# -DGGML_VULKAN=1 # 启用 Vulkan 支持进行编译
# -DGGML_BACKEND_SHARED=OFF  # <--- 新增这行，强制静态链接 Vulkan 后端
cmake -S "$SRC_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_BUILD_SERVER=ON
    # -DGGML_VULKAN=1 \
    # -DGGML_BACKEND_SHARED=OFF

# cmake --build "$BUILD_DIR" --config Release --target "$TARGET" -j"$(nproc)"
cmake --build "$BUILD_DIR" --config Release -j"$(nproc)"

echo "Built $TARGET at $BUILD_DIR/bin/$TARGET"
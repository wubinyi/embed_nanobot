#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_llamacpp"
SRC_DIR="$PROVIDER_DIR/llama.cpp-src"
BUILD_DIR="$PROVIDER_DIR/runtime/build"
TARGET="${LLAMACPP_BUILD_TARGET:-llama-server}"
REPO_URL="${LLAMACPP_REPO_URL:-https://github.com/ggml-org/llama.cpp.git}"

mkdir -p "$PROVIDER_DIR/runtime"

if [[ ! -d "$SRC_DIR/.git" ]]; then
    git clone --depth 1 "$REPO_URL" "$SRC_DIR"
else
    git -C "$SRC_DIR" fetch --depth 1 origin
    git -C "$SRC_DIR" pull --ff-only
fi

cmake -S "$SRC_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_BUILD_SERVER=ON

cmake --build "$BUILD_DIR" --config Release --target "$TARGET" -j"$(nproc)"

echo "Built $TARGET at $BUILD_DIR/bin/$TARGET"
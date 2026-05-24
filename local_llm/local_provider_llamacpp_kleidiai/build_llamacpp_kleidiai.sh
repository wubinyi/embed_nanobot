#!/usr/bin/env bash
# =============================================================================
# build_llamacpp_kleidiai.sh — Build llama-server with KleidiAI optimization
#
# KleidiAI (ARM's optimized kernel library) provides highly tuned matmul
# kernels for Q4-weight × INT8-activation mixed-precision arithmetic, using
# ARMv8.2-A FEAT_DOTPROD instructions available on the Cortex-A76 big cores
# of the Radxa Rock 5T (RK3588).
#
# Expected improvement over the baseline (plain BLAS) build:
#   baseline:   ~3.5 t/s  (local_provider_llamacpp)
#   KleidiAI:   ~5–7 t/s  (this provider, estimates before hardware validation)
#
# Key cmake differences from local_provider_llamacpp/build_llamacpp.sh:
#   -DGGML_USE_KLEIDIAI=ON              — enable KleidiAI kernel selection
#   -DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16"
#   -DCMAKE_C_FLAGS="-march=armv8.2-a+dotprod+fp16"
#       ^ Target exactly ARMv8.2-A + DOTPROD + FP16; do NOT use +i8mm which
#         requires ARMv8.6-A and is NOT present on Cortex-A76.
#
# Source sharing strategy:
#   This script reuses the same llama.cpp source checkout that lives in
#   local_provider_llamacpp/llama.cpp-src/.  A symlink is expected at
#   local_provider_llamacpp_kleidiai/llama.cpp-src -> ../local_provider_llamacpp/llama.cpp-src
#   (created automatically below if missing).
#
# Build output:
#   local_provider_llamacpp_kleidiai/runtime/build/bin/llama-server
#   — completely separate from the baseline provider's binary
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# This provider's own directory
PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_llamacpp_kleidiai"

# Reuse the same llama.cpp source as the baseline provider (avoids re-clone)
# The symlink is gitignored in this directory — create it on first build.
SIBLING_SRC="$ROOT_DIR/local_llm/local_provider_llamacpp/llama.cpp-src"
SYMLINK_PATH="$PROVIDER_DIR/llama.cpp-src"
SRC_DIR="$SYMLINK_PATH"

# This provider's dedicated build output (separate from baseline provider)
BUILD_DIR="$PROVIDER_DIR/runtime/build"

# Which cmake target to build (override with env var if needed)
TARGET="${LLAMACPP_BUILD_TARGET:-llama-server}"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [[ ! -d "$SIBLING_SRC/.git" ]]; then
    echo "ERROR: llama.cpp source not found at $SIBLING_SRC"
    echo "  → Clone it first by running:"
    echo "    bash local_llm/local_provider_llamacpp/build_llamacpp.sh"
    echo "  (or clone manually into $SIBLING_SRC)"
    exit 1
fi

# Create the symlink if it does not already exist
if [[ ! -e "$SYMLINK_PATH" ]]; then
    echo "[setup] Creating symlink: $SYMLINK_PATH -> $SIBLING_SRC"
    ln -s "$SIBLING_SRC" "$SYMLINK_PATH"
fi

mkdir -p "$PROVIDER_DIR/runtime"

# ---------------------------------------------------------------------------
# CMake configure — KleidiAI + ARMv8.2-A DOTPROD + FP16
# ---------------------------------------------------------------------------
echo "[build] Configuring cmake with KleidiAI for ARMv8.2-A (Cortex-A76/RK3588)..."
echo "  SRC_DIR  : $SRC_DIR"
echo "  BUILD_DIR: $BUILD_DIR"

# Architecture notes:
#   +dotprod  — FEAT_DOTPROD, present on A76 (ARMv8.2-A), required by KleidiAI
#   +fp16     — FEAT_FP16, present on A76, enables fp16 arithmetic
#   +i8mm     — FEAT_I8MM, requires ARMv8.6-A — ABSENT on A76, do NOT add
cmake -S "$SRC_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_BUILD_SERVER=ON \
    -DGGML_USE_KLEIDIAI=ON \
    -DCMAKE_CXX_FLAGS="-march=armv8.2-a+dotprod+fp16" \
    -DCMAKE_C_FLAGS="-march=armv8.2-a+dotprod+fp16"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
echo "[build] Compiling with $(nproc) parallel jobs..."
cmake --build "$BUILD_DIR" --config Release -j"$(nproc)"

echo ""
echo "[build] SUCCESS"
echo "  Binary: $BUILD_DIR/bin/$TARGET"
echo ""
echo "  To start the provider:"
echo "    bash $PROVIDER_DIR/start_local_provider.sh"

#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
out_dir="$repo_root/local_llm/local_provider_rknn_hybrid/runtime/backend"

mkdir -p "$out_dir"

cc \
  -DGGML_BACKEND_DL=1 \
  -DGGML_BACKEND_BUILD=1 \
  -DGGML_BACKEND_SHARED=1 \
  -fPIC \
  -shared \
  -O2 \
  -I"$repo_root/local_llm/local_provider_llamacpp/llama.cpp-src/ggml/include" \
  -I"$repo_root/local_llm/local_provider_llamacpp/llama.cpp-src/ggml/src" \
  "$script_dir/ggml_backend_rknn.c" \
  -o "$out_dir/libggml-rknn-probe.so"

printf '%s\n' "$out_dir/libggml-rknn-probe.so"
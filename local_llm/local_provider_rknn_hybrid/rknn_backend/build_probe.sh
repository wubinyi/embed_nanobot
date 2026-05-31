#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../../.." && pwd)
out_dir="$repo_root/local_llm/local_provider_rknn_hybrid/runtime/backend"

mkdir -p "$out_dir"

cc \
  -std=gnu11 \
  -DGGML_BACKEND_DL=1 \
  -DGGML_BACKEND_BUILD=1 \
  -DGGML_BACKEND_SHARED=1 \
  -fPIC \
  -shared \
  -O2 \
  -I"$repo_root/local_llm/local_provider_llamacpp/llama.cpp-src/ggml/include" \
  -I"$repo_root/local_llm/local_provider_llamacpp/llama.cpp-src/ggml/src" \
  -I"$repo_root/local_llm/local_provider_rkllm/rknn-llm-src/examples/multimodal_model_demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include" \
  "$script_dir/ggml_backend_rknn.c" \
  -ldl -lm \
  -o "$out_dir/libggml-rknn-probe.so"

printf '%s\n' "$out_dir/libggml-rknn-probe.so"
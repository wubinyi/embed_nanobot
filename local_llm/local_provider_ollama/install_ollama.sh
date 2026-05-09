#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OLLAMA_DIR="$ROOT_DIR/local_llm/local_provider_ollama"
LOCAL_INSTALL_DIR="$OLLAMA_DIR/runtime/ollama-dist"
LOCAL_BIN_DIR="$OLLAMA_DIR/runtime/bin"
ZST_ARCHIVE_URL="https://ollama.com/download/ollama-linux-arm64.tar.zst"
TGZ_ARCHIVE_URL="https://ollama.com/download/ollama-linux-arm64.tgz"

echo "[1/4] Checking platform"
arch="$(uname -m)"
echo "$arch"
if [[ "$arch" != "aarch64" && "$arch" != "arm64" ]]; then
    echo "Unsupported architecture for this helper: $arch" >&2
    exit 1
fi

echo "[2/4] Checking existing ollama installation"
if command -v ollama >/dev/null 2>&1; then
    echo "ollama already installed: $(ollama --version)"
    exit 0
fi

if [[ -x "$LOCAL_BIN_DIR/ollama" ]]; then
    echo "ollama already installed locally: $LOCAL_BIN_DIR/ollama"
    "$LOCAL_BIN_DIR/ollama" --version
    exit 0
fi

echo "[3/4] Installing ollama"
if sudo -n true >/dev/null 2>&1; then
    echo "Using system install path via official installer"
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "No passwordless sudo available; installing into $LOCAL_INSTALL_DIR"
    mkdir -p "$LOCAL_INSTALL_DIR" "$LOCAL_BIN_DIR"
    rm -rf "$LOCAL_INSTALL_DIR/bin" "$LOCAL_INSTALL_DIR/lib"
    if command -v zstd >/dev/null 2>&1 && curl --fail --silent --head --location "$ZST_ARCHIVE_URL" >/dev/null 2>&1; then
        curl -fL "$ZST_ARCHIVE_URL" | zstd -d | tar -xf - -C "$LOCAL_INSTALL_DIR"
    else
        curl -fL "$TGZ_ARCHIVE_URL" | tar -xzf - -C "$LOCAL_INSTALL_DIR"
    fi
    ln -sf "$LOCAL_INSTALL_DIR/bin/ollama" "$LOCAL_BIN_DIR/ollama"
fi

echo "[4/4] Verifying installation"
if command -v ollama >/dev/null 2>&1; then
    ollama --version
else
    "$LOCAL_BIN_DIR/ollama" --version
    echo "Add this to PATH for convenience: export PATH=$LOCAL_BIN_DIR:\$PATH"
fi

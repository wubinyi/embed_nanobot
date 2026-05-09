#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/local_llm/runtime"
OLLAMA_PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_ollama"
OLLAMA_RUNTIME_DIR="$OLLAMA_PROVIDER_DIR/runtime"
RKLLM_PROVIDER_DIR="$ROOT_DIR/local_llm/local_provider_rkllm"
RKLLM_RUNTIME_DIR="$RKLLM_PROVIDER_DIR/runtime"
LOG_DIR="$ROOT_DIR/local_llm/logs"
EMBED_ENV_BIN="/home/wubinyi/miniforge3/envs/embed_nanobot/bin"
if [[ -x "$EMBED_ENV_BIN/python" ]]; then
    PYTHON_BIN="$EMBED_ENV_BIN/python"
else
    PYTHON_BIN="$ROOT_DIR/.conda/bin/python"
fi

mode=""
config_path=""
prompt=""
expect=""
timeout_seconds=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            mode="$2"
            shift 2
            ;;
        --config)
            config_path="$2"
            shift 2
            ;;
        --prompt)
            prompt="$2"
            shift 2
            ;;
        --expect)
            expect="$2"
            shift 2
            ;;
        --timeout)
            timeout_seconds="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$mode" ]]; then
    echo "Usage: $0 --mode <local|remote|rkllm> [--config PATH] [--prompt TEXT] [--expect TOKEN]" >&2
    exit 2
fi

mkdir -p "$LOG_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
log_path="$LOG_DIR/agent_${mode}_${timestamp}.log"

case "$mode" in
    local)
        config_path="${config_path:-$OLLAMA_RUNTIME_DIR/local_ollama.json}"
        prompt="${prompt:-Reply with exactly LOCAL_OK and nothing else.}"
        expect="${expect:-LOCAL_OK}"
        timeout_seconds="${timeout_seconds:-600}"
        ;;
    remote)
        config_path="${config_path:-$RUNTIME_DIR/remote_current.json}"
        prompt="${prompt:-Reply with exactly REMOTE_OK and nothing else.}"
        expect="${expect:-REMOTE_OK}"
        timeout_seconds="${timeout_seconds:-180}"
        ;;
    rkllm)
        config_path="${config_path:-$RKLLM_RUNTIME_DIR/local_rkllm.json}"
        prompt="${prompt:-Reply with exactly RKLLM_OK and nothing else.}"
        expect="${expect:-RKLLM_OK}"
        timeout_seconds="${timeout_seconds:-180}"
        ;;
    *)
        echo "Unsupported mode: $mode" >&2
        exit 2
        ;;
esac

if [[ ! -f "$config_path" ]]; then
    echo "Config not found: $config_path" >&2
    echo "Generate configs first with: $PYTHON_BIN $ROOT_DIR/local_llm/scripts/render_agent_configs.py" >&2
    exit 1
fi

cmd=("$PYTHON_BIN" -m nanobot agent -c "$config_path" -m "$prompt" --no-logs)
env_prefix=()
if [[ "$mode" == "rkllm" ]]; then
    rkllm_workspace="$RKLLM_RUNTIME_DIR/workspaces/rkllm"
    mkdir -p "$rkllm_workspace"
    cat > "$rkllm_workspace/AGENTS.md" <<'EOF'
# Agent Instructions

Be concise. Reply directly. Avoid tool use unless strictly required.
EOF
    cat > "$rkllm_workspace/HEARTBEAT.md" <<'EOF'
# Heartbeat
EOF
    cat > "$rkllm_workspace/SOUL.md" <<'EOF'
# Soul

I am nanobot.
EOF
    cat > "$rkllm_workspace/TOOLS.md" <<'EOF'
# Tool Notes

Use tools only when needed.
EOF
    cat > "$rkllm_workspace/USER.md" <<'EOF'
# User

Technical user.
EOF
    mkdir -p "$rkllm_workspace/memory"
    cat > "$rkllm_workspace/memory/MEMORY.md" <<'EOF'
# Memory
EOF
    : > "$rkllm_workspace/memory/HISTORY.md"
    env_prefix=(NANOBOT_DISABLE_BUILTIN_SKILLS=1 NANOBOT_DISABLE_TOOLS=1)
    cmd+=(--workspace "$rkllm_workspace" --session "cli:rkllm-smoke-$timestamp")
fi

printf 'Running %s smoke test\n' "$mode" | tee "$log_path"
printf 'Timeout: %ss\n' "$timeout_seconds" | tee -a "$log_path"
printf 'Command: %s\n' "${cmd[*]}" | tee -a "$log_path"

if timeout "$timeout_seconds" env "${env_prefix[@]}" "${cmd[@]}" 2>&1 | tee -a "$log_path"; then
    if grep -Eq "^[[:space:]]*${expect}[[:space:]]*$" "$log_path"; then
        printf 'PASS: found %s in %s\n' "$expect" "$log_path" | tee -a "$log_path"
        exit 0
    fi
    printf 'FAIL: expected token %s not found in %s\n' "$expect" "$log_path" | tee -a "$log_path" >&2
    exit 1
fi

printf 'FAIL: nanobot agent exited non-zero for %s\n' "$mode" | tee -a "$log_path" >&2
exit 1
# Local LLM Workspace

This directory is the Radxa 5T operational workspace for local language-model
usage with embed_nanobot.

It mirrors the role of `esp32/` for device work, but for on-device inference:

- `configs/` contains sanitized example configs
- `docs/` records install and validation history
- `scripts/` contains reproducible setup and smoke-test helpers
- `logs/` stores captured agent and runtime logs
- `models/` is a placeholder for model-related assets tracked outside git
- `runtime/` holds generated configs derived from the live user config

## Quick start

```bash
bash local_llm/scripts/install_ollama.sh
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/bin:$PATH
ollama pull qwen2.5:0.5b
cat > local_llm/runtime/Modelfile.qwen2.5-0.5b-nb <<'EOF'
FROM qwen2.5:0.5b
PARAMETER num_ctx 8192
EOF
ollama create qwen2.5:0.5b-nb -f local_llm/runtime/Modelfile.qwen2.5-0.5b-nb
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py
bash local_llm/scripts/run_agent_smoke.sh --mode local
bash local_llm/scripts/run_agent_smoke.sh --mode remote
```

The validated Radxa path uses `qwen2.5:0.5b-nb` as the default local model.
Local smoke runs on CPU can take about 6 minutes, so the smoke helper now uses
`600s` by default for `--mode local`.

Use `local_llm/docs/RK3588_TOOLCHAIN_LOG.md` for setup history and
`local_llm/docs/AGENT_VALIDATION.md` for real `nanobot agent` test outcomes.

# Local LLM Workspace

This directory is the Radxa 5T operational workspace for local language-model
usage with embed_nanobot.

It mirrors the role of `esp32/` for device work, but for on-device inference:

- `configs/` contains sanitized example configs
- `docs/` records install and validation history
- `scripts/` contains reproducible setup and smoke-test helpers
- `local_provider/` contains the RKLLM-backed local provider launcher and OpenAI-compatible adapter
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

## RKLLM local provider quick start

The validated RKLLM path now includes a local provider bridge for nanobot.

1. Make sure the RKLLM model exists at:
	`/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm`
2. Start the provider bridge:

```bash
bash local_llm/local_provider/start_local_provider.sh
```

3. In another terminal, verify the adapter:

```bash
curl http://127.0.0.1:18000/health
```

4. Run nanobot against the local RKLLM provider:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode rkllm
```

The RKLLM smoke mode intentionally disables built-in skills and tool schemas so
the real `nanobot agent` request stays within this model's hard `4096` context
window.

5. Start an interactive session:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/runtime/local_rkllm.json
```

For manual testing, prefer a dedicated RKLLM session/workspace too:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent \
	-c local_llm/runtime/local_rkllm.json \
	--workspace /home/wubinyi/workspace/embed_nanobot/local_llm/runtime/workspaces/rkllm \
	--session cli:rkllm-direct
```

The RKLLM adapter currently targets standard chat and the low-context smoke
path first. Treat broader tool-calling workflows as experimental until they are
validated with a larger-context RKLLM model or a more compact agent prompt.

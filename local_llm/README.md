# Local LLM Workspace

This directory is the Radxa 5T operational workspace for local language-model
usage with embed_nanobot.

It mirrors the role of `esp32/` for device work, but for on-device inference:

- `configs/` contains stable example config templates checked into git
- `docs/` records install, validation, and RKLLM toolchain notes
- `scripts/` contains Ollama setup helpers plus shared smoke-test and config-rendering helpers
- `local_provider/` contains the RKLLM-backed custom provider and its OpenAI-compatible bridge
- `logs/` stores captured agent and runtime logs
- `models/` is a placeholder for model-related assets tracked outside git
- `runtime/` holds generated configs, repo-local runtime binaries, and dedicated test workspaces derived from the live user config

## Provider layout

`local_llm` currently supports two local-provider paths:

1. `ollama`
	 - direct local provider at `http://127.0.0.1:11434/v1`
	 - uses the repo-local Ollama binary under `local_llm/runtime/bin/ollama`
	 - validated via `local_llm/runtime/local_ollama.json`
2. `custom`
	 - RKLLM-backed provider exposed through `local_llm/local_provider/`
	 - nanobot talks to it through the OpenAI-compatible bridge at `http://127.0.0.1:18000/v1`
	 - validated via `local_llm/runtime/local_rkllm.json`

In practice, `local_llm/scripts/` is mostly the Ollama setup surface. The RKLLM
provider itself lives in `local_llm/local_provider/`, while the smoke runner and
config renderer in `scripts/` are shared by both provider paths.

## `configs/` vs `runtime/`

There are two config locations on purpose:

- `local_llm/configs/`
	- human-maintained examples and templates
	- safe to read, diff, and copy from
	- should stay stable and generic
- `local_llm/runtime/`
	- generated configs for the current machine and current live nanobot setup
	- contains concrete paths, local ports, and probe variants used during testing
	- also stores local runtime assets such as the repo-local Ollama binary and the dedicated RKLLM workspace

Rule of thumb: `configs/` is the source/template layer; `runtime/` is the
machine-specific generated layer actually used for validation.

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

## Ollama path

The validated Ollama path is the simpler local-provider route.

1. Start Ollama:

```bash
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/bin:$PATH
ollama serve
```

2. Probe it directly:

```bash
curl -s http://127.0.0.1:11434/v1/chat/completions \
	-H 'Content-Type: application/json' \
	-d '{
		"model": "qwen2.5:0.5b-nb",
		"stream": false,
		"messages": [{"role": "user", "content": "Reply with exactly OLLAMA_OK and nothing else."}]
	}'
```

3. Run nanobot against the generated local config:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode local
```

## RKLLM local provider quick start

The validated RKLLM path uses a custom local provider under
`local_llm/local_provider/`. It is not Ollama-based.

### What gets bridged

The bridge has two layers:

1. upstream RKLLM backend
	 - source: `local_llm/rknn-llm-src/examples/rkllm_server_demo/rkllm_server/flask_server.py`
	 - native endpoint: `http://127.0.0.1:8080/rkllm_chat`
2. OpenAI-compatible adapter
	 - source: `local_llm/local_provider/openai_adapter.py`
	 - exposed endpoint: `http://127.0.0.1:18000/v1/chat/completions`

nanobot then uses its existing `custom` provider support to talk to the adapter
as if it were a standard OpenAI-compatible API.

### How the local provider is created

`bash local_llm/local_provider/start_local_provider.sh` does all of the
provider assembly work:

- creates `local_llm/local_provider/runtime_backend/`
- copies the upstream RKLLM Flask demo into that runtime directory
- normalizes the copied server to the model-safe runtime settings (`4096` context, `1024` max new tokens)
- links `librkllmrt.so` into the runtime directory
- starts the RKLLM backend on port `8080`
- starts the OpenAI-compatible adapter on port `18000`

So the custom provider is not a separate compiled program checked into the repo.
It is a reproducible launcher that assembles the runtime backend from upstream
RKLLM demo components plus the adapter layer.

1. Make sure the RKLLM model exists at:
	`/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/qwen3-vl-2b-instruct_w8a8_rk3588.rkllm`
2. Start the provider bridge:

```bash
bash local_llm/local_provider/start_local_provider.sh
```

3. In another terminal, verify the adapter:

```bash
curl http://127.0.0.1:18000/health
curl -s http://127.0.0.1:18000/v1/chat/completions \
	-H 'Content-Type: application/json' \
	-d '{
		"model": "qwen3-vl-2b-rkllm",
		"stream": false,
		"messages": [{"role": "user", "content": "Reply with exactly RKLLM_OK and nothing else."}]
	}'
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

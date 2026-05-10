# Local LLM Workspace

This directory is the Radxa 5T operational workspace for local language-model
usage with embed_nanobot.

It mirrors the role of `esp32/` for device work, but for on-device inference:

- `configs/` contains stable example config templates checked into git
- `docs/` records install, validation, and RKLLM toolchain notes
- `scripts/` now contains only shared helpers such as the smoke runner and config renderer
- `local_provider_ollama/` owns the Ollama-specific install scripts, runtime, and local config
- `local_provider_llamacpp/` owns the source-built `llama.cpp` backend, adapter, and local config
- `local_provider_rkllm/` owns the RKLLM bridge, its dedicated runtime, and the upstream `rknn-llm-src` tree
- `logs/` stores captured agent and runtime logs
- `models/` is a placeholder for model-related assets tracked outside git
- `runtime/` is now the shared generated-config area for non-provider-specific runtime artifacts such as remote and hybrid probe configs

## Provider layout

`local_llm` now exposes three provider-owned local-provider paths plus a small shared layer:

1. `ollama`
	 - direct local provider at `http://127.0.0.1:11434/v1`
	 - uses the repo-local Ollama binary under `local_llm/local_provider_ollama/runtime/bin/ollama`
	 - validated via `local_llm/local_provider_ollama/runtime/local_ollama.json`
2. `custom`
	 - llama.cpp-backed provider exposed through `local_llm/local_provider_llamacpp/`
	 - source-builds `llama-server` from `ggml-org/llama.cpp`
	 - nanobot talks to it through the OpenAI-compatible adapter at `http://127.0.0.1:19000/v1`
	 - validated via `local_llm/local_provider_llamacpp/runtime/local_llamacpp.json`
3. `custom`
	 - RKLLM-backed provider exposed through `local_llm/local_provider_rkllm/`
	 - nanobot talks to it through the OpenAI-compatible bridge at `http://127.0.0.1:18000/v1`
	 - validated via `local_llm/local_provider_rkllm/runtime/local_rkllm.json`
4. `shared`
	 - `local_llm/scripts/run_agent_smoke.sh` and `local_llm/scripts/render_agent_configs.py`
	 - `local_llm/runtime/remote_current.json` and hybrid probe configs

The intent is to keep provider-specific operational surfaces inside each
provider directory, leaving only cross-provider helpers at the top level.

## `configs/` vs `runtime/`

There are now three config layers on purpose:

- `local_llm/configs/`
	- human-maintained examples and templates
	- safe to read, diff, and copy from
	- should stay stable and generic
- `local_llm/local_provider_ollama/runtime/`, `local_llm/local_provider_llamacpp/runtime/`, and `local_llm/local_provider_rkllm/runtime/`
	- provider-owned local configs and runtime assets
	- contain the exact binaries, model bridge state, and dedicated workspaces needed by that provider path
- `local_llm/runtime/`
	- shared generated configs for the current machine and current live nanobot setup
	- contains concrete paths, remote targets, and hybrid probe variants used during testing

Rule of thumb: `configs/` is the source/template layer, each `local_provider_*`
runtime directory owns provider-local runtime state, and top-level `runtime/`
holds only shared generated artifacts.

## llama.cpp path

The llama.cpp local-provider path is the current source-built GGUF route.

1. Build `llama-server` from GitHub source:

```bash
proxy_on && bash local_llm/local_provider_llamacpp/build_llamacpp.sh
```

If GitHub access is already working on the host, `proxy_on &&` is optional.

2. Start the provider-owned backend plus adapter:

```bash
bash local_llm/local_provider_llamacpp/start_local_provider.sh
```

3. Probe the provider directly:

```bash
curl -sS http://127.0.0.1:19000/health
curl -sS http://127.0.0.1:19000/v1/models
curl -sS http://127.0.0.1:19000/v1/chat/completions \
	-H 'Content-Type: application/json' \
	-d '{
		"model": "qwen3.5-9b-llamacpp",
		"stream": false,
		"temperature": 0,
		"messages": [{"role": "user", "content": "Reply with exactly LLAMACPP_OK and nothing else."}]
	}'
```

4. Render the nanobot runtime configs:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py
```

5. Validate the real `nanobot agent` path:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

The validated model is:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf
```

The smoke path uses a dedicated llama.cpp workspace and disables built-in
skills plus tool schemas so the request stays within the current `4096` token
server context configured for the local GGUF runtime.

## Quick start

```bash
bash local_llm/local_provider_ollama/install_ollama.sh
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_ollama/runtime/bin:$PATH
ollama pull qwen2.5:0.5b
cat > local_llm/local_provider_ollama/runtime/Modelfile.qwen2.5-0.5b-nb <<'EOF'
FROM qwen2.5:0.5b
PARAMETER num_ctx 8192
EOF
ollama create qwen2.5:0.5b-nb -f local_llm/local_provider_ollama/runtime/Modelfile.qwen2.5-0.5b-nb
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
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_ollama/runtime/bin:$PATH
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
`local_llm/local_provider_rkllm/`. It is not Ollama-based.

### What gets bridged

The bridge has two layers:

1. upstream RKLLM backend
	 - source: `local_llm/local_provider_rkllm/rknn-llm-src/examples/rkllm_server_demo/rkllm_server/flask_server.py`
	 - native endpoint: `http://127.0.0.1:8080/rkllm_chat`
2. OpenAI-compatible adapter
	 - source: `local_llm/local_provider_rkllm/openai_adapter.py`
	 - exposed endpoint: `http://127.0.0.1:18000/v1/chat/completions`

nanobot then uses its existing `custom` provider support to talk to the adapter
as if it were a standard OpenAI-compatible API.

### How the local provider is created

`bash local_llm/local_provider_rkllm/start_local_provider.sh` does all of the
provider assembly work:

- creates `local_llm/local_provider_rkllm/runtime_backend/`
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
bash local_llm/local_provider_rkllm/start_local_provider.sh
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

### Switch the live nanobot config to `local_provider`

If you want plain `nanobot agent` to use the RKLLM bridge instead of Ollama or
hybrid routing, update your live config at:

```text
/home/wubinyi/.embed_nanobot/config.json
```

The required changes are:

1. Set the default provider to `custom`
2. Set the default model to the RKLLM adapter model name
3. Point `providers.custom.apiBase` at the local OpenAI-compatible bridge
4. Prefer the dedicated RKLLM workspace so the prompt stays smaller

Minimal target shape:

```json
{
	"agents": {
		"defaults": {
			"provider": "custom",
			"model": "qwen3-vl-2b-rkllm",
			"workspace": "/home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_rkllm/runtime/workspaces/rkllm"
		}
	},
	"providers": {
		"custom": {
			"apiKey": "no-key",
			"apiBase": "http://127.0.0.1:18000/v1",
			"extraHeaders": null
		}
	}
}
```

After changing the live config, the startup order is:

1. Start the RKLLM local provider:

```bash
cd /home/wubinyi/workspace/embed_nanobot
bash local_llm/local_provider_rkllm/start_local_provider.sh
```

2. In another terminal, start nanobot with the live config:

```bash
cd /home/wubinyi/workspace/embed_nanobot
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent
```

If you want to avoid editing the live config, keep using the dedicated runtime
config instead:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent \
	-c local_llm/local_provider_rkllm/runtime/local_rkllm.json \
	--workspace /home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_rkllm/runtime/workspaces/rkllm \
	--session cli:rkllm-direct
```

Important: the current validated RKLLM model is still hard-limited to `4096`
runtime context tokens. The smoke path is known-good; a fully loaded default
agent workspace can still overflow that limit unless you keep the workspace and
prompt surface small.

The RKLLM smoke mode intentionally disables built-in skills and tool schemas so
the real `nanobot agent` request stays within this model's hard `4096` context
window.

5. Start an interactive session:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent -c local_llm/local_provider_rkllm/runtime/local_rkllm.json
```

For manual testing, prefer a dedicated RKLLM session/workspace too:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent \
	-c local_llm/local_provider_rkllm/runtime/local_rkllm.json \
	--workspace /home/wubinyi/workspace/embed_nanobot/local_llm/local_provider_rkllm/runtime/workspaces/rkllm \
	--session cli:rkllm-direct
```

The RKLLM adapter currently targets standard chat and the low-context smoke
path first. Treat broader tool-calling workflows as experimental until they are
validated with a larger-context RKLLM model or a more compact agent prompt.

### Change `local_provider_rkllm` to a different model

The current `local_provider_rkllm` path is wired to a specific default model only by
configuration and environment variables. For a normal model swap, you do not
need to edit any C or C++ source.

#### What you need to change

If you replace the current model under:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/qwen3-vl-2b/
```

with another `.rkllm` model, update these surfaces:

1. Model file path used by the launcher
	 - source: `local_llm/local_provider_rkllm/start_local_provider.sh`
	 - knob: `RKLLM_MODEL_PATH`
	 - easiest option: pass the new path as an environment variable instead of editing the script
2. Model name exposed by the OpenAI-compatible adapter
	 - source: `local_llm/local_provider_rkllm/openai_adapter.py`
	 - knob: `RKLLM_MODEL_NAME`
	 - this is the model name nanobot sends in chat-completions requests
3. Nanobot runtime config
	 - source: `local_llm/local_provider_rkllm/runtime/local_rkllm.json`
	 - update `agents.defaults.model` to match the adapter model name
4. Optional helper scripts or probes
	 - update any hardcoded model name in helper files if you use them for testing

#### Recommended workflow

Example: switch to `/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/my-model/my-model.rkllm`

1. Put the new `.rkllm` file under `local_llm/models/rkllm/<model-name>/`
2. Start the provider with the new model path and a new exposed model name:

```bash
cd /home/wubinyi/workspace/embed_nanobot
RKLLM_MODEL_PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/models/rkllm/my-model/my-model.rkllm \
RKLLM_MODEL_NAME=my-model-rkllm \
bash local_llm/local_provider_rkllm/start_local_provider.sh
```

3. Probe the adapter directly:

```bash
curl -s http://127.0.0.1:18000/v1/chat/completions \
	-H 'Content-Type: application/json' \
	-d '{
		"model": "my-model-rkllm",
		"stream": false,
		"messages": [{"role": "user", "content": "Reply with exactly RKLLM_OK and nothing else."}]
	}'
```

4. Update `local_llm/local_provider_rkllm/runtime/local_rkllm.json` so:
	 - `agents.defaults.model = "my-model-rkllm"`
	 - `providers.custom.apiBase = "http://127.0.0.1:18000/v1"` stays unchanged unless you change the port
5. Re-run the smoke test:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode rkllm
```

#### Do you need to modify C or C++ files?

Usually: no.

You do not need C/C++ changes when:

- the new model is already a valid `.rkllm` file for your target platform
- the model works with the same RKLLM server demo interface
- you only need text chat through the current OpenAI-compatible bridge

You may need deeper changes when:

- the new model is not yet converted to `.rkllm`
	- then you need RKLLM export/conversion work, not nanobot C/C++ changes
- the new model is multimodal and you want image input through the provider
	- the current `local_provider` path is built around the text-oriented RKLLM server demo, so multimodal serving likely needs Python-side integration changes and possibly a different upstream demo path
- the new model needs different chat-template behavior or special request formatting
	- then the Python adapter or upstream Python server may need changes
- the new model's runtime context limit differs from the current assumptions
	- then the launcher's forced `4096`/`1024` patch may need to be adjusted to match the actual converted model limit

So the practical answer is: for a standard `.rkllm` text-chat model swap, treat it as a launcher/config change, not a C/C++ change.

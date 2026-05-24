# llama.cpp Local Provider

This directory owns the `llama.cpp` local-provider surface for `local_llm`.

## What lives here

- a source-build helper that clones and compiles `ggml-org/llama.cpp`
- a startup launcher for `llama-server`
- a thin OpenAI-compatible adapter dedicated to nanobot
- the provider-owned runtime config for nanobot validation

## Model

Validated local model target:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf
```

## High-level flow

1. build `llama-server` from the upstream GitHub repo
2. launch the raw llama.cpp OpenAI-compatible backend on a backend-only port
3. launch the nanobot-facing adapter on a stable provider port
4. point nanobot's `custom` provider at that adapter

## Entry points

Build from source:

```bash
bash local_llm/local_provider_llamacpp/build_llamacpp.sh
```

Start the provider:

```bash
bash local_llm/local_provider_llamacpp/start_local_provider.sh
```

Smoke test through nanobot:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

## Validated runtime

- GGUF model:
	`/home/wubinyi/workspace/embed_nanobot/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf`
- backend port: `19080`
- nanobot-facing adapter port: `19000`
- model alias: `qwen3.5-9b-llamacpp`

## Full workflow

1. Build from upstream GitHub source:

```bash
proxy_on && bash local_llm/local_provider_llamacpp/build_llamacpp.sh
```

2. Start the raw backend plus adapter:

```bash
bash local_llm/local_provider_llamacpp/start_local_provider.sh
```

3. Wait for the warmup phase to finish. During initial load the adapter can
   return `503 Loading model`; this is expected until `llama-server` finishes
   loading the GGUF and warmup pass.

4. Probe the adapter directly:

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

5. Render the provider-owned nanobot config:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py
```

6. Validate with the real agent path:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

## Notes

- The backend is the upstream OpenAI-compatible `llama-server`, but the thin
  adapter gives nanobot a stable provider-owned endpoint and a small place for
  local normalization if future llama.cpp behavior changes.
- The validated `nanobot agent` smoke uses a dedicated provider workspace and
  disables built-in skills plus tool schemas to stay within the configured
  `4096` token local context window.
# f25: llama.cpp Local Provider — Test Report

**Task**: Add llama.cpp as a source-built local provider under `local_llm`  
**Date**: 2026-05-10  
**Environment**: Radxa Rock 5T, Armbian 26 / Debian 13, local GGUF model on CPU

---

## Validation Class

`real-hardware required`

Reason:

- the task requires a live source build on the Radxa host
- the model file is machine-local and large enough that actual load behavior matters
- the user explicitly required direct `curl` validation and a real `nanobot agent` run

---

## Executed checks

### 1. Runtime config rendering

Executed:

```bash
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python local_llm/scripts/render_agent_configs.py
```

Result: PASS

Generated:

- `local_llm/local_provider_ollama/runtime/local_ollama.json`
- `local_llm/local_provider_llamacpp/runtime/local_llamacpp.json`
- `local_llm/runtime/remote_current.json`

### 2. Source build from upstream GitHub

Executed:

```bash
proxy_on && bash local_llm/local_provider_llamacpp/build_llamacpp.sh
```

Result: PASS

Observed:

- initial network stall without proxy was resolved by `proxy_on`
- `ggml-org/llama.cpp` cloned successfully
- CMake configure succeeded on aarch64
- `llama-server` built successfully under `local_llm/local_provider_llamacpp/runtime/build/bin/llama-server`
- only non-blocking warning: OpenSSL not found, so HTTPS support remained disabled

### 3. Provider launch

Executed:

```bash
bash local_llm/local_provider_llamacpp/start_local_provider.sh
```

Result: PASS

Observed:

- backend started on `127.0.0.1:19080`
- adapter started on `127.0.0.1:19000`
- backend log showed successful GGUF load for `Qwen3.5-9B-Q4_K_M.gguf`

### 4. Health and model listing

Executed:

```bash
curl -sS http://127.0.0.1:19000/health
curl -sS http://127.0.0.1:19000/v1/models
```

Result: PASS

Observed:

- initial probe returned `503 Loading model` during backend warmup
- repeated probes succeeded after warmup
- models endpoint advertised `qwen3.5-9b-llamacpp`

### 5. Direct OpenAI-compatible completion

Executed:

```bash
curl -sS http://127.0.0.1:19000/v1/chat/completions \
	-H 'Content-Type: application/json' \
	-d '{
		"model": "qwen3.5-9b-llamacpp",
		"messages": [{"role": "user", "content": "Reply with exactly LLAMACPP_OK and nothing else."}],
		"stream": false,
		"temperature": 0
	}'
```

Result: PASS

Observed:

- assistant `content` returned `LLAMACPP_OK`
- backend also emitted `reasoning_content`, but the visible answer content matched the required token exactly

### 6. Real nanobot agent smoke: first failure

Executed:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

Initial result: FAIL

Observed:

```text
request (25970 tokens) exceeds the available context size (4096 tokens)
```

Interpretation:

- provider launch and adapter wiring were already correct
- failure was caused by the default nanobot prompt/tool payload being too large for the current local llama.cpp context setting

### 7. Real nanobot agent smoke: validated fix

Executed after updating the smoke runner:

```bash
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

Final result: PASS

Observed output:

```text
🐈 nanobot
LLAMACPP_OK
PASS: found LLAMACPP_OK in .../agent_llamacpp_20260510_030352.log
```

Interpretation:

- the real `nanobot agent` path works against the llama.cpp local provider
- the validated smoke mode now mirrors RKLLM's low-context strategy:
	- dedicated provider-owned workspace
	- built-in skills disabled
	- tool schemas disabled

---

## Real Hardware Validation

### Commands run

```bash
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python local_llm/scripts/render_agent_configs.py
proxy_on && bash local_llm/local_provider_llamacpp/build_llamacpp.sh
bash local_llm/local_provider_llamacpp/start_local_provider.sh
curl -sS http://127.0.0.1:19000/health
curl -sS http://127.0.0.1:19000/v1/models
curl -sS http://127.0.0.1:19000/v1/chat/completions -H 'Content-Type: application/json' -d '{...}'
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

### Outcome summary

- Source build from upstream GitHub: successful
- GGUF model deployment/load: successful
- Direct `curl` through nanobot-facing adapter: successful
- Real `nanobot agent` path: successful after reducing prompt/tool footprint for the local `4096` token context window
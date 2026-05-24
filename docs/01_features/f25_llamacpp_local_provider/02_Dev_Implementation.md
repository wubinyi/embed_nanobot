# f25: llama.cpp Local Provider — Dev Implementation

**Task**: Add llama.cpp as a source-built local provider under `local_llm`  
**Branch**: `main_embed`  
**Date**: 2026-05-10  
**Status**: Complete with real-hardware validation

---

## What was implemented

### 1. Provider-owned llama.cpp surface

Added a third provider-owned local-provider directory:

- `local_llm/local_provider_llamacpp/.gitignore`
- `local_llm/local_provider_llamacpp/README.md`
- `local_llm/local_provider_llamacpp/build_llamacpp.sh`
- `local_llm/local_provider_llamacpp/start_local_provider.sh`
- `local_llm/local_provider_llamacpp/openai_adapter.py`

This keeps llama.cpp-specific operational behavior out of the shared
`local_llm/scripts/` layer and avoids any nanobot core provider changes.

### 2. Source build workflow

`build_llamacpp.sh` now:

- clones or updates `https://github.com/ggml-org/llama.cpp.git`
- configures a provider-local CMake build under `local_provider_llamacpp/runtime/build`
- builds the `llama-server` target with `-j$(nproc)`

The validated Radxa run needed `proxy_on` for the initial GitHub clone. After
that, the build completed successfully on aarch64.

### 3. Provider-owned runtime launcher

`start_local_provider.sh` now:

- points at the existing GGUF model `local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf`
- starts raw `llama-server` on `127.0.0.1:19080`
- starts the provider-owned adapter on `127.0.0.1:19000`
- exposes the model alias `qwen3.5-9b-llamacpp`

The launcher keeps the backend and adapter ports stable for nanobot while still
allowing direct backend inspection via provider-local logs.

### 4. OpenAI-compatible adapter for nanobot

`openai_adapter.py` is intentionally thin:

- forwards `GET /health`
- forwards `GET /v1/models`
- forwards `POST /v1/chat/completions`
- injects the default model alias when the caller omits `model`

Although upstream `llama-server` is already OpenAI-compatible, the adapter keeps
the nanobot endpoint provider-owned and gives a stable compatibility layer if
future llama.cpp server behavior changes.

### 5. Shared config and smoke integration

Updated shared helpers:

- `local_llm/scripts/render_agent_configs.py`
	- generates `local_llm/local_provider_llamacpp/runtime/local_llamacpp.json`
	- reuses the existing `custom` provider path instead of changing nanobot core
- `local_llm/scripts/run_agent_smoke.sh`
	- adds `--mode llamacpp`
	- creates a provider-owned llama.cpp smoke workspace
	- disables built-in skills and tool schemas for the llama.cpp smoke path

### 6. Runtime artifact hygiene

Updated provider `.gitignore` files so generated smoke workspaces stay out of
git status.

---

## Live implementation findings

### Finding 1: Initial adapter `503` was normal warmup behavior

The first `/health` and `/v1/models` probes returned `503 Loading model`.
Backend logs showed this was just GGUF loading plus llama.cpp warmup. Once the
backend reported `server is listening`, the adapter became healthy without any
launcher change.

### Finding 2: The direct model path worked before the full agent path

Direct `curl` to `/v1/chat/completions` returned `LLAMACPP_OK` correctly through
the adapter, which isolated the remaining failure to the nanobot prompt surface
rather than the backend or adapter wiring.

### Finding 3: Real agent smoke initially overflowed local context

The first real `nanobot agent` smoke failed with:

```text
request (25970 tokens) exceeds the available context size (4096 tokens)
```

That showed the controlling problem was not the provider path but the default
agent prompt/tool footprint for this local runtime.

### Finding 4: llama.cpp needs the same low-context smoke pattern as RKLLM

The validated fix was to give llama.cpp smoke the same reduced-context pattern
already used for RKLLM:

- provider-owned dedicated workspace
- built-in skills disabled
- tool schemas disabled

After that change, the real `nanobot agent` path returned `LLAMACPP_OK`.

### Finding 5: No nanobot core provider changes were necessary

The existing `custom` provider path was sufficient. All implementation work
stayed in `local_llm/`, which kept conflict surface with upstream effectively
unchanged.

---

## Documentation Freshness Check

- `architecture.md`: OK — no core architecture change; this is an operational local-provider addition under `local_llm/`
- `configuration.md`: OK — no schema changes; llama.cpp reuses existing `custom` provider config
- `customization.md`: OK — no new nanobot extension-point changes
- `PRD.md`: OK — no requirement status change needed
- `agent.md`: OK — no upstream convention changes

### Post-Task Reflection

- **Workflow**: OK — build first, then direct adapter probe, then real agent validation kept the failure localized
- **Team roles**: OK — Reviewer pressure to validate the direct endpoint before touching nanobot prevented unnecessary provider-core changes
- **Conflict surface**: Unchanged — no upstream nanobot shared files were modified for runtime behavior
- **Tech debt**: llama.cpp smoke still depends on a reduced-context workspace for this local `4096` token configuration; larger-context local operation is a follow-up concern, not solved here
- **Docs**: Updated — provider README, local_llm README, validation log, toolchain log, feature docs, and roadmap entry now reflect the validated llama.cpp path
- **User preferences**: None recorded
- **Opportunities**: Add a shared helper that starts any provider-owned local backend and waits for health instead of duplicating provider-specific warmup handling
- **Security**: OK — local adapter binds to `127.0.0.1`; no secrets or model artifacts were committed
- **Skill updates applied**: None
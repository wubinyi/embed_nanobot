# f25: llama.cpp Local Provider — Design Log

**Task**: Add llama.cpp as a local provider under `local_llm`  
**Feature**: Source-built llama.cpp provider for nanobot  
**Branch**: `main_embed`  
**Date**: 2026-05-10

---

## 1. Context & Scope

`local_llm` already has two provider-owned paths:

- `local_provider_ollama/`
- `local_provider_rkllm/`

The next extension point should keep that same split rather than pushing more
provider-specific behavior back into `local_llm/scripts/` or `local_llm/runtime/`.

The user wants:

1. source build from the upstream GitHub repo
2. model deployment using the already-downloaded GGUF file
3. direct `curl` validation
4. a nanobot-facing adapter
5. a real `nanobot agent` validation path

Target model already present:

```text
/home/wubinyi/workspace/embed_nanobot/local_llm/models/gguf/Qwen3.5-9B-Q4_K_M.gguf
```

---

## 2. Design

### [Architect] Proposal

Create a third provider-owned directory:

| Path | Purpose |
|------|---------|
| `local_llm/local_provider_llamacpp/` | llama.cpp-owned provider surface |
| `local_llm/local_provider_llamacpp/build_llamacpp.sh` | Clone and build `llama-server` from GitHub source |
| `local_llm/local_provider_llamacpp/start_local_provider.sh` | Launch raw llama.cpp backend + nanobot-facing adapter |
| `local_llm/local_provider_llamacpp/openai_adapter.py` | Thin adapter on a stable port for nanobot |
| `local_llm/local_provider_llamacpp/runtime/local_llamacpp.json` | Generated runtime config for nanobot |
| `local_llm/local_provider_llamacpp/README.md` | Operational instructions |

Shared touchpoints:

- `local_llm/scripts/render_agent_configs.py`
- `local_llm/scripts/run_agent_smoke.sh`
- `local_llm/README.md`
- `local_llm/docs/*`

### Data Flow

```text
Qwen3.5-9B-Q4_K_M.gguf
    -> build_llamacpp.sh clones + builds llama-server
    -> start_local_provider.sh starts llama-server on backend port
    -> openai_adapter.py exposes stable nanobot-facing port
    -> render_agent_configs.py writes local_llamacpp.json
    -> run_agent_smoke.sh --mode llamacpp
    -> real nanobot agent validation
```

### [Reviewer] Challenge

1. **Why add an adapter when llama.cpp is already OpenAI-compatible?**  
   The adapter keeps a stable provider-owned endpoint, isolates backend launch
   details, and leaves room for nanobot-specific normalization without coupling
   nanobot directly to raw llama.cpp server behavior.

2. **Do we need nanobot core changes?**  
   No. The smallest correct change is to reuse the existing `custom` provider
   path and add only local-LLM operational assets.

3. **Validation class?**  
   `real-hardware required` for this task. The user explicitly wants a source
   build, live model deployment, direct `curl`, and real `nanobot agent`
   verification on the current machine.

Consensus: provider-owned local surface + shared config/smoke wiring.

---

## 3. Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `docs/01_features/f25_llamacpp_local_provider/01_Design_Log.md` | Design + plan |
| `docs/01_features/f25_llamacpp_local_provider/02_Dev_Implementation.md` | Implementation record |
| `docs/01_features/f25_llamacpp_local_provider/03_Test_Report.md` | Test evidence |
| `local_llm/local_provider_llamacpp/.gitignore` | Ignore source checkout and build artifacts |
| `local_llm/local_provider_llamacpp/README.md` | Operator guide |
| `local_llm/local_provider_llamacpp/build_llamacpp.sh` | Upstream source build helper |
| `local_llm/local_provider_llamacpp/start_local_provider.sh` | Backend + adapter launcher |
| `local_llm/local_provider_llamacpp/openai_adapter.py` | Thin adapter for nanobot |

### Modified Files

| File | Change |
|------|--------|
| `local_llm/scripts/render_agent_configs.py` | Generate `local_llamacpp.json` |
| `local_llm/scripts/run_agent_smoke.sh` | Add `llamacpp` mode |
| `local_llm/README.md` | Document llama.cpp provider layout and workflow |
| `local_llm/docs/AGENT_VALIDATION.md` | Add llama.cpp validation result |
| `local_llm/docs/RK3588_TOOLCHAIN_LOG.md` | Add build/deploy/test chronology |
| `docs/00_system/Project_Roadmap.md` | Append activity note |

### Upstream Impact

None on nanobot core behavior. The feature stays inside `local_llm/` and reuses
the existing `custom` provider.

---

## 4. Validation Plan

**Validation Class**: `real-hardware required`

### Required commands

```bash
bash local_llm/local_provider_llamacpp/build_llamacpp.sh
bash local_llm/local_provider_llamacpp/start_local_provider.sh

curl http://127.0.0.1:19000/health
curl -s http://127.0.0.1:19000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.5-9b-llamacpp",
    "stream": false,
    "messages": [{"role": "user", "content": "Reply with exactly LLAMACPP_OK and nothing else."}]
  }'

/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py
bash local_llm/scripts/run_agent_smoke.sh --mode llamacpp
```

### Pass criteria

1. `llama-server` builds from the upstream GitHub source tree.
2. The downloaded GGUF model loads successfully.
3. Direct `curl` to the nanobot-facing adapter returns `LLAMACPP_OK`.
4. `run_agent_smoke.sh --mode llamacpp` returns `LLAMACPP_OK` through real `nanobot agent`.
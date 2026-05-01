# f24: Radxa Local LLM Workspace — Design Log

**Task**: Radxa 5T local LLM workspace + real agent validation  
**Feature**: Local LLM operational workspace for RK3588/Radxa 5T  
**Branch**: `main_embed`  
**Date**: 2026-05-01

---

## 1. Context & Scope

The codebase already supports local inference through provider config and the
Hybrid Router:

- `providers.ollama`, `providers.vllm`, `providers.ovms`, and `providers.custom`
- `_make_provider()` in `nanobot/cli/commands.py`
- `HybridRouterProvider` in `nanobot/providers/hybrid_router.py`

What is missing on the Radxa 5T is the operational surface around that runtime:

- a dedicated top-level folder for local-model assets, scripts, logs, and docs
- a reproducible RK3588 setup path for the local model toolchain
- real `nanobot agent` validation against both local and remote providers

This task does **not** need new provider runtime code. The smallest correct
change is an operational workspace similar in intent to `esp32/`, plus scripts
that exercise the already-existing provider path.

---

## 2. Design

### [Architect] Proposal

Create a new top-level `local_llm/` folder with the following responsibilities:

| Path | Purpose |
|------|---------|
| `local_llm/README.md` | Entry point for local LLM workflow on Radxa 5T |
| `local_llm/docs/RK3588_TOOLCHAIN_LOG.md` | Append-only installation and validation log |
| `local_llm/docs/AGENT_VALIDATION.md` | Real `nanobot agent` validation procedure and captured results |
| `local_llm/scripts/install_ollama.sh` | Reproducible local toolchain installation helper |
| `local_llm/scripts/render_agent_configs.py` | Generate local/remote test configs from the user config without committing secrets |
| `local_llm/scripts/run_agent_smoke.sh` | Execute real single-message `nanobot agent` smoke tests |
| `local_llm/configs/*.jsonc` | Sanitized config templates and examples |
| `local_llm/models/` | Placeholder for downloaded model assets |
| `local_llm/logs/` | Captured runtime logs |
| `local_llm/runtime/` | Ignored generated configs and temporary outputs |

### Data Flow

```text
~/.embed_nanobot/config.json
    -> render_agent_configs.py
    -> local_llm/runtime/local_ollama.json
    -> local_llm/runtime/remote_openrouter.json

run_agent_smoke.sh --config <generated config>
    -> nanobot agent -c <config> -m <prompt>
    -> local_llm/logs/*.log
    -> AGENT_VALIDATION.md records outcome
```

### Toolchain choice

Use **Ollama** as the Radxa local runtime.

Reasoning:

- upstream config already supports `providers.ollama`
- Ollama exposes an OpenAI-compatible API path expected by the repo
- it is materially simpler on ARM64/RK3588 than bringing in vLLM
- this task is about getting a real local model running quickly on current hardware

### [Reviewer] Challenge

1. **Why not add a new provider?**  
   No gap exists in provider support. Adding new runtime code would widen the
   conflict surface without solving the actual operational problem.

2. **What about model storage outside the repo?**  
   Real model weights should not be committed. The repo should provide the
   folder contract and ignore rules, while Ollama continues to own its runtime
   model store under the user environment.

3. **Does this require real hardware validation?**  
   Yes. The user request is specifically about the Radxa 5T local runtime and
   asks for real `nanobot agent` tests. Simulation would not validate RK3588
   toolchain install, local serving, or runtime latency/availability.

Consensus: implement an operational workspace, not a new provider.

---

## 3. Implementation Plan

| # | File | Action |
|---|------|--------|
| 1 | `docs/01_features/f24_local_llm_workspace/01_Design_Log.md` | Create |
| 2 | `docs/01_features/f24_local_llm_workspace/02_Dev_Implementation.md` | Create |
| 3 | `docs/01_features/f24_local_llm_workspace/03_Test_Report.md` | Create |
| 4 | `local_llm/.gitignore` | Create |
| 5 | `local_llm/README.md` | Create |
| 6 | `local_llm/docs/RK3588_TOOLCHAIN_LOG.md` | Create/update |
| 7 | `local_llm/docs/AGENT_VALIDATION.md` | Create/update |
| 8 | `local_llm/scripts/install_ollama.sh` | Create |
| 9 | `local_llm/scripts/render_agent_configs.py` | Create |
| 10 | `local_llm/scripts/run_agent_smoke.sh` | Create |
| 11 | `local_llm/configs/ollama.example.jsonc` | Create |
| 12 | `local_llm/configs/remote.example.jsonc` | Create |
| 13 | `docs/TESTING_GUIDE.md` | Update with Radxa local-vs-remote agent test path |
| 14 | `docs/GETTING_STARTED.md` | Update with `local_llm/` reference |
| 15 | `docs/00_system/Project_Roadmap.md` | Record completion note |

---

## 4. Validation Plan

**Validation Class**: `real-hardware required`

Why:

- installs and runs a local LLM runtime on the actual Radxa 5T
- validates agent-visible behavior through real `nanobot agent` invocations
- compares local and remote provider paths on the live machine

### Required commands

```bash
# Toolchain install / verification
bash local_llm/scripts/install_ollama.sh
ollama --version
ollama pull qwen2.5:3b

# Local runtime
ollama serve

# Config generation
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python local_llm/scripts/render_agent_configs.py

# Real agent tests
bash local_llm/scripts/run_agent_smoke.sh --mode local
bash local_llm/scripts/run_agent_smoke.sh --mode remote
```

### Pass criteria

1. `ollama` is installed and reachable on Radxa 5T.
2. A local model is pulled and listed.
3. `nanobot agent -m ...` succeeds using a local-only config.
4. `nanobot agent -m ...` succeeds using a remote-only config.
5. All steps and outcomes are recorded in the local LLM docs.

---

## 5. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Ollama install requires sudo/systemd interaction | Medium | Log exact privilege requirement; use non-destructive checks first |
| Model too large for acceptable RK3588 latency | Medium | Start with `qwen2.5:3b` |
| Remote provider key/config drift | Medium | Generate runtime configs from the existing user config |
| Existing dirty worktree | Low | Avoid unrelated files and commit only task-owned changes |
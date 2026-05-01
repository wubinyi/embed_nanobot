# f24: Radxa Local LLM Workspace — Dev Implementation

**Task**: Radxa 5T local LLM workspace + real agent validation  
**Branch**: `main_embed`  
**Date**: 2026-05-01  
**Status**: Complete with real-hardware validation

---

## What was implemented

### 1. New top-level workspace: `local_llm/`

Created a dedicated operational workspace for Radxa-local inference:

- `local_llm/README.md`
- `local_llm/.gitignore`
- `local_llm/docs/RK3588_TOOLCHAIN_LOG.md`
- `local_llm/docs/AGENT_VALIDATION.md`
- `local_llm/scripts/install_ollama.sh`
- `local_llm/scripts/render_agent_configs.py`
- `local_llm/scripts/run_agent_smoke.sh`
- `local_llm/configs/ollama.example.jsonc`
- `local_llm/configs/remote.example.jsonc`
- `local_llm/models/.gitkeep`
- `local_llm/logs/.gitkeep`
- `local_llm/runtime/.gitkeep`

### 2. Runtime config generation

`render_agent_configs.py` now derives two runtime configs from the live user
config at `~/.embed_nanobot/config.json`:

- `local_llm/runtime/local_ollama.json`
- `local_llm/runtime/remote_current.json`

Key implementation detail:

- The generated configs intentionally omit `hybridRouter`, because the smoke
  tests are single-provider validations and do not need hybrid routing.
- This keeps the generated files compatible with the current Radxa runtime path
  and avoids unnecessary config-surface coupling.

### 3. Real agent smoke runner

`run_agent_smoke.sh` executes the real CLI path via:

```bash
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python -m nanobot agent ...
```

Important implementation choices:

- Prefer the documented `embed_nanobot` conda environment first
- Execute `python -m nanobot` instead of a standalone `nanobot` binary, so the
  current repository code is always used
- Write an explicit `PASS:` or `FAIL:` verdict into the captured log file
- Use a longer default timeout for local CPU inference on RK3588 (`600s`)

### 4. Documentation updates

Updated existing docs to reference the new workspace:

- `docs/GETTING_STARTED.md`
- `docs/TESTING_GUIDE.md`

---

## Live implementation findings

### Finding 1: VS Code-selected Python env does not match project docs

The workspace-selected environment was:

```text
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python
```

But the project documentation and the actual working Radxa environment are:

```text
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python
```

The smoke runner was updated to prefer the documented environment.

### Finding 2: The documented Radxa environment imports the current repo code

Verified with:

```python
import nanobot
from nanobot.config.schema import Config
```

Observed:

- `nanobot.__file__` resolved to the current repository path
- `Config.model_fields` includes `hybrid_router`

### Finding 3: The installer needed current Ollama archive endpoints

The helper supports two install paths:

1. official installer via sudo when available
2. user-local fallback extraction into `local_llm/runtime/ollama-dist`

The original fallback assumed GitHub release asset URLs. The working Radxa path
now uses the current upstream download endpoints from `ollama.com`:

- prefer `.tar.zst` when `zstd` is available
- fall back to `.tgz` when needed

This kept the installer compatible with the repo-local runtime workflow.

### Finding 4: The validated local model is a small alias, not the earlier 3B default

The first local validation target, `qwen2.5:3b`, was too heavy for stable CPU
use on the Radxa. The validated path now uses:

- base model: `qwen2.5:0.5b`
- alias: `qwen2.5:0.5b-nb`
- alias parameter: `num_ctx 8192`

`render_agent_configs.py` and `local_llm/configs/ollama.example.jsonc` now
default to this validated local model.

### Finding 5: The local smoke failure was a timeout mismatch, not a provider failure

The direct local `nanobot agent` path succeeded, but the original smoke helper
used a fixed `180s` timeout. Measured wall-clock runtime on the Radxa was about
`371s`, so the helper falsely reported failure. The script now defaults to:

- local mode: `600s`
- remote mode: `180s`

---

## Documentation Freshness Check

- `architecture.md`: OK — no architecture change required for this operational workspace
- `configuration.md`: OK — no schema changes
- `customization.md`: OK — no extension-point changes
- `PRD.md`: OK — local LLM support already documented; this task adds operational workflow
- `agent.md`: OK — no upstream convention changes

### Post-Task Reflection

- **Workflow**: OK — design first, then scripts, then live validation was the right order
- **Team roles**: OK — Reviewer surfaced the runtime-vs-timeout mismatch before unnecessary provider changes
- **Conflict surface**: Unchanged — no shared runtime files modified
- **Tech debt**: Local CPU inference is still slow on RK3588 even with the validated small model
- **Docs**: Updated — local_llm workspace now documents the validated small-model workflow
- **User preferences**: None recorded
- **Opportunities**: Add a helper to generate validated Ollama aliases automatically instead of documenting manual `Modelfile` creation
- **Security**: OK — no secrets committed; runtime configs are generated from local user config and ignored from git
- **Skill updates applied**: None

# f24: Radxa Local LLM Workspace — Dev Implementation

**Task**: Radxa 5T local LLM workspace + real agent validation  
**Branch**: `main_embed`  
**Date**: 2026-05-01  
**Status**: Partial completion with external blocker

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

### Finding 3: Ollama install is blocked by outbound GitHub connectivity

The helper supports two install paths:

1. official installer via sudo when available
2. user-local fallback extraction into `local_llm/runtime/ollama-dist`

On this Radxa host:

- sudo is not passwordless
- downloading the ARM64 Ollama archive from GitHub fails with connection timeout

This is an external environment blocker, not a repo-code defect.

---

## Documentation Freshness Check

- `architecture.md`: OK — no architecture change required for this operational workspace
- `configuration.md`: OK — no schema changes
- `customization.md`: OK — no extension-point changes
- `PRD.md`: OK — local LLM support already documented; this task adds operational workflow
- `agent.md`: OK — no upstream convention changes

### Post-Task Reflection

- **Workflow**: OK — design first, then scripts, then live validation was the right order
- **Team roles**: OK — Reviewer surfaced the environment mismatch and config-compat issue quickly
- **Conflict surface**: Unchanged — no shared runtime files modified
- **Tech debt**: External environment blocker remains for GitHub reachability to install Ollama locally
- **Docs**: Updated — local_llm workspace is now discoverable from user-facing docs
- **User preferences**: None recorded
- **Opportunities**: Add a proxy-aware or mirror-aware local runtime installer for restricted networks
- **Security**: OK — no secrets committed; runtime configs are generated from local user config and ignored from git
- **Skill updates applied**: None

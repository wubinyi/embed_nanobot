# Coding Guidelines — Align with HKUDS/nanobot

This document defines coding conventions for `wubinyi/embed_nanobot` to stay aligned with the upstream [HKUDS/nanobot](https://github.com/HKUDS/nanobot) repository and **minimize future merge conflicts**.

## Golden Rule

> **Upstream-first**: Always follow the upstream repository's patterns, file structure, and conventions. Our custom features should be **additive** — appended at the end of lists, registered last, and placed in separate files/modules.

---

## 1. Adding New Channels

Channels are a frequent source of divergence. Follow this exact pattern:

### File placement
- Place channel implementations in `nanobot/channels/<name>.py` (not in a separate top-level module)
- Exception: The `nanobot/mesh/` module is our custom feature and remains separate

### Config registration (`nanobot/config/schema.py`)
- Define your `XxxConfig(BaseModel)` class **after** all upstream config classes
- Add the field to `ChannelsConfig` **at the end** of the field list, after all upstream channels:

```python
class ChannelsConfig(BaseModel):
    # --- upstream channels (do NOT reorder) ---
    whatsapp: WhatsAppConfig = ...
    telegram: TelegramConfig = ...
    discord: DiscordConfig = ...
    feishu: FeishuConfig = ...
    dingtalk: DingTalkConfig = ...
    email: EmailConfig = ...
    slack: SlackConfig = ...
    qq: QQConfig = ...
    # --- our custom channels (append here) ---
    mesh: MeshConfig = ...
```

### Channel manager (`nanobot/channels/manager.py`)
- Register your channel **at the end** of `_init_channels()`, after all upstream channel blocks
- Follow the same pattern: `if config.enabled → try import → register → except ImportError`

### README
- Add documentation for custom channels **after** all upstream channel sections
- Do NOT modify upstream channel documentation

---

## 2. Adding New Providers / Features

### Provider extensions
- Place custom providers in their own files: `nanobot/providers/<name>.py`
- Register in `nanobot/providers/registry.py` by **appending** to the `PROVIDERS` list
- Do NOT modify existing provider entries

### Config extensions (`nanobot/config/schema.py`)
- Add new config models **after** existing ones
- Add fields to `Config` **at the end** of the class

### CLI extensions (`nanobot/cli/commands.py`)
- Add new CLI logic in a **clearly separated block** with comment headers
- When modifying shared functions like `_make_provider()`, add custom logic **before** the standard path (early return pattern) or in a separate helper function

---

## 3. File & Module Organization

| Category | Convention |
|----------|-----------|
| New features | Create new files/modules; avoid modifying upstream files |
| Channel implementations | `nanobot/channels/<name>.py` |
| Custom modules | Separate top-level package (e.g., `nanobot/mesh/`) |
| Tests | `tests/test_<feature>.py` |
| Documentation | `docs/<topic>.md` |

---

## 4. Conflict-Prone Files & Mitigation

These files are modified by both upstream and our fork. Take extra care:

| File | Conflict Risk | Mitigation |
|------|--------------|------------|
| `nanobot/config/schema.py` | **High** — both sides add config classes and fields | Append our fields at the end of `ChannelsConfig` and `Config` |
| `nanobot/channels/manager.py` | **High** — both sides register channels | Append our channel registration at the end of `_init_channels()` |
| `nanobot/cli/commands.py` | **Medium** — both sides modify CLI behavior | Isolate custom logic in separate functions; minimize inline changes |
| `nanobot/providers/__init__.py` | **Low** — both sides export providers | Append our exports after upstream's |
| `nanobot/providers/registry.py` | **Medium** — both sides add ProviderSpec entries | Append our entries at end of PROVIDERS tuple |
| `README.md` | **Medium** — both sides add documentation | Add custom sections at the end of relevant areas; don't rewrite upstream text |
| `.gitignore` | **Low** — simple list file | Append entries at the end |
| `pyproject.toml` | **Low** — version/deps | Don't modify version; append deps at end |

---

## 5. Syncing with Upstream

### Regular sync workflow
1. `git fetch upstream main`
2. `git merge upstream/main` (prefer merge over rebase to preserve history)
3. Resolve conflicts by keeping upstream's version for shared code, then re-adding our customizations at the end
4. Run tests: `python -m pytest tests/`

### Before starting new features
1. Sync with upstream first
2. Check if upstream already has or is working on a similar feature
3. If upstream has a different implementation, adopt theirs and extend it rather than maintaining a parallel implementation

---

## 6. Code Style

Follow the upstream project's conventions:

- **Python**: Type hints, `from __future__ import annotations`, loguru for logging
- **Config models**: Pydantic `BaseModel` with `Field(default_factory=...)`, `BaseSettings` for root config
- **Provider registry**: `ProviderSpec` supports `is_oauth`, `extra_headers`, `detect_by_base_keyword`
- **Channel pattern**: Inherit from `BaseChannel`, implement `start()`, `stop()`, `send()`
- **CLI framework**: `typer` + `prompt_toolkit` for interactive input
- **Imports**: Lazy imports inside functions for optional dependencies (wrapped in try/except)
- **Naming**: snake_case for files/functions, PascalCase for classes
- **Comments**: Minimal — only for non-obvious logic; use docstrings for public APIs
- **JSON config keys**: camelCase in config.json, snake_case in Python (Pydantic handles conversion)

---

## 7. What NOT to Change

Unless absolutely necessary, **do not modify** these upstream files:

- `nanobot/agent/loop.py` — Core agent logic
- `nanobot/bus/` — Message bus infrastructure  
- `nanobot/cron/` — Scheduling system
- `nanobot/session/` — Session management
- `nanobot/skills/` — Built-in skills
- `nanobot/providers/litellm_provider.py` — Core LLM provider
- `core_agent_lines.sh` — Line count script
- `Dockerfile`, `SECURITY.md`, `LICENSE`

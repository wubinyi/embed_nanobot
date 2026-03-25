# Upstream Sync: 2026-03-25

## Summary

- **Upstream HEAD**: `0ccfcf6` (428 commits ahead of previous sync point `ab89775`)
- **Merge conflicts**: 6 files (shell.py, commands.py, loader.py, schema.py, providers/__init__.py, pyproject.toml)
- **Additional fixes needed**: 2 (registry.py duplicate Ollama, test_providers_init.py `__all__` assertion)

## Major Upstream Changes

### 1. LiteLLM Removed — Native SDKs
- `nanobot/providers/litellm_provider.py` deleted
- New: `nanobot/providers/anthropic_provider.py` (native Anthropic SDK)
- New: `nanobot/providers/openai_compat_provider.py` (native OpenAI SDK)
- `_make_provider()` in commands.py now uses backend-specific instantiation
- **Impact on us**: HybridRouterProvider's sub-providers changed from `LiteLLMProvider` to `OpenAICompatProvider`

### 2. Lazy Provider Imports
- `nanobot/providers/__init__.py` uses `_LAZY_IMPORTS` dict + `__getattr__` instead of eager imports
- Our HybridRouterProvider added to `_LAZY_IMPORTS` + `__all__` + `TYPE_CHECKING`

### 3. Channel Config Decentralization
- All channel config classes (WhatsAppConfig, TelegramConfig, etc.) moved from `schema.py` into individual channel modules
- `ChannelsConfig` now uses `extra="allow"` — accepts any dict
- Each channel's `__init__` does `if isinstance(config, dict): config = XConfig.model_validate(config)`
- **Impact**: Our 240-line block of channel config classes in schema.py was the largest conflict

### 4. Channel Auto-Discovery
- New: `nanobot/channels/registry.py` with `discover_all()` using `pkgutil` + entry_points
- `ChannelManager._init_channels()` now iterates `discover_all()` instead of hardcoded if/try blocks
- Our mesh channel in `nanobot/mesh/channel.py` is NOT auto-discovered (intentional isolation)
- Added `display_name = "LAN Mesh"` to MeshChannel for compatibility

### 5. New Channels
- WeiXin (WeChat) channel
- WeCom (WeChat Work) channel

### 6. New Providers
- OVMS (OpenVINO Model Server) — added to providers and registry
- Ollama now native in upstream (we removed our duplicate ProviderSpec)

### 7. Security & Infrastructure
- CI/CD via `.github/workflows/ci.yml`
- `nanobot/security/` module (network validation, etc.)
- `nanobot/command/` module (built-in command routing)
- Shell tool: expanded path resolution with `expandvars` + `expanduser`
- `tiktoken` dependency added for token counting

### 8. Test Reorganization
- Tests moved from flat `tests/` to subdirectories: `tests/agent/`, `tests/channels/`, `tests/cli/`, `tests/config/`, `tests/cron/`, `tests/providers/`, `tests/security/`, `tests/tools/`

## Conflict Resolutions

### 1. `nanobot/agent/tools/shell.py` (trivial)
- **Ours**: `Path(raw).resolve()`
- **Theirs**: `os.path.expandvars(raw.strip())` + `Path(expanded).expanduser().resolve()`
- **Resolution**: Took theirs — security improvement for shell path validation

### 2. `nanobot/cli/commands.py` (medium)
- **Area**: `channel_status()` function
- **Ours**: Hardcoded channel status rows (WhatsApp, Discord, Feishu, etc.)
- **Theirs**: Dynamic `discover_all()` loop
- **Resolution**: Took theirs — much cleaner, auto-discovers all channels including mesh

### 3. `nanobot/config/loader.py` (semantic merge)
- **Ours**: Changed default path to `.embed_nanobot`, lost `_current_config_path` check
- **Theirs**: Added `_current_config_path` check, kept `.nanobot` path
- **Resolution**: Combined — kept `_current_config_path` check AND our `.embed_nanobot` default path

### 4. `nanobot/config/schema.py` (three regions, largest conflict)
- **Region 1**: All channel config classes (240 lines) vs upstream's empty space
  - **Resolution**: Removed all upstream channel configs (they're now in channel modules). Kept only MeshConfig.
- **Region 2**: ChannelsConfig fields — our typed fields vs upstream's `extra="allow"`
  - **Resolution**: Removed hardcoded channel fields. Kept only `mesh: MeshConfig` for typed access.
- **Region 3**: ProvidersConfig — our `ollama` vs upstream's `ollama + ovms`
  - **Resolution**: Took upstream's version (includes OVMS)

### 5. `nanobot/providers/__init__.py` (structural)
- **Ours**: Eager imports of LiteLLMProvider + HybridRouterProvider
- **Theirs**: Lazy import pattern with `_LAZY_IMPORTS` dict
- **Resolution**: Adopted upstream's lazy pattern, added HybridRouterProvider to `_LAZY_IMPORTS` + `__all__` + `TYPE_CHECKING`

### 6. `pyproject.toml` (trivial)
- **Ours**: `cryptography` dep
- **Theirs**: `tiktoken` dep
- **Resolution**: Kept both

## Additional Fixes (Not Conflicts)

### 1. `nanobot/providers/registry.py` — Duplicate Ollama ProviderSpec
- Upstream added native Ollama entry; our old entry used removed fields (`litellm_prefix`, `skip_prefixes`)
- Caused `TypeError: ProviderSpec.__init__() got unexpected keyword argument 'litellm_prefix'`
- **Fix**: Removed our duplicate Ollama entry entirely

### 2. `tests/providers/test_providers_init.py` — `__all__` assertion
- Upstream test asserts exact `__all__` list; ours includes HybridRouterProvider
- **Fix**: Updated assertion and added `hybrid_router` to monkeypatch cleanup

### 3. `nanobot/mesh/channel.py` — Added `display_name`
- Upstream's `BaseChannel` now requires `display_name` class attribute for `discover_all()` and channel status display
- **Fix**: Added `display_name = "LAN Mesh"` to MeshChannel

### 4. `nanobot/cli/commands.py` — LiteLLMProvider → OpenAICompatProvider
- HybridRouter creation used removed `LiteLLMProvider` for sub-providers
- **Fix**: Replaced with `OpenAICompatProvider` (upstream's general-purpose provider), removed `provider_name` kwarg

## New Rules Added to Conflict Minimization Strategy

- **Rule 9**: Never duplicate upstream config classes in `schema.py`
- **Rule 10**: Follow upstream's lazy import pattern for `__init__.py`
- **Rule 11**: Don't shadow upstream's new native features
- **Rule 12**: Adapt to upstream's channel discovery mechanism

## Test Results

- **1454 passed**, 1 skipped, 1 unrelated failure (`test_duckduckgo_search` — missing `ddgs` module)
- No merge-related test failures

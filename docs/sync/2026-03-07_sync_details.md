# Upstream Sync — 2026-03-07

## Summary

- **Upstream range**: `e86cfcd..ab89775` (211 commits, ~120 non-merge)
- **Conflicts**: 7 files (all resolved)
- **Tests**: 1047 passed (1 mesh test fixed for allow_from semantics)
- **New upstream tag**: v0.1.4.post3

## Key Upstream Changes

### New Features
- **Azure OpenAI provider** (`azure_openai_provider.py`): Direct Azure endpoint support with deployment name routing
- **Discord file attachments**: `send()` now supports file attachments via Discord API
- **WhatsApp media support**: Generic media sending (images, files) + message deduplication (OrderedDict)
- **Feishu channel rewrite**: Table splitting for large responses, interactive card content extraction, post content support
- **DingTalk media messages**: Images as image messages, files as attachments
- **Tool parameter auto-casting**: `base.py` auto-casts string params to match schema types (int/float/bool)
- **reasoning_effort config**: New `AgentDefaults` field for LLM thinking mode (e.g., Claude extended thinking)
- **Telegram streaming UX**: Improved streaming with table rendering support

### Bug Fixes
- **LiteLLM tool_call_id normalization**: Short alphanumeric IDs for Mistral compatibility; Copilot provider fix
- **Session poisoning prevention**: Filter empty/null assistant messages in `_save_turn`
- **QQ channel**: Pass msg_id in C2C reply; disable botpy file log for read-only FS
- **Shell tool**: Refactored path extraction into `_extract_absolute_paths` method (better Windows path parsing)
- **Feishu interactive cards**: Fix text extraction from interactive messages
- **Lark**: Remove non-existent `stop()` call
- **Codex provider**: Remove overly broad "codex" keyword
- **WhatsApp**: Avoid dropping media-only messages

### Architecture Changes
- **BaseChannel.allow_from validation**: Empty list `[]` now means "deny all" (previously ambiguous). `["*"]` for allow-all. `_validate_allow_from()` added to ChannelManager.
- **SSL verification**: Added SSL verification for chat completion calls
- **Timeout increase**: Longer timeout for chat completion calls
- **Subagent streamlining**: Reuses `ContextBuilder` and `SkillsLoader`
- **WeakValueDictionary**: Used for consolidation locks — auto-cleanup
- **reasoning_content**: Preserved in session history for thinking models

## Conflicts Resolved

| File | Ours | Theirs | Resolution |
|------|------|--------|------------|
| `shell.py` | Inline regex for path extraction | Extracted to `_extract_absolute_paths()` method | Accept upstream refactor (cleaner) |
| `manager.py` | Mesh channel registration at end | New `_validate_allow_from()` method | Keep both: mesh reg + validation method |
| `commands.py` (gateway) | Device control & reprogram tool registration | Upstream removed trailing block | Keep our extensions |
| `commands.py` (table) | Simple trailing whitespace | Feishu + Mochat table rows added | Accept upstream additions |
| `schema.py` | MeshConfig class at end | Upstream removed our additions | Keep our MeshConfig |
| `providers/__init__.py` | HybridRouterProvider export | AzureOpenAIProvider added | Merge: keep both exports |
| `registry.py` | Ollama ProviderSpec | Upstream didn't have Ollama | Keep our Ollama provider |
| `pyproject.toml` | cryptography dep | chardet + openai deps added | Keep all deps |

## Test Adaptation

- **Mesh tests** (`test_mesh.py`): Updated 3 tests to use `allow_from=["*"]` instead of `[]` to match new upstream semantics (empty list = deny all).
- **All 1047 tests pass**.

## Conflict Surface Update

| File | Risk Level | Notes |
|------|-----------|-------|
| `schema.py` | Medium | Still appending MeshConfig at end — upstream adds new config models |
| `manager.py` | Low | Our mesh block stays appended; new `_validate_allow_from` is separate method |
| `commands.py` | Medium | Two embed blocks in `gateway()`; upstream actively refactoring this file |
| `providers/__init__.py` | Low | Single-line append |
| `providers/registry.py` | Low | Ollama spec appended before auxiliary section |
| `pyproject.toml` | Low | Dep appended at end |
| `shell.py` | **Resolved** | No longer a conflict surface — our inline code was replaced by upstream method |

## Convention Updates

- **allow_from**: Empty = deny all. `["*"]` = allow all. Must set in tests when testing message flow.
- **Azure provider pattern**: `provider_name == "azure_openai"` check in `_make_provider()`.
- **Tool auto-cast**: `_cast_params()` in `base.py` — be aware when writing tool tests.

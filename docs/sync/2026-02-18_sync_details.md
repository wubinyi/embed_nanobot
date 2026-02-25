# Sync Details — 2026-02-18

**Commits**: 20
**Range**: `8053193` → `7f8a3df`
**Files changed**: 9, +269 / −127 lines
**Conflicts**: schema.py, commands.py
**Convention change**: All config models now inherit `Base` instead of `BaseModel`

---

## Upstream Features Merged

### 1. Pydantic Base Class with alias_generator — PR #766
- **Modified**: `nanobot/config/schema.py` — New `Base(BaseModel)` class with `ConfigDict(alias_generator=to_camel, populate_by_name=True)`. All config models now inherit `Base` instead of raw `BaseModel`. Fixes camelCase → snake_case conversion for MCP env keys and other nested config.
- **Impact on our code**: Migrated `MeshConfig` and `HybridRouterConfig` from `BaseModel` → `Base`.

### 2. Mochat Channel — PR #771
- **New config models**: `MochatMentionConfig`, `MochatGroupRule`, `MochatConfig` in schema.py.
- **New channel file**: `nanobot/channels/mochat.py` (already existed from prior upstream merge).
- **New field**: `mochat` in `ChannelsConfig` (between feishu and dingtalk).
- **Features**: Session/panel watching, mention handling per-group, reconnect with backoff, reply delay modes.

### 3. Custom Provider — PR #780
- **New file**: `nanobot/providers/custom_provider.py` — Direct OpenAI-compatible endpoint bypass (no LiteLLM).
- **Modified**: `nanobot/cli/commands.py` — `_make_provider()` now checks for `custom` provider before LiteLLM fallback.
- **Modified**: `nanobot/config/loader.py` — Config loading improvements.

### 4. Slack Enhancements
- **Modified**: `nanobot/channels/slack.py` — Added `reply_in_thread: bool = True` and `react_emoji: str = "eyes"` defaults.
- **Modified**: `nanobot/config/schema.py` — `SlackConfig` gains `reply_in_thread` and `react_emoji` fields.

### 5. Docker Compose Support
- **New file**: `docker-compose.yml` — Standard Docker Compose configuration for deployment.

### 6. Documentation Updates
- **Modified**: `README.md` — Updated with new features and chat app table.
- **Modified**: `SECURITY.md` — Updated security policy.

---

## Conflicts Resolved

| File | Conflict | Resolution |
|------|----------|------------|
| `nanobot/config/schema.py` | 4 zones: (1) Mochat classes + SlackDMConfig base class, (2) MeshConfig + ChannelsConfig base class, (3) HybridRouterConfig + WebSearchConfig base class, (4) hybrid_router field in Config | Accepted all upstream code; migrated our MeshConfig/HybridRouterConfig to `Base`; restored `mochat` field in ChannelsConfig; kept append-only markers |
| `nanobot/cli/commands.py` | Docstring difference for `_make_provider()` | Accepted upstream's shorter docstring; HybridRouter code block preserved |

## Auto-Merged Files (no conflicts)
- `README.md` — Upstream changes merged cleanly with our extensions section.
- `SECURITY.md` — No custom changes, accepted as-is.
- `docker-compose.yml` — New file, accepted as-is.
- `nanobot/channels/slack.py` — New fields merged cleanly.
- `nanobot/config/loader.py` — No custom changes.
- `nanobot/providers/custom_provider.py` — New file, accepted as-is.
- `nanobot/providers/registry.py` — New entries merged cleanly.

## Convention Change: BaseModel → Base
All config models upstream now use `Base` instead of raw `BaseModel`. Our custom models have been updated accordingly. This change must be followed for any future config models we add.

## Remaining Upstream Commits
- **0** — fully synced with upstream/main (7f8a3df).

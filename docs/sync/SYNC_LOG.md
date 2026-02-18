# Upstream Sync Log

Tracks all merges from `HKUDS/nanobot` (upstream) `main` into our `main_embed` branch.

## Log

| Date | Upstream HEAD | Commits Merged | Conflicts | Resolution | PR |
|------|---------------|----------------|-----------|------------|----|
| 2026-02-07 | ea1d2d7 | ~15 | schema.py, manager.py, commands.py, README.md | Appended our config fields, re-registered mesh channel, kept our CLI additions. See MERGE_ANALYSIS.md | [#4](https://github.com/wubinyi/embed_nanobot/pull/4) |
| 2026-02-10 | ea1d2d7 | 3 (MiniMax, MoChat, DingTalk) | schema.py (MiniMax config) | Resolved conflicts, adapted MiniMax. Added missing channel docs. | [#6](https://github.com/wubinyi/embed_nanobot/pull/6) |
| 2026-02-12 | ea1d2d7 | 0 | None | Clean merge (main already up to date) | Direct merge |
| 2026-02-17 | a219a91 | 116 (77 non-merge) | README.md, commands.py, providers/__init__.py, pyproject.toml | Upstream-first; appended HybridRouter/Codex integration in CLI; kept vLLM/Mesh sections in README. See details below. | `copilot/sync-upstream-and-merge-main-embed` |
| 2026-02-17b | 8053193 | 22 (11 non-merge) | README.md | Telegram media, GitHub Copilot provider, cron timezone, ClawHub skill, empty content fix | Accept upstream README, preserve embed_nanobot extensions section |
| 2026-02-18 | 7f8a3df | 20 | schema.py, commands.py | Base(BaseModel) alias_generator, Mochat channel, CustomProvider, Slack reply_in_thread/react_emoji, Docker Compose | Migrated MeshConfig/HybridRouterConfig to Base; restored mochat field |
| 2026-02-18b | ce4f005 | 9 (4 non-merge) | None | SiliconFlow provider, workspace-scoped sessions with legacy migration, tool metadata in history | Clean merge, no conflicts |

---

## 2026-02-17 Sync Details

### Upstream Features Merged (ea1d2d7 → a219a91)

This sync brought in a large batch of upstream improvements spanning **35 files changed**, **+2,070 / −610 lines**.

#### 1. MCP (Model Context Protocol) Support — PR #554
- **New file**: `nanobot/agent/tools/mcp.py` — `MCPToolWrapper` class wraps external MCP tool servers as nanobot tools.
- **New config**: `MCPServerConfig` in `schema.py` — supports both stdio and HTTP MCP servers.
- **New field**: `tools.mcp_servers` dict in `ToolsConfig`.
- **Agent loop**: `AgentLoop._connect_mcp()` connects to configured MCP servers at startup and registers their tools dynamically.
- **Cleanup**: `close_mcp()` properly teardowns MCP connections on exit.

#### 2. OpenAI Codex Provider — PR #151 (OAuth-based)
- **New file**: `nanobot/providers/openai_codex_provider.py` — Full OAuth flow for Codex authentication.
- **New registry entry**: `ProviderSpec(name="openai_codex", is_oauth=True, ...)` in `registry.py`.
- **New config field**: `openai_codex` in `ProvidersConfig`.
- **CLI integration**: `nanobot login` command for OAuth login; status display shows Codex login state.

#### 3. Redesigned Memory System — PR #565
- **Rewritten**: `nanobot/agent/memory.py` — Two-layer architecture:
  - `MEMORY.md` for long-term persistent facts
  - `HISTORY.md` for grep-searchable conversation log
- **Session consolidation**: `AgentLoop._consolidate_memory()` summarizes old messages via LLM, writes to MEMORY.md/HISTORY.md, and trims session.
- **`/new` slash command**: Clears session and triggers full consolidation.

#### 4. Slash Commands — PR #569
- **`/new`**: Start a new conversation with memory consolidation.
- **`/help`**: Show available commands.
- Unified across all channels (Telegram, Discord, Slack, CLI, etc.).

#### 5. Interleaved Chain-of-Thought — PR #538
- **Modified**: `nanobot/agent/loop.py` — Agent loop now passes through `thinking`/reasoning content from models that support it (e.g., Claude extended thinking).

#### 6. CLI UX Overhaul — PR #488, #604
- **Rewritten CLI input**: `prompt_toolkit` integration for proper readline, multi-line editing, history.
- **Non-destructive onboarding**: `nanobot onboard` now merges config instead of overwriting.
- **Custom provider support**: New `custom` provider in `ProvidersConfig` for any OpenAI-compatible endpoint.
- **OAuth login**: `nanobot login` command for Codex and future OAuth providers.

#### 7. Security Hardening — PR #587
- **WhatsApp bridge**: Bound to localhost + optional token authentication (`bridge/src/server.ts`).
- **New file**: `SECURITY.md` with responsible disclosure policy.

#### 8. Cron/Scheduling Improvements — PR #533
- **One-time `at` schedule**: `feat(cron): add 'at' parameter for one-time scheduled tasks`.
- **Timezone support**: Cron jobs respect timezone configuration.
- **Updated SKILL.md**: `nanobot/skills/cron/SKILL.md` reflects `at` parameter and timezone.

#### 9. Channel Improvements
- **Telegram** (PR #694, #701): Message length limit handling (smart splitting), consistent `sender_id` for command allowlist.
- **Feishu** (PR #629, #593): Rich text message extraction, direct + localized post formats, markdown heading fix.
- **Slack** (PR #717): `slackify-markdown` for proper mrkdwn formatting, table-to-text conversion.
- **DingTalk/QQ**: Minor stability fixes, async improvements.

#### 10. Agent & Provider Fixes
- **JSON repair**: `json_repair` library for robust LLM response parsing (PR #664).
- **Temperature/max_tokens**: Properly wired to all chat calls (PR #523).
- **Provider improvements**: `extra_headers` support, `is_oauth` flag in `ProviderSpec`, `custom` provider.
- **Subagent**: Added `edit_file` tool and time context to sub agent (PR #543).
- **`max_messages` increase**: Temporary workaround to 500 messages.

#### 11. ClawHub Skill Support
- `feat: support openclaw/clawhub skill metadata format` — Agent can now search and install skills from the ClawHub public registry.
- New skill: `nanobot/skills/` ClawHub skill for public skill marketplace.

### Conflicts Resolved

| File | Conflict | Resolution |
|------|----------|------------|
| `README.md` | Both sides updated news/feature sections | Kept upstream news; preserved our vLLM, Hybrid Router, LAN Mesh sections at bottom |
| `nanobot/cli/commands.py` | Upstream added Codex provider + OAuth login; we have HybridRouterProvider | Integrated both: upstream Codex flows first, our HybridRouter appended |
| `nanobot/providers/__init__.py` | Upstream added Codex export; we have hybrid_router export | Kept both exports |
| `pyproject.toml` | Upstream added mcp, prompt-toolkit, json-repair, python-socks deps | Accepted all upstream deps |

### New Upstream Files Accepted As-Is
- `nanobot/agent/tools/mcp.py`
- `nanobot/providers/openai_codex_provider.py`
- `SECURITY.md`
- `tests/test_cli_input.py`, `tests/test_consolidate_offset.py`

## Pending

As of 2026-02-17 (second sync), upstream is **fully synced** — 0 commits ahead.

**Next sync**: On-demand, before starting next feature task.

---

## 2026-02-17b Sync Details

### Upstream Features Merged (a219a91 → 8053193)

This sync brought in the remaining 22 upstream commits (11 non-merge), spanning **12 files changed**.

#### 1. Telegram Media File Support — PR #747
- `nanobot/channels/telegram.py` — Handle voice messages, audio, images, and documents. Clean up media sending logic.

#### 2. GitHub Copilot Provider — PR #720
- `nanobot/providers/registry.py` — Added `github_copilot` provider spec with `is_oauth=True`.
- `nanobot/cli/commands.py` — Refactored to use `is_oauth` flag instead of hardcoded provider name check.

#### 3. Cron Timezone Support — PR #744
- `nanobot/agent/tools/cron.py` — Timezone validation and display bug fix.
- `nanobot/cron/service.py` — Timezone propagation improvements.
- `nanobot/skills/cron/SKILL.md` — Updated skill docs with timezone examples.

#### 4. ClawHub Skill — PR #758
- **New file**: `nanobot/skills/clawhub/SKILL.md` — Skill for searching and installing agent skills from the public ClawHub registry.
- `nanobot/skills/README.md` — Updated index.

#### 5. Bug Fixes
- `nanobot/agent/context.py`, `nanobot/agent/tools/message.py` — Omit empty content entries in assistant messages.

### Conflicts Resolved

| File | Conflict | Resolution |
|------|----------|------------|
| `README.md` | Upstream restructured README significantly (new sections, updated Chat Apps table with Mochat) | Accept upstream version entirely; moved our custom sections (vLLM, Hybrid Router, LAN Mesh) to a new "embed_nanobot Extensions" section before Star History |

### Auto-Merged Files (no conflicts)
- `nanobot/cli/commands.py` — GitHub Copilot `is_oauth` refactor merged cleanly with our HybridRouter additions.
- `nanobot/config/schema.py` — No new fields from upstream; our appended fields preserved.
- `nanobot/providers/registry.py` — New `github_copilot` spec merged above our appended `vllm` spec.

### Remaining Upstream Commits
- **0** — fully synced with upstream/main (8053193).

---

## 2026-02-18 Sync Details

### Upstream Features Merged (8053193 → 7f8a3df)

This sync brought in 20 upstream commits spanning **9 files changed**, **+269 / −127 lines**.

#### 1. Pydantic Base Class with alias_generator — PR #766
- **Modified**: `nanobot/config/schema.py` — New `Base(BaseModel)` class with `ConfigDict(alias_generator=to_camel, populate_by_name=True)`. All config models now inherit `Base` instead of raw `BaseModel`. Fixes camelCase → snake_case conversion for MCP env keys and other nested config.
- **Impact on our code**: Migrated `MeshConfig` and `HybridRouterConfig` from `BaseModel` → `Base`.

#### 2. Mochat Channel — PR #771
- **New config models**: `MochatMentionConfig`, `MochatGroupRule`, `MochatConfig` in schema.py.
- **New channel file**: `nanobot/channels/mochat.py` (already existed from prior upstream merge).
- **New field**: `mochat` in `ChannelsConfig` (between feishu and dingtalk).
- **Features**: Session/panel watching, mention handling per-group, reconnect with backoff, reply delay modes.

#### 3. Custom Provider — PR #780
- **New file**: `nanobot/providers/custom_provider.py` — Direct OpenAI-compatible endpoint bypass (no LiteLLM).
- **Modified**: `nanobot/cli/commands.py` — `_make_provider()` now checks for `custom` provider before LiteLLM fallback.
- **Modified**: `nanobot/config/loader.py` — Config loading improvements.

#### 4. Slack Enhancements
- **Modified**: `nanobot/channels/slack.py` — Added `reply_in_thread: bool = True` and `react_emoji: str = "eyes"` defaults.
- **Modified**: `nanobot/config/schema.py` — `SlackConfig` gains `reply_in_thread` and `react_emoji` fields.

#### 5. Docker Compose Support
- **New file**: `docker-compose.yml` — Standard Docker Compose configuration for deployment.

#### 6. Documentation Updates
- **Modified**: `README.md` — Updated with new features and chat app table.
- **Modified**: `SECURITY.md` — Updated security policy.

### Conflicts Resolved

| File | Conflict | Resolution |
|------|----------|------------|
| `nanobot/config/schema.py` | 4 zones: (1) Mochat classes + SlackDMConfig base class, (2) MeshConfig + ChannelsConfig base class, (3) HybridRouterConfig + WebSearchConfig base class, (4) hybrid_router field in Config | Accepted all upstream code; migrated our MeshConfig/HybridRouterConfig to `Base`; restored `mochat` field in ChannelsConfig; kept append-only markers |
| `nanobot/cli/commands.py` | Docstring difference for `_make_provider()` | Accepted upstream's shorter docstring; HybridRouter code block preserved |

### Auto-Merged Files (no conflicts)
- `README.md` — Upstream changes merged cleanly with our extensions section.
- `SECURITY.md` — No custom changes, accepted as-is.
- `docker-compose.yml` — New file, accepted as-is.
- `nanobot/channels/slack.py` — New fields merged cleanly.
- `nanobot/config/loader.py` — No custom changes.
- `nanobot/providers/custom_provider.py` — New file, accepted as-is.
- `nanobot/providers/registry.py` — New entries merged cleanly.

### Convention Change: BaseModel → Base
All config models upstream now use `Base` instead of raw `BaseModel`. Our custom models have been updated accordingly. This change must be followed for any future config models we add.

### Remaining Upstream Commits
- **0** — fully synced with upstream/main (7f8a3df).

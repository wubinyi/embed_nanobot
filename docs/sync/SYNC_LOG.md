# Upstream Sync Log

Tracks all merges from `HKUDS/nanobot` (upstream) `main` into our `main_embed` branch.

## Log

| Date | Upstream HEAD | Commits Merged | Conflicts | Resolution | PR |
|------|---------------|----------------|-----------|------------|----|
| 2026-02-07 | ea1d2d7 | ~15 | schema.py, manager.py, commands.py, README.md | Appended our config fields, re-registered mesh channel, kept our CLI additions. See MERGE_ANALYSIS.md | [#4](https://github.com/wubinyi/embed_nanobot/pull/4) |
| 2026-02-10 | ea1d2d7 | 3 (MiniMax, MoChat, DingTalk) | schema.py (MiniMax config) | Resolved conflicts, adapted MiniMax. Added missing channel docs. | [#6](https://github.com/wubinyi/embed_nanobot/pull/6) |
| 2026-02-12 | ea1d2d7 | 0 | None | Clean merge (main already up to date) | Direct merge |
| 2026-02-17 | a219a91 | 116 (77 non-merge) | README.md, commands.py, providers/__init__.py, pyproject.toml | Upstream-first; appended HybridRouter/Codex integration in CLI; kept vLLM/Mesh sections in README. See details below. | `copilot/sync-upstream-and-merge-main-embed` |

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

As of 2026-02-17, upstream has **22 more commits** ahead of `origin/main` (post-sync):
- `8053193` Merge PR #747: add media file sending support for Telegram
- `d89736a` Merge PR #720: add GitHub Copilot provider support
- `d405dcb` Merge PR #744: add timezone support for cron scheduling
- `23726cb` Add ClawHub skill for searching and installing agent skills
- Plus more fixes and refactors

**Next sync needed**: Before starting task 1.9 (PSK authentication).

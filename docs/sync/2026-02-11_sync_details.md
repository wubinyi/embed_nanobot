# Sync Details — 2026-02-11

Covers changes merged from upstream during the **2026-02-07** and **2026-02-10** syncs.

- **2026-02-07**: ~15 commits merged (initial upstream merge). Conflicts in schema.py, manager.py, commands.py, README.md.
- **2026-02-10**: 3 commits (MiniMax, MoChat, DingTalk). Conflict in schema.py (MiniMax config).

Base commit: `8af9800` → upstream HEAD: `ea1d2d7` (Merge PR #307: feat: add MiniMax support).

---

## New Channels

### Email Channel (`nanobot/channels/email.py`)
- **IMAP/SMTP email channel** with consent gating (`consent_granted` flag).
- IMAP polling for inbound emails with configurable interval and mailbox.
- SMTP outbound replies with subject threading (`In-Reply-To`, `References` headers).
- Sender allowlisting (`allow_from`), HTML-to-text extraction, UID deduplication, and auto-read marking.
- Configurable `max_body_chars`, `subject_prefix`, date-range fetching for summarization.
- Test suite added: `tests/test_email_channel.py` (311 lines).

### Slack Channel (`nanobot/channels/slack.py`)
- **Slack Socket Mode** integration using `slack_sdk`.
- Channel-vs-DM policy enforcement: `mention`, `open`, or `allowlist` for group channels; DM policy with separate allowlist.
- Bot mention stripping, message threading (`thread_ts`), eyes reaction (👀) on incoming messages.
- App Home step for onboarding (documented in README).

### QQ Channel (`nanobot/channels/qq.py`)
- **QQ bot** integration via the `botpy` SDK (C2C private messaging).
- WebSocket-based connection; message deduplication with a 1000-entry deque.
- Intent flags support (`PUBLIC_MESSAGES`, `C2C_GROUP_AT_MESSAGES`).

### MoChat Channel (`nanobot/channels/mochat.py`)
- **MoChat (formerly MoltChat)** channel with dual-mode operation:
  - Socket.IO WebSocket real-time messaging.
  - HTTP polling fallback when Socket.IO is unavailable.
- Session/panel discovery and auto-refresh targeting.
- LRU message deduplication (2000 entries), cursor tracking, delayed message buffering for groups.
- Per-group mention requirement rules.

---

## New / Updated Providers

### MiniMax Provider
- Added `ProviderSpec` for **MiniMax** in `nanobot/providers/registry.py`.
  - LiteLLM prefix: `minimax/` (e.g., `MiniMax-M2.1` → `minimax/MiniMax-M2.1`).
  - Environment variable: `MINIMAX_API_KEY`.
  - Default API base: `https://api.minimax.io/v1`.
- Added `minimax: ProviderConfig` field to `ProvidersConfig` in `nanobot/config/schema.py`.
- Updated `LiteLLMProvider` docstring to list MiniMax.

### LiteLLM Provider Auth Improvement
- `nanobot/providers/litellm_provider.py` now passes `api_key` directly to `litellm.acompletion()` kwargs for more robust authentication (not relying solely on environment variables).

---

## Configuration Schema Updates (`nanobot/config/schema.py`)

New Pydantic config models added:

| Config Class | Fields |
|---|---|
| `EmailConfig` | `enabled`, `consent_granted`, IMAP settings, SMTP settings, `auto_reply_enabled`, `poll_interval_seconds`, `mark_seen`, `max_body_chars`, `subject_prefix`, `allow_from` |
| `MochatConfig` | `enabled`, `base_url`, `socket_url`, Socket.IO settings, `claw_token`, `agent_user_id`, `sessions`, `panels`, `allow_from`, `mention`, `groups`, `reply_delay_mode/ms` |
| `MochatMentionConfig` | `require_in_groups` |
| `MochatGroupRule` | `require_mention` |
| `SlackConfig` | `enabled`, `mode`, `bot_token`, `app_token`, `group_policy`, `group_allow_from`, `dm` sub-config |
| `SlackDMConfig` | `enabled`, `policy`, `allow_from` |
| `QQConfig` | `enabled`, `app_id`, `secret`, `allow_from` |

`ChannelsConfig` now includes: `mochat`, `email`, `slack`, `qq` (in addition to existing telegram, discord, whatsapp, feishu, dingtalk).

---

## Channel Manager Updates (`nanobot/channels/manager.py`)

Added initialization blocks for:
- **MoChat** — lazy import of `MochatChannel`
- **Email** — lazy import of `EmailChannel`
- **Slack** — lazy import of `SlackChannel`
- **QQ** — lazy import of `QQChannel`

Each follows the same pattern: check `config.channels.<name>.enabled`, import, instantiate, and register.

---

## CLI Improvements (`nanobot/cli/commands.py`)

### Agent Command Enhancements
- **Markdown rendering**: `--markdown/--no-markdown` flag (default: on). Responses rendered with Rich `Markdown` inside a `Panel`.
- **Log control**: `--logs/--no-logs` flag toggles loguru log output during chat.
- **Thinking spinner**: Conditional "nanobot is thinking..." spinner (shows only when logs are off).
- **Exit commands**: `exit`, `quit`, `/exit`, `/quit`, `:q` now cleanly exit interactive mode.
- **EOFError handling**: Graceful exit on piped input or Ctrl-D.
- **`_print_agent_response()`**: Unified response rendering with a cyan-bordered panel.
- **`_is_exit_command()`**: Centralized exit command detection.

### Onboard Command
- Now creates `workspace/skills/` directory on first run.

### Channels Status
- Added **Feishu** and **Mochat** and **Slack** to the `channels status` table.

---

## Security / Safety Fixes

### Shell Tool Safety Guard (`nanobot/agent/tools/shell.py`)
- **Fixed false-positive path blocking** for relative paths (e.g., `.venv/bin/python` no longer triggers workspace escape detection).
- Path regex changed from `/[^\s\"']+` to `(?:^|[\s|>])(/[^\s\"'>]+)` to only match absolute paths.
- Added `p.is_absolute()` check before rejecting a path as outside working directory.

### Agent Loop Metadata Pass-Through (`nanobot/agent/loop.py`)
- `OutboundMessage` now passes `metadata` from inbound messages (e.g., Slack `thread_ts` for threading support).

---

## Summary of File Changes

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `nanobot/channels/email.py` | **New** | 403 | 0 |
| `nanobot/channels/mochat.py` | **New** | 895 | 0 |
| `nanobot/channels/qq.py` | **New** | 131 | 0 |
| `nanobot/channels/slack.py` | **New** | 205 | 0 |
| `nanobot/channels/manager.py` | Modified | 46 | 0 |
| `nanobot/cli/commands.py` | Modified | 98 | 8 |
| `nanobot/config/schema.py` | Modified | 99 | 0 |
| `nanobot/providers/registry.py` | Modified | 19 | 0 |
| `nanobot/providers/litellm_provider.py` | Modified | 6 | 1 |
| `nanobot/agent/loop.py` | Modified | 3 | 1 |
| `nanobot/agent/tools/shell.py` | Modified | 9 | 5 |
| `tests/test_email_channel.py` | **New** | 311 | 0 |
| **Total** | | **+2214** | **−11** |

---

## Commits Included

```
19b19d0 docs: update minimax tips
39dd7fe resolve conflicts with main and adapt MiniMax
c98ca70 docs: update provider tips
ef1b062 fix: create skills dir on onboard
8626caf fix: prevent safety guard from blocking relative paths in exec tool
cd4eeb1 docs: update mochat guidelines
ba2bdb0 refactor: streamline mochat channel
f634658 fixed dingtalk exception
a779f8c docs: update release news
76e51ca docs: release v0.1.3.post6
fc9dc4b Release v0.1.3.post6
fba5345 fix: pass api_key directly to litellm for more robust auth
ec4340d feat: add App Home step to Slack guide, default groupPolicy to mention
4f928e9 feat: improve QQ channel setup guide and fix botpy intent flags
03d3c69 docs: improve Email channel setup guide
1e95f8b docs: add 9 feb news
a63a44f fix: align QQ channel with BaseChannel conventions
f3ab806 fix: use websockets backend, simplify subtype check, add Slack docs
7ffd90a docs: update email channel tips
866942e fix: update agentUserId in README and change base_url to HTTPS
3779225 refactor(channels): rename moltchat integration to mochat
20b8a2f feat(channels): add Moltchat websocket channel with polling fallback
34dc933 feat: add QQ channel integration with botpy SDK
d223454 fix: cap processed UIDs, move email docs into README
d47219e fix: unify exit cleanup, conditionally show spinner with --logs flag
8fda0fc Document agent markdown/log flags and interactive exit commands
0a2d557 Improve agent CLI chat UX with markdown output and clearer interaction feedback
3c8eadf feat: add MiniMax provider support via LiteLLM
cfe43e4 feat(email): add consent-gated IMAP/SMTP email channel
051e396 feat: add Slack channel support
```

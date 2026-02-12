# Merge Analysis: wubinyi/embed_nanobot ← HKUDS/nanobot

This document analyzes the differences between our fork (`wubinyi/embed_nanobot`) and the upstream repository (`HKUDS/nanobot`) as of February 2026.

## Summary

- **Merge base**: commit `8af9800` (Merge pull request #225 from chaowu2009/main)
- **Our fork**: 19 commits ahead of merge base
- **Upstream**: 30 commits ahead of merge base
- **Conflict files**: 3 files (`.gitignore`, `nanobot/channels/manager.py`, `nanobot/config/schema.py`)
- **Auto-merged files**: 2 files (`README.md`, `nanobot/cli/commands.py`)

## Our Fork's Unique Changes (19 commits)

### 1. Hybrid Router (Local + API dual-model routing)
- **New files**: `nanobot/providers/hybrid_router.py`, `tests/test_hybrid_router.py`
- **Modified**: `nanobot/providers/__init__.py`, `nanobot/providers/registry.py`, `nanobot/config/schema.py`, `nanobot/cli/commands.py`
- **Purpose**: Route easy tasks to a local LLM and hard tasks to an API model with automatic PII sanitization
- **Config model**: `HybridRouterConfig` added to schema

### 2. LAN Mesh Communication
- **New files**: `nanobot/mesh/__init__.py`, `nanobot/mesh/channel.py`, `nanobot/mesh/discovery.py`, `nanobot/mesh/protocol.py`, `nanobot/mesh/transport.py`, `tests/test_mesh.py`
- **Modified**: `nanobot/channels/manager.py`, `nanobot/config/schema.py`
- **Purpose**: Device-to-device messaging on local network via UDP discovery and TCP transport
- **Config model**: `MeshConfig` added to schema

### 3. Developer Documentation
- **New files**: `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`
- **Purpose**: Internal architecture docs, config reference, customization guide

### 4. Repository Setup
- **New files**: `.github/agents/update_doc.agent.md`
- **Modified**: `.gitignore`, `README.md`
- **Purpose**: Agent documentation workflow, README updates for new features

## Upstream's Changes (30 commits)

### 1. New Chat Channels
- **Email**: `nanobot/channels/email.py`, `tests/test_email_channel.py` — IMAP polling + SMTP replies with consent gating
- **Slack**: `nanobot/channels/slack.py` — Socket Mode integration
- **QQ**: `nanobot/channels/qq.py` — botpy SDK integration
- **Config models**: `EmailConfig`, `SlackConfig`, `SlackDMConfig`, `QQConfig` added to schema

### 2. CLI UX Improvements
- **Modified**: `nanobot/cli/commands.py`
- Rich markdown rendering for agent responses (`--markdown/--no-markdown` flag)
- Runtime log toggle (`--logs/--no-logs` flag)
- Exit commands (`exit`, `quit`, `/exit`, `/quit`, `:q`)
- Thinking spinner when logs are off
- Slack status in `channels status` command

### 3. Provider Improvements
- **Modified**: `nanobot/providers/litellm_provider.py`
- Pass `api_key` directly to litellm for more robust authentication

### 4. Agent Loop Enhancement
- **Modified**: `nanobot/agent/loop.py`
- Pass through metadata in `OutboundMessage` for channel-specific needs (e.g., Slack thread_ts)

### 5. Version Bump & Dependencies
- **Modified**: `pyproject.toml`
- Version: `0.1.3.post5` → `0.1.3.post6`
- New dependencies: `slack-sdk>=3.26.0`, `qq-botpy>=1.0.0`

### 6. README Updates
- New news entries for v0.1.3.post6
- Setup guides for Slack, Email, QQ channels
- Updated chat apps listing, CLI docs, and contributor image

## Conflict Resolution

### `.gitignore`
- **Conflict**: Both sides added entries after `.pytest_cache/`
- **Resolution**: Keep all entries from both sides (`tests/`, `botpy.log` from upstream)

### `nanobot/channels/manager.py`
- **Conflict**: Our fork added Mesh channel; upstream added Email, Slack, QQ channels in the same location
- **Resolution**: Keep all channels. Upstream channels (Email, Slack, QQ) placed before our Mesh channel to follow upstream ordering convention

### `nanobot/config/schema.py`
- **Conflict**: Our fork added `mesh` field; upstream added `email`, `slack`, `qq` fields in `ChannelsConfig`
- **Resolution**: Keep all fields. Upstream fields placed first, then our `mesh` field appended at the end

## Files Only in Our Fork (no conflict)
- `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`
- `nanobot/mesh/` (entire module)
- `nanobot/providers/hybrid_router.py`, `nanobot/providers/__init__.py`, `nanobot/providers/registry.py`
- `tests/test_hybrid_router.py`, `tests/test_mesh.py`
- `.github/agents/update_doc.agent.md`

## Files Only in Upstream (no conflict)
- `nanobot/channels/email.py`, `nanobot/channels/slack.py`, `nanobot/channels/qq.py`
- `nanobot/agent/loop.py`, `nanobot/providers/litellm_provider.py`
- `tests/test_email_channel.py`
- `pyproject.toml`

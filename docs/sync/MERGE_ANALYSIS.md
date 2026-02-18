# Merge Analysis: wubinyi/embed_nanobot ← HKUDS/nanobot

This document analyzes the differences between our fork (`wubinyi/embed_nanobot`) and the upstream repository (`HKUDS/nanobot`).

**Last updated**: 2026-02-18

## Summary (Latest Sync: 2026-02-18)

- **Previous upstream HEAD**: `8053193`
- **New upstream HEAD**: `7f8a3df` (= `origin/main` after sync)
- **Commits merged**: 20
- **Conflict files**: 2 files (`nanobot/config/schema.py`, `nanobot/cli/commands.py`)
- **Files changed**: 9 files, +269 / −127 lines
- **Convention change**: All config models now inherit `Base` instead of `BaseModel`

## Our Fork's Unique Changes

### 1. Hybrid Router (Local + API dual-model routing)
- **New files**: `nanobot/providers/hybrid_router.py`, `tests/test_hybrid_router.py`
- **Modified**: `nanobot/providers/__init__.py`, `nanobot/providers/registry.py`, `nanobot/config/schema.py`, `nanobot/cli/commands.py`
- **Purpose**: Route easy tasks to a local LLM and hard tasks to an API model with automatic PII sanitization
- **Config model**: `HybridRouterConfig` added to schema

### 2. LAN Mesh Communication
- **New files**: `nanobot/mesh/__init__.py`, `nanobot/mesh/channel.py`, `nanobot/mesh/discovery.py`, `nanobot/mesh/protocol.py`, `nanobot/mesh/transport.py`, `nanobot/mesh/security.py`, `tests/test_mesh.py`
- **Modified**: `nanobot/channels/manager.py`, `nanobot/config/schema.py`
- **Purpose**: Device-to-device messaging on local network via UDP discovery and TCP transport
- **Config model**: `MeshConfig` added to schema (inherits `Base`)
- **Security**: HMAC-SHA256 PSK authentication, nonce replay protection, per-device key store

### 3. Developer Documentation
- **New files**: `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`, `docs/PRD.md`
- **Purpose**: Internal architecture docs, config reference, customization guide, product requirements

### 4. Project Workflow & Copilot Integration
- **New files**: `.github/copilot-instructions.md`, `docs/00_system/BOOTSTRAP_PROTOCOL.md`, `docs/00_system/Project_Roadmap.md`
- **Purpose**: Multi-agent workflow, session bootstrap, project roadmap tracking

## Upstream's New Changes (8053193 → 7f8a3df)

### 1. Pydantic Base Class (alias_generator)
- `Base(BaseModel)` with `ConfigDict(alias_generator=to_camel, populate_by_name=True)` — all config models use `Base`

### 2. Mochat Channel
- `MochatMentionConfig`, `MochatGroupRule`, `MochatConfig` — full IM platform support with mention/groups/reconnect

### 3. Custom Provider
- `nanobot/providers/custom_provider.py` — Direct OpenAI-compatible endpoint, bypasses LiteLLM

### 4. Slack Enhancements
- `reply_in_thread`, `react_emoji` defaults in `SlackConfig`

### 5. Docker Compose
- `docker-compose.yml` for standard deployment

### 6. Previous Upstream Changes (still active)
- MCP (Model Context Protocol) Support
- OpenAI Codex Provider (OAuth)
- GitHub Copilot Provider (OAuth)
- Redesigned Memory System (MEMORY.md + HISTORY.md)
- CLI Overhaul (prompt_toolkit, slash commands)
- Security Hardening (WhatsApp bridge, SECURITY.md)
- Telegram Media File Support
- ClawHub Skill marketplace
- Cron timezone support

## Conflict Surface (Current)

Files we modify that also exist upstream — the merge conflict risk area:

| Our File | Upstream File | Our Changes | Status |
|----------|--------------|-------------|--------|
| `nanobot/config/schema.py` | Same | Appended `MeshConfig(Base)`, `HybridRouterConfig(Base)` fields | Medium risk — upstream changed BaseModel→Base |
| `nanobot/channels/manager.py` | Same | Appended mesh channel registration | Low risk — append-only |
| `nanobot/cli/commands.py` | Same | Added HybridRouterProvider + CustomProvider in `_make_provider()` | Medium risk — upstream active |
| `nanobot/providers/__init__.py` | Same | Added hybrid_router export | Low risk — append-only |
| `nanobot/providers/registry.py` | Same | Appended hybrid_router ProviderSpec entry | Low risk — append-only |
| `README.md` | Same | Added embed_nanobot section at bottom | Medium risk — upstream updates frequently |
| `pyproject.toml` | Same | Added deps at end | Low risk |

## Files Only in Our Fork (no conflict)
- `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`, `docs/PRD.md`
- `docs/00_system/` (Project_Roadmap.md, BOOTSTRAP_PROTOCOL.md, UPSTREAM_SYNC_PROTOCOL.md)
- `docs/01_features/` (feature design logs, implementation docs, test reports)
- `docs/sync/` (SYNC_LOG.md, MERGE_ANALYSIS.md)
- `.github/copilot-instructions.md`
- `nanobot/mesh/` (entire module: channel, discovery, protocol, transport, security)
- `nanobot/providers/hybrid_router.py`
- `tests/test_hybrid_router.py`, `tests/test_mesh.py`

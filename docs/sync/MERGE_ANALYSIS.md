# Merge Analysis: wubinyi/embed_nanobot ← HKUDS/nanobot

This document analyzes the differences between our fork (`wubinyi/embed_nanobot`) and the upstream repository (`HKUDS/nanobot`).

**Last updated**: 2026-02-17

## Summary (Latest Sync: 2026-02-17)

- **Previous upstream HEAD**: `ea1d2d7`
- **New upstream HEAD**: `a219a91` (= `origin/main` after sync)
- **Commits merged**: 116 total (77 non-merge)
- **Conflict files**: 4 files (`README.md`, `nanobot/cli/commands.py`, `nanobot/providers/__init__.py`, `pyproject.toml`)
- **Files changed**: 35 files, +2,070 / −610 lines

## Our Fork's Unique Changes

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
- **New files**: `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`, `docs/PRD.md`
- **Purpose**: Internal architecture docs, config reference, customization guide, product requirements

### 4. Project Workflow & Copilot Integration
- **New files**: `.github/copilot-instructions.md`, `docs/00_system/BOOTSTRAP_PROTOCOL.md`, `docs/00_system/Project_Roadmap.md`
- **Purpose**: Multi-agent workflow, session bootstrap, project roadmap tracking

## Upstream's New Changes (ea1d2d7 → a219a91)

### 1. MCP (Model Context Protocol) Support
- `nanobot/agent/tools/mcp.py` — Dynamic MCP tool integration
- `MCPServerConfig` + `tools.mcp_servers` in schema

### 2. OpenAI Codex Provider (OAuth)
- `nanobot/providers/openai_codex_provider.py` — Full OAuth flow
- `ProviderSpec(name="openai_codex", is_oauth=True)` in registry

### 3. Redesigned Memory System
- Two-layer: `MEMORY.md` (long-term) + `HISTORY.md` (grep-searchable log)
- Consolidation via LLM summarization, `/new` command

### 4. CLI Overhaul
- `prompt_toolkit` integration, non-destructive onboard, slash commands (`/new`, `/help`)
- Custom provider, OAuth login, improved status display

### 5. Security Hardening
- WhatsApp bridge bound to localhost + token auth
- `SECURITY.md` added

### 6. Channel Improvements
- Telegram: message splitting, sender_id fix
- Feishu: rich text extraction, localized post formats
- Slack: `slackify-markdown`, table-to-text conversion

### 7. Cron Improvements
- One-time `at` schedule, timezone support

### 8. Agent Improvements
- Interleaved chain-of-thought, `json_repair` for robust parsing
- `edit_file` tool + time context for subagent
- Temperature/max_tokens properly wired

### 9. ClawHub Skill Support
- Public skill marketplace integration

## Conflict Surface (Current)

Files we modify that also exist upstream — the merge conflict risk area:

| Our File | Upstream File | Our Changes | Status |
|----------|--------------|-------------|--------|
| `nanobot/config/schema.py` | Same | Appended `MeshConfig`, `HybridRouterConfig` fields | Low risk — append-only |
| `nanobot/channels/manager.py` | Same | Appended mesh channel registration | Low risk — append-only |
| `nanobot/cli/commands.py` | Same | Added HybridRouterProvider in `_make_provider()` | Medium risk — upstream active |
| `nanobot/providers/__init__.py` | Same | Added hybrid_router export | Low risk — append-only |
| `nanobot/providers/registry.py` | Same | Appended hybrid_router ProviderSpec entry | Low risk — append-only |
| `README.md` | Same | Added embed_nanobot section at bottom | Medium risk — upstream updates frequently |
| `pyproject.toml` | Same | Added deps at end | Low risk |

## Files Only in Our Fork (no conflict)
- `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`, `docs/PRD.md`
- `docs/00_system/` (Project_Roadmap.md, BOOTSTRAP_PROTOCOL.md)
- `docs/sync/` (SYNC_LOG.md, MERGE_ANALYSIS.md)
- `.github/copilot-instructions.md`
- `nanobot/mesh/` (entire module)
- `nanobot/providers/hybrid_router.py`
- `tests/test_hybrid_router.py`, `tests/test_mesh.py`

# Upstream Sync Log

Tracks all merges from `HKUDS/nanobot` (upstream) `main` into our `main_embed` branch.

**Last updated**: 2026-02-27

---

## Sync Summary

| Date | Upstream HEAD | Commits | Conflicts | Key Features | Details |
|------|---------------|---------|-----------|--------------|---------|
| 2026-02-07 | ea1d2d7 | ~15 | schema.py, manager.py, commands.py, README.md | Initial upstream merge — Email, Slack, QQ, MoChat channels; CLI UX | [2026-02-11 details](2026-02-11_sync_details.md) |
| 2026-02-10 | ea1d2d7 | 3 | schema.py | MiniMax provider, MoChat/DingTalk fixes | [2026-02-11 details](2026-02-11_sync_details.md) |
| 2026-02-12 | ea1d2d7 | 0 | None | Clean merge (main already up to date) | — |
| 2026-02-17 | a219a91 | 116 (77 non-merge) | README.md, commands.py, providers/__init__.py, pyproject.toml | MCP, Codex, memory redesign, CLI overhaul, security hardening, ClawHub | [2026-02-17 details](2026-02-17_sync_details.md) |
| 2026-02-17b | 8053193 | 22 (11 non-merge) | README.md | Telegram media, GitHub Copilot provider, cron timezone, ClawHub skill | [2026-02-17b details](2026-02-17b_sync_details.md) |
| 2026-02-18 | 7f8a3df | 20 | schema.py, commands.py | Pydantic Base class, Mochat channel, CustomProvider, Slack enhancements, Docker Compose | [2026-02-18 details](2026-02-18_sync_details.md) |
| 2026-02-18b | ce4f005 | 9 (4 non-merge) | None | SiliconFlow provider, workspace-scoped sessions, tool metadata in history | [2026-02-18b details](2026-02-18b_sync_details.md) |
| 2026-02-25 | 9e806d7 | 276 (148 non-merge) | manager.py (×2), commands.py, pyproject.toml | v0.1.4 era: workspace→templates migration, memory consolidation types, VolcEngine provider, Mochat channel, HeartbeatService refactor, prompt caching, progress streaming, agent defaults (temp 0.1, max_iter 40), pinned dep versions | [2026-02-25 details](2026-02-25_sync_details.md) |
| 2026-02-27 | e86cfcd | 107 (78 non-merge) | manager.py, schema.py, test_heartbeat_service.py | Matrix (Element) channel, agent context refactor, /stop command + task cancellation, explicit provider selection, exec path_append, Telegram media-group fix, workspace template auto-sync, heartbeat test rewrite | [2026-02-27 details](2026-02-27_sync_details.md) |

**Current status**: Fully synced with upstream/main (`e86cfcd`). 0 commits pending.

---

## Our Fork's Unique Changes

### 1. Hybrid Router (Local + API dual-model routing)
- **New files**: `nanobot/providers/hybrid_router.py`, `tests/test_hybrid_router.py`
- **Modified**: `nanobot/providers/__init__.py`, `nanobot/providers/registry.py`, `nanobot/config/schema.py`, `nanobot/cli/commands.py`
- **Config model**: `HybridRouterConfig(Base)` — routes easy tasks to local LLM, hard tasks to API, with PII sanitization

### 2. LAN Mesh Communication
- **New files**: `nanobot/mesh/` (channel, discovery, protocol, transport, security, encryption, enrollment, registry, commands, routing, automation)
- **Modified**: `nanobot/channels/manager.py`, `nanobot/config/schema.py`
- **Config model**: `MeshConfig(Base)` — device-to-device messaging via UDP discovery + TCP transport
- **Security**: HMAC-SHA256 PSK authentication, nonce replay protection, per-device key store

### 3. Developer Documentation
- `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md`, `docs/PRD.md`

### 4. Project Workflow & Copilot Integration
- `.github/copilot-instructions.md`, `docs/00_system/` (Bootstrap, Roadmap, Sync Protocol)

---

## Conflict Surface

Files we modify that also exist upstream — the merge conflict risk area:

| Our File | Our Changes | Risk |
|----------|-------------|------|
| `nanobot/config/schema.py` | Appended `MeshConfig(Base)`, `HybridRouterConfig(Base)` fields | Medium — upstream adds fields/models frequently |
| `nanobot/channels/manager.py` | Appended mesh channel registration (loguru format) | Low — append-only |
| `nanobot/cli/commands.py` | Added HybridRouterProvider in `_make_provider()`, DeviceControlTool + routing in `gateway()` | Medium — upstream active |
| `nanobot/providers/__init__.py` | Added hybrid_router export | Low — append-only |
| `README.md` | Added embed_nanobot section at bottom | Medium — upstream updates frequently |
| `pyproject.toml` | Appended `cryptography` dep | Low |
| `tests/test_heartbeat_service.py` | Accepted upstream rewrite (DummyProvider + LLMResponse pattern) | Low — upstream-only file |

---

## Files Only in Our Fork (no conflict)

- `nanobot/mesh/` (entire module)
- `nanobot/providers/hybrid_router.py`
- `tests/test_hybrid_router.py`, `tests/test_mesh.py`
- `docs/` (architecture, configuration, customization, PRD, 00_system/, 01_features/, sync/)
- `.github/copilot-instructions.md`

---

## Active Convention Notes

- **BaseModel → Base**: All config models must inherit `Base` (not `BaseModel`) since 2026-02-18 upstream change.
- **Loguru `{}` formatting**: All `logger.warning()`/`logger.info()` use `{}` (loguru native), NOT f-strings. Adopted in 2026-02-25 sync.
- **Append-only markers**: Our additions in shared files are marked with `# --- embed_nanobot extensions ---`.
- **Pinned deps with upper bounds**: Upstream now uses version ranges like `>=X.Y.Z,<X+1.0.0`. Our custom deps should follow same pattern.
- **Agent defaults changed**: temperature=0.1, max_tool_iterations=40, memory_window=100 (upstream 2026-02-25).
- **workspace/ → nanobot/templates/**: Template files now bundled as package data, not separate workspace/ dir (upstream 2026-02-25).
- **Literal import**: `from typing import Literal` now used in schema.py (MatrixConfig.group_policy).
- **Explicit provider selection**: `provider: str = "auto"` in AgentDefaults; `match_provider()` checks before model detection.
- **Heartbeat test pattern**: DummyProvider + LLMResponse/ToolCallRequest replaces MagicMock stubs.
- **Next sync**: On-demand, before starting next feature task.

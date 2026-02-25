# Upstream Sync Log

Tracks all merges from `HKUDS/nanobot` (upstream) `main` into our `main_embed` branch.

**Last updated**: 2026-02-18

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

**Current status**: Fully synced with upstream/main (`ce4f005`). 0 commits pending.

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
| `nanobot/config/schema.py` | Appended `MeshConfig(Base)`, `HybridRouterConfig(Base)` fields | Medium — upstream changed BaseModel→Base |
| `nanobot/channels/manager.py` | Appended mesh channel registration | Low — append-only |
| `nanobot/cli/commands.py` | Added HybridRouterProvider + CustomProvider in `_make_provider()` | Medium — upstream active |
| `nanobot/providers/__init__.py` | Added hybrid_router export | Low — append-only |
| `nanobot/providers/registry.py` | Appended hybrid_router ProviderSpec entry | Low — append-only |
| `README.md` | Added embed_nanobot section at bottom | Medium — upstream updates frequently |
| `pyproject.toml` | Added deps at end | Low |

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
- **Append-only markers**: Our additions in shared files are marked with `# --- embed_nanobot extensions ---`.
- **Next sync**: On-demand, before starting next feature task.

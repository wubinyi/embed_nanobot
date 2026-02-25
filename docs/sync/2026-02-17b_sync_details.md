# Sync Details — 2026-02-17b

**Commits**: 22 (11 non-merge)
**Range**: `a219a91` → `8053193`
**Files changed**: 12
**Conflicts**: README.md
**Resolution**: Accept upstream README, preserve embed_nanobot extensions section

---

## Upstream Features Merged

### 1. Telegram Media File Support — PR #747
- `nanobot/channels/telegram.py` — Handle voice messages, audio, images, and documents. Clean up media sending logic.

### 2. GitHub Copilot Provider — PR #720
- `nanobot/providers/registry.py` — Added `github_copilot` provider spec with `is_oauth=True`.
- `nanobot/cli/commands.py` — Refactored to use `is_oauth` flag instead of hardcoded provider name check.

### 3. Cron Timezone Support — PR #744
- `nanobot/agent/tools/cron.py` — Timezone validation and display bug fix.
- `nanobot/cron/service.py` — Timezone propagation improvements.
- `nanobot/skills/cron/SKILL.md` — Updated skill docs with timezone examples.

### 4. ClawHub Skill — PR #758
- **New file**: `nanobot/skills/clawhub/SKILL.md` — Skill for searching and installing agent skills from the public ClawHub registry.
- `nanobot/skills/README.md` — Updated index.

### 5. Bug Fixes
- `nanobot/agent/context.py`, `nanobot/agent/tools/message.py` — Omit empty content entries in assistant messages.

---

## Conflicts Resolved

| File | Conflict | Resolution |
|------|----------|------------|
| `README.md` | Upstream restructured README significantly (new sections, updated Chat Apps table with Mochat) | Accept upstream version entirely; moved our custom sections (vLLM, Hybrid Router, LAN Mesh) to a new "embed_nanobot Extensions" section before Star History |

## Auto-Merged Files (no conflicts)
- `nanobot/cli/commands.py` — GitHub Copilot `is_oauth` refactor merged cleanly with our HybridRouter additions.
- `nanobot/config/schema.py` — No new fields from upstream; our appended fields preserved.
- `nanobot/providers/registry.py` — New `github_copilot` spec merged above our appended `vllm` spec.

## Remaining Upstream Commits
- **0** — fully synced with upstream/main (8053193).

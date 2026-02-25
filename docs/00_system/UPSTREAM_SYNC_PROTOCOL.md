# Upstream Sync Protocol

> **Owner**: Architect  
> **Frequency**: At the end of every Session Bootstrap, and on-demand  
> **Reference**: Called from `BOOTSTRAP_PROTOCOL.md` Step E and from `copilot-instructions.md` Session_Bootstrap

---

## Overview

The project must stay aligned with HKUDS/nanobot. This protocol defines the structured merge process, verification steps, and completion gate that ensure every sync is fully logged and documented.

---

## Prerequisites

Before starting the sync, confirm:

- [ ] You are on the `main_embed` branch with a clean working tree (`git status` is clean).
- [ ] `upstream` remote points to `https://github.com/HKUDS/nanobot.git`.
- [ ] `origin` remote points to `https://github.com/wubinyi/embed_nanobot.git`.

---

## Sync Steps

### Step 1: Fetch upstream

```bash
git fetch upstream
```

### Step 2: Update origin/main (HARD PREREQUISITE)

**This step is mandatory.** Our `main` branch must mirror upstream exactly before any merge into `main_embed`.

```bash
git checkout main
git merge upstream/main --ff-only
git push origin main
```

If the `--ff-only` merge fails, it means `main` has diverged from upstream — investigate and fix before proceeding.

### Step 3: Post-fetch analysis

Before merging, analyze what's coming:

```bash
# Count pending commits
PENDING=$(git log --oneline main_embed..main | wc -l)
echo "Pending commits to merge: $PENDING"

# Categorize upstream changes by feature area
git log --oneline main_embed..main

# Dry-run merge to preview conflicts
git checkout main_embed
git merge --no-commit --no-ff main
git diff --name-only --diff-filter=U  # List conflicted files
git merge --abort
```

### Step 4: Merge main into main_embed

```bash
git checkout main_embed
git merge main --no-edit
```

### Step 5: Resolve conflicts (if any)

If conflicts arise:

1. Document in `docs/sync/YYYY-MM-DD_sync.md`
2. Resolve following conventions in `agent.md` (upstream-first, our code appended last)
3. Follow the **Conflict Resolution Rules** below
4. Test after resolution

### Step 6: Push and log

```bash
git push origin main_embed
```

- Append summary row to `docs/sync/SYNC_LOG.md`
- For syncs with >10 commits or any conflicts, create `docs/sync/YYYY-MM-DD_sync_details.md`

### Step 7: Post-sync verification

After pushing, verify the sync is complete:

```bash
# Confirm no remaining upstream commits
REMAINING=$(git log --oneline main_embed..upstream/main | wc -l)
echo "Remaining upstream commits: $REMAINING"

# Verify main_embed includes main
git log --oneline main..main_embed | head -5
```

Record the remaining count in the sync log entry.

---

## Sync Log Format

The sync log (`docs/sync/SYNC_LOG.md`) contains the summary. Detailed entries go in separate files.

### Summary Table (in SYNC_LOG.md)

```markdown
| Date | Upstream HEAD | Commits | Conflicts | Key Features | Details |
|------|---------------|---------|-----------|--------------|--------|
| 2026-02-12 | abc1234 | 5 | None | Bug fixes | — |
| 2026-02-13 | def5678 | 3 | schema.py | New provider | [details](YYYY-MM-DD_sync_details.md) |
```

**Key Features column**: Briefly list the major features/changes in the merged commits.
**Details column**: Link to the detail file (or `—` for clean merges with <10 commits).

### Detail File (in `docs/sync/YYYY-MM-DD_sync_details.md`)

For syncs with >10 commits or any conflicts, create a separate detail file:

```markdown
# Sync Details — YYYY-MM-DD

**Commits**: [count] ([non-merge count] non-merge)
**Range**: `<old-hash>` → `<new-hash>`

## Upstream Features Merged
- **Category 1**: Brief description
- **Category 2**: Brief description

## Conflicts Resolved
- `file.py`: How it was resolved

## Remaining Upstream Commits
- [count] commits still pending
```

---

## Conflict Resolution Rules

1. **Config schema** (`nanobot/config/schema.py`): Upstream fields first, our fields appended at end.
2. **Channel manager** (`nanobot/channels/manager.py`): Upstream channels registered first, ours last.
3. **CLI** (`nanobot/cli/commands.py`): Check for both Hybrid Router and upstream provider logic; integrate both sequentially.
4. **Providers** (`nanobot/providers/__init__.py`): Export both upstream and custom providers.
5. **Dependencies** (`pyproject.toml`): Keep all upstream dependencies, add ours at end if needed.
6. **New upstream files**: Accept as-is (they don't conflict with our separate modules).
7. **README**: Accept upstream news/version updates, preserve our custom feature sections (vLLM, Hybrid Router, LAN Mesh).

---

## Completion Gate

**MANDATORY**: Before declaring a sync complete, verify ALL of the following:

- [ ] `origin/main` is up-to-date with `upstream/main` (Step 2 done)
- [ ] `main_embed` has been merged and pushed (Step 6 done)
- [ ] `docs/sync/SYNC_LOG.md` summary table updated with new row (including Key Features + Details link)
- [ ] For large syncs (>10 commits) or conflicts: `docs/sync/YYYY-MM-DD_sync_details.md` created
- [ ] Conflict surface table in `docs/sync/SYNC_LOG.md` updated if changed
- [ ] **Documentation Freshness Check** triggered (see `copilot-instructions.md`)
- [ ] `docs/00_system/Project_Roadmap.md` updated with sync metrics

**Do NOT push and declare "done" until every checkbox above is satisfied.**

---

## Post-Sync: Documentation Freshness Check

After every sync that introduces functional changes, the Documentation Freshness Check (defined in `copilot-instructions.md`) is **mandatory**. This is not optional — it was the #1 gap identified in our process.

Quick reminder of what to check:
- `docs/architecture.md` — new modules, changed components
- `docs/configuration.md` — new config fields, providers, channels
- `docs/customization.md` — new extension patterns
- `docs/PRD.md` — requirement status changes
- `agent.md` — upstream convention changes, conflict-prone files

See the full procedure in the `<Documentation_Freshness_Check>` section of `copilot-instructions.md`.

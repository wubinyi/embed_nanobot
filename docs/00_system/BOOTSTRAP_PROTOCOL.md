# Embed Nanobot — Bootstrap Protocol

## Purpose

This protocol is executed at the **start of every new Copilot session** to:
1. Recover context from previous work (eliminate AI session amnesia).
2. Detect upstream changes that may affect our roadmap.
3. Align the current session with the project roadmap.
4. Identify technical debt or hazards before proceeding.

## When to Trigger

- **Automatically**: At the start of every new conversation session.
- **Manually**: When the user says "bootstrap", "sync context", or "review roadmap".
- **After long gaps**: If more than 24 hours have passed since the last session.

---

## Execution Flow

### Step A: Context Sync (Read & Understand)

Read the following files in order. Summarize key points from each.

1. **Project Identity**:
   - `#file:docs/PRD.md` — What are we building? What phase are we in?
   - `#file:agent.md` — What are our coding conventions?

2. **Current State**:
   - `#file:docs/00_system/Project_Roadmap.md` — What tasks are done? What's next?
   - `#file:docs/sync/SYNC_LOG.md` — When was the last upstream sync? Any unresolved conflicts?

3. **Recent Work** (scan `docs/01_features/` for the latest feature folders):
   - Read the most recent `01_Design_Log.md` and `02_Dev_Implementation.md`.
   - Understand what was last worked on and whether it was completed.

4. **Codebase Check**:
   - Run: `git status` — Any uncommitted changes?
   - Run: `git log --oneline main_embed -10` — What are the recent commits?
   - Run: `git log --oneline origin/main -5` — Any new upstream commits?

### Step B: Upstream Delta Analysis

Check if upstream has new changes since our last sync:

```bash
git fetch upstream
git log --oneline main_embed..upstream/main
```

If there are new upstream commits:
- **[Architect]** assesses whether they affect any of our custom modules (`mesh/`, `providers/hybrid_router.py`, `config/schema.py`).
- Determine if an immediate sync is needed or if it can wait until the end of the session.
- Note findings in the bootstrap report.

### Step C: Deep Reflection & Hazard Detection

**[Architect & Reviewer]** jointly analyze:

1. **Implementation gaps**: Is there unfinished work from the last session? Any half-implemented features?
2. **Technical debt**: Are there TODOs, hacks, or shortcuts that need addressing?
3. **Security hazards**: For mesh/device features — are there authentication gaps, unencrypted channels, or missing input validation?
4. **Upstream conflict risk**: Do our recent changes touch files that upstream also modified? Review the conflict surface table in copilot-instructions.md.
5. **Test coverage**: Are there untested modules?
6. **Documentation staleness**: Run the Documentation Freshness Check (defined in copilot-instructions.md `<Documentation_Freshness_Check>`). Quick scan: do `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md` still match the current codebase?
7. **Convention drift**: Has upstream changed patterns since our last sync? Check `agent.md` still reflects upstream's actual code style.

### Step D: Roadmap Alignment

1. Open `docs/00_system/Project_Roadmap.md`.
2. Verify all "Done" items are actually implemented (spot-check by reading relevant files).
3. If the roadmap doesn't exist yet, create it based on the PRD phases.
4. **[Architect]** refines the next 1-2 tasks:
   - Break them into concrete sub-items with specific files to create/modify.
   - Estimate complexity (S/M/L).
5. **[Reviewer]** challenges the priority order.

### Step E: Sync Decision

If upstream has new changes (from Step B):
- **If no conflicts expected**: Perform sync now (follow Upstream_Sync_Protocol in copilot-instructions.md).
- **If conflicts likely**: Defer sync to after current task, but document the risk.
- **If our `main` is behind**: Always update `main` to match `upstream/main`.

---

## Output

After completing Steps A–E, produce a **Bootstrap Report** with the following structure:

```markdown
## Bootstrap Report — [YYYY-MM-DD]

### Context Recovery
- **Last completed task**: [feature name + status]
- **Uncommitted changes**: [yes/no, what]
- **Recent commits**: [list last 3-5]

### Upstream Status
- **Last sync date**: [date]
- **New upstream commits**: [count, key changes]
- **Sync needed**: [yes/no, urgency]
- **Conflict risk**: [low/medium/high, affected files]

### Hazards & Debt
- [List any issues found]

### Roadmap Status
- **Current phase**: [Phase N]
- **Next task**: [task name]
- **Refined sub-items**: [list]

### Recommendation
[Proposed action for this session]
```

Then ask the user:

> **"Context synced. [Summary of status]. Shall we proceed with [next task] or would you like to address something else?"**

---

## Quick Bootstrap (Short Sessions)

For brief sessions where full bootstrap is unnecessary, run a minimal version:

1. `git status` + `git log --oneline main_embed -5`
2. Read `docs/00_system/Project_Roadmap.md` (find next task).
3. Check `git log --oneline main_embed..upstream/main` (any new upstream?).
4. Proceed directly to the task.

Trigger with: "quick bootstrap" or "let's continue".

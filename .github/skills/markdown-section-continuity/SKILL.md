---
name: markdown-section-continuity
description: "Check and repair markdown heading continuity (section/chapter ordering and parent-child placement) before doc commits."
---

# Markdown Section Continuity Check

Use this skill whenever feature docs are edited and especially before `git commit`.

## Goal

Catch and fix heading displacement issues like:
- `### 11.5` appearing under section `12`
- orphaned subsection blocks
- out-of-order chapter numbering

## Input

One or more markdown files under `docs/`.

## Steps

1. Extract heading outline and verify ordering
2. Validate parent-child continuity (`### X.Y` must be under nearest preceding `## X`)
3. If mismatched, move blocks to the correct parent section
4. Re-run checks and confirm no violations remain
5. Include the continuity fix in the same commit as the content change

## Quick Command

```bash
/home/wubinyi/workspace/embed_nanobot/.conda/bin/python scripts/check_markdown_continuity.py docs/01_features/f26_hybrid_npu_inference/02_Dev_Implementation.md
```

## Pass Criteria

- No parent mismatch errors
- No out-of-order numbering errors
- File reads naturally in top-down chapter order

## Notes

- Preserve original content text; only relocate displaced blocks.
- Prefer minimal edits; avoid reformatting unrelated sections.

# Upstream Sync Log

Tracks all merges from `HKUDS/nanobot` (upstream) `main` into our `main_embed` branch.

## Log

| Date | Upstream HEAD | Commits Merged | Conflicts | Resolution | PR |
|------|---------------|----------------|-----------|------------|----|
| 2026-02-07 | ea1d2d7 | ~15 | schema.py, manager.py, commands.py, README.md | Appended our config fields, re-registered mesh channel, kept our CLI additions. See MERGE_ANALYSIS.md | [#4](https://github.com/wubinyi/embed_nanobot/pull/4) |
| 2026-02-10 | ea1d2d7 | 3 (MiniMax, MoChat, DingTalk) | schema.py (MiniMax config) | Resolved conflicts, adapted MiniMax. Added missing channel docs. | [#6](https://github.com/wubinyi/embed_nanobot/pull/6) |
| 2026-02-12 | ea1d2d7 | 0 | None | Clean merge (main already up to date) | Direct merge |

## Pending

As of 2026-02-12, upstream has **9 new commits** ahead of `origin/main`:
- `b429bf9` fix: improve long-running stability for various channels
- `dd63337` Merge PR #516: fix Pydantic V2 deprecation warning
- `c8831a1` Merge PR #488: refactor CLI input with prompt_toolkit
- Plus 6 more

**Next sync needed**: Before starting next feature work.

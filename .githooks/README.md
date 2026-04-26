# Git Hooks

This repository ships `commit-msg` and `pre-push` hooks that enforce the
documentation gates described in `.github/copilot-instructions.md`.

## What it checks

- `feat(scope): ...` commits must stage:
  - `docs/01_features/fXX_<feature>/01_Design_Log.md`
  - `docs/01_features/fXX_<feature>/02_Dev_Implementation.md`
  - `docs/01_features/fXX_<feature>/03_Test_Report.md`
  - `docs/00_system/Project_Roadmap.md`
  - Feature docs must come from exactly one folder, and that folder slug must
    match the commit scope. Example: `feat(esp32): ...` should stage docs from
    a folder like `docs/01_features/f23_esp32_led/`.
  - The staged `02_Dev_Implementation.md` must contain `Documentation Freshness Check`
    and `Post-Task Reflection` headings.
  - If the staged change is hardware-sensitive (`esp32/`, `nanobot/mesh/`,
    `nanobot/agent/tools/device.py`, or ESP32 testing docs), the staged
    `03_Test_Report.md` must contain `Real Hardware Validation` and record a
    real `nanobot agent` validation path.
- `fix(scope): ...` commits must stage:
  - `docs/02_bugfix/BUGFIX_LOG.md`
- Sync-style commits (`sync:`, `sync(...)`, `chore(sync):`, `merge(upstream):`)
  must stage:
  - `docs/sync/SYNC_LOG.md`

## When it runs

- `commit-msg` checks the files currently staged for the commit being created.
- `pre-push` re-checks each commit being pushed, so history that bypassed local
  commit hooks still gets blocked before it leaves the repo.

## Enable the hooks

Run this once in the repository:

```bash
bash scripts/install_git_hooks.sh
```

Git will then execute the repo-managed hook on every commit.

Manual equivalent:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/commit-msg .githooks/pre-push \
  scripts/check_commit_requirements.sh scripts/check_pushed_commit_requirements.sh
```

## Scope aliases

If a commit scope should map to a feature folder with a different slug, add an
entry to `.githooks/feature_scope_map.tsv`:

```text
esp32    esp32_led    led,device_led
```

Format: `scope<TAB>feature_folder_slug<TAB>optional comma-separated aliases`

## Bypass

Use `git commit --no-verify` only when you intentionally need to bypass the
policy.
#!/usr/bin/env bash

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

chmod +x \
  .githooks/commit-msg \
  .githooks/pre-push \
  scripts/check_commit_requirements.sh \
  scripts/check_pushed_commit_requirements.sh \
  scripts/install_git_hooks.sh

git config core.hooksPath .githooks

echo "Installed repo-managed git hooks from $repo_root/.githooks"
echo "git config core.hooksPath=$(git config core.hooksPath)"
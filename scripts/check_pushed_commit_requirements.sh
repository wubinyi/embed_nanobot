#!/usr/bin/env bash

set -euo pipefail

remote_name="${1:-}"
repo_root="$(git rev-parse --show-toplevel)"
checker="$repo_root/scripts/check_commit_requirements.sh"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

zero_oid='0000000000000000000000000000000000000000'

while read -r local_ref local_sha remote_ref remote_sha; do
  [[ -z "${local_sha:-}" ]] && continue
  [[ "$local_sha" == "$zero_oid" ]] && continue

  commits=()
  if [[ "$remote_sha" == "$zero_oid" ]]; then
    if [[ -n "$remote_name" ]]; then
      mapfile -t commits < <(git rev-list --reverse "$local_sha" --not --remotes="$remote_name")
    else
      mapfile -t commits < <(git rev-list --reverse "$local_sha" --not --remotes)
    fi
  else
    mapfile -t commits < <(git rev-list --reverse "${remote_sha}..${local_sha}")
  fi

  for sha in "${commits[@]}"; do
    subject_file="$tmpdir/$sha.msg"
    git show -s --format=%s "$sha" > "$subject_file"
    changed_files="$(git diff-tree --root --no-commit-id --name-only --diff-filter=ACMR -r "$sha")"
    [[ -z "$changed_files" ]] && continue
    if ! STAGED_FILES_OVERRIDE="$changed_files" "$checker" "$subject_file"; then
      echo "pre-push: commit $sha failed documentation policy checks" >&2
      exit 1
    fi
  done
done

exit 0
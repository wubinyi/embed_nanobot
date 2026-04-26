#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/check_commit_requirements.sh <commit-message-file>

Validates embed_nanobot commit requirements against a file list.
EOF
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

msg_file="$1"
if [[ ! -f "$msg_file" ]]; then
  echo "commit-requirements: commit message file not found: $msg_file" >&2
  exit 2
fi

commit_subject="$(sed -n '1p' "$msg_file" | tr -d '\r')"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if [[ -n "${STAGED_FILES_OVERRIDE:-}" ]]; then
  staged_files="$STAGED_FILES_OVERRIDE"
else
  staged_files="$(git diff --cached --name-only --diff-filter=ACMR)"
fi

has_staged_match() {
  local pattern="$1"
  if [[ -z "$staged_files" ]]; then
    return 1
  fi
  grep -Eq "$pattern" <<<"$staged_files"
}

normalize_token() {
  tr '[:upper:]' '[:lower:]' <<<"$1" | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//; s/_+/_/g'
}

trim() {
  sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' <<<"$1"
}

extract_scope() {
  sed -nE 's/^[a-z]+\(([^)]+)\):.*/\1/p' <<<"$commit_subject"
}

feature_doc_folders() {
  if [[ -z "$staged_files" ]]; then
    return 0
  fi
  grep -E '^docs/01_features/[^/]+/(01_Design_Log|02_Dev_Implementation|03_Test_Report)\.md$' <<<"$staged_files" \
    | cut -d/ -f1-3 \
    | sort -u
}

feature_impl_doc_path() {
  local folder="$1"
  printf '%s/02_Dev_Implementation.md\n' "$folder"
}

feature_test_report_path() {
  local folder="$1"
  printf '%s/03_Test_Report.md\n' "$folder"
}

read_staged_path_content() {
  local path="$1"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    if git show ":$path" >/dev/null 2>&1; then
      git show ":$path"
      return 0
    fi
  fi
  if [[ -f "$repo_root/$path" ]]; then
    cat "$repo_root/$path"
    return 0
  fi
  return 1
}

load_scope_aliases() {
  local feature_slug="$1"
  local map_file="$repo_root/.githooks/feature_scope_map.tsv"
  local aliases=()
  if [[ -f "$map_file" ]]; then
    while IFS=$'\t' read -r raw_scope raw_feature raw_aliases; do
      raw_scope="$(trim "${raw_scope:-}")"
      raw_feature="$(trim "${raw_feature:-}")"
      raw_aliases="$(trim "${raw_aliases:-}")"
      [[ -z "$raw_scope" || "$raw_scope" == \#* ]] && continue
      if [[ "$(normalize_token "$raw_feature")" == "$feature_slug" ]]; then
        aliases+=("$(normalize_token "$raw_scope")")
        IFS=',' read -ra extra_aliases <<<"$raw_aliases"
        for alias in "${extra_aliases[@]}"; do
          alias="$(normalize_token "$(trim "$alias")")"
          [[ -n "$alias" ]] && aliases+=("$alias")
        done
      fi
    done < "$map_file"
  fi
  printf '%s\n' "${aliases[@]}" | awk 'NF && !seen[$0]++'
}

is_sync_style_commit() {
  commit_subject_matches '^(sync(\([^)]+\))?:|chore\(sync\):|merge\(upstream\):|merge upstream([[:space:]]|$))'
}

is_real_hardware_sensitive_change() {
  has_staged_match '^esp32/' || \
  has_staged_match '^nanobot/mesh/' || \
  has_staged_match '^nanobot/agent/tools/device\.py$' || \
  has_staged_match '^docs/(TESTING_GUIDE|TESTING_FAQ|MICROPYTHON_GUIDE|GETTING_STARTED)\.md$'
}

fail_requirement() {
  local summary="$1"
  shift
  {
    echo "commit-requirements: $summary"
    while [[ $# -gt 0 ]]; do
      echo "- $1"
      shift
    done
    echo "- Commit subject: $commit_subject"
  } >&2
  exit 1
}

commit_subject_matches() {
  local pattern="$1"
  grep -Eq "$pattern" <<<"$commit_subject"
}

if commit_subject_matches '^feat\([^)]+\):[[:space:]].+'; then
  missing=()
  has_staged_match '^docs/01_features/[^/]+/01_Design_Log\.md$' || missing+=("stage a feature design log: docs/01_features/fXX_<feature>/01_Design_Log.md")
  has_staged_match '^docs/01_features/[^/]+/02_Dev_Implementation\.md$' || missing+=("stage a feature implementation log: docs/01_features/fXX_<feature>/02_Dev_Implementation.md")
  has_staged_match '^docs/01_features/[^/]+/03_Test_Report\.md$' || missing+=("stage a feature test report: docs/01_features/fXX_<feature>/03_Test_Report.md")
  has_staged_match '^docs/00_system/Project_Roadmap\.md$' || missing+=("stage the roadmap update: docs/00_system/Project_Roadmap.md")

  if [[ ${#missing[@]} -gt 0 ]]; then
    fail_requirement "feature commits must include feature docs and roadmap updates" "Required by .github/copilot-instructions.md Phase 2/3 workflow." "${missing[@]}"
  fi

  mapfile -t doc_folders < <(feature_doc_folders)
  if [[ ${#doc_folders[@]} -ne 1 ]]; then
    fail_requirement "feature commits must stage docs from exactly one feature folder" "Stage one feature folder under docs/01_features/fXX_<feature>/ for each feat(...) commit." "Found folders: ${doc_folders[*]:-(none)}"
  fi

  feature_scope="$(normalize_token "$(extract_scope)")"
  feature_folder="${doc_folders[0]##*/}"
  feature_slug="$(normalize_token "${feature_folder#f[0-9][0-9]_}")"
  mapfile -t allowed_scopes < <(load_scope_aliases "$feature_slug")
  if [[ ${#allowed_scopes[@]} -eq 0 ]]; then
    allowed_scopes=("$feature_slug")
  fi

  scope_match=1
  for allowed_scope in "${allowed_scopes[@]}"; do
    if [[ -n "$feature_scope" && ( "$feature_slug" == *"$feature_scope"* || "$feature_scope" == *"$feature_slug"* || "$feature_scope" == "$allowed_scope" ) ]]; then
      scope_match=0
      break
    fi
  done
  if [[ $scope_match -ne 0 ]]; then
    fail_requirement "feature commit scope must match its staged feature docs folder" "Commit scope '$feature_scope' does not match docs folder '${doc_folders[0]}'" "Allowed scopes for '$feature_slug': ${allowed_scopes[*]}"
  fi

  impl_doc="$(feature_impl_doc_path "${doc_folders[0]}")"
  if ! read_staged_path_content "$impl_doc" | grep -Fq 'Documentation Freshness Check'; then
    fail_requirement "feature implementation docs must record the documentation freshness check" "Add a 'Documentation Freshness Check' section to $impl_doc." "Required by .github/copilot-instructions.md Documentation Freshness Check."
  fi

  if ! read_staged_path_content "$impl_doc" | grep -Fq 'Post-Task Reflection'; then
    fail_requirement "feature implementation docs must include a post-task reflection note" "Add a 'Post-Task Reflection' section to $impl_doc." "Required by .github/copilot-instructions.md Self-Reflection Protocol."
  fi

  if is_real_hardware_sensitive_change; then
    test_report="$(feature_test_report_path "${doc_folders[0]}")"
    if ! read_staged_path_content "$test_report" | grep -Fq 'Real Hardware Validation'; then
      fail_requirement "hardware-sensitive feature commits must record real hardware validation" "Add a 'Real Hardware Validation' section to $test_report." "Required by .github/copilot-instructions.md Real Hardware Validation Policy."
    fi
    if ! read_staged_path_content "$test_report" | grep -Fq 'nanobot agent'; then
      fail_requirement "hardware-sensitive feature test reports must include the real nanobot agent validation path" "Record the actual 'nanobot agent' validation command in $test_report." "User-visible device behavior must be validated through the real assistant path."
    fi
  fi
fi

if commit_subject_matches '^fix\([^)]+\):[[:space:]].+'; then
  if ! has_staged_match '^docs/02_bugfix/BUGFIX_LOG\.md$'; then
    fail_requirement "fix commits must update the bug fix log" "Stage docs/02_bugfix/BUGFIX_LOG.md for fix(...) commits." "Required by .github/copilot-instructions.md Bugfix Workflow."
  fi
fi

if is_sync_style_commit; then
  if ! has_staged_match '^docs/sync/SYNC_LOG\.md$'; then
    fail_requirement "sync-style commits must update the sync log" "Stage docs/sync/SYNC_LOG.md for sync/upstream merge commits." "Required by .github/copilot-instructions.md Upstream Sync Protocol."
  fi
fi

exit 0
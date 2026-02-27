# Sync Details — 2026-02-27

**Commits**: 107 (78 non-merge)
**Range**: `9e806d7` → `e86cfcd`

## Upstream Features Merged

- **Matrix (Element) channel**: Full-featured Matrix/Element chat channel with E2EE support, markdown rendering (nh3 sanitization), media attachments (inbound + outbound), typing indicators, group policy/mention gating, configurable reaction emoji, room invite handling. 682 LOC + 1302 LOC tests.
- **Agent context refactor**: Untrusted runtime context layer for stable prompt prefix, base64 image stripping from session history (prevents context overflow), runtime context metadata filtering from session history.
- **Agent loop improvements**: `_save_turn` refactored (merge user-role branches), message tool suppress simplified (bool check instead of target tracking), assistant messages without tool calls now saved to session.
- **Subagent task cancellation**: `/stop` command with task-based dispatch, parallel subagent cancellation, session tracking for spawned subagents.
- **Feishu**: Configurable reaction emoji (`react_emoji` field).
- **Telegram**: Media-group aggregation fix (aggregate images into single inbound turn).
- **Web channel fix**: Use `self.api_key` instead of undefined `api_key`.
- **Exec tool**: `path_append` config to extend PATH for subprocess.
- **Workspace template sync**: Auto-sync workspace templates on startup.
- **Explicit provider selection**: `provider` field in AgentDefaults (e.g. "anthropic", "openrouter", or "auto").
- **helpers.py cleanup**: Dead code removal, compressed docstrings.
- **Heartbeat tests**: Rewritten to match two-phase tool-call architecture (DummyProvider + LLMResponse/ToolCallRequest).
- **New test files**: test_matrix_channel.py, test_message_tool.py, test_message_tool_suppress.py, test_task_cancel.py.

## Conflicts Resolved

- **`nanobot/channels/manager.py`**: Upstream added Matrix channel registration in the spot where our mesh channel was. Resolution: Accept Matrix block first, re-append mesh channel block after (append-only convention).
- **`nanobot/config/schema.py`**: Upstream added `MatrixConfig` to `ChannelsConfig` where our `MeshConfig` was. Resolution: Accept `matrix` field first, re-append `mesh` field after (append-only convention).
- **`tests/test_heartbeat_service.py`**: Upstream rewrote tests entirely (DummyProvider pattern + LLMResponse/ToolCallRequest imports). Our previous MagicMock stub was obsolete. Resolution: Accept upstream version entirely.

## Remaining Upstream Commits
- 0 commits pending (fully synced)

## Test Results
- **910 tests passed**, zero failures (was 894 pre-sync, gained 16 upstream tests)
- Matrix channel tests skipped (require optional `nh3`, `matrix-nio` dependencies)

## Convention Updates
- **`Literal` import**: `from typing import Literal` now used in schema.py (for MatrixConfig.group_policy)
- **Provider selection**: New `provider: str = "auto"` field in AgentDefaults; `match_provider()` checks this before model-based detection
- **`path_append`**: New field on ExecToolConfig
- **`react_emoji`**: New field on FeishuConfig
- **Heartbeat test pattern**: DummyProvider + LLMResponse/ToolCallRequest replaces MagicMock stubs

# Upstream Sync Details — 2026-02-25

## Summary

| Field | Value |
|-------|-------|
| Previous HEAD | ce4f005 |
| New HEAD | 9e806d7 |
| Total commits | 276 (148 non-merge) |
| Files changed | 125 |
| Lines | +2,863 / −16,962 |
| Tags | v0.1.4, v0.1.4.post1, v0.1.4.post2 |
| Conflicts | 3 files (manager.py ×2, commands.py, pyproject.toml) |

## Key Upstream Changes

### Architecture
- **workspace/ → nanobot/templates/**: Template files (AGENTS.md, USER.md, SOUL.md, TOOLS.md, HEARTBEAT.md, memory/MEMORY.md) moved into the package. CLI `_create_workspace_templates()` now uses `importlib.resources`.
- **Memory consolidation extraction**: Consolidation types moved to `nanobot/agent/memory_types.py` for reuse.
- **CLI bus routing refactor**: Session management integration, outbound message routing through bus.

### Providers
- **VolcEngine provider** (火山引擎): New provider config in schema.py, entry in registry.py.
- **Provider matching refactored**: Registry now uses updated keyword matching logic.

### Channels
- **Mochat channel**: New channel added to manager (our first conflict zone).
- **BaseChannel._handle_message**: Gained optional `session_key` parameter. Our MeshChannel is compatible (uses kwargs, session_key defaults to None).
- **Progress streaming**: Channels can stream agent text progress and tool hints via `send_progress` and `send_tool_hints` config fields.

### Agent
- **Defaults changed**: temperature 0.7→0.1, max_tool_iterations 20→40, memory_window 50→100.
- **Prompt caching**: New context prompt caching mechanism.
- **HeartbeatService refactored**: Replaced HEARTBEAT_OK token-parsing with virtual tool-call decision (skip/run). `HEARTBEAT_OK_TOKEN` constant removed. Constructor now requires `provider` + `model` instead of `on_heartbeat` callback.

### Dependencies
- All deps now pinned with upper bounds (e.g., `>=X.Y.Z,<X+1.0.0`).
- New deps: `python-socketio>=5.16.0,<6.0.0`, `msgpack>=1.1.0,<2.0.0`.
- Removed: standalone `socksio` (now part of telegram socks dep).

## Conflict Resolution

### 1. `nanobot/channels/manager.py` (2 conflict zones)

**Zone 1** (Feishu→DingTalk gap): Upstream added Mochat channel registration block. Our side had nothing.
- **Resolution**: Accept upstream Mochat block.

**Zone 2** (QQ channel logger): Upstream changed `logger.warning(f"...")` to `logger.warning("...", e)` (loguru native format). Our side had f-string format plus mesh channel block appended after.
- **Resolution**: Accept upstream loguru format for QQ. Re-append mesh channel block with loguru-style `logger.warning("...", e)` formatting and `# --- embed_nanobot extensions ---` marker.

### 2. `nanobot/cli/commands.py` (1 conflict zone)

**Zone** (after workspace template creation): Upstream added `(workspace / "skills").mkdir(exist_ok=True)`. Our side had nothing.
- **Resolution**: Accept upstream skills mkdir line.

Note: Our HybridRouter code in `_make_provider()` and DeviceControlTool/routing blocks in `gateway()` auto-merged successfully (verified intact at L242-296 and L472-489).

### 3. `pyproject.toml` (1 conflict zone)

**Zone** (full dependencies array): Our side had loose version pins + cryptography. Upstream had strict version ranges.
- **Resolution**: Accept all upstream pinned versions. Re-append `"cryptography>=41.0.0,<44.0.0"` with upper bound following upstream convention.

## Additional Fix

### `tests/test_heartbeat_service.py` (upstream stale test)

The upstream test file (added in commit `bfdae1b`, partially updated in `6f4d1c2`) imported `HEARTBEAT_OK_TOKEN` which was removed in commit `ec55f77`. The test also used the old `on_heartbeat` callback constructor API.
- **Fix**: Rewrote test to use mock `LLMProvider` with current HeartbeatService constructor (`provider`, `model`, `on_execute`, `on_notify`). Removed `test_heartbeat_ok_detection` (tested obsolete behavior). Kept `test_start_is_idempotent` with updated constructor.

## Post-Merge Verification

- [x] No conflict markers remaining in source files
- [x] MeshConfig, HybridRouterConfig, mesh/hybrid_router fields intact in schema.py
- [x] DeviceControlTool and routing blocks intact in commands.py gateway()
- [x] BaseChannel._handle_message session_key compatible with MeshChannel
- [x] workspace/ removed, nanobot/templates/ present
- [x] Upstream features present (send_progress, volcengine, HeartbeatConfig, temperature=0.1)
- [x] All 438 tests pass (24 new upstream tests)

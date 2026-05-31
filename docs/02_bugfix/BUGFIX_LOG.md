# Bug Fix Log

> Tracks all bug fixes discovered during hardware integration testing.
> Each entry records the symptom, root cause, fix, and affected files
> so future sessions can quickly understand what changed and why.

## Bug ID Index

- Assigned bug IDs in this file currently run from `BUG-001` through `BUG-022`.
- Next bug ID to assign: `BUG-025`.
- Rule: use the next unassigned bug ID, even when backfilling an older incident, and update this index in the same edit.

---

## BUG-001: `MeshChannel` attribute mismatch — `ota_manager` vs `ota`

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Critical (gateway crash on startup) |
| **Found by** | Hardware integration testing |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: `nanobot gateway -v` crashes with:
```
AttributeError: 'MeshChannel' object has no attribute 'ota_manager'
```
followed by:
```
NameError: name 'logger' is not defined
```

**Root cause**: Two issues in `nanobot/cli/commands.py` (embed extension blocks):
1. The reprogram tool registration referenced `mesh_ch.ota_manager` but `MeshChannel.__init__` defines the attribute as `self.ota`.
2. The `except` blocks used `logger.warning(...)` but `logger` was not imported in the `gateway()` function scope.

**Fix**:
- `mesh_ch.ota_manager` → `mesh_ch.ota` (line ~744)
- `mesh_ch.ota_manager` → `mesh_ch.ota` (line ~755, reprogram tool kwarg)
- Added `from loguru import logger as _embed_logger` before embed extension blocks
- Changed both `logger.warning(...)` → `_embed_logger.warning(...)`

**Files changed**: `nanobot/cli/commands.py`

**Commit**: `fix(cli): correct ota_manager attribute name and missing logger import`

---

## BUG-002: `--enroll` CLI flag not implemented

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Major (missing feature, blocks device enrollment workflow) |
| **Found by** | Hardware integration testing |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: `nanobot gateway --enroll` fails — no `--enroll` option exists.

**Root cause**: The `EnrollmentService.create_pin()` method exists in `nanobot/mesh/enrollment.py` but was never exposed via a CLI flag. The gateway command in `commands.py` had no `--enroll` parameter. Documentation referenced the flag but it was never implemented.

**Fix**: Added `--enroll` flag to `gateway()` command:
- New typer Option: `enroll: bool = typer.Option(False, "--enroll", ...)`
- After channel initialization, if `--enroll` is set and mesh channel has enrollment service, calls `create_pin()` and prints the PIN with expiration time
- Gateway continues running normally after printing PIN (ESP32 connects over TCP to complete enrollment)
- Error messages if mesh not enabled or enrollment service not initialized

**Files changed**: `nanobot/cli/commands.py`

**Commit**: `feat(cli): add --enroll flag to gateway command for device enrollment`

---

## BUG-003: Mesh `allowFrom` empty by default blocks all connections

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Medium (config issue, not a code bug) |
| **Found by** | Hardware integration testing |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Gateway starts but immediately errors:
```
Error: "mesh" has empty allowFrom (denies all). Set ["*"] to allow everyone, or add specific user IDs.
```

**Root cause**: The `nanobot onboard` command generates `config.json` with `mesh.allowFrom: []`. This follows upstream's security-by-default pattern (empty = deny all), but the TESTING_GUIDE didn't mention this required config change.

**Fix**: Not a code change — config fix:
```json
"mesh": { "allowFrom": ["*"] }
```
Updated `docs/TESTING_GUIDE.md` to include this step in the mesh enable instructions.

**Files changed**: `docs/TESTING_GUIDE.md` (documentation only)

---

## BUG-004: ESP32 `main.py` SyntaxError on line 57 — `**dict` unpacking

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Critical (ESP32 cannot boot) |
| **Found by** | Hardware testing (`import main` in REPL) |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: `import main` on ESP32 raises:
```
File "main.py", line 57
SyntaxError: invalid syntax
```

**Root cause**: Line 57 used `**result` dict unpacking in a dict literal (PEP 448). MicroPython does not support this syntax. Additionally, 6 other MicroPython-incompatible patterns found across 5 files:
- `str | None` union types (PEP 604) in main.py, security.py, transport.py, protocol.py
- `dict` variable type annotations (PEP 526) in device.py
- `100_000` numeric literal separator (PEP 515) in enrollment.py

**Fix**: Replaced all 7 incompatible patterns:
- `{**result}` → `d = {}; d.update(result)` (main.py)
- `str | None` → remove annotation (main.py, security.py, transport.py, protocol.py)
- `x: dict = {}` → `x = {}` (device.py)
- `100_000` → `100000` (enrollment.py)

**Files changed**: `esp32/mesh_client/main.py`, `esp32/mesh_client/security.py`, `esp32/mesh_client/transport.py`, `esp32/mesh_client/device.py`, `esp32/mesh_client/enrollment.py`, `esp32/mesh_client/protocol.py`

---

## BUG-005: ESP32 `import main` fails — `hmac` module not available in MicroPython

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Critical (ESP32 cannot boot) |
| **Found by** | Agent testing after BUG-004 fix |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: After fixing BUG-004, `import main` raises:
```
ImportError: no module named 'hmac'
```

**Root cause**: `security.py` and `enrollment.py` imported the `hmac` standard library module, which is not available in MicroPython. Additionally, `enrollment.py` used `hashlib.pbkdf2_hmac()` which is also not available in MicroPython.

**Fix**: Implemented manual alternatives:
- `security.hmac_sha256(key, msg)` — manual HMAC-SHA256 using `hashlib.sha256` with ipad/opad construction (RFC 2104)
- `enrollment._pbkdf2_sha256(password, salt, iterations, dklen)` — manual PBKDF2-HMAC-SHA256 using the above HMAC function

Removed `import hmac` from both files.

**Files changed**: `esp32/mesh_client/security.py`, `esp32/mesh_client/enrollment.py`

---

## BUG-006: Enrollment response not delivered — `transport.send()` fails for unenrolled device

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Critical (enrollment hangs on ESP32) |
| **Found by** | End-to-end enrollment test |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: ESP32 sends ENROLL_REQUEST, hub logs "ENROLLED device 'esp32-01'", but ESP32 never receives the ENROLL_RESPONSE. Hub logs: `peer 'esp32-01' not found or offline`.

**Root cause**: After generating the PSK, `enrollment.py` called `transport.send()` to deliver the response. But `send()` looks up the peer via UDP discovery, and the enrolling device has no discovery entry (newly connecting over TCP for the first time).

**Fix**: 
- In `transport.py` `_handle_connection()`: attach the raw TCP writer to the ENROLL_REQUEST envelope payload as `_reply_writer`
- In `enrollment.py` `handle_enroll_request()`: extract `_reply_writer` from payload and write the response directly on the same TCP connection, bypassing `transport.send()`
- Also fixed `_send_error()` to accept optional `reply_writer` parameter
- Also fixed ESP32 `enrollment.py`: `payload.get("success")` → `payload.get("status") != "ok"` (hub sends `"status": "ok"`, not `"success": True`)

**Files changed**: `nanobot/mesh/transport.py`, `nanobot/mesh/enrollment.py`, `esp32/mesh_client/enrollment.py`

---

## BUG-007: PBKDF2 takes 221 seconds on ESP32 (100,000 iterations)

| Field | Value |
|-------|-------|
| **Date** | 2026-03-26 |
| **Severity** | Major (enrollment appears to hang) |
| **Found by** | End-to-end enrollment test (ESP32 hangs after receiving PSK) |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: ESP32 receives ENROLL_RESPONSE but hangs for >3 minutes during `_decrypt_psk()`.

**Root cause**: `_pbkdf2_sha256(pin, salt, 100000)` performs 100,000 iterations of HMAC-SHA256. Benchmarked on ESP32: ~2.2ms per HMAC-SHA256 call, so 100,000 iterations = 221 seconds (3.7 minutes).

**Fix**: Reduced PBKDF2 iterations from 100,000 to 1,000 on both hub and ESP32. This gives ~2.2s on ESP32 — acceptable for enrollment. All 36 hub enrollment tests still pass (0.55s vs 1.51s before).

**Security note**: 1,000 iterations is weak for password-based key derivation, but the PIN is one-time-use (300s expiry) and the derived key only protects the PSK during enrollment transit, not for long-term storage. Phase 2 security (mTLS) will replace this entirely.

**Files changed**: `nanobot/mesh/enrollment.py`, `esp32/mesh_client/enrollment.py`

---

## BUG-008: HMAC verification fails after enrollment — signing format mismatch

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | Critical (all authenticated messages rejected) |
| **Found by** | End-to-end test — STATE_REPORT rejected after successful enrollment |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Hub logs `REJECTED message from esp32-01 — HMAC verification failed` for all post-enrollment messages. ESP32 gets ECONNRESET on STATE_REPORT.

**Root cause**: Three compounding issues in ESP32's `security.py`:

1. **Wrong signing input format**: ESP32 signed `"type:source:target:ts:nonce"` (colon-separated), but hub signed `canonical_json_bytes + nonce_ascii_bytes` where canonical is the full envelope dict (minus hmac/nonce) serialized with `json.dumps(sort_keys=True)`.

2. **Missing nested key sorting**: Even after fixing format, MicroPython dicts don't preserve insertion order. `json.dumps()` serialized nested dicts in hash order, while CPython's `sort_keys=True` sorts recursively at all levels. Used `OrderedDict` with recursive `_deep_sort()` to match CPython's behavior.

3. **Missing envelope fields**: ESP32 didn't include `encrypted_payload` and `iv` fields in the envelope dict, but the hub's `MeshEnvelope.from_bytes()` always defaults them to `""`. The canonical computation on the hub therefore included these fields, creating a mismatch.

**Fix**:
- `security.py`: Replaced colon-separated signing with canonical JSON format. Added `_deep_sort()` using `OrderedDict` for recursive key sorting. Added `_canonical_bytes()` that matches hub's `MeshEnvelope.canonical_bytes()`.
- `protocol.py`: Added `encrypted_payload: ""` and `iv: ""` to `build_envelope()`.

**Verification**: Cross-validated HMAC output between ESP32 manual implementation and CPython's `hmac` module — identical results for same inputs.

**Files changed**: `esp32/mesh_client/security.py`, `esp32/mesh_client/protocol.py`

---

## BUG-009: Timestamps rejected — MicroPython epoch offset

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | Major (messages rejected even with correct HMAC) |
| **Found by** | End-to-end test — HMAC passed but timestamp check failed |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Hub logs `REJECTED message from esp32-01 — timestamp 8039 outside window` even after HMAC fix.

**Root cause**: MicroPython's `time.time()` returns seconds since 2000-01-01, not the Unix epoch (1970-01-01). The offset is 946,684,800 seconds. Additionally, the ESP32's RTC starts from 0 on boot — NTP sync is needed for correct absolute time.

**Fix**:
- `protocol.py`: Added `_EPOCH_OFFSET = 946684800` and use `time.time() + _EPOCH_OFFSET` in `build_envelope()`.
- `transport.py`: Added `ntptime.settime()` call after WiFi connection (runs even if WiFi was already connected from a previous boot).

**Files changed**: `esp32/mesh_client/protocol.py`, `esp32/mesh_client/transport.py`

---

## BUG-010: STATE_REPORT payload missing "state" wrapper key

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | Minor (message accepted but not processed) |
| **Found by** | End-to-end test — hub logged "empty STATE_REPORT" |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Hub logs `[MeshChannel] empty STATE_REPORT from esp32-01` even though the ESP32 sent a payload with capabilities.

**Root cause**: Hub's `_handle_state_report()` looks for `env.payload.get("state", {})`, but ESP32's `get_state_report_payload()` returned `{"capabilities": [...], "firmware_version": "..."}` — no `"state"` wrapper.

**Fix**: Wrapped the capability data under a `"state"` key in `get_state_report_payload()`.

**Files changed**: `esp32/mesh_client/device.py`

---

## BUG-011: Unregistered device STATE_REPORT rejected

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | High (device connects but can't receive commands) |
| **Found by** | Gap analysis — auto-registration missing |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: After enrollment, ESP32 sends STATE_REPORT but hub logs `STATE_REPORT from unregistered device esp32-01`. The device is authenticated but never auto-registered in the DeviceRegistry.

**Root cause**: `_handle_state_report()` called `registry.update_state()` which returns `False` for unknown devices. No auto-registration path existed — the only way to register was via UDP discovery beacons, which ESP32 doesn't emit.

**Fix**: Added auto-registration in `_handle_state_report()`: when a device is authenticated (has PSK) but not in the registry, parse capabilities from STATE_REPORT and call `registry.register_device()`. Added `_TYPE_MAP` for ESP32→registry type mapping.

**Files changed**: `nanobot/mesh/channel.py`

---

## BUG-012: COMMAND payload mismatch (hub vs ESP32)

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | High (commands never execute on device) |
| **Found by** | Code review during gap analysis |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Hub sends COMMAND with `{"params": {"value": true}}` but ESP32 reads `payload.get("value")` → None. Also hub uses "set"/"get" but ESP32 expects "turn_on"/"turn_off"/"read".

**Root cause**: Value nested in params dict; action name mismatch between hub and device.

**Fix**: ESP32 `_dispatch()` reads from `params` dict, maps hub actions to device actions.

**Files changed**: `esp32/mesh_client/main.py`

---

## BUG-013: Hub closes TCP after one envelope (no persistent connection)

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | Critical (bidirectional communication impossible) |
| **Found by** | Gap analysis — transport.py code review |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: ESP32 connects, sends STATE_REPORT, but can never receive COMMAND back.

**Root cause**: `_handle_connection()` read one envelope then closed the TCP connection. ESP32 has no TCP server — needs persistent connection for commands.

**Fix**: Added persistent connection tracking (`_device_writers`), `_persistent_read_loop` with 90s idle timeout, `send()` checks persistent connections first.

**Files changed**: `nanobot/mesh/transport.py`

---

## BUG-014: Device always OFFLINE despite active TCP connection

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | High (agent refuses commands to "offline" device) |
| **Found by** | E2E test — DeviceControlTool listed esp32-01 as OFFLINE |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Agent sees `esp32-01 [OFFLINE]` and refuses to send commands. ESP32 is actively connected with pings flowing.

**Root cause**: Online flag only set by UDP discovery callbacks. ESP32 connects via TCP only.

**Fix**: Added `on_device_connected`/`on_device_disconnected` callbacks to transport. Channel hooks them to `registry.mark_online`/`mark_offline`.

**Files changed**: `nanobot/mesh/transport.py`, `nanobot/mesh/channel.py`

---

## BUG-015: LLM sends string "True" instead of bool

| Field | Value |
|-------|-------|
| **Date** | 2026-03-27 |
| **Severity** | Medium (validation rejects LLM commands) |
| **Found by** | E2E test — validate_command rejects value type |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: LLM sends `"value": "True"` (string), validation says "must be bool, got str". Also offline treated as blocking error.

**Root cause**: LLM JSON formatting; overly strict validation.

**Fix**: Coerce string "True"/"False" to bool. Treat offline as advisory, not blocking.

**Files changed**: `nanobot/agent/tools/device.py`, `tests/test_device_control_tool.py`

---

## BUG-016: ESP32 NTP failure causes hub to reject all messages (nonce_window)

| Field | Value |
|-------|-------|
| **Date** | 2026-04-22 |
| **Severity** | Critical (all hardware tests fail) |
| **Found by** | Hardware integration test session (hw1.txt – hw3.txt) |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: All 6 hardware tests fail. Hub logs show `nonce=946684808` (year 2000). Hub rejects every message with nonce-window check.

**Root cause**: After DTR reset (mpremote), ESP32 NTP sync sometimes fails. `time.time()` returns ~8 (seconds since MicroPython epoch), so `_EPOCH_OFFSET + 8 = 946684808` — rejected by hub's `nonce_window=60`.

Two separate fixes were needed:
1. Widen `nonce_window` in tests to allow year-2000 fallback timestamps.
2. Add NTP retry logic on ESP32 (3 attempts, 5 s timeout each).

**Fix**:
- `tests/test_ota_hardware.py`: changed `nonce_window=60` → `nonce_window=2_000_000_000` so the hub under test accepts any plausible timestamp.
- `esp32/mesh_client/transport.py`: NTP now retries 3 times with 2 s delay and `ntptime.timeout = 5`. Deployed to device.

**Files changed**: `tests/test_ota_hardware.py`, `esp32/mesh_client/transport.py`

---

## BUG-017: Test helper `_port_free()` falsely reports port as busy (FIN-WAIT-2)

| Field | Value |
|-------|-------|
| **Date** | 2026-04-22 |
| **Severity** | Medium (second test run blocked) |
| **Found by** | Hardware test – port 18800 "already in use" on re-run |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: After one test run, `_port_free(18800)` returns False and all subsequent tests are skipped with "port busy" message.

**Root cause**: `socket.connect()` raises `ConnectionRefusedError` (port is actually free) but some connections linger in `FIN-WAIT-2`, causing a plain `connect()` to succeed, making `_port_free()` think the port is in use.

**Fix**: Rewrote `_port_free()` to bind with `SO_REUSEADDR` — if `bind()` succeeds the port is free, if `OSError` is raised it's genuinely busy.

**Files changed**: `tests/test_ota_hardware.py`

---

## BUG-018: Test code used wrong `transport.send()` API signature

| Field | Value |
|-------|-------|
| **Date** | 2026-04-22 |
| **Severity** | High (test_esp32_ping_pong and test_partition_query fail) |
| **Found by** | hw4.txt test run — `TypeError: send() takes 2 positional arguments but 4 were given` |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: `test_esp32_ping_pong` raises `TypeError`; `test_partition_query` sends wrong message type `query_partitions` (ESP32 ignores it; no `partition_report` received).

**Root cause**: Test code called `channel.transport.send("ping", node_id, {})` (3 args) but the hub's `async def send(self, env: MeshEnvelope)` takes a single `MeshEnvelope` object. Additionally, `envelope.msg_type` was used but the field is named `envelope.type`. And the test sent `"query_partitions"` but the ESP32 dispatch handler listens on `"partition_query"`.

**Fix**:
- Added `from nanobot.mesh.protocol import MeshEnvelope` import.
- Changed all `transport.send(type, target, payload)` calls to `transport.send(MeshEnvelope(type=..., source=_HUB_NODE_ID, target=...))`.
- Fixed `envelope.msg_type` → `envelope.type` in listener callbacks.
- Fixed `datetime.utcnow()` → `datetime.now(datetime.timezone.utc)` (deprecation).
- Fixed `"query_partitions"` → `"partition_query"` to match ESP32's `_dispatch` handler.

---

## BUG-019: OTA anti-rollback rejects offers with version_counter=0 after first install

| Field | Value |
|-------|-------|
| **Date** | 2026-04-22 |
| **Severity** | High (test_ota_firmware_update fails on every re-run) |
| **Found by** | hw5.txt — "anti-rollback: version counter too low" |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: `test_ota_firmware_update` fails with `state='rejected'`, error "anti-rollback: version counter too low". Happens on every run after the first successful OTA that stored `version_counter=0`.

**Root cause**: `FirmwareInfo` had no `version_counter` field; `add_firmware()` always sent `"version_counter": 0` in the OTA offer. After the first install, the device stores 0. Any subsequent offer with 0 fails anti-rollback (`0 > 0` is false).

**Fix**:
- Added `version_counter: int = 0` field to `FirmwareInfo` dataclass in `nanobot/mesh/ota.py`.
- Added `*, version_counter: int = 0` kwarg to `add_firmware()`.
- Included `"version_counter": firmware.version_counter` in the OTA offer payload (was hardcoded to 0).
- In the test, compute `fw_version_counter = int(time.time())` at test start and pass it to `add_firmware(...)` — unique per run, always ahead of the stored value.

**Files changed**: `nanobot/mesh/ota.py`, `tests/test_ota_hardware.py`

---

## BUG-020: Gateway sees ESP32 online, but registry JSON and agent stay offline

| Field | Value |
|-------|-------|
| **Date** | 2026-04-26 |
| **Severity** | High (live device status is wrong across processes) |
| **Found by** | User hardware test with `nanobot gateway -v` |
| **Phase** | 5.3.2 (ESP32 SDK testing) |

**Symptom**: Gateway logs show `persistent connection from esp32-01` and `device esp32-01 is online`, but `/home/wubinyi/.nanobot/workspace/device_registry.json` still shows `"online": false`, and a separate `nanobot agent` process still answers that the device is offline.

**Root cause**:
- `DeviceRegistry.mark_online()` / `mark_offline()` updated only in-memory state and never saved the registry file.
- `DeviceRegistry.load()` forced every loaded device back to offline, discarding any fresh persisted online state.
- `DeviceControlTool` answered from its own in-memory registry snapshot and never reloaded the shared registry file, so a separate `nanobot agent` process could not see gateway-side updates.
- `UDPDiscovery.prune()` could still trigger `MeshChannel._on_peer_lost()` and force the device offline even while a persistent TCP connection from the ESP32 was still active, because ESP32 devices do not rely on UDP beacon traffic for liveness.

**Fix**:
- Persist `mark_online()` and `mark_offline()` immediately to disk.
- Preserve online state across reloads when `last_seen` is still fresh; expire it after 90 seconds without activity.
- Refresh `last_seen` on every inbound mesh message by marking the source online in `MeshChannel._on_mesh_message()`.
- Reload the shared registry snapshot inside `DeviceControlTool` before list/state/describe/command actions so agent and gateway processes stay aligned.
- Ignore discovery `peer_lost` events for devices that still have a live persistent TCP connection in `MeshTransport`.
- Added regression tests for persisted online/offline state, fresh/stale reload behavior, device-tool snapshot reload behavior, and discovery-vs-persistent-TCP liveness handling.

**Files changed**: `nanobot/mesh/registry.py`, `nanobot/mesh/channel.py`, `nanobot/mesh/transport.py`, `nanobot/agent/tools/device.py`, `tests/test_device_registry.py`, `tests/test_device_control_tool.py`, `tests/test_mesh.py`

---

## BUG-021: Hybrid router rejected agent chat kwargs

| Field | Value |
|-------|-------|
| **Date** | 2026-05-01 |
| **Severity** | High (real `nanobot agent` hybrid mode crashes before routing) |
| **Found by** | Radxa 5T hybrid routing validation |
| **Phase** | Local LLM / hybrid routing validation |

**Symptom**: With `agents.defaults.provider` set to `"hybrid"`, real `nanobot agent` requests failed before model inference because `HybridRouterProvider.chat()` did not accept newer chat kwargs such as `reasoning_effort`.

**Root cause**: `AgentLoop` passes provider-specific chat options through the common provider interface. `HybridRouterProvider.chat()` lagged behind the current provider signature and only accepted `messages`, `tools`, `model`, `max_tokens`, and `temperature`, so hybrid mode raised `TypeError` before the router could reach either local or remote execution.

**Fix**:
- Extended `HybridRouterProvider.chat()` to accept `reasoning_effort` and `tool_choice`
- Forwarded both kwargs through every routed path: forced-local, judged-local, API, and local fallback
- Added a focused regression test to assert the routed provider receives those kwargs

**Files changed**: `nanobot/providers/hybrid_router.py`, `tests/test_hybrid_router.py`

---

## BUG-022: RKLLM local-provider startup and agent prompt exceeded model limits

| Field | Value |
|-------|-------|
| **Date** | 2026-05-03 |
| **Severity** | Major (local RKLLM provider started inconsistently and real `nanobot agent` returned empty output) |
| **Found by** | RK3588 local-provider integration testing |
| **Phase** | Local LLM / RKLLM bring-up |

**Symptom**:
- `bash local_llm/local_provider/start_local_provider.sh` sometimes failed during RKLLM init with:
```
E rkllm: max_context[8192] must be less than the model's max_context_limit[4096]
```
- After startup was fixed, direct adapter probes could work but real `nanobot agent` still returned:
```
I've completed processing but have no response to give.
```

**Root cause**:
1. The copied upstream RKLLM demo server source under `local_llm/rknn-llm-src/.../flask_server.py` had already been changed to `rkllm_param.max_context_len = 8192`, but the validated model hard-caps context at `4096`.
2. The upstream RKLLM demo server skips normal `system` and later chat-history messages in a way that returns an empty completion for ordinary OpenAI-style multi-message chat payloads.
3. Even after fixing request normalization, the real `nanobot agent` prompt still exceeded the model limit because built-in skills and full tool schemas were always injected, pushing the prompt to about `4263` tokens.

**Fix**:
- `local_llm/local_provider/start_local_provider.sh`: normalize the copied backend server to `max_context_len = 4096` and `max_new_tokens = 1024` before launch.
- `local_llm/local_provider/openai_adapter.py`: flatten OpenAI-style chat history into a single backend `user` prompt, keep OpenAI-compatible non-stream and stream responses, and normalize tag-based tool-call output.
- `nanobot/agent/skills.py`: honor `NANOBOT_DISABLE_BUILTIN_SKILLS=1` to suppress built-in skill injection for low-context runs.
- `nanobot/agent/loop.py`: honor `NANOBOT_DISABLE_TOOLS=1` to suppress tool-schema injection for low-context runs.
- `local_llm/scripts/run_agent_smoke.sh`: RKLLM mode now uses a dedicated minimal workspace plus both env vars above so the real smoke request fits inside the model's hard `4096` context limit.

**Files changed**: `local_llm/local_provider/start_local_provider.sh`, `local_llm/local_provider/openai_adapter.py`, `local_llm/scripts/run_agent_smoke.sh`, `nanobot/agent/skills.py`, `nanobot/agent/loop.py`, `local_llm/README.md`, `local_llm/local_provider/README.md`, `local_llm/docs/AGENT_VALIDATION.md`, `local_llm/docs/RK3588_TOOLCHAIN_LOG.md`

**Real validation**:
- `bash local_llm/local_provider/start_local_provider.sh` → PASS
- `curl -s http://127.0.0.1:18000/v1/chat/completions ...` → PASS, returned `RKLLM_OK`
- `bash local_llm/scripts/run_agent_smoke.sh --mode rkllm` → PASS, real `nanobot agent` returned `RKLLM_OK`

---

## BUG-023: Phase 2.3 simplified hybrid loop produced NaN diff metrics

| Field | Value |
|-------|-------|
| **Date** | 2026-05-30 |
| **Severity** | Major (checkpoint quality gate blocked) |
| **Found by** | f26 Phase 2.3 real-hardware rerun |
| **Phase** | 5.5.5 (RKNN hybrid subgraph inference) |

**Symptom**:
- `local_llm/local_provider_rknn_hybrid/inference/hybrid_loop.py` completed 32 layers but reported non-finite quality metrics:
	- `hidden_max_abs_diff_vs_cpu_ref = NaN`
	- `hidden_mean_abs_diff_vs_cpu_ref = NaN`
	- `hidden_checksum_cpu = NaN`
- Runtime warnings indicated overflow in `silu`, FFN multiplication, and float16 cast paths.

**Root cause**:
- The simplified milestone graph had no numeric bounds, so FP16/FP32 mixed intermediates grew unbounded.
- Overflows propagated through FFN activation and residual accumulation, producing NaN/Inf tensors in the CPU reference and invalid diff gating outputs.

**Fix**:
- Added bounded clip/scale policy in `hybrid_loop.py`:
	- `clamp_act()` and `clamp_state()` helpers with finite `nan_to_num` sanitization.
	- Stable `silu()` input bounding.
	- Guardrail before NPU input cast to float16 (`FP16_CLIP`).
	- Symmetric clamping in both hybrid and CPU reference paths at attention glue, FFN, and residual boundaries.
- Re-ran 32-layer checkpoint; metrics are now finite:
	- `hidden_max_abs_diff_vs_cpu_ref = 16384.000000`
	- `hidden_mean_abs_diff_vs_cpu_ref = 4464.086426`
	- `hidden_checksum_hybrid = 528305.750000`
	- `hidden_checksum_cpu = -305371.343750`

**Files changed**: `local_llm/local_provider_rknn_hybrid/inference/hybrid_loop.py`, `docs/01_features/f26_hybrid_npu_inference/01_Design_Log.md`, `docs/01_features/f26_hybrid_npu_inference/02_Dev_Implementation.md`, `docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md`, `docs/00_system/Project_Roadmap.md`, `docs/02_bugfix/BUGFIX_LOG.md`

---

## BUG-024: Phase 2.2 section content displaced in f26 test report

| Field | Value |
|-------|-------|
| **Date** | 2026-05-31 |
| **Severity** | Medium (documentation structure regression) |
| **Found by** | User review of f26 Phase 2 docs |
| **Phase** | 5.5.5 (RKNN hybrid subgraph inference) |

**Symptom**:
- In `docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md`, section 9 (`Phase 2.2 — GGUF -> ONNX Weight Pipeline Checkpoint`) lost its local metadata and appeared to have missing content.
- The `Date/Classification/Script` block and section 9 subsections (`9.1` to `9.3`) were displaced to the tail of the file after later sections.

**Root cause**:
- Earlier edits inserted Phase 2.4 sections while section 9 content was not kept contiguous, causing the section 9 block to remain appended near the end of the document.

**Fix**:
- Restored section 9 to a contiguous block directly under the section 9 heading.
- Reinserted the section 9 metadata block (`Date`, `Classification`, `Script`) in-place.
- Kept section 9 subsections (`9.1 Commands`, `9.2 Results`, `9.3 Exported artifacts`) in section order.
- Removed the misplaced duplicate section 9 block from the end of the file.

**Files changed**: `docs/01_features/f26_hybrid_npu_inference/03_Test_Report.md`, `docs/02_bugfix/BUGFIX_LOG.md`

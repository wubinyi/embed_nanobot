# Bug Fix Log

> Tracks all bug fixes discovered during hardware integration testing.
> Each entry records the symptom, root cause, fix, and affected files
> so future sessions can quickly understand what changed and why.

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

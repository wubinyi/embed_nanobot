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

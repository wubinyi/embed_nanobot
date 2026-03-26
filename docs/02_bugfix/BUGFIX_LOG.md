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

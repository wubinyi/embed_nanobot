# boot_manager.py — Dual-partition boot manager for ESP32 (task 5.2.1).
#
# Manages a core/app partition layout on the ESP32 filesystem:
#   Core partition (read-only):  Main mesh client modules (main.py, transport.py, etc.)
#   App partition  (read-write): Hub-deployed application code (app.py)
#
# Boot sequence:
#   1. Check if app.py exists
#   2. Verify app hash matches app_meta.json
#   3. Execute app (import + call setup/loop or main)
#   4. If app crashes: increment crash_count in NVS
#   5. If crash_count >= max_crash: rollback to last-known-good
#
# The boot_manager also sends PARTITION_REPORT to the hub after each boot,
# reporting core version, app version, boot state, and crash count.
#
# MicroPython rules: no typing, no | union, no dataclasses, no _ in numbers.

import json
import os
import time

try:
    import hashlib
except ImportError:
    hashlib = None


# Boot states
STATE_NORMAL = "normal"
STATE_CRASH_LOOP = "crash_loop"
STATE_ROLLBACK = "rollback"
STATE_BARE = "bare"

# Paths
APP_PATH = "app.py"
APP_META_PATH = "app_meta.json"
APP_BACKUP_PATH = "app_backup.py"
APP_BACKUP_META_PATH = "app_backup_meta.json"
CRASH_STATE_PATH = "boot_state.json"

# Default crash threshold before rollback
DEFAULT_MAX_CRASHES = 3


def _file_exists(path):
    """Check if a file exists (MicroPython-compatible)."""
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _read_json(path):
    """Read a JSON file, return dict or None on failure."""
    try:
        f = open(path, "r")
        data = json.load(f)
        f.close()
        return data
    except Exception:
        return None


def _write_json(path, data):
    """Write a dict as JSON to a file."""
    try:
        f = open(path, "w")
        f.write(json.dumps(data))
        f.close()
        return True
    except Exception:
        return False


def _sha256_file(path):
    """Compute SHA-256 hex digest of a file. Returns '' if hashlib unavailable."""
    if hashlib is None:
        return ""
    try:
        h = hashlib.sha256()
        f = open(path, "rb")
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            h.update(chunk)
        f.close()
        return "".join("{:02x}".format(b) for b in h.digest())
    except Exception:
        return ""


def _copy_file(src, dst):
    """Copy a file on the filesystem."""
    try:
        fin = open(src, "rb")
        fout = open(dst, "wb")
        while True:
            chunk = fin.read(1024)
            if not chunk:
                break
            fout.write(chunk)
        fin.close()
        fout.close()
        return True
    except Exception:
        return False


def _remove_file(path):
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Crash state management (persisted to boot_state.json)
# ---------------------------------------------------------------------------


def load_boot_state():
    """Load boot state from flash. Returns dict with crash_count and boot_state."""
    data = _read_json(CRASH_STATE_PATH)
    if data is None:
        data = {"crash_count": 0, "boot_state": STATE_BARE, "boot_ts": 0}
    return data


def save_boot_state(state):
    """Persist boot state to flash."""
    _write_json(CRASH_STATE_PATH, state)


def increment_crash():
    """Record an app crash. Returns updated state dict."""
    state = load_boot_state()
    state["crash_count"] = state.get("crash_count", 0) + 1
    state["boot_state"] = STATE_NORMAL
    if state["crash_count"] >= DEFAULT_MAX_CRASHES:
        state["boot_state"] = STATE_CRASH_LOOP
    save_boot_state(state)
    return state


def reset_crash_count():
    """Reset crash counter after successful app run."""
    state = load_boot_state()
    state["crash_count"] = 0
    state["boot_state"] = STATE_NORMAL
    save_boot_state(state)
    return state


# ---------------------------------------------------------------------------
# App partition management
# ---------------------------------------------------------------------------


def get_app_meta():
    """Read app_meta.json. Returns dict or None."""
    return _read_json(APP_META_PATH)


def set_app_meta(version, sha256, deployed_at=0, firmware_hmac="", version_counter=0):
    """Write app_meta.json."""
    if deployed_at == 0:
        deployed_at = time.time()
    data = {
        "version": version,
        "sha256": sha256,
        "deployed_at": deployed_at,
        "firmware_hmac": firmware_hmac,
        "version_counter": version_counter,
    }
    return _write_json(APP_META_PATH, data)


def verify_app():
    """Verify app.py integrity against app_meta.json.

    Returns (ok, reason) tuple. ok is True if app is valid.
    """
    if not _file_exists(APP_PATH):
        return False, "no app.py"

    meta = get_app_meta()
    if meta is None:
        return False, "no app_meta.json"

    expected_hash = meta.get("sha256", "")
    if not expected_hash:
        # No hash to check — treat as valid (legacy deploy)
        return True, "no hash, skipping verification"

    actual_hash = _sha256_file(APP_PATH)
    if not actual_hash:
        # hashlib not available — skip verification
        return True, "hashlib unavailable, skipping"

    if actual_hash != expected_hash:
        return False, "hash mismatch: expected {} got {}".format(expected_hash[:8], actual_hash[:8])

    return True, "ok"


def backup_current_app():
    """Backup the current app.py as the last-known-good version."""
    if not _file_exists(APP_PATH):
        return False
    _copy_file(APP_PATH, APP_BACKUP_PATH)
    if _file_exists(APP_META_PATH):
        _copy_file(APP_META_PATH, APP_BACKUP_META_PATH)
    return True


def rollback_app():
    """Restore last-known-good app from backup.

    Returns True if rollback was performed.
    """
    if not _file_exists(APP_BACKUP_PATH):
        # No backup — remove corrupted app, go bare
        _remove_file(APP_PATH)
        _remove_file(APP_META_PATH)
        state = load_boot_state()
        state["boot_state"] = STATE_BARE
        state["crash_count"] = 0
        save_boot_state(state)
        return False

    _copy_file(APP_BACKUP_PATH, APP_PATH)
    if _file_exists(APP_BACKUP_META_PATH):
        _copy_file(APP_BACKUP_META_PATH, APP_META_PATH)

    state = load_boot_state()
    state["boot_state"] = STATE_ROLLBACK
    state["crash_count"] = 0
    save_boot_state(state)
    return True


# ---------------------------------------------------------------------------
# Firmware signature verification (task 5.2.2)
# ---------------------------------------------------------------------------


def verify_firmware_hmac(firmware_path, version_counter, psk, expected_hmac):
    """Verify HMAC-SHA256 of firmware file using PSK.

    HMAC covers: file_data + version_counter (4-byte big-endian).
    Returns True if valid.
    """
    if not expected_hmac or not psk:
        return True  # No HMAC to check — legacy deploy

    try:
        import security
        # Read firmware data
        f = open(firmware_path, "rb")
        fw_data = f.read()
        f.close()

        # Build HMAC input: firmware + version counter (4-byte BE)
        counter_bytes = bytes([
            (version_counter >> 24) & 0xff,
            (version_counter >> 16) & 0xff,
            (version_counter >> 8) & 0xff,
            version_counter & 0xff,
        ])
        mac_input = fw_data + counter_bytes

        # Compute HMAC using the security module's hmac_sha256
        computed = security.hmac_sha256(psk, mac_input)
        computed_hex = "".join("{:02x}".format(b) for b in computed)

        return computed_hex == expected_hmac
    except Exception as e:
        print("[boot_mgr] HMAC verify error:", e)
        return False


def check_anti_rollback(new_counter):
    """Check if a firmware version counter is allowed (anti-rollback).

    Returns True if the new counter is greater than the current one.
    """
    meta = get_app_meta()
    if meta is None:
        return True  # No app installed — any version is fine
    current = meta.get("version_counter", 0)
    return new_counter > current


# ---------------------------------------------------------------------------
# Partition report (for sending to Hub)
# ---------------------------------------------------------------------------


def build_partition_report(core_version="1.0.0"):
    """Build a dict suitable for PARTITION_REPORT payload."""
    state = load_boot_state()
    meta = get_app_meta()

    report = {
        "core_version": core_version,
        "core_hash": "",
        "app_version": "",
        "app_hash": "",
        "boot_state": state.get("boot_state", STATE_BARE),
        "crash_count": state.get("crash_count", 0),
    }

    if meta:
        report["app_version"] = meta.get("version", "")
        report["app_hash"] = meta.get("sha256", "")

    return report


# ---------------------------------------------------------------------------
# Boot sequence
# ---------------------------------------------------------------------------


def boot_app():
    """Execute the app partition if valid.

    Returns True if app was loaded successfully. Returns False if no app,
    verification failed, or crash threshold exceeded.

    This function is called from boot.py/main.py AFTER mesh client starts.
    """
    state = load_boot_state()

    # If in crash loop, attempt rollback
    if state.get("boot_state") == STATE_CRASH_LOOP:
        print("[boot_mgr] Crash loop detected — attempting rollback")
        if rollback_app():
            print("[boot_mgr] Rolled back to last-known-good app")
        else:
            print("[boot_mgr] No backup available — running bare (core only)")
            return False

    if not _file_exists(APP_PATH):
        state["boot_state"] = STATE_BARE
        save_boot_state(state)
        return False

    # Verify app integrity
    ok, reason = verify_app()
    if not ok:
        print("[boot_mgr] App verification failed: " + reason)
        # Don't increment crash — it's a hash mismatch, not a runtime crash
        _remove_file(APP_PATH)
        _remove_file(APP_META_PATH)
        state["boot_state"] = STATE_BARE
        state["crash_count"] = 0
        save_boot_state(state)
        return False

    # Mark boot attempt (crash counter incremented BEFORE app runs)
    state["crash_count"] = state.get("crash_count", 0) + 1
    state["boot_state"] = STATE_NORMAL
    state["boot_ts"] = time.time()
    save_boot_state(state)

    try:
        print("[boot_mgr] Loading app.py...")
        # Dynamic import of app module
        import app as app_module
        if hasattr(app_module, "setup"):
            app_module.setup()
        if hasattr(app_module, "main"):
            app_module.main()
        # If we get here, app ran successfully — reset crash counter
        reset_crash_count()
        return True
    except Exception as e:
        print("[boot_mgr] App crashed: " + str(e))
        state = load_boot_state()
        if state.get("crash_count", 0) >= DEFAULT_MAX_CRASHES:
            print("[boot_mgr] Max crashes exceeded — entering crash loop state")
            state["boot_state"] = STATE_CRASH_LOOP
            save_boot_state(state)
        return False

# sdk.py  --  ESP32 core partition SDK (task 5.2.5)
#
# This module is the PUBLIC API for app-partition code.
# Apps should import sdk and use its functions rather than
# importing core modules (transport, protocol, security, etc.)
# directly.
#
# Core modules (stable, rarely updated via core OTA):
#   config, security, protocol, enrollment, transport,
#   boot_manager, device, sdk
#
# App partition (updated frequently via app OTA):
#   app.py  +  app_meta.json  +  app_backup.py
#
# MicroPython rules: no typing, no |, no ** dict, no _ in numbers

CORE_VERSION = "1.0.0"

# List of files that constitute the core partition.
# deploy.sh uses this to know what to push, and
# boot_manager uses it for integrity verification.
CORE_FILES = [
    "config.py",
    "security.py",
    "protocol.py",
    "enrollment.py",
    "transport.py",
    "boot_manager.py",
    "device.py",
    "main.py",
    "boot.py",
    "sdk.py",
]

# ---- re-exports from core ------------------------------------------
# This avoids apps needing to know internal module structure.

def get_core_version():
    """Return core partition version string."""
    return CORE_VERSION


def get_device_state():
    """Return the full state report payload for this device."""
    import device
    return device.get_state_report_payload()


def execute_command(capability, action, value=None):
    """Execute a hardware command and return result dict.

    Parameters
    ----------
    capability : str
        Capability name (e.g. "led", "temperature").
    action : str
        One of "turn_on", "turn_off", "set_value", "read".
    value : optional
        Value for set_value action.

    Returns
    -------
    dict  with keys: ok (bool), capability, action, value, error
    """
    import device
    return device.execute_command(capability, action, value)


def get_config(key, default=None):
    """Read a config value by name.

    Parameters
    ----------
    key : str
        Attribute name in config.py (e.g. "NODE_ID", "HUB_IP").
    default : optional
        Value to return if key not found.
    """
    import config as cfg
    return getattr(cfg, key, default)


def send_message(transport, msg_type, target, payload):
    """Send a mesh message to the hub or another device.

    Parameters
    ----------
    transport : MeshTransport
        The transport instance (passed to app on init).
    msg_type : str
        Message type string (e.g. "state_report").
    target : str
        Target node_id or "hub".
    payload : dict
        Message payload.
    """
    transport.send(msg_type, target, payload)


def get_psk():
    """Load the pre-shared key from flash. Returns bytes or None."""
    import security
    return security.load_psk()


def is_enrolled():
    """Check if this device has a PSK (i.e. is enrolled)."""
    import security
    return security.psk_exists()


def get_partition_report():
    """Build a partition report dict for this device."""
    import boot_manager
    return boot_manager.build_partition_report(CORE_VERSION)


def verify_core_integrity():
    """Check that all core files exist on the filesystem.

    Returns
    -------
    dict with keys: ok (bool), missing (list of missing files)
    """
    import os
    missing = []
    for f in CORE_FILES:
        try:
            os.stat(f)
        except OSError:
            missing.append(f)
    result = {}
    result["ok"] = len(missing) == 0
    result["missing"] = missing
    return result


def get_core_file_hashes():
    """Compute SHA-256 hashes for all core files.

    Returns dict mapping filename to hex hash string.
    Missing files are skipped.
    """
    import hashlib
    import os
    hashes = {}
    for f in CORE_FILES:
        try:
            os.stat(f)
        except OSError:
            continue
        h = hashlib.sha256()
        fh = open(f, "rb")
        while True:
            chunk = fh.read(512)
            if not chunk:
                break
            h.update(chunk)
        fh.close()
        hashes[f] = h.digest().hex()
    return hashes

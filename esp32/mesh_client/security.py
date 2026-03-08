"""security.py — HMAC-SHA256 signing and PSK persistence for ESP32.

PSK is stored to flash as /psk.bin (32 raw bytes).
On first boot the PSK file does not exist; enrollment.py obtains a PSK
from the hub and then calls save_psk().
"""

import hashlib
import hmac
import ubinascii

_PSK_PATH = "/psk.bin"


# ----------------------------------------------------------------------
# HMAC signing
# ----------------------------------------------------------------------

def sign_envelope(envelope: dict, psk: bytes) -> str:
    """Return HMAC-SHA256 hex digest for the given envelope.

    Signing input mirrors nanobot/mesh/security.py:
        "<type>:<source>:<target>:<ts>:<nonce>"
    """
    msg = "{}:{}:{}:{}:{}".format(
        envelope["type"],
        envelope["source"],
        envelope["target"],
        envelope["ts"],
        envelope["nonce"],
    ).encode("utf-8")
    digest = hmac.new(psk, msg, hashlib.sha256).digest()
    return ubinascii.hexlify(digest).decode()


def verify_envelope(envelope: dict, psk: bytes) -> bool:
    """Return True if the envelope's HMAC is valid."""
    expected = sign_envelope(envelope, psk)
    provided = envelope.get("hmac", "")
    # Constant-time comparison (MicroPython does not have hmac.compare_digest)
    if len(expected) != len(provided):
        return False
    result = 0
    for a, b in zip(expected, provided):
        result |= ord(a) ^ ord(b)
    return result == 0


# ----------------------------------------------------------------------
# PSK persistence
# ----------------------------------------------------------------------

def save_psk(psk: bytes) -> None:
    """Write PSK to flash. Call this once after successful enrollment."""
    with open(_PSK_PATH, "wb") as f:
        f.write(psk)


def load_psk() -> bytes | None:
    """Load PSK from flash. Returns None if not yet enrolled."""
    try:
        with open(_PSK_PATH, "rb") as f:
            return f.read(32)
    except OSError:
        return None


def psk_exists() -> bool:
    """True if a PSK has been stored on this device."""
    try:
        import os
        os.stat(_PSK_PATH)
        return True
    except OSError:
        return False

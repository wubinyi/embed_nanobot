"""security.py — HMAC-SHA256 signing and PSK persistence for ESP32.

PSK is stored to flash as /psk.bin (32 raw bytes).
On first boot the PSK file does not exist; enrollment.py obtains a PSK
from the hub and then calls save_psk().
"""

import hashlib
import ubinascii

_PSK_PATH = "/psk.bin"
_SHA256_BLOCK = 64  # SHA-256 block size in bytes


# ----------------------------------------------------------------------
# HMAC-SHA256 (manual — MicroPython has no hmac module)
# ----------------------------------------------------------------------

def hmac_sha256(key, msg):
    """Compute HMAC-SHA256(key, msg) and return raw digest bytes."""
    if len(key) > _SHA256_BLOCK:
        key = hashlib.sha256(key).digest()
    key = key + b'\x00' * (_SHA256_BLOCK - len(key))
    o_pad = bytes(b ^ 0x5C for b in key)
    i_pad = bytes(b ^ 0x36 for b in key)
    inner = hashlib.sha256(i_pad + msg).digest()
    return hashlib.sha256(o_pad + inner).digest()

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
    digest = hmac_sha256(psk, msg)
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


def load_psk():
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

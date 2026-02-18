"""AES-256-GCM encryption for LAN mesh message payloads.

Provides payload encryption and decryption using per-device Pre-Shared Keys.
The encryption key is derived from the PSK via HMAC-SHA256 to ensure
cryptographic key separation between authentication (raw PSK → HMAC) and
encryption (derived key → AES-GCM).

Security model
--------------
- Each device's 32-byte PSK yields a separate 256-bit AES key via
  ``HMAC-SHA256(key=PSK, msg=b"mesh-encrypt-v1")``.
- Every message uses a fresh random 96-bit nonce/IV.
- AES-GCM provides *authenticated encryption*: ciphertext + 128-bit tag.
- Envelope metadata (type, source, target, ts) is included as AAD
  (Additional Authenticated Data), binding the ciphertext to its context.
- Combined with the existing HMAC signature (Encrypt-then-MAC), this gives
  defence-in-depth against passive eavesdropping and active tampering.

Dependencies
------------
Requires the ``cryptography`` package (``pip install cryptography``).
If unavailable, encryption is silently disabled and a warning is logged.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from typing import Any

from loguru import logger

# ------------------------------------------------------------------
# Optional dependency – graceful degradation when not installed.
# ------------------------------------------------------------------
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_AESGCM = True
except ImportError:
    HAS_AESGCM = False
    logger.warning(
        "[Mesh/Encryption] cryptography package not installed — "
        "mesh encryption unavailable. Install with: pip install cryptography"
    )

# Domain separator for key derivation.  Changing this value rotates all
# derived encryption keys without touching the underlying PSKs.
_ENC_KEY_INFO = b"mesh-encrypt-v1"


# ------------------------------------------------------------------
# Key derivation
# ------------------------------------------------------------------

def derive_encryption_key(psk_hex: str) -> bytes:
    """Derive a 256-bit AES key from a hex-encoded PSK.

    Uses ``HMAC-SHA256(key=PSK, msg=context)`` as a PRF for key separation:
    the raw PSK is reserved for HMAC authentication, while the derived key
    is used exclusively for AES-GCM.
    """
    psk_bytes = bytes.fromhex(psk_hex)
    return _hmac.new(psk_bytes, _ENC_KEY_INFO, hashlib.sha256).digest()


# ------------------------------------------------------------------
# AAD construction
# ------------------------------------------------------------------

def build_aad(msg_type: str, source: str, target: str, ts: float) -> bytes:
    """Build Additional Authenticated Data from envelope metadata.

    This binds the ciphertext to the envelope context so that an attacker
    cannot move an encrypted payload into a different message.
    """
    return f"{msg_type}|{source}|{target}|{ts}".encode("utf-8")


# ------------------------------------------------------------------
# Encrypt / decrypt
# ------------------------------------------------------------------

def encrypt_payload(
    payload: dict[str, Any],
    psk_hex: str,
    msg_type: str,
    source: str,
    target: str,
    ts: float,
) -> tuple[str, str] | None:
    """Encrypt a payload dict with AES-256-GCM.

    Returns ``(encrypted_payload_hex, iv_hex)`` on success, or ``None``
    if the ``cryptography`` library is not installed.

    The returned *encrypted_payload_hex* contains both the ciphertext and
    the 16-byte GCM authentication tag (appended by AESGCM).
    """
    if not HAS_AESGCM:
        return None

    enc_key = derive_encryption_key(psk_hex)
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    iv = os.urandom(12)  # 96-bit nonce — recommended for GCM
    aad = build_aad(msg_type, source, target, ts)

    aesgcm = AESGCM(enc_key)
    ciphertext = aesgcm.encrypt(iv, plaintext, aad)  # ciphertext + tag

    return ciphertext.hex(), iv.hex()


def decrypt_payload(
    encrypted_payload_hex: str,
    iv_hex: str,
    psk_hex: str,
    msg_type: str,
    source: str,
    target: str,
    ts: float,
) -> dict[str, Any] | None:
    """Decrypt an AES-256-GCM encrypted payload.

    Returns the decrypted payload dict, or ``None`` on failure (wrong key,
    tampered ciphertext, or missing library).
    """
    if not HAS_AESGCM:
        logger.error(
            "[Mesh/Encryption] cannot decrypt — cryptography package not installed"
        )
        return None

    try:
        enc_key = derive_encryption_key(psk_hex)
        ciphertext = bytes.fromhex(encrypted_payload_hex)
        iv = bytes.fromhex(iv_hex)
        aad = build_aad(msg_type, source, target, ts)

        aesgcm = AESGCM(enc_key)
        plaintext = aesgcm.decrypt(iv, ciphertext, aad)

        return json.loads(plaintext)
    except Exception as exc:
        logger.warning(f"[Mesh/Encryption] decryption failed: {exc}")
        return None


# ------------------------------------------------------------------
# Availability check
# ------------------------------------------------------------------

def is_available() -> bool:
    """Return ``True`` if AES-GCM encryption is available."""
    return HAS_AESGCM

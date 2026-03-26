"""enrollment.py — One-time PIN enrollment to obtain a PSK from the Hub.

This module is only used on the FIRST boot (or after factory reset).
After a PSK is obtained and saved to flash, enrollment is never run again.

Enrollment protocol (mirrors nanobot/mesh/enrollment.py on the hub):
  1. Client sends ENROLL_REQUEST with:
       pin_proof = HMAC-SHA256(pin_bytes, node_id_bytes)
       node_id   = this device's NODE_ID
  2. Hub replies ENROLL_RESPONSE with:
       success        = True / False
       encrypted_psk  = hex(XOR(psk, PBKDF2(pin, salt, 100k iters)))
       salt           = hex(16 random bytes)
       error          = str (on failure)
  3. Client decrypts PSK and saves it with security.save_psk().
"""

import hashlib
import ubinascii

from protocol import build_envelope, encode, decode
import security
from security import hmac_sha256


_PBKDF2_ITERS = 1000


def _pbkdf2_sha256(password, salt, iterations, dklen=32):
    """PBKDF2-HMAC-SHA256 (manual — MicroPython has no hashlib.pbkdf2_hmac).

    Only supports dklen <= 32 (single block).
    """
    u = hmac_sha256(password, salt + b'\x00\x00\x00\x01')
    result = u
    for _ in range(iterations - 1):
        u = hmac_sha256(password, u)
        result = bytes(a ^ b for a, b in zip(result, u))
    return result[:dklen]


def _pin_proof(pin: str, node_id: str) -> str:
    """Compute HMAC-SHA256(pin_bytes, node_id_bytes) as hex string."""
    digest = hmac_sha256(pin.encode(), node_id.encode())
    return ubinascii.hexlify(digest).decode()


def _decrypt_psk(encrypted_psk_hex: str, salt_hex: str, pin: str) -> bytes:
    """XOR-decrypt the hub-provided PSK using a PBKDF2-derived key."""
    enc_psk = ubinascii.unhexlify(encrypted_psk_hex)
    salt    = ubinascii.unhexlify(salt_hex)
    dk      = _pbkdf2_sha256(pin.encode(), salt, _PBKDF2_ITERS, 32)
    psk     = bytes(a ^ b for a, b in zip(enc_psk, dk))
    return psk


def enroll(sock, node_id: str, pin: str) -> bytes:
    """Perform enrollment over *sock* using *pin*.

    Returns the decrypted PSK on success.
    Raises RuntimeError on failure.
    """
    print("[enroll] Sending ENROLL_REQUEST for node:", node_id)
    proof = _pin_proof(pin, node_id)
    env = build_envelope(
        msg_type="enroll_request",
        source=node_id,
        target="hub",
        payload={"pin_proof": proof, "node_id": node_id},
        psk=None,   # no PSK yet — unsigned request
    )
    sock.sendall(encode(env))

    resp = decode(sock)
    if resp.get("type") != "enroll_response":
        raise RuntimeError("Unexpected response type: " + str(resp.get("type")))

    payload = resp.get("payload", {})
    if payload.get("status") != "ok":
        raise RuntimeError("Enrollment rejected: " + str(payload.get("reason", "unknown")))

    psk = _decrypt_psk(payload["encrypted_psk"], payload["salt"], pin)
    print("[enroll] PSK received, length:", len(psk))

    # Persist to flash so we never need a PIN again
    security.save_psk(psk)
    print("[enroll] PSK saved to flash")
    return psk

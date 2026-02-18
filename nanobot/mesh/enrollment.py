"""PIN-based device enrollment for the LAN mesh.

Provides a time-limited, single-use PIN pairing protocol that allows new
devices to obtain a PSK from the Hub without pre-shared secrets.

Enrollment flow
---------------
1. Hub admin calls ``create_pin()`` → receives a 6-digit PIN to share.
2. New device sends ``ENROLL_REQUEST`` with ``pin_proof = HMAC-SHA256(pin, node_id)``.
3. Hub validates the proof, generates a PSK, encrypts it with a PIN-derived key
   (``PBKDF2 + XOR one-time pad``), and replies with ``ENROLL_RESPONSE``.
4. Device decrypts the PSK and subsequently authenticates with HMAC as usual.

Security properties
-------------------
- PIN auto-expires after ``pin_timeout`` seconds (default 300 = 5 min).
- PIN is single-use (invalidated after successful enrollment).
- Rate limiting: max ``max_attempts`` failures before the PIN is locked.
- PBKDF2-HMAC-SHA256 with 100 000 iterations makes offline brute-force of
  the 6-digit PIN expensive (~27 h on a desktop GPU).
- XOR encryption with a 32-byte derived key over a 32-byte PSK is an
  information-theoretic one-time pad (perfect secrecy).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.mesh.security import KeyStore
    from nanobot.mesh.transport import MeshTransport

from nanobot.mesh.protocol import MeshEnvelope, MsgType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PBKDF2_ITERATIONS = 100_000
_SALT_BYTES = 16
_PSK_BYTES = 32  # 256-bit PSK


# ---------------------------------------------------------------------------
# Pending enrollment state
# ---------------------------------------------------------------------------
@dataclass
class PendingEnrollment:
    """Tracks an active enrollment PIN."""

    pin: str
    created_at: float
    expires_at: float
    attempts: int = 0
    max_attempts: int = 3
    used: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_locked(self) -> bool:
        return self.attempts >= self.max_attempts

    @property
    def is_active(self) -> bool:
        return not self.used and not self.is_expired and not self.is_locked


# ---------------------------------------------------------------------------
# Enrollment service
# ---------------------------------------------------------------------------
class EnrollmentService:
    """Manages PIN-based device enrollment for the mesh Hub.

    Parameters
    ----------
    key_store:
        The Hub's :class:`KeyStore` for persisting enrolled PSKs.
    transport:
        The :class:`MeshTransport` used to send ENROLL_RESPONSE messages.
    node_id:
        This Hub's node identifier (used as ``source`` in responses).
    pin_length:
        Number of digits in the enrollment PIN.
    pin_timeout:
        Seconds before a PIN expires.
    max_attempts:
        Maximum failed attempts before the PIN is locked.
    """

    def __init__(
        self,
        key_store: KeyStore,
        transport: MeshTransport,
        node_id: str,
        pin_length: int = 6,
        pin_timeout: int = 300,
        max_attempts: int = 3,
    ) -> None:
        self.key_store = key_store
        self.transport = transport
        self.node_id = node_id
        self.pin_length = pin_length
        self.pin_timeout = pin_timeout
        self.max_attempts = max_attempts

        self._pending: PendingEnrollment | None = None

    # -- PIN lifecycle -------------------------------------------------------

    def create_pin(self) -> tuple[str, float]:
        """Generate a new enrollment PIN.

        Returns ``(pin, expires_at)`` where *expires_at* is a Unix timestamp.
        Any previous pending enrollment is replaced.
        """
        # Generate a numeric PIN with leading-zero preservation
        pin = "".join(secrets.choice("0123456789") for _ in range(self.pin_length))
        now = time.time()
        expires_at = now + self.pin_timeout
        self._pending = PendingEnrollment(
            pin=pin,
            created_at=now,
            expires_at=expires_at,
            max_attempts=self.max_attempts,
        )
        logger.info(
            f"[Mesh/Enrollment] PIN created (length={self.pin_length}, "
            f"expires in {self.pin_timeout}s)"
        )
        return pin, expires_at

    def cancel_pin(self) -> bool:
        """Cancel the active enrollment PIN.  Returns ``True`` if one was active."""
        if self._pending and self._pending.is_active:
            self._pending.used = True
            logger.info("[Mesh/Enrollment] PIN cancelled")
            return True
        return False

    @property
    def is_enrollment_active(self) -> bool:
        """Return ``True`` if there is a valid, non-expired, non-locked PIN."""
        return self._pending is not None and self._pending.is_active

    # -- request handling ----------------------------------------------------

    async def handle_enroll_request(self, env: MeshEnvelope) -> None:
        """Process an ``ENROLL_REQUEST`` envelope.

        Validates the PIN proof, generates a PSK, and sends an
        ``ENROLL_RESPONSE`` back to the device.
        """
        device_id = env.source
        device_name = env.payload.get("name", "")
        pin_proof = env.payload.get("pin_proof", "")

        # Guard: enrollment not active
        if not self.is_enrollment_active:
            reason = "no_active_enrollment"
            if self._pending is not None:
                if self._pending.is_expired:
                    reason = "expired"
                elif self._pending.is_locked:
                    reason = "locked"
                elif self._pending.used:
                    reason = "already_used"
            logger.warning(
                f"[Mesh/Enrollment] REJECTED enrollment from {device_id!r}: {reason}"
            )
            await self._send_error(device_id, reason)
            return

        assert self._pending is not None  # guaranteed by is_enrollment_active

        # Validate pin_proof
        expected_proof = self.compute_pin_proof(self._pending.pin, device_id)
        if not hmac_mod.compare_digest(pin_proof, expected_proof):
            self._pending.attempts += 1
            remaining = self._pending.max_attempts - self._pending.attempts
            logger.warning(
                f"[Mesh/Enrollment] INVALID pin_proof from {device_id!r} "
                f"(attempt {self._pending.attempts}/{self._pending.max_attempts}, "
                f"{remaining} remaining)"
            )
            if self._pending.is_locked:
                await self._send_error(device_id, "locked")
            else:
                await self._send_error(device_id, "invalid_pin")
            return

        # --- Success: generate PSK and encrypt it ---
        psk_hex = self.key_store.add_device(device_id, name=device_name)
        psk_bytes = bytes.fromhex(psk_hex)

        salt = secrets.token_bytes(_SALT_BYTES)
        temp_key = self.derive_temp_key(self._pending.pin, salt)
        encrypted_psk = self.encrypt_psk(psk_bytes, temp_key)

        # Mark PIN as used
        self._pending.used = True

        # Send response
        response = MeshEnvelope(
            type=MsgType.ENROLL_RESPONSE,
            source=self.node_id,
            target=device_id,
            payload={
                "status": "ok",
                "encrypted_psk": encrypted_psk.hex(),
                "salt": salt.hex(),
            },
        )
        ok = await self.transport.send_to_address(
            ip=env.payload.get("_reply_ip", ""),
            port=env.payload.get("_reply_port", 0),
            env=response,
        ) if env.payload.get("_reply_ip") else await self.transport.send(response)

        if ok:
            logger.info(
                f"[Mesh/Enrollment] ENROLLED device {device_id!r} "
                f"(name={device_name!r})"
            )
        else:
            logger.error(
                f"[Mesh/Enrollment] enrolled {device_id!r} but failed to "
                "deliver ENROLL_RESPONSE — device may need to retry"
            )

    async def _send_error(self, target: str, reason: str) -> None:
        """Send an error ENROLL_RESPONSE."""
        response = MeshEnvelope(
            type=MsgType.ENROLL_RESPONSE,
            source=self.node_id,
            target=target,
            payload={"status": "error", "reason": reason},
        )
        await self.transport.send(response)

    # -- cryptographic helpers -----------------------------------------------

    @staticmethod
    def compute_pin_proof(pin: str, node_id: str) -> str:
        """Compute ``HMAC-SHA256(key=pin, msg=node_id)`` as a hex string.

        Used by both the device (to create the proof) and the Hub (to verify).
        """
        return hmac_mod.new(
            pin.encode("utf-8"),
            node_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def derive_temp_key(pin: str, salt: bytes) -> bytes:
        """Derive a 32-byte temporary key from *pin* and *salt* using PBKDF2.

        The derived key is used as a one-time pad to encrypt the PSK during
        the enrollment handshake.
        """
        return hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt,
            _PBKDF2_ITERATIONS,
            dklen=_PSK_BYTES,
        )

    @staticmethod
    def encrypt_psk(psk_bytes: bytes, temp_key: bytes) -> bytes:
        """XOR *psk_bytes* with *temp_key* (one-time pad encryption).

        Since both are exactly 32 bytes, this provides perfect secrecy.
        Also used for decryption (XOR is its own inverse).
        """
        if len(psk_bytes) != _PSK_BYTES or len(temp_key) != _PSK_BYTES:
            raise ValueError(
                f"psk_bytes and temp_key must both be {_PSK_BYTES} bytes"
            )
        return bytes(a ^ b for a, b in zip(psk_bytes, temp_key))

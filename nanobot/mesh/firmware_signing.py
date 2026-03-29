"""Firmware signing and verification for secure OTA (task 5.2.2).

Two layers of firmware authentication:

1. **EC P-256 signature** (hub-side only, for audit/accountability):
   - Hub signs firmware packages with its CA private key.
   - Signature stored alongside firmware in the store.
   - Requires ``cryptography`` library (already a dependency).

2. **HMAC-SHA256 signature** (transport-level, for device verification):
   - Hub computes HMAC of firmware data using the device's PSK.
   - Included in OTA_OFFER so the device can verify before writing.
   - Device already has the PSK — no additional keys needed.

Additionally implements:
- **Anti-rollback counter**: Monotonic version numbers per device.
  The hub refuses to deploy firmware with version ≤ device's current version.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
import time
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class FirmwareSignature:
    """Cryptographic signatures for a firmware package."""

    firmware_id: str
    sha256: str                     # Hex SHA-256 of firmware data
    ec_signature: str = ""          # Hex EC P-256 signature (hub audit)
    hmac_signatures: dict[str, str] = None  # node_id → HMAC-SHA256 hex (per-device)
    version_counter: int = 0        # Anti-rollback monotonic counter
    signed_at: float = 0.0

    def __post_init__(self) -> None:
        if self.hmac_signatures is None:
            self.hmac_signatures = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "firmware_id": self.firmware_id,
            "sha256": self.sha256,
            "ec_signature": self.ec_signature,
            "hmac_signatures": self.hmac_signatures,
            "version_counter": self.version_counter,
            "signed_at": self.signed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FirmwareSignature:
        return cls(
            firmware_id=d.get("firmware_id", ""),
            sha256=d.get("sha256", ""),
            ec_signature=d.get("ec_signature", ""),
            hmac_signatures=d.get("hmac_signatures", {}),
            version_counter=d.get("version_counter", 0),
            signed_at=d.get("signed_at", 0.0),
        )


class FirmwareSigner:
    """Signs firmware packages using the hub's CA key and per-device PSKs.

    Parameters
    ----------
    ca :
        MeshCA instance for EC P-256 signing (optional — if None, only HMAC is used).
    key_store :
        KeyStore instance for PSK-based HMAC signing.
    """

    def __init__(self, ca: Any = None, key_store: Any = None):
        self._ca = ca
        self._key_store = key_store
        self._ca_key = None
        if ca is not None:
            self._ca_key = self._load_ca_key()

    def _load_ca_key(self) -> Any:
        """Load the CA private key for firmware signing."""
        if self._ca is None:
            return None
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            key_path = self._ca.ca_key_path
            if not key_path.exists():
                return None
            key_data = key_path.read_bytes()
            return load_pem_private_key(key_data, password=None)
        except Exception as e:
            logger.warning("Could not load CA key for firmware signing: {}", e)
            return None

    def sign_firmware(
        self,
        firmware_id: str,
        firmware_data: bytes,
        version_counter: int = 0,
    ) -> FirmwareSignature:
        """Sign firmware data with the CA key (EC P-256).

        Returns a FirmwareSignature with the EC signature and SHA-256 hash.
        """
        sha256_hex = hashlib.sha256(firmware_data).hexdigest()

        ec_sig_hex = ""
        if self._ca_key is not None:
            ec_sig_hex = self._ec_sign(firmware_data)

        return FirmwareSignature(
            firmware_id=firmware_id,
            sha256=sha256_hex,
            ec_signature=ec_sig_hex,
            version_counter=version_counter,
            signed_at=time.time(),
        )

    def add_device_hmac(
        self,
        signature: FirmwareSignature,
        node_id: str,
        firmware_data: bytes,
    ) -> str:
        """Compute HMAC-SHA256 for a specific device using its PSK.

        The HMAC covers: firmware_data + version_counter (4-byte BE).
        This ties the signature to the specific firmware AND version,
        preventing replay of old firmware.

        Returns the HMAC hex string.
        """
        if self._key_store is None:
            return ""
        psk_hex = self._key_store.get_psk(node_id)
        if not psk_hex:
            return ""

        # HMAC input: firmware bytes + version counter (anti-rollback)
        counter_bytes = struct.pack(">I", signature.version_counter)
        mac_input = firmware_data + counter_bytes
        psk_bytes = bytes.fromhex(psk_hex)
        mac = hmac.new(psk_bytes, mac_input, hashlib.sha256).hexdigest()

        signature.hmac_signatures[node_id] = mac
        return mac

    def verify_ec_signature(
        self,
        firmware_data: bytes,
        ec_signature_hex: str,
    ) -> bool:
        """Verify EC P-256 signature (hub-side verification for audit)."""
        if not ec_signature_hex or self._ca is None:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric import ec as ec_module
            from cryptography.hazmat.primitives.hashes import SHA256
            from cryptography.x509 import load_pem_x509_certificate

            cert_path = self._ca.ca_cert_path
            if not cert_path.exists():
                return False
            cert_data = cert_path.read_bytes()
            cert = load_pem_x509_certificate(cert_data)
            public_key = cert.public_key()

            sig_bytes = bytes.fromhex(ec_signature_hex)
            public_key.verify(sig_bytes, firmware_data, ec_module.ECDSA(SHA256()))
            return True
        except Exception:
            return False

    @staticmethod
    def verify_device_hmac(
        firmware_data: bytes,
        version_counter: int,
        psk_hex: str,
        expected_hmac_hex: str,
    ) -> bool:
        """Verify HMAC-SHA256 of firmware data using a PSK.

        Can be used on both hub and device side.
        """
        if not psk_hex or not expected_hmac_hex:
            return False
        counter_bytes = struct.pack(">I", version_counter)
        mac_input = firmware_data + counter_bytes
        psk_bytes = bytes.fromhex(psk_hex)
        computed = hmac.new(psk_bytes, mac_input, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, expected_hmac_hex)

    def _ec_sign(self, data: bytes) -> str:
        """Sign data with EC P-256 private key. Returns hex signature."""
        try:
            from cryptography.hazmat.primitives.asymmetric import ec as ec_module
            from cryptography.hazmat.primitives.hashes import SHA256

            sig_bytes = self._ca_key.sign(data, ec_module.ECDSA(SHA256()))
            return sig_bytes.hex()
        except Exception as e:
            logger.warning("EC signing failed: {}", e)
            return ""


def check_anti_rollback(
    current_counter: int,
    new_counter: int,
) -> bool:
    """Check if a firmware version is allowed (anti-rollback).

    The new version counter must be strictly greater than the current one.
    Returns True if the update is allowed.
    """
    return new_counter > current_counter

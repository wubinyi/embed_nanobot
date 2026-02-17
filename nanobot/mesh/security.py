"""PSK-based authentication for LAN mesh transport.

Provides HMAC-SHA256 signing and verification of mesh envelopes using
per-device Pre-Shared Keys (PSKs).  Also manages the on-disk key store
and tracks nonces to prevent replay attacks.

Security model
--------------
- Each enrolled device shares a unique 32-byte PSK with the Hub.
- Every mesh envelope includes an HMAC-SHA256 signature computed over the
  canonical message body + nonce using the device's PSK.
- The Hub verifies the HMAC before processing any message.
- A random nonce and timestamp window guard against replay attacks.
- Unenrolled nodes are rejected at the transport layer.

This is Phase 1 security (simple, ESP32-friendly).  Phase 2 will upgrade
to mTLS with a local CA for production-grade device identity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class DeviceRecord:
    """Metadata for an enrolled device."""

    psk: str  # hex-encoded 32-byte key
    enrolled_at: str  # ISO-8601 timestamp
    name: str = ""  # human-friendly label


class KeyStore:
    """Manages per-device PSKs and provides HMAC sign/verify operations.

    The key store is persisted as a JSON file with restrictive permissions
    (``0600``).  In-memory nonce tracking prevents replay attacks within
    a configurable time window.

    Parameters
    ----------
    path:
        Filesystem path for the key store JSON file.
    nonce_window:
        Seconds within which a nonce must be unique (default 60).
    """

    def __init__(self, path: str | Path, nonce_window: int = 60) -> None:
        self.path = Path(path)
        self.nonce_window = nonce_window

        # node_id → DeviceRecord
        self._devices: dict[str, DeviceRecord] = {}

        # Replay protection: nonce → timestamp when first seen
        # OrderedDict for efficient pruning of oldest entries.
        self._seen_nonces: OrderedDict[str, float] = OrderedDict()

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Load the key store from disk.  No-op if the file doesn't exist."""
        if not self.path.exists():
            logger.debug(f"[Mesh/Security] key store not found at {self.path}, starting empty")
            return
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            for node_id, rec in raw.items():
                self._devices[node_id] = DeviceRecord(
                    psk=rec["psk"],
                    enrolled_at=rec.get("enrolled_at", ""),
                    name=rec.get("name", ""),
                )
            logger.info(f"[Mesh/Security] loaded {len(self._devices)} device(s) from {self.path}")
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.error(f"[Mesh/Security] failed to load key store: {exc}")

    def save(self) -> None:
        """Persist the key store to disk with ``0600`` permissions."""
        data = {
            node_id: {
                "psk": rec.psk,
                "enrolled_at": rec.enrolled_at,
                "name": rec.name,
            }
            for node_id, rec in self._devices.items()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # Windows doesn't support Unix permissions
        logger.debug(f"[Mesh/Security] saved {len(self._devices)} device(s) to {self.path}")

    # -- device management ---------------------------------------------------

    def add_device(self, node_id: str, name: str = "") -> str:
        """Enroll a device: generate a PSK, store it, and return the hex key.

        If the device already exists, its PSK is rotated.
        """
        psk_bytes = secrets.token_bytes(32)
        psk_hex = psk_bytes.hex()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._devices[node_id] = DeviceRecord(psk=psk_hex, enrolled_at=now, name=name)
        self.save()
        logger.info(f"[Mesh/Security] enrolled device {node_id!r} (name={name!r})")
        return psk_hex

    def remove_device(self, node_id: str) -> bool:
        """Revoke a device's PSK.  Returns True if it existed."""
        if node_id in self._devices:
            del self._devices[node_id]
            self.save()
            logger.info(f"[Mesh/Security] revoked device {node_id!r}")
            return True
        return False

    def get_psk(self, node_id: str) -> str | None:
        """Return the hex PSK for *node_id*, or ``None`` if not enrolled."""
        rec = self._devices.get(node_id)
        return rec.psk if rec else None

    def has_device(self, node_id: str) -> bool:
        """Check whether *node_id* is enrolled."""
        return node_id in self._devices

    def list_devices(self) -> dict[str, DeviceRecord]:
        """Return a copy of all enrolled devices."""
        return dict(self._devices)

    # -- HMAC operations (static helpers) ------------------------------------

    @staticmethod
    def generate_nonce() -> str:
        """Generate a random 16-character hex nonce."""
        return secrets.token_hex(8)

    @staticmethod
    def compute_hmac(canonical_body: bytes, nonce: str, psk_hex: str) -> str:
        """Compute HMAC-SHA256 over ``canonical_body + nonce`` using *psk_hex*.

        Returns the hex-encoded digest.
        """
        psk_bytes = bytes.fromhex(psk_hex)
        msg = canonical_body + nonce.encode("ascii")
        return hmac.new(psk_bytes, msg, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_hmac(canonical_body: bytes, nonce: str, psk_hex: str, hmac_hex: str) -> bool:
        """Verify an HMAC-SHA256 signature (constant-time comparison)."""
        expected = KeyStore.compute_hmac(canonical_body, nonce, psk_hex)
        return hmac.compare_digest(expected, hmac_hex)

    # -- canonical serialisation ---------------------------------------------

    @staticmethod
    def canonical_bytes(envelope_dict: dict[str, Any]) -> bytes:
        """Return the canonical JSON bytes for HMAC computation.

        Excludes ``hmac`` and ``nonce`` fields, then serialises with sorted
        keys for deterministic output.
        """
        filtered = {k: v for k, v in envelope_dict.items() if k not in ("hmac", "nonce")}
        return json.dumps(filtered, sort_keys=True, ensure_ascii=False).encode("utf-8")

    # -- nonce replay protection ---------------------------------------------

    def check_and_record_nonce(self, nonce: str) -> bool:
        """Return ``True`` if the nonce is fresh (not seen within the window).

        Also records the nonce and prunes stale entries.
        """
        self._prune_nonces()
        if nonce in self._seen_nonces:
            return False  # replay
        self._seen_nonces[nonce] = time.time()
        return True

    def _prune_nonces(self) -> None:
        """Remove nonces older than ``nonce_window`` seconds."""
        cutoff = time.time() - self.nonce_window
        # OrderedDict is insertion-ordered; prune from the front.
        while self._seen_nonces:
            oldest_nonce, oldest_ts = next(iter(self._seen_nonces.items()))
            if oldest_ts < cutoff:
                self._seen_nonces.pop(oldest_nonce)
            else:
                break

    # -- timestamp validation ------------------------------------------------

    def check_timestamp(self, ts: float) -> bool:
        """Return ``True`` if *ts* is within ``nonce_window`` of the current time."""
        return abs(time.time() - ts) <= self.nonce_window

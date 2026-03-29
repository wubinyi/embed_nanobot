"""Tests for nanobot.mesh.firmware_signing (task 5.2.2)."""

from __future__ import annotations

import hashlib
import hmac
import struct
from unittest.mock import MagicMock, PropertyMock

import pytest

from nanobot.mesh.firmware_signing import (
    FirmwareSignature,
    FirmwareSigner,
    check_anti_rollback,
)


# ---------------------------------------------------------------------------
# FirmwareSignature
# ---------------------------------------------------------------------------


class TestFirmwareSignature:
    def test_to_dict_round_trip(self):
        sig = FirmwareSignature(
            firmware_id="fw-01",
            sha256="abc123",
            ec_signature="def456",
            version_counter=5,
        )
        d = sig.to_dict()
        sig2 = FirmwareSignature.from_dict(d)
        assert sig2.firmware_id == "fw-01"
        assert sig2.sha256 == "abc123"
        assert sig2.ec_signature == "def456"
        assert sig2.version_counter == 5

    def test_default_hmac_signatures(self):
        sig = FirmwareSignature(firmware_id="fw-01", sha256="abc")
        assert sig.hmac_signatures == {}


# ---------------------------------------------------------------------------
# HMAC signing/verification
# ---------------------------------------------------------------------------


class TestHMACSigningNoCA:
    """Test HMAC-based firmware signing (no CA needed)."""

    def test_sign_firmware_sha256(self):
        signer = FirmwareSigner()
        data = b"print('hello')"
        sig = signer.sign_firmware("fw-01", data, version_counter=1)
        assert sig.sha256 == hashlib.sha256(data).hexdigest()
        assert sig.ec_signature == ""  # No CA
        assert sig.version_counter == 1

    def test_add_device_hmac(self):
        key_store = MagicMock()
        key_store.get_psk.return_value = "aa" * 32  # 32-byte key
        signer = FirmwareSigner(key_store=key_store)

        data = b"firmware data"
        sig = signer.sign_firmware("fw-01", data, version_counter=1)
        mac = signer.add_device_hmac(sig, "esp-01", data)

        assert mac != ""
        assert sig.hmac_signatures["esp-01"] == mac

    def test_add_device_hmac_no_psk(self):
        key_store = MagicMock()
        key_store.get_psk.return_value = None
        signer = FirmwareSigner(key_store=key_store)

        data = b"firmware data"
        sig = signer.sign_firmware("fw-01", data)
        mac = signer.add_device_hmac(sig, "unknown-device", data)
        assert mac == ""

    def test_verify_device_hmac(self):
        psk_hex = "bb" * 32
        data = b"firmware data"
        version_counter = 3

        # Compute expected HMAC
        counter_bytes = struct.pack(">I", version_counter)
        mac_input = data + counter_bytes
        psk_bytes = bytes.fromhex(psk_hex)
        expected = hmac.new(psk_bytes, mac_input, hashlib.sha256).hexdigest()

        assert FirmwareSigner.verify_device_hmac(data, version_counter, psk_hex, expected) is True

    def test_verify_device_hmac_wrong_counter(self):
        psk_hex = "bb" * 32
        data = b"firmware data"

        # Sign with counter=3
        counter_bytes = struct.pack(">I", 3)
        mac_input = data + counter_bytes
        psk_bytes = bytes.fromhex(psk_hex)
        mac = hmac.new(psk_bytes, mac_input, hashlib.sha256).hexdigest()

        # Verify with counter=4 — should fail
        assert FirmwareSigner.verify_device_hmac(data, 4, psk_hex, mac) is False

    def test_verify_device_hmac_wrong_data(self):
        psk_hex = "bb" * 32
        data = b"firmware data"

        counter_bytes = struct.pack(">I", 1)
        mac_input = data + counter_bytes
        psk_bytes = bytes.fromhex(psk_hex)
        mac = hmac.new(psk_bytes, mac_input, hashlib.sha256).hexdigest()

        # Verify with different data — should fail
        assert FirmwareSigner.verify_device_hmac(b"other", 1, psk_hex, mac) is False

    def test_verify_device_hmac_empty(self):
        assert FirmwareSigner.verify_device_hmac(b"data", 1, "", "abc") is False
        assert FirmwareSigner.verify_device_hmac(b"data", 1, "aa" * 32, "") is False

    def test_add_device_hmac_no_key_store(self):
        signer = FirmwareSigner()
        sig = FirmwareSignature(firmware_id="fw-01", sha256="abc")
        mac = signer.add_device_hmac(sig, "esp-01", b"data")
        assert mac == ""


# ---------------------------------------------------------------------------
# EC P-256 signing (requires cryptography library)
# ---------------------------------------------------------------------------


class TestECSigning:
    """Test EC P-256 firmware signing using a real CA."""

    @pytest.fixture
    def ca_with_key(self, tmp_path):
        """Create a real MeshCA with generated keys."""
        try:
            from nanobot.mesh.ca import MeshCA, is_available
            if not is_available():
                pytest.skip("cryptography not installed")
            ca = MeshCA(ca_dir=str(tmp_path / "ca"))
            ca.initialize()
            return ca
        except ImportError:
            pytest.skip("cryptography not installed")

    def test_ec_sign_and_verify(self, ca_with_key):
        signer = FirmwareSigner(ca=ca_with_key)
        data = b"print('hello world')"
        sig = signer.sign_firmware("fw-01", data, version_counter=1)

        assert sig.ec_signature != ""
        assert signer.verify_ec_signature(data, sig.ec_signature) is True

    def test_ec_verify_wrong_data(self, ca_with_key):
        signer = FirmwareSigner(ca=ca_with_key)
        data = b"firmware data"
        sig = signer.sign_firmware("fw-01", data)

        assert signer.verify_ec_signature(b"tampered", sig.ec_signature) is False

    def test_ec_verify_no_ca(self):
        signer = FirmwareSigner()
        assert signer.verify_ec_signature(b"data", "deadbeef") is False


# ---------------------------------------------------------------------------
# Anti-rollback
# ---------------------------------------------------------------------------


class TestAntiRollback:
    def test_allows_higher_version(self):
        assert check_anti_rollback(current_counter=1, new_counter=2) is True

    def test_blocks_same_version(self):
        assert check_anti_rollback(current_counter=2, new_counter=2) is False

    def test_blocks_lower_version(self):
        assert check_anti_rollback(current_counter=3, new_counter=1) is False

    def test_zero_to_one(self):
        assert check_anti_rollback(current_counter=0, new_counter=1) is True


# ---------------------------------------------------------------------------
# Integration: sign + HMAC + verify round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_full_sign_and_verify_flow(self):
        """Sign firmware, add device HMAC, verify both."""
        key_store = MagicMock()
        psk_hex = "cc" * 32
        key_store.get_psk.return_value = psk_hex

        signer = FirmwareSigner(key_store=key_store)
        data = b"def setup(): pass\ndef loop(): pass\n"

        # Sign
        sig = signer.sign_firmware("fw-sensor-v1", data, version_counter=1)

        # Add per-device HMAC
        mac = signer.add_device_hmac(sig, "esp-01", data)
        assert mac != ""

        # Verify
        assert FirmwareSigner.verify_device_hmac(data, 1, psk_hex, mac) is True

        # Anti-rollback: trying to install v0 should fail
        assert check_anti_rollback(current_counter=1, new_counter=0) is False
        # v2 should pass
        assert check_anti_rollback(current_counter=1, new_counter=2) is True

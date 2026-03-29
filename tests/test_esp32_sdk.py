"""Tests for esp32/mesh_client/sdk.py — Core partition SDK (task 5.2.5).

These tests run on the HOST (not on ESP32). Modules that rely on
MicroPython-only APIs (machine, usocket) are mocked.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test setup: make esp32/mesh_client importable
# ---------------------------------------------------------------------------

ESP32_DIR = str(Path(__file__).resolve().parent.parent / "esp32" / "mesh_client")

@pytest.fixture(autouse=True)
def _patch_sys_path():
    """Temporarily add esp32/mesh_client to sys.path."""
    original = sys.path.copy()
    sys.path.insert(0, ESP32_DIR)

    # Provide mock config module
    mock_config = types.ModuleType("config")
    mock_config.NODE_ID = "test-node"
    mock_config.HUB_IP = "192.168.0.1"
    mock_config.HUB_PORT = 18800
    mock_config.FIRMWARE_VERSION = "0.1.0"
    mock_config.CAPABILITIES = [{"name": "led", "type": "switch"}]
    mock_config.WIFI_SSID = "test"
    mock_config.WIFI_PASSWORD = "pass"
    mock_config.WIFI_TIMEOUT = 10
    mock_config.PING_INTERVAL_S = 30
    mock_config.RECONNECT_DELAY_S = 5
    sys.modules["config"] = mock_config

    # Mock MicroPython-only modules
    for mod_name in ("machine", "network", "ntptime", "usocket"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    yield

    sys.path = original
    # Clean up imported modules
    for mod in list(sys.modules):
        if mod in ("sdk", "security", "device", "boot_manager", "protocol", "config"):
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCoreVersion:
    def test_core_version_string(self):
        import sdk
        assert sdk.CORE_VERSION == "1.0.0"

    def test_get_core_version(self):
        import sdk
        assert sdk.get_core_version() == "1.0.0"


class TestCoreFiles:
    def test_core_files_list(self):
        import sdk
        assert "sdk.py" in sdk.CORE_FILES
        assert "security.py" in sdk.CORE_FILES
        assert "transport.py" in sdk.CORE_FILES
        assert "boot_manager.py" in sdk.CORE_FILES
        assert len(sdk.CORE_FILES) >= 9


class TestGetConfig:
    def test_get_existing_key(self):
        import sdk
        assert sdk.get_config("NODE_ID") == "test-node"

    def test_get_missing_key(self):
        import sdk
        assert sdk.get_config("NONEXISTENT", "default") == "default"


class TestIsEnrolled:
    def test_not_enrolled(self):
        mock_sec = MagicMock()
        mock_sec.psk_exists.return_value = False
        sys.modules["security"] = mock_sec
        # Force reimport
        if "sdk" in sys.modules:
            del sys.modules["sdk"]
        import sdk
        assert sdk.is_enrolled() is False

    def test_enrolled(self):
        mock_sec = MagicMock()
        mock_sec.psk_exists.return_value = True
        sys.modules["security"] = mock_sec
        if "sdk" in sys.modules:
            del sys.modules["sdk"]
        import sdk
        assert sdk.is_enrolled() is True


class TestVerifyCoreIntegrity:
    def test_with_real_files(self):
        """All CORE_FILES exist in the esp32/mesh_client dir — should pass."""
        # Temporarily mock os.stat to check files in ESP32_DIR
        import os as real_os
        import sdk

        original_stat = real_os.stat
        def mock_stat(path):
            full = Path(ESP32_DIR) / path
            return original_stat(str(full))

        with patch("os.stat", side_effect=mock_stat):
            result = sdk.verify_core_integrity()
            # All core files should exist in esp32/mesh_client/
            assert result["ok"] is True
            assert result["missing"] == []

    def test_with_missing_file(self):
        import os as real_os
        import sdk

        original_stat = real_os.stat
        def mock_stat(path):
            if path == "nonexistent.py":
                raise OSError("not found")
            full = Path(ESP32_DIR) / path
            return original_stat(str(full))

        # Temporarily add a fake file to CORE_FILES
        sdk.CORE_FILES.append("nonexistent.py")
        try:
            with patch("os.stat", side_effect=mock_stat):
                result = sdk.verify_core_integrity()
                assert result["ok"] is False
                assert "nonexistent.py" in result["missing"]
        finally:
            sdk.CORE_FILES.remove("nonexistent.py")


class TestGetCoreFileHashes:
    def test_hashes_are_hex(self):
        """Verify hash computation works for real files."""
        import hashlib
        import sdk

        # Redirect file reads to ESP32_DIR
        original_open = open
        original_stat = __import__("os").stat

        def patched_stat(path):
            return original_stat(str(Path(ESP32_DIR) / path))

        def patched_open(path, mode="r", **kwargs):
            return original_open(str(Path(ESP32_DIR) / path), mode, **kwargs)

        with patch("os.stat", side_effect=patched_stat), \
             patch("builtins.open", side_effect=patched_open):
            hashes = sdk.get_core_file_hashes()
            assert "sdk.py" in hashes
            # SHA-256 hex digest is 64 chars
            assert len(hashes["sdk.py"]) == 64


class TestSendMessage:
    def test_delegates_to_transport(self):
        import sdk
        transport = MagicMock()
        sdk.send_message(transport, "state_report", "hub", {"status": "ok"})
        transport.send.assert_called_once_with("state_report", "hub", {"status": "ok"})


class TestExecuteCommand:
    def test_delegates_to_device(self):
        mock_device = MagicMock()
        mock_device.execute_command.return_value = {"ok": True}
        sys.modules["device"] = mock_device
        if "sdk" in sys.modules:
            del sys.modules["sdk"]
        import sdk
        result = sdk.execute_command("led", "turn_on")
        mock_device.execute_command.assert_called_once_with("led", "turn_on", None)
        assert result["ok"] is True

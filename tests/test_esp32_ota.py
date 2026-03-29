"""Tests for ESP32 OTA chunk receiver (esp32/mesh_client/main.py).

Tests the device-side OTA logic: offer → chunk receive → verify → complete/abort.
Runs on CPython with mocked MicroPython modules.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

# ---------------------------------------------------------------------------
# Mock MicroPython modules so esp32/mesh_client/main.py can import on CPython
# ---------------------------------------------------------------------------

# Build path to esp32/mesh_client/ relative to this test file
_ESP32_DIR = Path(__file__).resolve().parent.parent / "esp32" / "mesh_client"


@pytest.fixture(autouse=True)
def _mock_micropython_modules(monkeypatch, tmp_path):
    """Patch sys.modules with mock MicroPython modules and set up config."""
    # Mock 'machine' module
    mock_machine = MagicMock()
    mock_machine.Pin = MagicMock()
    mock_machine.reset = MagicMock()

    # Mock 'network' module
    mock_network = MagicMock()

    # Mock 'ubinascii' — provide real base64 implementations
    mock_ubinascii = MagicMock()
    mock_ubinascii.hexlify = lambda b: base64.b16encode(b).lower()
    mock_ubinascii.a2b_base64 = lambda s: base64.b64decode(s)

    # Mock 'ntptime'
    mock_ntptime = MagicMock()

    # Config module — create a real one
    config_mod = MagicMock()
    config_mod.WIFI_SSID = "TestSSID"
    config_mod.WIFI_PASSWORD = "TestPass"
    config_mod.WIFI_TIMEOUT = 5
    config_mod.HUB_IP = "127.0.0.1"
    config_mod.HUB_PORT = 18800
    config_mod.NODE_ID = "test-esp32"
    config_mod.DEVICE_TYPE = "esp32"
    config_mod.CAPABILITIES = [
        {"name": "led", "type": "switch", "access": "write",
         "value_type": "bool", "current_value": False, "gpio_pin": 2},
    ]
    config_mod.PING_INTERVAL_S = 30
    config_mod.RECONNECT_DELAY_S = 5
    config_mod.FIRMWARE_VERSION = "0.1.0"

    # Install mocks into sys.modules
    monkeypatch.setitem(sys.modules, "machine", mock_machine)
    monkeypatch.setitem(sys.modules, "network", mock_network)
    monkeypatch.setitem(sys.modules, "ubinascii", mock_ubinascii)
    monkeypatch.setitem(sys.modules, "ntptime", mock_ntptime)
    monkeypatch.setitem(sys.modules, "config", config_mod)

    # Add esp32/mesh_client to sys.path
    monkeypatch.syspath_prepend(str(_ESP32_DIR))

    # Override file paths to use tmp_path for OTA temp files
    monkeypatch.chdir(tmp_path)

    yield

    # Clean up any imported esp32 modules from sys.modules
    to_remove = [k for k in sys.modules if k in (
        "main", "transport", "device", "protocol", "security", "enrollment",
    )]
    for k in to_remove:
        del sys.modules[k]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_transport_mock():
    """Create a mock MeshTransport with a send method that records calls."""
    transport = MagicMock()
    transport.sent = []

    def _send(msg_type, target, payload):
        transport.sent.append({"type": msg_type, "target": target, "payload": payload})

    transport.send = _send
    return transport


def _make_firmware_data(size=256):
    """Create deterministic firmware bytes."""
    return bytes(range(256)) * (size // 256) + bytes(range(size % 256))


def _chunk_firmware(data, chunk_size=64):
    """Split firmware into base64-encoded chunks like the hub does."""
    chunks = []
    total = (len(data) + chunk_size - 1) // chunk_size
    for i in range(total):
        offset = i * chunk_size
        raw = data[offset:offset + chunk_size]
        chunks.append({
            "firmware_id": "test-fw-001",
            "seq": i,
            "total_chunks": total,
            "data": base64.b64encode(raw).decode("ascii"),
        })
    return chunks


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOTAOffer:
    def test_offer_initializes_session(self):
        import main

        transport = _make_transport_mock()
        payload = {
            "firmware_id": "fw-001",
            "version": "1.0.0",
            "size": 256,
            "sha256": "abc123",
            "total_chunks": 4,
        }
        main._handle_ota_offer(payload, transport, "hub-01")

        # Session should be initialized
        assert main._ota is not None
        assert main._ota["firmware_id"] == "fw-001"
        assert main._ota["total_chunks"] == 4
        assert main._ota["sha256"] == "abc123"
        assert main._ota["received"] == 0

        # Should have sent ota_accept
        assert len(transport.sent) == 1
        assert transport.sent[0]["type"] == "ota_accept"
        assert transport.sent[0]["payload"]["firmware_id"] == "fw-001"

    def test_offer_cleans_up_previous_session(self):
        import main

        transport = _make_transport_mock()
        # First offer
        main._handle_ota_offer({
            "firmware_id": "old-fw",
            "version": "0.9",
            "size": 100,
            "sha256": "old",
            "total_chunks": 2,
        }, transport, "hub-01")

        # Second offer replaces the first
        main._handle_ota_offer({
            "firmware_id": "new-fw",
            "version": "1.0",
            "size": 200,
            "sha256": "new",
            "total_chunks": 3,
        }, transport, "hub-01")

        assert main._ota["firmware_id"] == "new-fw"
        assert main._ota["total_chunks"] == 3


class TestOTAChunk:
    def test_chunk_writes_data_and_acks(self):
        import main

        transport = _make_transport_mock()
        fw_data = _make_firmware_data(128)
        chunks = _chunk_firmware(fw_data, chunk_size=64)

        # Start session
        main._handle_ota_offer({
            "firmware_id": "test-fw-001",
            "version": "1.0",
            "size": len(fw_data),
            "sha256": hashlib.sha256(fw_data).hexdigest(),
            "total_chunks": len(chunks),
        }, transport, "hub-01")
        transport.sent.clear()

        # Send first chunk
        main._handle_ota_chunk(chunks[0], transport, "hub-01")

        assert main._ota["received"] == 1
        # Should have sent ota_chunk_ack
        assert len(transport.sent) == 1
        assert transport.sent[0]["type"] == "ota_chunk_ack"
        assert transport.sent[0]["payload"]["seq"] == 0

    def test_ignores_chunk_without_session(self):
        import main

        main._ota = None
        transport = _make_transport_mock()
        main._handle_ota_chunk({
            "firmware_id": "test",
            "seq": 0,
            "total_chunks": 1,
            "data": base64.b64encode(b"hello").decode(),
        }, transport, "hub-01")

        # Should not send anything — no active session
        assert len(transport.sent) == 0

    def test_ignores_chunk_with_wrong_firmware_id(self):
        import main

        transport = _make_transport_mock()
        main._handle_ota_offer({
            "firmware_id": "fw-A",
            "version": "1.0",
            "size": 64,
            "sha256": "abc",
            "total_chunks": 1,
        }, transport, "hub-01")
        transport.sent.clear()

        # Send chunk with different firmware_id
        main._handle_ota_chunk({
            "firmware_id": "fw-B",
            "seq": 0,
            "total_chunks": 1,
            "data": base64.b64encode(b"x").decode(),
        }, transport, "hub-01")

        # Should not ACK — wrong firmware_id
        assert len(transport.sent) == 0


class TestOTAVerify:
    def test_full_transfer_triggers_verify(self):
        import main

        transport = _make_transport_mock()
        fw_data = _make_firmware_data(128)
        expected_hash = hashlib.sha256(fw_data).hexdigest()
        chunks = _chunk_firmware(fw_data, chunk_size=64)

        # Start session
        main._handle_ota_offer({
            "firmware_id": "test-fw-001",
            "version": "1.0",
            "size": len(fw_data),
            "sha256": expected_hash,
            "total_chunks": len(chunks),
        }, transport, "hub-01")
        transport.sent.clear()

        # Send all chunks
        for chunk in chunks:
            main._handle_ota_chunk(chunk, transport, "hub-01")

        # Last message should be ota_verify (after the last chunk_ack)
        verify_msgs = [m for m in transport.sent if m["type"] == "ota_verify"]
        assert len(verify_msgs) == 1
        assert verify_msgs[0]["payload"]["firmware_id"] == "test-fw-001"
        assert verify_msgs[0]["payload"]["sha256"] == expected_hash


class TestOTAComplete:
    def test_complete_installs_firmware_and_resets(self, monkeypatch):
        import main
        import machine as mach

        transport = _make_transport_mock()
        fw_data = _make_firmware_data(128)
        chunks = _chunk_firmware(fw_data, chunk_size=64)

        # Start session + transfer all chunks
        main._handle_ota_offer({
            "firmware_id": "test-fw-001",
            "version": "1.0",
            "size": len(fw_data),
            "sha256": hashlib.sha256(fw_data).hexdigest(),
            "total_chunks": len(chunks),
        }, transport, "hub-01")
        for chunk in chunks:
            main._handle_ota_chunk(chunk, transport, "hub-01")

        # Mock time.sleep and machine.reset to avoid actual reset
        monkeypatch.setattr("time.sleep", lambda s: None)
        mach.reset = MagicMock()

        # Send ota_complete
        main._handle_ota_complete(
            {"firmware_id": "test-fw-001"}, transport, "hub-01",
        )

        # Firmware should be installed at /app.py
        assert os.path.exists("app.py")
        with open("app.py", "rb") as f:
            assert f.read() == fw_data

        # Session should be cleared
        assert main._ota is None

        # machine.reset should have been called
        mach.reset.assert_called_once()


class TestOTAAbort:
    def test_abort_cleans_up(self):
        import main

        transport = _make_transport_mock()

        # Start a session
        main._handle_ota_offer({
            "firmware_id": "fw-abort",
            "version": "1.0",
            "size": 64,
            "sha256": "abc",
            "total_chunks": 1,
        }, transport, "hub-01")

        assert main._ota is not None
        tmp_path = main._ota["tmp_path"]

        # Send abort
        main._handle_ota_abort(
            {"firmware_id": "fw-abort", "reason": "hash_mismatch"},
            transport, "hub-01",
        )

        # Session should be cleared
        assert main._ota is None

        # Temp file should be removed
        assert not os.path.exists(tmp_path)


class TestOTADispatch:
    """Test that _dispatch correctly routes OTA messages."""

    def test_dispatch_routes_ota_messages(self):
        import main

        transport = _make_transport_mock()

        # Test ota_offer via dispatch
        main._dispatch({
            "type": "ota_offer",
            "payload": {
                "firmware_id": "dispatch-fw",
                "version": "2.0",
                "size": 64,
                "sha256": "xyz",
                "total_chunks": 1,
            },
            "source": "hub-01",
        }, transport)

        assert main._ota is not None
        assert main._ota["firmware_id"] == "dispatch-fw"

        # Test ota_chunk via dispatch
        main._dispatch({
            "type": "ota_chunk",
            "payload": {
                "firmware_id": "dispatch-fw",
                "seq": 0,
                "total_chunks": 1,
                "data": base64.b64encode(b"test-data").decode(),
            },
            "source": "hub-01",
        }, transport)

        # Test ota_abort via dispatch
        main._dispatch({
            "type": "ota_abort",
            "payload": {"firmware_id": "dispatch-fw", "reason": "cancelled"},
            "source": "hub-01",
        }, transport)

        assert main._ota is None

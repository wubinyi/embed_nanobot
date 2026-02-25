"""Tests for OTA firmware update protocol (task 3.3).

Covers: FirmwareStore, FirmwareInfo, OTASession, OTAManager state machine,
chunk transfer, verification, abort, and MeshChannel integration.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.ota import (
    DEFAULT_CHUNK_SIZE,
    FirmwareInfo,
    FirmwareStore,
    OTAManager,
    OTASession,
    UpdateState,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_firmware(size: int = 1024) -> bytes:
    """Return deterministic firmware bytes of given size."""
    return bytes(range(256)) * (size // 256) + bytes(range(size % 256))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# FirmwareInfo
# ---------------------------------------------------------------------------

class TestFirmwareInfo:
    def test_to_dict_roundtrip(self):
        info = FirmwareInfo(
            firmware_id="fw-01", version="1.0.0", device_type="sensor",
            filename="fw-01.bin", size=1024, sha256="abc123",
            added_date="2026-01-01T00:00:00Z",
        )
        d = info.to_dict()
        restored = FirmwareInfo.from_dict(d)
        assert restored.firmware_id == "fw-01"
        assert restored.size == 1024
        assert restored.sha256 == "abc123"

    def test_from_dict_ignores_extra_keys(self):
        d = {"firmware_id": "fw-02", "version": "2.0", "device_type": "light",
             "filename": "fw-02.bin", "extra_key": "ignored"}
        info = FirmwareInfo.from_dict(d)
        assert info.firmware_id == "fw-02"


# ---------------------------------------------------------------------------
# FirmwareStore
# ---------------------------------------------------------------------------

class TestFirmwareStore:
    def test_add_and_list(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = _make_firmware(512)
        info = store.add_firmware("fw-01", "1.0.0", "sensor", data)
        assert info.size == 512
        assert info.sha256 == _sha256(data)
        assert len(store.list_firmware()) == 1

    def test_remove(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", b"data")
        assert store.remove_firmware("fw-01") is True
        assert store.get_firmware("fw-01") is None
        assert len(store.list_firmware()) == 0

    def test_remove_nonexistent(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        assert store.remove_firmware("no-such") is False

    def test_get_firmware(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", b"hello")
        info = store.get_firmware("fw-01")
        assert info is not None
        assert info.version == "1.0.0"
        assert store.get_firmware("missing") is None

    def test_read_chunk(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = b"0123456789abcdef"
        store.add_firmware("fw-01", "1.0.0", "sensor", data)
        chunk = store.read_chunk("fw-01", 4, 8)
        assert chunk == b"456789ab"

    def test_read_chunk_unknown(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        assert store.read_chunk("missing", 0, 10) == b""

    def test_read_chunk_beyond_end(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", b"short")
        chunk = store.read_chunk("fw-01", 3, 100)
        assert chunk == b"rt"

    def test_manifest_persistence(self, tmp_path):
        path = str(tmp_path / "fw")
        store = FirmwareStore(path)
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", b"data")

        # Reload
        store2 = FirmwareStore(path)
        store2.load()
        assert len(store2.list_firmware()) == 1
        assert store2.get_firmware("fw-01").sha256 == _sha256(b"data")

    def test_binary_file_written(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = _make_firmware(256)
        store.add_firmware("fw-01", "1.0.0", "sensor", data)
        written = (tmp_path / "fw" / "fw-01.bin").read_bytes()
        assert written == data

    def test_remove_deletes_binary(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", b"data")
        store.remove_firmware("fw-01")
        assert not (tmp_path / "fw" / "fw-01.bin").exists()


# ---------------------------------------------------------------------------
# OTASession
# ---------------------------------------------------------------------------

class TestOTASession:
    def _make_session(self, size: int = 1024, chunk_size: int = 256) -> OTASession:
        fw = FirmwareInfo(
            firmware_id="fw-01", version="1.0.0", device_type="sensor",
            filename="fw-01.bin", size=size, sha256="abc",
        )
        return OTASession(node_id="dev-01", firmware=fw, chunk_size=chunk_size)

    def test_total_chunks_exact(self):
        s = self._make_session(size=1024, chunk_size=256)
        assert s.total_chunks == 4

    def test_total_chunks_remainder(self):
        s = self._make_session(size=1000, chunk_size=256)
        assert s.total_chunks == 4  # ceil(1000/256)

    def test_total_chunks_single(self):
        s = self._make_session(size=100, chunk_size=256)
        assert s.total_chunks == 1

    def test_progress_initial(self):
        s = self._make_session()
        assert s.progress == 0.0

    def test_progress_partial(self):
        s = self._make_session(size=1024, chunk_size=256)  # 4 chunks
        s.acked_up_to = 1  # 2 of 4 ACK'd
        assert abs(s.progress - 0.5) < 0.01

    def test_progress_complete(self):
        s = self._make_session(size=1024, chunk_size=256)
        s.acked_up_to = 3  # All 4 ACK'd
        assert s.progress == 1.0

    def test_to_status(self):
        s = self._make_session()
        status = s.to_status()
        assert status["node_id"] == "dev-01"
        assert status["firmware_id"] == "fw-01"
        assert status["state"] == "offered"
        assert status["progress"] == 0.0


# ---------------------------------------------------------------------------
# OTAManager — full protocol flow
# ---------------------------------------------------------------------------

class TestOTAManagerStart:
    """Tests for start_update and basic preconditions."""

    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = _make_firmware(1024)
        store.add_firmware("fw-01", "1.0.0", "sensor", data)
        send_fn = AsyncMock(return_value=True)
        mgr = OTAManager(store, send_fn, node_id="hub", chunk_size=256)
        return mgr, send_fn, data

    @pytest.mark.asyncio
    async def test_start_sends_offer(self, setup):
        mgr, send_fn, _ = setup
        session = await mgr.start_update("dev-01", "fw-01")
        assert session is not None
        assert session.state == UpdateState.OFFERED
        send_fn.assert_called_once()
        env = send_fn.call_args[0][0]
        assert env.type == MsgType.OTA_OFFER
        assert env.target == "dev-01"
        assert env.payload["firmware_id"] == "fw-01"

    @pytest.mark.asyncio
    async def test_start_unknown_firmware(self, setup):
        mgr, send_fn, _ = setup
        session = await mgr.start_update("dev-01", "no-such-fw")
        assert session is None
        send_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_duplicate_rejected(self, setup):
        mgr, _, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        session2 = await mgr.start_update("dev-01", "fw-01")
        assert session2 is None

    @pytest.mark.asyncio
    async def test_start_after_complete_allowed(self, setup):
        mgr, _, _ = setup
        s1 = await mgr.start_update("dev-01", "fw-01")
        s1.state = UpdateState.COMPLETE  # simulate completion
        s2 = await mgr.start_update("dev-01", "fw-01")
        assert s2 is not None


class TestOTAManagerFlow:
    """Tests for the full OTA state machine flow."""

    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = _make_firmware(1024)
        store.add_firmware("fw-01", "1.0.0", "sensor", data)
        sent: list[MeshEnvelope] = []

        async def capture_send(env: MeshEnvelope) -> bool:
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        return mgr, sent, data

    @pytest.mark.asyncio
    async def test_accept_starts_transfer(self, setup):
        mgr, sent, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        sent.clear()

        # Device sends ACCEPT
        accept = MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        )
        await mgr.handle_ota_message(accept)

        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.TRANSFERRING
        # Should have sent first chunk
        assert len(sent) == 1
        assert sent[0].type == MsgType.OTA_CHUNK
        assert sent[0].payload["seq"] == 0

    @pytest.mark.asyncio
    async def test_reject(self, setup):
        mgr, sent, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        sent.clear()

        reject = MeshEnvelope(
            type=MsgType.OTA_REJECT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01", "reason": "insufficient_storage"},
        )
        await mgr.handle_ota_message(reject)

        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.REJECTED
        assert "insufficient_storage" in session.error

    @pytest.mark.asyncio
    async def test_chunk_ack_sends_next(self, setup):
        mgr, sent, _ = setup
        await mgr.start_update("dev-01", "fw-01")

        # Accept
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        ))
        sent.clear()

        # ACK chunk 0
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_CHUNK_ACK, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01", "seq": 0},
        ))

        assert len(sent) == 1
        assert sent[0].payload["seq"] == 1

    @pytest.mark.asyncio
    async def test_full_transfer_completes(self, setup):
        mgr, sent, data = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")

        # Accept
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        ))

        # ACK all chunks (4 chunks for 1024 bytes / 256 chunk size)
        for seq in range(session.total_chunks):
            sent.clear()
            await mgr.handle_ota_message(MeshEnvelope(
                type=MsgType.OTA_CHUNK_ACK, source="dev-01", target="hub",
                payload={"firmware_id": "fw-01", "seq": seq},
            ))

        assert session.state == UpdateState.VERIFYING

        # Device sends correct hash
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_VERIFY, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01", "sha256": _sha256(data)},
        ))

        assert session.state == UpdateState.COMPLETE
        # Last sent message should be OTA_COMPLETE
        assert sent[-1].type == MsgType.OTA_COMPLETE

    @pytest.mark.asyncio
    async def test_verify_hash_mismatch(self, setup):
        mgr, sent, data = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")

        # Move to VERIFYING state directly
        session.state = UpdateState.VERIFYING

        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_VERIFY, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01", "sha256": "wrong_hash"},
        ))

        assert session.state == UpdateState.FAILED
        assert "hash mismatch" in session.error
        assert sent[-1].type == MsgType.OTA_ABORT

    @pytest.mark.asyncio
    async def test_device_abort(self, setup):
        mgr, _, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")

        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ABORT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01", "reason": "low_battery"},
        ))

        assert session.state == UpdateState.FAILED
        assert "low_battery" in session.error


class TestOTAManagerAbort:
    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", _make_firmware(512))
        send_fn = AsyncMock(return_value=True)
        mgr = OTAManager(store, send_fn, node_id="hub", chunk_size=256)
        return mgr, send_fn

    @pytest.mark.asyncio
    async def test_abort_active_session(self, setup):
        mgr, send_fn = setup
        await mgr.start_update("dev-01", "fw-01")
        send_fn.reset_mock()

        aborted = await mgr.abort_update("dev-01", "maintenance")
        assert aborted is True
        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.FAILED
        assert "maintenance" in session.error
        # Should send OTA_ABORT
        send_fn.assert_called_once()
        env = send_fn.call_args[0][0]
        assert env.type == MsgType.OTA_ABORT

    @pytest.mark.asyncio
    async def test_abort_no_session(self, setup):
        mgr, _ = setup
        assert await mgr.abort_update("no-device") is False

    @pytest.mark.asyncio
    async def test_abort_completed_session(self, setup):
        mgr, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        mgr.get_session("dev-01").state = UpdateState.COMPLETE
        assert await mgr.abort_update("dev-01") is False


class TestOTAManagerStatus:
    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", _make_firmware(512))
        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub")
        return mgr

    @pytest.mark.asyncio
    async def test_get_status(self, setup):
        mgr = setup
        await mgr.start_update("dev-01", "fw-01")
        status = mgr.get_status("dev-01")
        assert status["state"] == "offered"
        assert status["firmware_id"] == "fw-01"

    @pytest.mark.asyncio
    async def test_get_status_none(self, setup):
        mgr = setup
        assert mgr.get_status("missing") is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, setup):
        mgr = setup
        await mgr.start_update("dev-01", "fw-01")
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["node_id"] == "dev-01"


class TestOTAManagerChunkData:
    """Verify that chunk data matches the original firmware."""

    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        data = _make_firmware(600)
        store.add_firmware("fw-01", "1.0.0", "sensor", data)
        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        return mgr, sent, data

    @pytest.mark.asyncio
    async def test_reassembled_data_matches(self, setup):
        """ACK all chunks, reconstruct firmware, verify sha256."""
        mgr, sent, orig_data = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")

        # Accept
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        ))

        reassembled = bytearray()
        for seq in range(session.total_chunks):
            # Find the chunk envelope with this seq
            chunk_envs = [
                e for e in sent
                if e.type == MsgType.OTA_CHUNK and e.payload.get("seq") == seq
            ]
            assert len(chunk_envs) == 1, f"expected 1 chunk env for seq={seq}, got {len(chunk_envs)}"
            chunk_data = base64.b64decode(chunk_envs[0].payload["data"])
            reassembled.extend(chunk_data)

            # ACK
            await mgr.handle_ota_message(MeshEnvelope(
                type=MsgType.OTA_CHUNK_ACK, source="dev-01", target="hub",
                payload={"firmware_id": "fw-01", "seq": seq},
            ))

        assert bytes(reassembled) == orig_data
        assert _sha256(bytes(reassembled)) == _sha256(orig_data)


class TestOTAManagerProgress:
    """Verify progress callbacks are invoked."""

    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", _make_firmware(512))
        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=256)
        return mgr

    @pytest.mark.asyncio
    async def test_progress_callback_called(self, setup):
        mgr = setup
        progress_events: list[dict] = []
        mgr.on_progress(lambda s: progress_events.append(s.to_status()))

        await mgr.start_update("dev-01", "fw-01")
        assert len(progress_events) >= 1
        assert progress_events[0]["state"] == "offered"

    @pytest.mark.asyncio
    async def test_progress_on_accept(self, setup):
        mgr = setup
        events: list[dict] = []
        mgr.on_progress(lambda s: events.append(s.to_status()))

        await mgr.start_update("dev-01", "fw-01")
        events.clear()

        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        ))
        assert any(e["state"] == "transferring" for e in events)


class TestOTAManagerEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", _make_firmware(512))
        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        return mgr, sent

    @pytest.mark.asyncio
    async def test_message_from_unknown_device(self, setup):
        mgr, sent = setup
        # No session started, device sends ACK
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_CHUNK_ACK, source="unknown", target="hub",
            payload={"firmware_id": "fw-01", "seq": 0},
        ))
        # Should be ignored without error
        assert mgr.get_session("unknown") is None

    @pytest.mark.asyncio
    async def test_firmware_id_mismatch(self, setup):
        mgr, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")

        # Device sends ACK with wrong firmware_id
        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_CHUNK_ACK, source="dev-01", target="hub",
            payload={"firmware_id": "wrong-fw", "seq": 0},
        ))
        # State unchanged
        assert session.state == UpdateState.OFFERED

    @pytest.mark.asyncio
    async def test_accept_when_not_offered(self, setup):
        mgr, _ = setup
        await mgr.start_update("dev-01", "fw-01")
        session = mgr.get_session("dev-01")
        session.state = UpdateState.TRANSFERRING  # Wrong state for accept

        await mgr.handle_ota_message(MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub",
            payload={"firmware_id": "fw-01"},
        ))
        # Should remain in TRANSFERRING (not reset)
        assert session.state == UpdateState.TRANSFERRING

    @pytest.mark.asyncio
    async def test_concurrent_devices(self, setup):
        mgr, sent = setup
        # Add second firmware
        mgr.store.add_firmware("fw-02", "2.0.0", "light", _make_firmware(256))

        s1 = await mgr.start_update("dev-01", "fw-01")
        s2 = await mgr.start_update("dev-02", "fw-02")

        assert s1 is not None
        assert s2 is not None
        assert s1.node_id != s2.node_id
        assert len(mgr.list_sessions()) == 2


# ---------------------------------------------------------------------------
# Channel integration
# ---------------------------------------------------------------------------

class TestChannelOTAIntegration:
    """Test OTA wiring in MeshChannel."""

    def _make_channel(self, tmp_path):
        """Create a minimal MeshChannel with OTA enabled."""
        fw_dir = str(tmp_path / "firmware")
        config = MagicMock()
        config.node_id = "hub-test"
        config.tcp_port = 0  # unused in unit test
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.registry_path = str(tmp_path / "registry.json")
        config.automation_rules_path = str(tmp_path / "automation.json")
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.firmware_dir = fw_dir
        config.ota_chunk_size = 256
        config.ota_chunk_timeout = 30
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config._workspace_path = str(tmp_path)
        return config, fw_dir

    def test_ota_manager_created_when_firmware_dir_set(self, tmp_path):
        config, fw_dir = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        assert ch.firmware_store is not None
        assert ch.ota is not None

    def test_ota_manager_none_when_no_firmware_dir(self, tmp_path):
        config, _ = self._make_channel(tmp_path)
        config.firmware_dir = ""
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        assert ch.firmware_store is None
        assert ch.ota is None

    @pytest.mark.asyncio
    async def test_start_ota_update_convenience(self, tmp_path):
        config, fw_dir = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        # Add firmware to store
        ch.firmware_store.add_firmware("fw-test", "1.0", "sensor", b"firmware_data")

        # Mock transport send
        ch.transport.send = AsyncMock(return_value=True)
        # OTA manager uses transport.send via reference
        ch.ota._send = ch.transport.send

        session = await ch.start_ota_update("dev-01", "fw-test")
        assert session is not None
        assert session.state == UpdateState.OFFERED
        ch.transport.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_ota_no_ota_manager(self, tmp_path):
        config, _ = self._make_channel(tmp_path)
        config.firmware_dir = ""
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        result = await ch.start_ota_update("dev-01", "fw-test")
        assert result is None

    @pytest.mark.asyncio
    async def test_ota_message_routing(self, tmp_path):
        config, fw_dir = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        ch.firmware_store.add_firmware("fw-test", "1.0", "sensor", b"data")
        ch.transport.send = AsyncMock(return_value=True)
        ch.ota._send = ch.transport.send

        await ch.start_ota_update("dev-01", "fw-test")

        # Simulate device sending OTA_ACCEPT through mesh message handler
        accept = MeshEnvelope(
            type=MsgType.OTA_ACCEPT, source="dev-01", target="hub-test",
            payload={"firmware_id": "fw-test"},
        )
        await ch._on_mesh_message(accept)

        session = ch.ota.get_session("dev-01")
        assert session.state == UpdateState.TRANSFERRING

    def test_get_ota_status(self, tmp_path):
        config, fw_dir = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        # No session → None
        assert ch.get_ota_status("dev-01") is None

    @pytest.mark.asyncio
    async def test_abort_ota_convenience(self, tmp_path):
        config, fw_dir = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        ch.firmware_store.add_firmware("fw-test", "1.0", "sensor", b"data")
        ch.transport.send = AsyncMock(return_value=True)
        ch.ota._send = ch.transport.send

        await ch.start_ota_update("dev-01", "fw-test")
        aborted = await ch.abort_ota_update("dev-01", "test_abort")
        assert aborted is True

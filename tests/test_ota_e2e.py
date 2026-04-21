"""tests/test_ota_e2e.py — End-to-end OTA flow simulation tests (task 5.4.1).

Tests the complete OTA WiFi firmware update protocol by simulating both sides:
  - Hub side:    OTAManager  (nanobot/mesh/ota.py)
  - Device side: FakeESP32   (mirrors main.py OTA handlers in Python)

The two sides communicate through an in-memory message queue — no real
hardware or network is required.  These tests complement the unit tests in
test_ota.py by exercising the full protocol end-to-end.

Test categories
---------------
1.  Happy path (small, medium, large firmware)
2.  Large-firmware chunking integrity (data reconstructed byte-for-byte)
3.  Concurrent multi-device OTA
4.  Abort scenarios (hub-initiated, device-initiated, mid-transfer, retry)
5.  Hash mismatch (device sends tampered SHA-256)
6.  Anti-rollback rejection (version_counter check)
7.  Timeout handling (offer / chunk-ack / verify timeouts)
8.  Protocol edge cases (unexpected messages, firmware_id mismatch)
9.  Progress callback accuracy
10. Firmware store integration
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.mesh.ota import (
    CHUNK_ACK_TIMEOUT,
    DEFAULT_CHUNK_SIZE,
    OFFER_TIMEOUT,
    VERIFY_TIMEOUT,
    FirmwareStore,
    OTAManager,
    OTASession,
    UpdateState,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType

import base64
import hashlib


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_firmware(size: int) -> bytes:
    """Return deterministic pseudo-firmware bytes of the given size."""
    return bytes(range(256)) * (size // 256) + bytes(range(size % 256))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_store_and_mgr(
    tmp_path,
    fw_data: bytes,
    fw_id: str = "fw-01",
    version: str = "1.0.0",
    chunk_size: int = 256,
) -> tuple[FirmwareStore, OTAManager]:
    """Create a FirmwareStore + OTAManager pre-loaded with one firmware entry."""
    store = FirmwareStore(str(tmp_path / "fw"))
    store.load()
    store.add_firmware(fw_id, version, "sensor", fw_data)
    # Use an AsyncMock as the initial send_fn; drive_session will override it
    mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=chunk_size)
    return store, mgr


# ---------------------------------------------------------------------------
# FakeESP32 — simulates main.py OTA handlers
# ---------------------------------------------------------------------------

class FakeESP32:
    """Simulates the MicroPython OTA handlers from esp32/mesh_client/main.py.

    Call ``handle(env)`` with a hub→device ``MeshEnvelope`` to receive the
    list of device→hub response envelopes.

    Parameters
    ----------
    node_id:
        The device's node_id (used as ``source`` in response envelopes).
    tamper_hash:
        If True the device reports a wrong SHA-256 in OTA_VERIFY.
    anti_rollback_min:
        Minimum acceptable ``version_counter``.  0 = no anti-rollback.
    abort_after_seq:
        If set, the device sends OTA_ABORT instead of ACK after receiving
        this many chunks (0 = abort on the very first chunk).
    """

    def __init__(
        self,
        node_id: str,
        *,
        tamper_hash: bool = False,
        anti_rollback_min: int = 0,
        abort_after_seq: int | None = None,
    ) -> None:
        self.node_id = node_id
        self.tamper_hash = tamper_hash
        self.anti_rollback_min = anti_rollback_min
        self.abort_after_seq = abort_after_seq

        # OTA session state (mirrors main.py module-level _ota)
        self._ota: dict[str, Any] | None = None
        self._received_data = bytearray()

        # Outcome flags
        self.app_py_content: bytes | None = None  # set when OTA_COMPLETE received
        self.aborted: bool = False                 # set when OTA_ABORT received
        self.rejected: bool = False                # set when anti-rollback fires

    # -- dispatch ------------------------------------------------------------

    def handle(self, env: MeshEnvelope) -> list[MeshEnvelope]:
        """Process one hub→device message.  Returns device→hub responses."""
        t = env.type
        if t == MsgType.OTA_OFFER:
            return self._on_offer(env)
        elif t == MsgType.OTA_CHUNK:
            return self._on_chunk(env)
        elif t == MsgType.OTA_COMPLETE:
            return self._on_complete(env)
        elif t == MsgType.OTA_ABORT:
            return self._on_abort(env)
        return []

    # -- helpers -------------------------------------------------------------

    def _resp(self, msg_type: MsgType, payload: dict[str, Any]) -> MeshEnvelope:
        return MeshEnvelope(
            type=msg_type,
            source=self.node_id,
            target="hub",
            payload=payload,
        )

    # -- OTA_OFFER -----------------------------------------------------------

    def _on_offer(self, env: MeshEnvelope) -> list[MeshEnvelope]:
        payload = env.payload
        fw_id = payload.get("firmware_id", "")
        version_counter = payload.get("version_counter", 0)

        # Anti-rollback check (mirrors main.py boot_manager.check_anti_rollback)
        if version_counter < self.anti_rollback_min:
            self.rejected = True
            return [self._resp(MsgType.OTA_REJECT, {
                "firmware_id": fw_id,
                "reason": "anti-rollback: version counter too low",
            })]

        self._ota = {
            "firmware_id": fw_id,
            "total_chunks": payload.get("total_chunks", 0),
            "sha256": payload.get("sha256", ""),
            "received": 0,
        }
        self._received_data = bytearray()
        return [self._resp(MsgType.OTA_ACCEPT, {"firmware_id": fw_id})]

    # -- OTA_CHUNK -----------------------------------------------------------

    def _on_chunk(self, env: MeshEnvelope) -> list[MeshEnvelope]:
        if self._ota is None:
            return []

        payload = env.payload
        fw_id = payload.get("firmware_id", "")
        if fw_id != self._ota["firmware_id"]:
            return []

        seq = payload.get("seq", -1)
        chunk_bytes = base64.b64decode(payload.get("data", ""))
        self._received_data.extend(chunk_bytes)
        self._ota["received"] = seq + 1

        # Device-initiated abort injection (simulates e.g. low battery)
        if self.abort_after_seq is not None and seq >= self.abort_after_seq:
            return [self._resp(MsgType.OTA_ABORT, {
                "firmware_id": fw_id,
                "reason": "low_battery",
            })]

        responses: list[MeshEnvelope] = [
            self._resp(MsgType.OTA_CHUNK_ACK, {"firmware_id": fw_id, "seq": seq}),
        ]

        # All chunks received → compute SHA-256 and send OTA_VERIFY
        if self._ota["received"] >= self._ota["total_chunks"]:
            digest = _sha256(bytes(self._received_data))
            if self.tamper_hash:
                digest = "0" * 64  # deliberately wrong hash
            responses.append(self._resp(MsgType.OTA_VERIFY, {
                "firmware_id": fw_id,
                "sha256": digest,
            }))

        return responses

    # -- OTA_COMPLETE --------------------------------------------------------

    def _on_complete(self, env: MeshEnvelope) -> list[MeshEnvelope]:
        if self._ota is None:
            return []
        # Simulate: os.rename(tmp_path, "app.py")
        self.app_py_content = bytes(self._received_data)
        self._ota = None
        return []  # no response message needed

    # -- OTA_ABORT -----------------------------------------------------------

    def _on_abort(self, env: MeshEnvelope) -> list[MeshEnvelope]:
        self.aborted = True
        self._ota = None
        self._received_data = bytearray()
        return []


# ---------------------------------------------------------------------------
# Session driver — wires hub OTAManager to FakeESP32
# ---------------------------------------------------------------------------

async def drive_session(
    mgr: OTAManager,
    esp32: FakeESP32,
    node_id: str,
    firmware_id: str,
    *,
    max_rounds: int = 100_000,
) -> OTASession | None:
    """Drive a complete OTA session between hub OTAManager and FakeESP32.

    Intercepts the hub's ``_send`` function, routes hub→ESP32 messages through
    ``FakeESP32.handle()``, and feeds responses back into the hub via
    ``handle_ota_message()``.  Returns the final ``OTASession``.
    """
    pending: list[MeshEnvelope] = []

    async def intercept_send(env: MeshEnvelope) -> bool:
        pending.append(env)
        return True

    original_send = mgr._send
    mgr._send = intercept_send

    try:
        await mgr.start_update(node_id, firmware_id)

        for _ in range(max_rounds):
            if not pending:
                break
            env = pending.pop(0)
            for resp in esp32.handle(env):
                await mgr.handle_ota_message(resp)

        return mgr.get_session(node_id)
    finally:
        mgr._send = original_send


# ===========================================================================
# 1. Happy Path
# ===========================================================================

class TestE2EHappyPath:
    """End-to-end happy path: complete OTA without errors."""

    @pytest.mark.asyncio
    async def test_small_firmware_reaches_complete(self, tmp_path):
        fw = _make_firmware(1024)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session is not None
        assert session.state == UpdateState.COMPLETE

    @pytest.mark.asyncio
    async def test_medium_firmware_reaches_complete(self, tmp_path):
        fw = _make_firmware(10_000)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=512)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE

    @pytest.mark.asyncio
    async def test_large_firmware_reaches_complete(self, tmp_path):
        """100 KB firmware at default 4096-byte chunks → 25 chunks."""
        fw = _make_firmware(100_000)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=DEFAULT_CHUNK_SIZE)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert session.total_chunks == 25  # ceil(100000/4096) = 25

    @pytest.mark.asyncio
    async def test_esp32_installs_correct_app_py(self, tmp_path):
        """Device's installed app.py matches the original firmware bytes exactly."""
        fw = _make_firmware(2048)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_progress_reaches_1_on_complete(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert mgr.get_session("dev-01").progress == 1.0

    @pytest.mark.asyncio
    async def test_single_chunk_firmware(self, tmp_path):
        """Firmware fits in one chunk — edge case for total_chunks=1."""
        fw = _make_firmware(128)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=256)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert session.total_chunks == 1
        assert esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_exact_multiple_chunks(self, tmp_path):
        """Firmware size is exactly N * chunk_size — no trailing partial chunk."""
        fw = _make_firmware(1024)   # 1024 / 256 = 4 exactly
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=256)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert session.total_chunks == 4
        assert esp32.app_py_content == fw


# ===========================================================================
# 2. Large-Firmware Chunking Integrity
# ===========================================================================

class TestE2EChunkingIntegrity:
    """Verify that the reassembled firmware data on the device is byte-accurate."""

    @pytest.mark.asyncio
    async def test_128kb_firmware_byte_accurate(self, tmp_path):
        fw = _make_firmware(128 * 1024)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=DEFAULT_CHUNK_SIZE)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert len(esp32.app_py_content) == len(fw)
        assert esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_non_power_of_two_size(self, tmp_path):
        """513 bytes, 256-byte chunks → 3 chunks (256 + 256 + 1)."""
        fw = _make_firmware(513)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=256)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert session.total_chunks == 3
        assert esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_sha256_matches_original_after_transfer(self, tmp_path):
        """SHA-256 of installed app.py must match original firmware."""
        fw = _make_firmware(50_000)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=1000)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert _sha256(esp32.app_py_content) == _sha256(fw)

    @pytest.mark.asyncio
    async def test_1_byte_firmware(self, tmp_path):
        """Minimal 1-byte firmware — extreme edge case."""
        fw = b"\x42"
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=256)
        esp32 = FakeESP32("dev-01")

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert esp32.app_py_content == fw


# ===========================================================================
# 3. Concurrent Multi-Device OTA
# ===========================================================================

class TestE2EConcurrentDevices:
    """Multiple devices receive simultaneous OTA updates."""

    @pytest.mark.asyncio
    async def test_two_devices_same_firmware(self, tmp_path):
        fw = _make_firmware(2048)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", fw)

        sent: list[MeshEnvelope] = []

        async def capture_send(env: MeshEnvelope) -> bool:
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        esp1 = FakeESP32("dev-01")
        esp2 = FakeESP32("dev-02")

        await mgr.start_update("dev-01", "fw-01")
        await mgr.start_update("dev-02", "fw-01")

        esp_map = {"dev-01": esp1, "dev-02": esp2}

        for _ in range(100_000):
            if not sent:
                break
            env = sent.pop(0)
            if env.target in esp_map:
                for resp in esp_map[env.target].handle(env):
                    await mgr.handle_ota_message(resp)

        assert mgr.get_session("dev-01").state == UpdateState.COMPLETE
        assert mgr.get_session("dev-02").state == UpdateState.COMPLETE
        assert esp1.app_py_content == fw
        assert esp2.app_py_content == fw

    @pytest.mark.asyncio
    async def test_three_devices_different_firmware(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        fw_specs = {"fw-a": 512, "fw-b": 1024, "fw-c": 768}
        fws = {fid: _make_firmware(sz) for fid, sz in fw_specs.items()}
        for fid, data in fws.items():
            store.add_firmware(fid, "1.0", "sensor", data)

        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        devices = {
            "dev-A": (FakeESP32("dev-A"), "fw-a"),
            "dev-B": (FakeESP32("dev-B"), "fw-b"),
            "dev-C": (FakeESP32("dev-C"), "fw-c"),
        }
        for nid, (_, fw_id) in devices.items():
            await mgr.start_update(nid, fw_id)

        esp_map = {nid: esp32 for nid, (esp32, _) in devices.items()}
        for _ in range(200_000):
            if not sent:
                break
            env = sent.pop(0)
            if env.target in esp_map:
                for resp in esp_map[env.target].handle(env):
                    await mgr.handle_ota_message(resp)

        for nid, (esp32, fw_id) in devices.items():
            assert mgr.get_session(nid).state == UpdateState.COMPLETE
            assert esp32.app_py_content == fws[fw_id]

    @pytest.mark.asyncio
    async def test_aborting_one_device_does_not_affect_other(self, tmp_path):
        """Aborting dev-01 must not affect dev-02's active session."""
        fw = _make_firmware(512)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0", "sensor", fw)

        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        esp2 = FakeESP32("dev-02")

        await mgr.start_update("dev-01", "fw-01")
        await mgr.start_update("dev-02", "fw-01")

        # Abort dev-01 while both OFFERs are still pending
        await mgr.abort_update("dev-01", "test_isolation")

        # Drive only dev-02 messages to completion; silently discard dev-01 messages
        for _ in range(50_000):
            if not sent:
                break
            env = sent.pop(0)
            if env.target == "dev-02":
                for resp in esp2.handle(env):
                    await mgr.handle_ota_message(resp)
            # Messages addressed to dev-01 are intentionally ignored

        assert mgr.get_session("dev-01").state == UpdateState.FAILED
        assert mgr.get_session("dev-02").state == UpdateState.COMPLETE
        assert esp2.app_py_content == fw


# ===========================================================================
# 4. Abort Scenarios
# ===========================================================================

class TestE2EAbortScenarios:
    """Hub-initiated and device-initiated abort during OTA."""

    @pytest.mark.asyncio
    async def test_hub_abort_before_accept(self, tmp_path):
        fw = _make_firmware(1024)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", fw)

        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        await mgr.start_update("dev-01", "fw-01")  # OFFER sent
        assert any(e.type == MsgType.OTA_OFFER for e in sent)
        sent.clear()

        aborted = await mgr.abort_update("dev-01", "hub_maintenance")

        assert aborted is True
        assert mgr.get_session("dev-01").state == UpdateState.FAILED
        abort_msgs = [e for e in sent if e.type == MsgType.OTA_ABORT]
        assert len(abort_msgs) == 1
        assert abort_msgs[0].target == "dev-01"

    @pytest.mark.asyncio
    async def test_hub_abort_mid_transfer(self, tmp_path):
        """Hub aborts after some chunks are transferred."""
        fw = _make_firmware(1024)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0.0", "sensor", fw)

        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        esp32 = FakeESP32("dev-01")

        await mgr.start_update("dev-01", "fw-01")

        # Process OFFER → ACCEPT
        offer = sent.pop(0)
        for resp in esp32.handle(offer):
            await mgr.handle_ota_message(resp)

        # Process first chunk → ACK
        assert any(e.type == MsgType.OTA_CHUNK for e in sent)
        chunk0 = next(e for e in sent if e.type == MsgType.OTA_CHUNK)
        sent.remove(chunk0)
        for resp in esp32.handle(chunk0):
            await mgr.handle_ota_message(resp)

        assert mgr.get_session("dev-01").state == UpdateState.TRANSFERRING
        sent.clear()

        # Hub aborts mid-transfer
        aborted = await mgr.abort_update("dev-01", "firmware_recalled")
        assert aborted is True
        assert mgr.get_session("dev-01").state == UpdateState.FAILED
        assert "firmware_recalled" in mgr.get_session("dev-01").error
        assert any(e.type == MsgType.OTA_ABORT for e in sent)

    @pytest.mark.asyncio
    async def test_device_abort_on_first_chunk(self, tmp_path):
        """Device sends OTA_ABORT instead of ACK on chunk 0 → FAILED."""
        fw = _make_firmware(1024)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", abort_after_seq=0)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.FAILED
        assert "device aborted" in session.error

    @pytest.mark.asyncio
    async def test_device_abort_mid_transfer_carries_reason(self, tmp_path):
        """Device abort reason (low_battery) is preserved in session.error."""
        fw = _make_firmware(2048)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", abort_after_seq=3)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.FAILED
        assert "low_battery" in session.error

    @pytest.mark.asyncio
    async def test_retry_after_device_abort_succeeds(self, tmp_path):
        """After a FAILED session, a new OTA session can start and completes."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        # First attempt: device aborts
        bad_esp32 = FakeESP32("dev-01", abort_after_seq=0)
        session1 = await drive_session(mgr, bad_esp32, "dev-01", "fw-01")
        assert session1.state == UpdateState.FAILED

        # Second attempt: fresh device, completes
        good_esp32 = FakeESP32("dev-01")
        session2 = await drive_session(mgr, good_esp32, "dev-01", "fw-01")
        assert session2.state == UpdateState.COMPLETE
        assert good_esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_abort_nonexistent_session_returns_false(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        result = await mgr.abort_update("unknown-device", "test")
        assert result is False

    @pytest.mark.asyncio
    async def test_abort_completed_session_returns_false(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")
        assert mgr.get_session("dev-01").state == UpdateState.COMPLETE

        result = await mgr.abort_update("dev-01", "too_late")
        assert result is False


# ===========================================================================
# 5. Hash Mismatch
# ===========================================================================

class TestE2EHashMismatch:
    """Device sends a corrupted SHA-256 — hub must abort."""

    @pytest.mark.asyncio
    async def test_hash_mismatch_results_in_failed(self, tmp_path):
        fw = _make_firmware(1024)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", tamper_hash=True)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.FAILED
        assert "hash mismatch" in session.error

    @pytest.mark.asyncio
    async def test_hub_sends_ota_abort_to_device_on_mismatch(self, tmp_path):
        """Hub must send OTA_ABORT to device after detecting hash mismatch."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", tamper_hash=True)

        # Run the full session through drive_session; check device receives abort
        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert esp32.aborted is True
        assert esp32.app_py_content is None

    @pytest.mark.asyncio
    async def test_retry_after_hash_mismatch_succeeds(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        # First attempt: tampered hash
        bad_esp32 = FakeESP32("dev-01", tamper_hash=True)
        session1 = await drive_session(mgr, bad_esp32, "dev-01", "fw-01")
        assert session1.state == UpdateState.FAILED

        # Retry with honest device
        good_esp32 = FakeESP32("dev-01")
        session2 = await drive_session(mgr, good_esp32, "dev-01", "fw-01")
        assert session2.state == UpdateState.COMPLETE
        assert good_esp32.app_py_content == fw

    @pytest.mark.asyncio
    async def test_hash_mismatch_does_not_install_firmware(self, tmp_path):
        """On hash mismatch the device must NOT have app.py installed."""
        fw = _make_firmware(768)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", tamper_hash=True)

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert esp32.app_py_content is None


# ===========================================================================
# 6. Anti-Rollback
# ===========================================================================

class TestE2EAntiRollback:
    """ESP32 anti-rollback rejects OTA offers with an insufficient version_counter."""

    @pytest.mark.asyncio
    async def test_offer_without_version_counter_accepted(self, tmp_path):
        """Hub OTA_OFFER omits version_counter → ESP32 defaults to 0 → accepted."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", anti_rollback_min=0)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.COMPLETE
        assert esp32.rejected is False

    @pytest.mark.asyncio
    async def test_anti_rollback_rejects_offer(self, tmp_path):
        """ESP32 requires version_counter >= 5; hub sends default 0 → REJECTED."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", anti_rollback_min=5)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.REJECTED
        assert esp32.rejected is True

    @pytest.mark.asyncio
    async def test_rejection_reason_preserved_in_session(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", anti_rollback_min=10)

        session = await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert session.state == UpdateState.REJECTED
        assert "anti-rollback" in session.error

    @pytest.mark.asyncio
    async def test_firmware_not_installed_on_rejection(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01", anti_rollback_min=99)

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert esp32.app_py_content is None


# ===========================================================================
# 7. Timeout Handling
# ===========================================================================

class TestE2ETimeouts:
    """Timeout detection via OTAManager.check_timeouts()."""

    @pytest.mark.asyncio
    async def test_offer_timeout(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        await mgr.start_update("dev-01", "fw-01")

        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.OFFERED

        # Backdate last_activity to simulate timeout
        session.last_activity = time.time() - (OFFER_TIMEOUT + 1)
        timed_out = mgr.check_timeouts()

        assert "dev-01" in timed_out
        assert session.state == UpdateState.FAILED

    @pytest.mark.asyncio
    async def test_chunk_ack_timeout(self, tmp_path):
        fw = _make_firmware(1024)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        await mgr.start_update("dev-01", "fw-01")

        session = mgr.get_session("dev-01")
        session.state = UpdateState.TRANSFERRING

        session.last_activity = time.time() - (CHUNK_ACK_TIMEOUT + 1)
        timed_out = mgr.check_timeouts()

        assert "dev-01" in timed_out
        assert session.state == UpdateState.FAILED

    @pytest.mark.asyncio
    async def test_verify_timeout(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        await mgr.start_update("dev-01", "fw-01")

        session = mgr.get_session("dev-01")
        session.state = UpdateState.VERIFYING
        session.last_activity = time.time() - (VERIFY_TIMEOUT + 1)

        timed_out = mgr.check_timeouts()

        assert "dev-01" in timed_out
        assert session.state == UpdateState.FAILED

    @pytest.mark.asyncio
    async def test_complete_session_not_timed_out(self, tmp_path):
        """A COMPLETE session must never be marked timed-out."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")
        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.COMPLETE

        # Force very old last_activity
        session.last_activity = time.time() - 100_000
        timed_out = mgr.check_timeouts()

        assert "dev-01" not in timed_out
        assert session.state == UpdateState.COMPLETE

    @pytest.mark.asyncio
    async def test_only_stalled_session_times_out(self, tmp_path):
        """With two sessions, only the stalled one times out."""
        fw = _make_firmware(512)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0", "sensor", fw)
        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=256)

        await mgr.start_update("dev-01", "fw-01")
        await mgr.start_update("dev-02", "fw-01")

        # Only dev-01 is stale
        mgr.get_session("dev-01").last_activity = time.time() - (OFFER_TIMEOUT + 5)

        timed_out = mgr.check_timeouts()

        assert "dev-01" in timed_out
        assert "dev-02" not in timed_out
        assert mgr.get_session("dev-01").state == UpdateState.FAILED
        assert mgr.get_session("dev-02").state == UpdateState.OFFERED

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_terminal_sessions(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")
        session = mgr.get_session("dev-01")
        assert session.state == UpdateState.COMPLETE

        session.last_activity = time.time() - 301
        removed = mgr.cleanup_completed(max_age=300.0)

        assert removed == 1
        assert mgr.get_session("dev-01") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_sessions(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        # Session just completed — should NOT be cleaned up with max_age=300
        removed = mgr.cleanup_completed(max_age=300.0)

        assert removed == 0
        assert mgr.get_session("dev-01") is not None


# ===========================================================================
# 8. Progress Callback Accuracy
# ===========================================================================

class TestE2EProgressTracking:
    """Verify progress callbacks cover the full state lifecycle."""

    @pytest.mark.asyncio
    async def test_all_states_observed_in_happy_path(self, tmp_path):
        """Callbacks must observe OFFERED → TRANSFERRING → VERIFYING → COMPLETE."""
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        states: list[str] = []
        mgr.on_progress(lambda s: states.append(s.state.value))

        esp32 = FakeESP32("dev-01")
        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert "offered" in states
        assert "transferring" in states
        assert "verifying" in states
        assert "complete" in states

    @pytest.mark.asyncio
    async def test_progress_monotonic_during_transfer(self, tmp_path):
        fw = _make_firmware(2048)
        _, mgr = _make_store_and_mgr(tmp_path, fw, chunk_size=256)

        progress_values: list[float] = []
        mgr.on_progress(lambda s: progress_values.append(s.progress))

        esp32 = FakeESP32("dev-01")
        await drive_session(mgr, esp32, "dev-01", "fw-01")

        # Filter to only non-zero progress values recorded during transfer
        transfer_progress = [p for p in progress_values if 0 < p <= 1.0]
        for i in range(len(transfer_progress) - 1):
            assert transfer_progress[i] <= transfer_progress[i + 1], (
                f"Progress decreased: {transfer_progress[i]} → {transfer_progress[i + 1]}"
            )

    @pytest.mark.asyncio
    async def test_failed_state_in_callbacks_on_device_abort(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        states: list[str] = []
        mgr.on_progress(lambda s: states.append(s.state.value))

        esp32 = FakeESP32("dev-01", abort_after_seq=0)
        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert "failed" in states

    @pytest.mark.asyncio
    async def test_rejected_state_in_callbacks_on_anti_rollback(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        states: list[str] = []
        mgr.on_progress(lambda s: states.append(s.state.value))

        esp32 = FakeESP32("dev-01", anti_rollback_min=99)
        await drive_session(mgr, esp32, "dev-01", "fw-01")

        assert "rejected" in states

    @pytest.mark.asyncio
    async def test_callback_receives_correct_firmware_id(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw, fw_id="my-firmware", version="3.1.4")

        statuses: list[dict] = []
        mgr.on_progress(lambda s: statuses.append(s.to_status()))

        esp32 = FakeESP32("dev-01")
        await drive_session(mgr, esp32, "dev-01", "my-firmware")

        assert all(s["firmware_id"] == "my-firmware" for s in statuses)
        assert all(s["node_id"] == "dev-01" for s in statuses)


# ===========================================================================
# 9. Protocol Edge Cases
# ===========================================================================

class TestE2EProtocolEdgeCases:
    """Handle unexpected or malformed protocol messages gracefully."""

    @pytest.mark.asyncio
    async def test_spurious_message_from_unknown_device_ignored(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        spurious = MeshEnvelope(
            type=MsgType.OTA_CHUNK_ACK,
            source="ghost-device",
            target="hub",
            payload={"firmware_id": "fw-01", "seq": 0},
        )
        await mgr.handle_ota_message(spurious)  # must not raise

        assert mgr.get_session("ghost-device") is None

    @pytest.mark.asyncio
    async def test_wrong_firmware_id_in_accept_ignored(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        await mgr.start_update("dev-01", "fw-01")

        # Device accepts with wrong firmware_id
        wrong_accept = MeshEnvelope(
            type=MsgType.OTA_ACCEPT,
            source="dev-01",
            target="hub",
            payload={"firmware_id": "wrong-fw"},
        )
        await mgr.handle_ota_message(wrong_accept)

        # Session stays in OFFERED (message ignored)
        assert mgr.get_session("dev-01").state == UpdateState.OFFERED

    @pytest.mark.asyncio
    async def test_duplicate_chunk_ack_does_not_regress_progress(self, tmp_path):
        """Receiving the same ACK seq twice must not decrease progress."""
        fw = _make_firmware(1024)
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0", "sensor", fw)

        sent: list[MeshEnvelope] = []

        async def capture_send(env):
            sent.append(env)
            return True

        mgr = OTAManager(store, capture_send, node_id="hub", chunk_size=256)
        esp32 = FakeESP32("dev-01")
        await mgr.start_update("dev-01", "fw-01")

        # Process OFFER → ACCEPT
        for resp in esp32.handle(sent.pop(0)):
            await mgr.handle_ota_message(resp)

        # Process chunk 0
        chunk0 = next(e for e in sent if e.type == MsgType.OTA_CHUNK)
        sent.remove(chunk0)
        for resp in esp32.handle(chunk0):
            await mgr.handle_ota_message(resp)

        session = mgr.get_session("dev-01")
        progress_after_first = session.acked_up_to

        # Replay duplicate ACK for seq=0
        dup_ack = MeshEnvelope(
            type=MsgType.OTA_CHUNK_ACK,
            source="dev-01",
            target="hub",
            payload={"firmware_id": "fw-01", "seq": 0},
        )
        await mgr.handle_ota_message(dup_ack)

        assert session.acked_up_to >= progress_after_first

    @pytest.mark.asyncio
    async def test_accept_in_wrong_state_ignored(self, tmp_path):
        fw = _make_firmware(512)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        await mgr.start_update("dev-01", "fw-01")

        session = mgr.get_session("dev-01")
        session.state = UpdateState.TRANSFERRING  # Already in transfer

        late_accept = MeshEnvelope(
            type=MsgType.OTA_ACCEPT,
            source="dev-01",
            target="hub",
            payload={"firmware_id": "fw-01"},
        )
        await mgr.handle_ota_message(late_accept)

        assert session.state == UpdateState.TRANSFERRING

    @pytest.mark.asyncio
    async def test_start_update_unknown_firmware_returns_none(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        session = await mgr.start_update("dev-01", "does-not-exist")

        assert session is None

    @pytest.mark.asyncio
    async def test_start_duplicate_active_session_returns_none(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)

        s1 = await mgr.start_update("dev-01", "fw-01")
        s2 = await mgr.start_update("dev-01", "fw-01")

        assert s1 is not None
        assert s2 is None

    @pytest.mark.asyncio
    async def test_list_sessions_reflects_all_active(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        store.add_firmware("fw-01", "1.0", "sensor", _make_firmware(256))
        store.add_firmware("fw-02", "2.0", "light", _make_firmware(256))
        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=256)

        await mgr.start_update("dev-01", "fw-01")
        await mgr.start_update("dev-02", "fw-02")

        sessions = mgr.list_sessions()
        node_ids = {s["node_id"] for s in sessions}
        assert "dev-01" in node_ids
        assert "dev-02" in node_ids


# ===========================================================================
# 10. Firmware Store Integration
# ===========================================================================

class TestE2EFirmwareStoreIntegration:
    """Firmware store state reflects OTA activity correctly."""

    @pytest.mark.asyncio
    async def test_multiple_firmware_versions_coexist(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        entries = [
            ("fw-1.0", "1.0.0", _make_firmware(512)),
            ("fw-1.1", "1.1.0", _make_firmware(768)),
            ("fw-2.0", "2.0.0", _make_firmware(1024)),
        ]
        for fw_id, ver, data in entries:
            store.add_firmware(fw_id, ver, "sensor", data)

        assert len(store.list_firmware()) == 3

        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=256)
        esp32 = FakeESP32("dev-01")
        session = await drive_session(mgr, esp32, "dev-01", "fw-2.0")

        assert session.state == UpdateState.COMPLETE

    @pytest.mark.asyncio
    async def test_sequential_ota_to_same_device(self, tmp_path):
        """Two sequential OTA sessions to the same device both succeed."""
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        fw_v1 = _make_firmware(512)
        fw_v2 = _make_firmware(768)
        store.add_firmware("fw-v1", "1.0", "sensor", fw_v1)
        store.add_firmware("fw-v2", "2.0", "sensor", fw_v2)

        mgr = OTAManager(store, AsyncMock(return_value=True), node_id="hub", chunk_size=256)

        esp1 = FakeESP32("dev-01")
        session1 = await drive_session(mgr, esp1, "dev-01", "fw-v1")
        assert session1.state == UpdateState.COMPLETE
        assert esp1.app_py_content == fw_v1

        esp2 = FakeESP32("dev-01")
        session2 = await drive_session(mgr, esp2, "dev-01", "fw-v2")
        assert session2.state == UpdateState.COMPLETE
        assert esp2.app_py_content == fw_v2

    def test_firmware_manifest_sha256_correct(self, tmp_path):
        store = FirmwareStore(str(tmp_path / "fw"))
        store.load()
        fw = _make_firmware(1024)
        info = store.add_firmware("fw-01", "1.0", "sensor", fw)

        assert info.sha256 == _sha256(fw)

        # Reload from disk and verify manifest persists correctly
        store2 = FirmwareStore(str(tmp_path / "fw"))
        store2.load()
        assert store2.get_firmware("fw-01").sha256 == _sha256(fw)

    @pytest.mark.asyncio
    async def test_get_status_after_complete(self, tmp_path):
        fw = _make_firmware(256)
        _, mgr = _make_store_and_mgr(tmp_path, fw)
        esp32 = FakeESP32("dev-01")

        await drive_session(mgr, esp32, "dev-01", "fw-01")

        status = mgr.get_status("dev-01")
        assert status is not None
        assert status["state"] == "complete"
        assert status["firmware_id"] == "fw-01"
        assert status["progress"] == 1.0

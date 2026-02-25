"""Tests for error recovery and fault tolerance (task 3.5).

Covers: RetryPolicy, retry_send, Watchdog, supervised_task,
discovery auto-prune, transport send_with_retry, OTA timeout/cleanup,
channel start/stop safety, protocol read_envelope safety.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.resilience import RetryPolicy, Watchdog, retry_send, supervised_task


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_retries == 3
        assert p.base_delay == 0.5
        assert p.max_delay == 10.0
        assert p.backoff_factor == 2.0

    def test_delay_for(self):
        p = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=10.0)
        assert p.delay_for(0) == 1.0
        assert p.delay_for(1) == 2.0
        assert p.delay_for(2) == 4.0
        assert p.delay_for(3) == 8.0
        assert p.delay_for(4) == 10.0  # capped

    def test_delay_respects_max(self):
        p = RetryPolicy(base_delay=5.0, backoff_factor=3.0, max_delay=6.0)
        assert p.delay_for(0) == 5.0
        assert p.delay_for(1) == 6.0  # 15 capped to 6


# ---------------------------------------------------------------------------
# retry_send
# ---------------------------------------------------------------------------

class TestRetrySend:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        fn = AsyncMock(return_value=True)
        result = await retry_send(fn, policy=RetryPolicy(max_retries=2, base_delay=0.01))
        assert result is True
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        fn = AsyncMock(side_effect=[False, False, True])
        result = await retry_send(
            fn, policy=RetryPolicy(max_retries=3, base_delay=0.01),
        )
        assert result is True
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self):
        fn = AsyncMock(return_value=False)
        result = await retry_send(
            fn, policy=RetryPolicy(max_retries=2, base_delay=0.01),
        )
        assert result is False
        assert fn.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_exception_in_send(self):
        fn = AsyncMock(side_effect=[OSError("net"), True])
        result = await retry_send(
            fn, policy=RetryPolicy(max_retries=1, base_delay=0.01),
        )
        assert result is True
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_all_exceptions(self):
        fn = AsyncMock(side_effect=OSError("down"))
        result = await retry_send(
            fn, policy=RetryPolicy(max_retries=1, base_delay=0.01),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_passes_args_through(self):
        fn = AsyncMock(return_value=True)
        await retry_send(fn, "arg1", "arg2", key="val", policy=RetryPolicy(base_delay=0.01))
        fn.assert_called_with("arg1", "arg2", key="val")

    @pytest.mark.asyncio
    async def test_no_retries(self):
        fn = AsyncMock(return_value=False)
        result = await retry_send(
            fn, policy=RetryPolicy(max_retries=0, base_delay=0.01),
        )
        assert result is False
        assert fn.call_count == 1


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

class TestWatchdog:
    @pytest.mark.asyncio
    async def test_callback_invoked(self):
        counter = {"n": 0}

        def tick():
            counter["n"] += 1

        w = Watchdog("test", tick, interval=0.05)
        w.start()
        await asyncio.sleep(0.18)
        w.stop()
        assert counter["n"] >= 2

    @pytest.mark.asyncio
    async def test_async_callback(self):
        counter = {"n": 0}

        async def tick():
            counter["n"] += 1

        w = Watchdog("test-async", tick, interval=0.05)
        w.start()
        await asyncio.sleep(0.18)
        w.stop()
        assert counter["n"] >= 2

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_stop(self):
        counter = {"n": 0}

        def tick():
            counter["n"] += 1
            if counter["n"] == 1:
                raise ValueError("boom")

        w = Watchdog("test-err", tick, interval=0.05)
        w.start()
        await asyncio.sleep(0.2)
        w.stop()
        # Should have continued after the exception
        assert counter["n"] >= 2

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        w = Watchdog("test-idle", lambda: None, interval=1.0)
        w.stop()  # Never started — should not raise
        w.start()
        w.stop()
        w.stop()  # Double stop — should not raise


# ---------------------------------------------------------------------------
# supervised_task
# ---------------------------------------------------------------------------

class TestSupervisedTask:
    @pytest.mark.asyncio
    async def test_normal_completion(self):
        async def good():
            return 42

        task = supervised_task(good(), name="test-good")
        result = await task
        assert result == 42

    @pytest.mark.asyncio
    async def test_exception_logged(self):
        async def bad():
            raise RuntimeError("oops")

        task = supervised_task(bad(), name="test-bad")
        with pytest.raises(RuntimeError):
            await task

    @pytest.mark.asyncio
    async def test_cancelled_no_error(self):
        async def slow():
            await asyncio.sleep(100)

        task = supervised_task(slow(), name="test-cancel")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Discovery auto-prune
# ---------------------------------------------------------------------------

class TestDiscoveryAutoPrune:
    def test_prune_watchdog_exists(self):
        from nanobot.mesh.discovery import UDPDiscovery
        d = UDPDiscovery("test", tcp_port=18800, peer_timeout=30.0)
        assert hasattr(d, "_prune_watchdog")
        assert isinstance(d._prune_watchdog, Watchdog)

    def test_prune_watchdog_interval(self):
        from nanobot.mesh.discovery import UDPDiscovery
        d = UDPDiscovery("test", tcp_port=18800, peer_timeout=20.0)
        assert d._prune_watchdog._interval == 10.0  # peer_timeout / 2

    def test_prune_removes_stale_peers(self):
        from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
        d = UDPDiscovery("test", tcp_port=18800, peer_timeout=5.0)
        d.peers["stale"] = PeerInfo(
            node_id="stale", ip="1.2.3.4", tcp_port=18800,
            last_seen=time.time() - 10,
        )
        d.peers["fresh"] = PeerInfo(
            node_id="fresh", ip="1.2.3.5", tcp_port=18800,
            last_seen=time.time(),
        )
        d.prune()
        assert "stale" not in d.peers
        assert "fresh" in d.peers

    def test_prune_fires_peer_lost_callback(self):
        from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
        d = UDPDiscovery("test", tcp_port=18800, peer_timeout=5.0)
        d.peers["gone"] = PeerInfo(
            node_id="gone", ip="1.2.3.4", tcp_port=18800,
            last_seen=time.time() - 10,
        )
        lost = []
        d.on_peer_lost(lambda nid: lost.append(nid))
        d.prune()
        assert lost == ["gone"]


# ---------------------------------------------------------------------------
# Transport send_with_retry
# ---------------------------------------------------------------------------

class TestTransportSendWithRetry:
    def _make_transport(self):
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.transport import MeshTransport
        disc = MagicMock(spec=UDPDiscovery)
        t = MeshTransport(
            node_id="hub", discovery=disc, tcp_port=18800,
            psk_auth_enabled=False,
        )
        return t

    @pytest.mark.asyncio
    async def test_send_with_retry_success(self):
        t = self._make_transport()
        t.send = AsyncMock(return_value=True)
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        env = MeshEnvelope(type=MsgType.COMMAND, source="hub", target="dev-01")
        result = await t.send_with_retry(env, policy=RetryPolicy(max_retries=2, base_delay=0.01))
        assert result is True
        assert t.send.call_count == 1

    @pytest.mark.asyncio
    async def test_send_with_retry_eventual_success(self):
        t = self._make_transport()
        t.send = AsyncMock(side_effect=[False, True])
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        env = MeshEnvelope(type=MsgType.COMMAND, source="hub", target="dev-01")
        result = await t.send_with_retry(env, policy=RetryPolicy(max_retries=2, base_delay=0.01))
        assert result is True
        assert t.send.call_count == 2

    @pytest.mark.asyncio
    async def test_send_with_retry_all_fail(self):
        t = self._make_transport()
        t.send = AsyncMock(return_value=False)
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        env = MeshEnvelope(type=MsgType.COMMAND, source="hub", target="dev-01")
        result = await t.send_with_retry(env, policy=RetryPolicy(max_retries=1, base_delay=0.01))
        assert result is False
        assert t.send.call_count == 2


# ---------------------------------------------------------------------------
# OTA timeout and cleanup
# ---------------------------------------------------------------------------

class TestOTATimeoutAndCleanup:
    def _make_ota_manager(self):
        from nanobot.mesh.ota import FirmwareInfo, FirmwareStore, OTAManager, OTASession, UpdateState
        store = MagicMock(spec=FirmwareStore)
        mgr = OTAManager(
            store=store,
            send_fn=AsyncMock(return_value=True),
            node_id="hub",
        )
        return mgr

    def test_check_timeouts_no_sessions(self):
        mgr = self._make_ota_manager()
        assert mgr.check_timeouts() == []

    def test_check_timeouts_stale_offered(self):
        from nanobot.mesh.ota import FirmwareInfo, OTASession, UpdateState
        mgr = self._make_ota_manager()
        fw = FirmwareInfo(
            firmware_id="fw1", version="1.0", device_type="sensor",
            filename="fw.bin", size=1024, sha256="abc",
        )
        session = OTASession(node_id="dev-01", firmware=fw)
        session.state = UpdateState.OFFERED
        session.last_activity = time.time() - 120  # Stale (> OFFER_TIMEOUT=60)
        mgr._sessions["dev-01"] = session
        result = mgr.check_timeouts()
        assert "dev-01" in result
        assert session.state == UpdateState.FAILED
        assert "timeout" in session.error

    def test_check_timeouts_fresh_session_not_affected(self):
        from nanobot.mesh.ota import FirmwareInfo, OTASession, UpdateState
        mgr = self._make_ota_manager()
        fw = FirmwareInfo(
            firmware_id="fw1", version="1.0", device_type="sensor",
            filename="fw.bin", size=1024, sha256="abc",
        )
        session = OTASession(node_id="dev-01", firmware=fw)
        session.state = UpdateState.TRANSFERRING
        session.last_activity = time.time()  # Fresh
        mgr._sessions["dev-01"] = session
        result = mgr.check_timeouts()
        assert result == []
        assert session.state == UpdateState.TRANSFERRING

    def test_check_timeouts_skips_terminal(self):
        from nanobot.mesh.ota import FirmwareInfo, OTASession, UpdateState
        mgr = self._make_ota_manager()
        fw = FirmwareInfo(
            firmware_id="fw1", version="1.0", device_type="sensor",
            filename="fw.bin", size=1024, sha256="abc",
        )
        session = OTASession(node_id="dev-01", firmware=fw)
        session.state = UpdateState.COMPLETE
        session.last_activity = time.time() - 1000
        mgr._sessions["dev-01"] = session
        result = mgr.check_timeouts()
        assert result == []

    def test_cleanup_completed(self):
        from nanobot.mesh.ota import FirmwareInfo, OTASession, UpdateState
        mgr = self._make_ota_manager()
        fw = FirmwareInfo(
            firmware_id="fw1", version="1.0", device_type="sensor",
            filename="fw.bin", size=1024, sha256="abc",
        )
        # Old completed session
        s1 = OTASession(node_id="dev-01", firmware=fw)
        s1.state = UpdateState.COMPLETE
        s1.last_activity = time.time() - 600
        mgr._sessions["dev-01"] = s1

        # Recent failed session (should NOT be cleaned)
        s2 = OTASession(node_id="dev-02", firmware=fw)
        s2.state = UpdateState.FAILED
        s2.last_activity = time.time()
        mgr._sessions["dev-02"] = s2

        # Active session (should NOT be cleaned)
        s3 = OTASession(node_id="dev-03", firmware=fw)
        s3.state = UpdateState.TRANSFERRING
        s3.last_activity = time.time() - 600
        mgr._sessions["dev-03"] = s3

        removed = mgr.cleanup_completed(max_age=300)
        assert removed == 1
        assert "dev-01" not in mgr._sessions
        assert "dev-02" in mgr._sessions
        assert "dev-03" in mgr._sessions

    def test_cleanup_completed_no_sessions(self):
        mgr = self._make_ota_manager()
        assert mgr.cleanup_completed() == 0


# ---------------------------------------------------------------------------
# Channel start/stop safety
# ---------------------------------------------------------------------------

class TestChannelStartStopSafety:
    def _make_channel(self, tmp_path):
        config = MagicMock()
        config.node_id = "hub-test"
        config.tcp_port = 0
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
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = str(tmp_path / "groups.json")
        config.scenes_path = str(tmp_path / "scenes.json")
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config._workspace_path = str(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        return ch

    @pytest.mark.asyncio
    async def test_stop_transport_error_doesnt_break_discovery_stop(self, tmp_path):
        ch = self._make_channel(tmp_path)
        ch.transport.stop = AsyncMock(side_effect=RuntimeError("transport boom"))
        ch.discovery.stop = AsyncMock()
        await ch.stop()
        # Discovery.stop should still have been called
        ch.discovery.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_transport_failure_stops_discovery(self, tmp_path):
        ch = self._make_channel(tmp_path)
        ch.discovery.start = AsyncMock()
        ch.transport.start = AsyncMock(side_effect=RuntimeError("bind fail"))
        ch.discovery.stop = AsyncMock()

        with pytest.raises(RuntimeError, match="bind fail"):
            await ch.start()
        # Discovery should have been stopped after transport failure
        ch.discovery.stop.assert_called_once()
        assert ch._running is False

    @pytest.mark.asyncio
    async def test_start_discovery_failure_doesnt_start_transport(self, tmp_path):
        ch = self._make_channel(tmp_path)
        ch.discovery.start = AsyncMock(side_effect=RuntimeError("socket fail"))
        ch.transport.start = AsyncMock()

        with pytest.raises(RuntimeError, match="socket fail"):
            await ch.start()
        ch.transport.start.assert_not_called()
        assert ch._running is False


# ---------------------------------------------------------------------------
# Protocol read_envelope safety
# ---------------------------------------------------------------------------

class TestReadEnvelopeSafety:
    @pytest.mark.asyncio
    async def test_malformed_json(self):
        from nanobot.mesh.protocol import read_envelope
        # Build a length-prefixed payload of invalid JSON
        body = b"{not valid json}"
        header = struct.pack("!I", len(body))
        reader = AsyncMock()
        reader.readexactly = AsyncMock(side_effect=[header, body])
        result = await read_envelope(reader)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_envelope(self):
        from nanobot.mesh.protocol import MeshEnvelope, MsgType, read_envelope
        env = MeshEnvelope(type=MsgType.PING, source="a", target="b")
        body = json.dumps(env.to_dict()).encode()
        header = struct.pack("!I", len(body))
        reader = AsyncMock()
        reader.readexactly = AsyncMock(side_effect=[header, body])
        result = await read_envelope(reader)
        assert result is not None
        assert result.type == MsgType.PING

    @pytest.mark.asyncio
    async def test_invalid_struct(self):
        from nanobot.mesh.protocol import read_envelope
        reader = AsyncMock()
        # Return only 2 bytes instead of 4 for the header — struct.error
        reader.readexactly = AsyncMock(side_effect=[b"\x00\x00", b""])
        result = await read_envelope(reader)
        assert result is None

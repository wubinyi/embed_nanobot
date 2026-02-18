"""Tests for the LAN mesh communication module."""

import asyncio
import json
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.channel import MeshChannel, _default_node_id
from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
from nanobot.mesh.enrollment import EnrollmentService, PendingEnrollment, _PBKDF2_ITERATIONS, _PSK_BYTES
from nanobot.mesh.encryption import (
    HAS_AESGCM,
    build_aad,
    decrypt_payload,
    derive_encryption_key,
    encrypt_payload,
    is_available,
)
from nanobot.mesh.protocol import MeshEnvelope, MsgType, read_envelope, write_envelope
from nanobot.mesh.security import KeyStore
from nanobot.mesh.transport import MeshTransport

# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------


class TestMeshEnvelope:
    """Tests for MeshEnvelope serialisation / deserialisation."""

    def test_roundtrip(self):
        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="node-a",
            target="node-b",
            payload={"text": "hello"},
            ts=1700000000.0,
        )
        raw = env.to_bytes()
        # First 4 bytes are the length prefix
        (length,) = struct.unpack("!I", raw[:4])
        body = raw[4:]
        assert len(body) == length

        restored = MeshEnvelope.from_bytes(body)
        assert restored.type == MsgType.CHAT
        assert restored.source == "node-a"
        assert restored.target == "node-b"
        assert restored.payload == {"text": "hello"}
        assert restored.ts == 1700000000.0

    def test_broadcast_target(self):
        env = MeshEnvelope(type=MsgType.PING, source="a", target="*")
        raw = env.to_bytes()
        body = raw[4:]
        restored = MeshEnvelope.from_bytes(body)
        assert restored.target == "*"

    def test_empty_payload(self):
        env = MeshEnvelope(type=MsgType.PONG, source="a", target="b")
        raw = env.to_bytes()
        body = raw[4:]
        restored = MeshEnvelope.from_bytes(body)
        assert restored.payload == {}


class TestReadWriteEnvelope:
    """Tests for stream-based read/write helpers."""

    @pytest.mark.asyncio
    async def test_read_envelope(self):
        env = MeshEnvelope(
            type=MsgType.COMMAND,
            source="hub",
            target="vacuum",
            payload={"action": "start_cleaning"},
        )
        raw = env.to_bytes()

        reader = AsyncMock()
        reader.readexactly = AsyncMock(side_effect=[raw[:4], raw[4:]])

        result = await read_envelope(reader)
        assert result is not None
        assert result.type == MsgType.COMMAND
        assert result.source == "hub"
        assert result.payload["action"] == "start_cleaning"

    def test_write_envelope(self):
        env = MeshEnvelope(type=MsgType.CHAT, source="a", target="b", payload={"text": "hi"})
        writer = MagicMock()
        write_envelope(writer, env)
        writer.write.assert_called_once()
        written = writer.write.call_args[0][0]
        assert isinstance(written, bytes)
        # Verify it's a valid length-prefixed message
        (length,) = struct.unpack("!I", written[:4])
        body = json.loads(written[4:])
        assert body["type"] == "chat"


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestUDPDiscovery:
    """Tests for peer discovery logic (unit-level, no real sockets)."""

    def test_handle_beacon_adds_peer(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800)
        beacon = json.dumps({
            "node_id": "other",
            "tcp_port": 18800,
            "roles": ["device", "vacuum"],
        }).encode()

        disc._handle_beacon(beacon, "192.168.1.42")

        assert "other" in disc.peers
        peer = disc.peers["other"]
        assert peer.ip == "192.168.1.42"
        assert peer.tcp_port == 18800
        assert peer.roles == ["device", "vacuum"]

    def test_handle_beacon_ignores_own(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800)
        beacon = json.dumps({"node_id": "me", "tcp_port": 18800}).encode()
        disc._handle_beacon(beacon, "192.168.1.1")
        assert "me" not in disc.peers

    def test_handle_beacon_ignores_invalid_json(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800)
        disc._handle_beacon(b"not json!", "1.2.3.4")
        assert len(disc.peers) == 0

    def test_get_peer_online(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800, peer_timeout=30.0)
        disc.peers["other"] = PeerInfo(
            node_id="other", ip="10.0.0.2", tcp_port=18800, last_seen=time.time()
        )
        peer = disc.get_peer("other")
        assert peer is not None
        assert peer.ip == "10.0.0.2"

    def test_get_peer_stale(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800, peer_timeout=30.0)
        disc.peers["other"] = PeerInfo(
            node_id="other", ip="10.0.0.2", tcp_port=18800,
            last_seen=time.time() - 60,
        )
        assert disc.get_peer("other") is None

    def test_online_peers(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800, peer_timeout=30.0)
        now = time.time()
        disc.peers["a"] = PeerInfo(node_id="a", ip="10.0.0.2", tcp_port=18800, last_seen=now)
        disc.peers["b"] = PeerInfo(node_id="b", ip="10.0.0.3", tcp_port=18800, last_seen=now - 60)
        online = disc.online_peers()
        assert len(online) == 1
        assert online[0].node_id == "a"

    def test_prune(self):
        disc = UDPDiscovery(node_id="me", tcp_port=18800, peer_timeout=30.0)
        disc.peers["stale"] = PeerInfo(
            node_id="stale", ip="10.0.0.5", tcp_port=18800,
            last_seen=time.time() - 60,
        )
        disc.peers["fresh"] = PeerInfo(
            node_id="fresh", ip="10.0.0.6", tcp_port=18800,
            last_seen=time.time(),
        )
        disc.prune()
        assert "stale" not in disc.peers
        assert "fresh" in disc.peers


# ---------------------------------------------------------------------------
# Transport integration tests (real TCP on localhost)
# ---------------------------------------------------------------------------


class TestMeshTransport:
    """Integration tests that use real TCP connections on localhost."""

    @pytest.mark.asyncio
    async def test_send_and_receive(self):
        """Two transports can exchange a message over TCP."""
        received: list[MeshEnvelope] = []

        disc_a = UDPDiscovery(node_id="node-a", tcp_port=0)
        disc_b = UDPDiscovery(node_id="node-b", tcp_port=0)

        transport_a = MeshTransport(node_id="node-a", discovery=disc_a, tcp_port=0)
        transport_b = MeshTransport(node_id="node-b", discovery=disc_b, tcp_port=0)

        async def handler(env: MeshEnvelope) -> None:
            received.append(env)

        transport_b.on_message(handler)

        await transport_a.start()
        await transport_b.start()

        # Get actual port assigned by the OS for transport_b
        port_b = transport_b._server.sockets[0].getsockname()[1]

        # Register b as a peer of a
        disc_a.peers["node-b"] = PeerInfo(
            node_id="node-b", ip="127.0.0.1", tcp_port=port_b
        )

        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="node-a",
            target="node-b",
            payload={"text": "hello from a"},
        )
        ok = await transport_a.send(env)
        assert ok is True

        # Give the server time to process
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].source == "node-a"
        assert received[0].payload["text"] == "hello from a"

        await transport_a.stop()
        await transport_b.stop()

    @pytest.mark.asyncio
    async def test_send_to_unknown_peer(self):
        """Sending to an unknown peer returns False."""
        disc = UDPDiscovery(node_id="node-a", tcp_port=0)
        transport = MeshTransport(node_id="node-a", discovery=disc, tcp_port=0)
        await transport.start()

        env = MeshEnvelope(
            type=MsgType.CHAT, source="node-a", target="ghost", payload={}
        )
        ok = await transport.send(env)
        assert ok is False

        await transport.stop()


# ---------------------------------------------------------------------------
# MeshChannel tests
# ---------------------------------------------------------------------------


class TestMeshChannel:
    """Tests for the MeshChannel (bus integration)."""

    def test_default_node_id(self):
        nid = _default_node_id()
        assert nid.startswith("nanobot-")

    @pytest.mark.asyncio
    async def test_on_mesh_message_publishes_to_bus(self):
        """A CHAT envelope becomes an InboundMessage on the bus."""
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        config = MagicMock()
        config.node_id = "test-hub"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.allow_from = []
        config.psk_auth_enabled = False
        config.key_store_path = ""
        config.allow_unauthenticated = False
        config.nonce_window = 60

        channel = MeshChannel(config, bus, node_id="test-hub", tcp_port=0, udp_port=0)

        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="vacuum-1",
            target="test-hub",
            payload={"text": "cleaning done"},
        )
        await channel._on_mesh_message(env)

        assert bus.inbound_size == 1
        msg = await bus.consume_inbound()
        assert msg.channel == "mesh"
        assert msg.sender_id == "vacuum-1"
        assert msg.content == "cleaning done"

    @pytest.mark.asyncio
    async def test_on_mesh_message_ignores_ping(self):
        """PING messages are not forwarded to the agent loop."""
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        config = MagicMock()
        config.node_id = "hub"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.allow_from = []
        config.psk_auth_enabled = False
        config.key_store_path = ""
        config.allow_unauthenticated = False
        config.nonce_window = 60

        channel = MeshChannel(config, bus, node_id="hub", tcp_port=0, udp_port=0)

        env = MeshEnvelope(type=MsgType.PING, source="x", target="hub")
        await channel._on_mesh_message(env)

        assert bus.inbound_size == 0

    @pytest.mark.asyncio
    async def test_on_mesh_message_ignores_empty_text(self):
        """CHAT with empty text is ignored."""
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        config = MagicMock()
        config.node_id = "hub"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.allow_from = []
        config.psk_auth_enabled = False
        config.key_store_path = ""
        config.allow_unauthenticated = False
        config.nonce_window = 60

        channel = MeshChannel(config, bus, node_id="hub", tcp_port=0, udp_port=0)

        env = MeshEnvelope(
            type=MsgType.CHAT, source="x", target="hub", payload={}
        )
        await channel._on_mesh_message(env)

        assert bus.inbound_size == 0


# ---------------------------------------------------------------------------
# Config schema tests
# ---------------------------------------------------------------------------


class TestMeshConfig:
    """Tests for MeshConfig in the schema."""

    def test_default_mesh_config(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig()
        assert cfg.enabled is False
        assert cfg.tcp_port == 18800
        assert cfg.udp_port == 18799
        assert cfg.roles == ["nanobot"]
        # PSK auth defaults (task 1.9)
        assert cfg.psk_auth_enabled is True
        assert cfg.key_store_path == ""
        assert cfg.allow_unauthenticated is False
        assert cfg.nonce_window == 60

    def test_channels_config_has_mesh(self):
        from nanobot.config.schema import ChannelsConfig
        channels = ChannelsConfig()
        assert hasattr(channels, "mesh")
        assert channels.mesh.enabled is False


# ---------------------------------------------------------------------------
# PSK Authentication tests (task 1.9)
# ---------------------------------------------------------------------------


class TestKeyStore:
    """Tests for the KeyStore — PSK management, HMAC, nonce tracking."""

    def test_add_and_get_device(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json")
        psk = ks.add_device("dev-01", name="Light")
        assert len(psk) == 64  # 32 bytes hex
        assert ks.has_device("dev-01")
        assert ks.get_psk("dev-01") == psk
        assert ks.get_psk("unknown") is None

    def test_remove_device(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json")
        ks.add_device("dev-01")
        assert ks.remove_device("dev-01") is True
        assert ks.has_device("dev-01") is False
        assert ks.remove_device("dev-01") is False

    def test_list_devices(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json")
        ks.add_device("dev-01", name="Light")
        ks.add_device("dev-02", name="Lock")
        devices = ks.list_devices()
        assert len(devices) == 2
        assert "dev-01" in devices
        assert devices["dev-01"].name == "Light"

    def test_persistence(self, tmp_path):
        path = tmp_path / "keys.json"
        ks1 = KeyStore(path=path)
        psk = ks1.add_device("dev-01", name="Sensor")

        ks2 = KeyStore(path=path)
        ks2.load()
        assert ks2.get_psk("dev-01") == psk
        assert ks2.list_devices()["dev-01"].name == "Sensor"

    def test_load_nonexistent(self, tmp_path):
        """Loading from a missing file is a no-op."""
        ks = KeyStore(path=tmp_path / "missing.json")
        ks.load()
        assert len(ks.list_devices()) == 0

    def test_psk_rotation(self, tmp_path):
        """Adding a device that already exists rotates its PSK."""
        ks = KeyStore(path=tmp_path / "keys.json")
        psk1 = ks.add_device("dev-01")
        psk2 = ks.add_device("dev-01")
        assert psk1 != psk2
        assert ks.get_psk("dev-01") == psk2


class TestHMAC:
    """Tests for HMAC signing and verification."""

    def test_sign_and_verify(self):
        psk = "ab" * 32  # 64 hex chars = 32 bytes
        body = b'{"source":"a","target":"b","type":"chat"}'
        nonce = "1234567890abcdef"

        sig = KeyStore.compute_hmac(body, nonce, psk)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

        assert KeyStore.verify_hmac(body, nonce, psk, sig) is True

    def test_verify_fails_wrong_psk(self):
        psk_a = "aa" * 32
        psk_b = "bb" * 32
        body = b'{"msg":"hello"}'
        nonce = "aaaa"

        sig = KeyStore.compute_hmac(body, nonce, psk_a)
        assert KeyStore.verify_hmac(body, nonce, psk_b, sig) is False

    def test_verify_fails_wrong_nonce(self):
        psk = "cc" * 32
        body = b'{"msg":"hello"}'
        nonce_a = "aaaa"
        nonce_b = "bbbb"

        sig = KeyStore.compute_hmac(body, nonce_a, psk)
        assert KeyStore.verify_hmac(body, nonce_b, psk, sig) is False

    def test_verify_fails_tampered_body(self):
        psk = "dd" * 32
        body = b'{"msg":"hello"}'
        nonce = "1111"

        sig = KeyStore.compute_hmac(body, nonce, psk)
        assert KeyStore.verify_hmac(b'{"msg":"tampered"}', nonce, psk, sig) is False

    def test_canonical_bytes_excludes_hmac_nonce(self):
        d = {"type": "chat", "source": "a", "target": "b", "ts": 1.0, "hmac": "xxx", "nonce": "yyy"}
        canonical = KeyStore.canonical_bytes(d)
        import json
        parsed = json.loads(canonical)
        assert "hmac" not in parsed
        assert "nonce" not in parsed
        assert parsed["type"] == "chat"

    def test_canonical_bytes_sorted_keys(self):
        d1 = {"type": "chat", "source": "a", "target": "b"}
        d2 = {"target": "b", "type": "chat", "source": "a"}
        assert KeyStore.canonical_bytes(d1) == KeyStore.canonical_bytes(d2)


class TestNonceTracking:
    """Tests for replay protection via nonce tracking."""

    def test_fresh_nonce_accepted(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json", nonce_window=60)
        assert ks.check_and_record_nonce("nonce-1") is True

    def test_duplicate_nonce_rejected(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json", nonce_window=60)
        ks.check_and_record_nonce("nonce-1")
        assert ks.check_and_record_nonce("nonce-1") is False

    def test_different_nonces_accepted(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json", nonce_window=60)
        assert ks.check_and_record_nonce("nonce-1") is True
        assert ks.check_and_record_nonce("nonce-2") is True

    def test_stale_nonce_pruned(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json", nonce_window=1)
        ks.check_and_record_nonce("old-nonce")
        # Manually age the nonce
        ks._seen_nonces["old-nonce"] = time.time() - 2.0
        # After pruning, the "old" nonce should be accepted again
        assert ks.check_and_record_nonce("old-nonce") is True

    def test_timestamp_validation(self, tmp_path):
        ks = KeyStore(path=tmp_path / "keys.json", nonce_window=60)
        assert ks.check_timestamp(time.time()) is True
        assert ks.check_timestamp(time.time() - 30) is True
        assert ks.check_timestamp(time.time() - 120) is False
        assert ks.check_timestamp(time.time() + 120) is False


class TestEnvelopeAuth:
    """Tests for MeshEnvelope HMAC fields and canonical serialisation."""

    def test_envelope_with_auth_fields_roundtrip(self):
        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="dev-01",
            target="hub",
            payload={"text": "hi"},
            nonce="abc123",
            hmac="def456",
        )
        raw = env.to_bytes()
        body = raw[4:]
        restored = MeshEnvelope.from_bytes(body)
        assert restored.nonce == "abc123"
        assert restored.hmac == "def456"

    def test_envelope_without_auth_backward_compatible(self):
        """Envelopes without hmac/nonce still deserialise cleanly."""
        env = MeshEnvelope(
            type=MsgType.CHAT, source="a", target="b", payload={"text": "hi"}
        )
        raw = env.to_bytes()
        body = raw[4:]
        restored = MeshEnvelope.from_bytes(body)
        assert restored.hmac == ""
        assert restored.nonce == ""

    def test_canonical_bytes_deterministic(self):
        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="a",
            target="b",
            payload={"text": "hi"},
            ts=1700000000.0,
            nonce="xxx",
            hmac="yyy",
        )
        c1 = env.canonical_bytes()
        c2 = env.canonical_bytes()
        assert c1 == c2
        # hmac and nonce must be excluded
        import json
        parsed = json.loads(c1)
        assert "hmac" not in parsed
        assert "nonce" not in parsed

    def test_sign_verify_envelope_end_to_end(self):
        """Full sign/verify cycle using MeshEnvelope methods."""
        psk = "ee" * 32
        env = MeshEnvelope(
            type=MsgType.COMMAND,
            source="dev-01",
            target="hub",
            payload={"action": "turn_on"},
            ts=1700000000.0,
        )
        # Sign
        env.nonce = KeyStore.generate_nonce()
        canonical = env.canonical_bytes()
        env.hmac = KeyStore.compute_hmac(canonical, env.nonce, psk)

        # Verify (receiver side)
        canonical2 = env.canonical_bytes()
        assert KeyStore.verify_hmac(canonical2, env.nonce, psk, env.hmac) is True


class TestTransportAuth:
    """Integration tests for authenticated transport."""

    @pytest.mark.asyncio
    async def test_authenticated_send_receive(self):
        """Authenticated messages pass through when both sides share a PSK."""
        received: list[MeshEnvelope] = []

        disc_a = UDPDiscovery(node_id="node-a", tcp_port=0)
        disc_b = UDPDiscovery(node_id="node-b", tcp_port=0)

        # Create shared key stores
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        ks_a = KeyStore(path=os.path.join(tmpdir, "keys_a.json"), nonce_window=60)
        ks_b = KeyStore(path=os.path.join(tmpdir, "keys_b.json"), nonce_window=60)

        # Enroll both nodes in both stores with same PSK
        psk_a = ks_a.add_device("node-a", name="Node A")
        psk_b = ks_a.add_device("node-b", name="Node B")
        # Manually set same PSKs in ks_b
        ks_b._devices["node-a"] = ks_a._devices["node-a"]
        ks_b._devices["node-b"] = ks_a._devices["node-b"]

        transport_a = MeshTransport(
            node_id="node-a", discovery=disc_a, tcp_port=0,
            key_store=ks_a, psk_auth_enabled=True,
            encryption_enabled=False,  # Test auth only, not encryption
        )
        transport_b = MeshTransport(
            node_id="node-b", discovery=disc_b, tcp_port=0,
            key_store=ks_b, psk_auth_enabled=True,
            encryption_enabled=False,  # Test auth only, not encryption
        )

        async def handler(env: MeshEnvelope) -> None:
            received.append(env)

        transport_b.on_message(handler)

        await transport_a.start()
        await transport_b.start()

        port_b = transport_b._server.sockets[0].getsockname()[1]
        disc_a.peers["node-b"] = PeerInfo(
            node_id="node-b", ip="127.0.0.1", tcp_port=port_b
        )

        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="node-a",
            target="node-b",
            payload={"text": "authenticated hello"},
        )
        ok = await transport_a.send(env)
        assert ok is True

        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload["text"] == "authenticated hello"

        await transport_a.stop()
        await transport_b.stop()

        # Cleanup
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_unauthenticated_message_rejected(self):
        """Messages without HMAC are rejected when auth is enabled."""
        received: list[MeshEnvelope] = []

        disc_a = UDPDiscovery(node_id="node-a", tcp_port=0)
        disc_b = UDPDiscovery(node_id="node-b", tcp_port=0)

        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        ks_b = KeyStore(path=os.path.join(tmpdir, "keys_b.json"), nonce_window=60)
        ks_b.add_device("node-a", name="Node A")

        # node-a sends WITHOUT auth (no key store)
        transport_a = MeshTransport(
            node_id="node-a", discovery=disc_a, tcp_port=0,
            psk_auth_enabled=False,  # sender has no auth
        )
        # node-b expects auth
        transport_b = MeshTransport(
            node_id="node-b", discovery=disc_b, tcp_port=0,
            key_store=ks_b, psk_auth_enabled=True,
        )

        async def handler(env: MeshEnvelope) -> None:
            received.append(env)

        transport_b.on_message(handler)

        await transport_a.start()
        await transport_b.start()

        port_b = transport_b._server.sockets[0].getsockname()[1]
        disc_a.peers["node-b"] = PeerInfo(
            node_id="node-b", ip="127.0.0.1", tcp_port=port_b
        )

        env = MeshEnvelope(
            type=MsgType.CHAT, source="node-a", target="node-b",
            payload={"text": "unsigned"},
        )
        await transport_a.send(env)
        await asyncio.sleep(0.2)

        # Message should NOT be delivered
        assert len(received) == 0

        await transport_a.stop()
        await transport_b.stop()

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_unknown_node_rejected(self):
        """Messages from unenrolled nodes are rejected."""
        received: list[MeshEnvelope] = []

        disc_a = UDPDiscovery(node_id="rogue", tcp_port=0)
        disc_b = UDPDiscovery(node_id="node-b", tcp_port=0)

        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        # ks_a has rogue's own key, but ks_b does NOT have rogue enrolled
        ks_a = KeyStore(path=os.path.join(tmpdir, "keys_a.json"), nonce_window=60)
        ks_a.add_device("rogue")
        ks_b = KeyStore(path=os.path.join(tmpdir, "keys_b.json"), nonce_window=60)
        # ks_b has no "rogue" entry

        transport_a = MeshTransport(
            node_id="rogue", discovery=disc_a, tcp_port=0,
            key_store=ks_a, psk_auth_enabled=True,
        )
        transport_b = MeshTransport(
            node_id="node-b", discovery=disc_b, tcp_port=0,
            key_store=ks_b, psk_auth_enabled=True,
        )

        async def handler(env: MeshEnvelope) -> None:
            received.append(env)

        transport_b.on_message(handler)

        await transport_a.start()
        await transport_b.start()

        port_b = transport_b._server.sockets[0].getsockname()[1]
        disc_a.peers["node-b"] = PeerInfo(
            node_id="node-b", ip="127.0.0.1", tcp_port=port_b
        )

        env = MeshEnvelope(
            type=MsgType.CHAT, source="rogue", target="node-b",
            payload={"text": "intruder"},
        )
        await transport_a.send(env)
        await asyncio.sleep(0.2)

        assert len(received) == 0

        await transport_a.stop()
        await transport_b.stop()

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_allow_unauthenticated_mode(self):
        """With allow_unauthenticated=True, unsigned messages are processed."""
        received: list[MeshEnvelope] = []

        disc_a = UDPDiscovery(node_id="node-a", tcp_port=0)
        disc_b = UDPDiscovery(node_id="node-b", tcp_port=0)

        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        ks_b = KeyStore(path=os.path.join(tmpdir, "keys_b.json"), nonce_window=60)

        transport_a = MeshTransport(
            node_id="node-a", discovery=disc_a, tcp_port=0,
            psk_auth_enabled=False,
        )
        transport_b = MeshTransport(
            node_id="node-b", discovery=disc_b, tcp_port=0,
            key_store=ks_b, psk_auth_enabled=True,
            allow_unauthenticated=True,
        )

        async def handler(env: MeshEnvelope) -> None:
            received.append(env)

        transport_b.on_message(handler)

        await transport_a.start()
        await transport_b.start()

        port_b = transport_b._server.sockets[0].getsockname()[1]
        disc_a.peers["node-b"] = PeerInfo(
            node_id="node-b", ip="127.0.0.1", tcp_port=port_b
        )

        env = MeshEnvelope(
            type=MsgType.CHAT, source="node-a", target="node-b",
            payload={"text": "unsigned but allowed"},
        )
        await transport_a.send(env)
        await asyncio.sleep(0.2)

        # Should pass through with warning
        assert len(received) == 1

        await transport_a.stop()
        await transport_b.stop()

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Enrollment tests (task 1.10)
# ---------------------------------------------------------------------------


class TestPendingEnrollment:
    """Tests for PendingEnrollment state tracking."""

    def test_active_when_fresh(self):
        pe = PendingEnrollment(
            pin="123456",
            created_at=time.time(),
            expires_at=time.time() + 300,
        )
        assert pe.is_active
        assert not pe.is_expired
        assert not pe.is_locked
        assert not pe.used

    def test_expired(self):
        pe = PendingEnrollment(
            pin="123456",
            created_at=time.time() - 600,
            expires_at=time.time() - 1,
        )
        assert pe.is_expired
        assert not pe.is_active

    def test_locked_after_max_attempts(self):
        pe = PendingEnrollment(
            pin="123456",
            created_at=time.time(),
            expires_at=time.time() + 300,
            max_attempts=3,
        )
        pe.attempts = 3
        assert pe.is_locked
        assert not pe.is_active

    def test_used(self):
        pe = PendingEnrollment(
            pin="123456",
            created_at=time.time(),
            expires_at=time.time() + 300,
        )
        pe.used = True
        assert not pe.is_active


class TestEnrollmentCrypto:
    """Tests for enrollment cryptographic helpers."""

    def test_pin_proof_deterministic(self):
        proof1 = EnrollmentService.compute_pin_proof("482917", "esp32-kitchen")
        proof2 = EnrollmentService.compute_pin_proof("482917", "esp32-kitchen")
        assert proof1 == proof2
        assert len(proof1) == 64  # SHA-256 hex digest

    def test_pin_proof_different_pin(self):
        proof_a = EnrollmentService.compute_pin_proof("111111", "device-1")
        proof_b = EnrollmentService.compute_pin_proof("222222", "device-1")
        assert proof_a != proof_b

    def test_pin_proof_different_node(self):
        proof_a = EnrollmentService.compute_pin_proof("111111", "device-1")
        proof_b = EnrollmentService.compute_pin_proof("111111", "device-2")
        assert proof_a != proof_b

    def test_derive_temp_key_deterministic(self):
        salt = b"\x00" * 16
        key1 = EnrollmentService.derive_temp_key("482917", salt)
        key2 = EnrollmentService.derive_temp_key("482917", salt)
        assert key1 == key2
        assert len(key1) == 32

    def test_derive_temp_key_different_pin(self):
        salt = b"\x00" * 16
        key_a = EnrollmentService.derive_temp_key("111111", salt)
        key_b = EnrollmentService.derive_temp_key("222222", salt)
        assert key_a != key_b

    def test_derive_temp_key_different_salt(self):
        key_a = EnrollmentService.derive_temp_key("111111", b"\x00" * 16)
        key_b = EnrollmentService.derive_temp_key("111111", b"\xff" * 16)
        assert key_a != key_b

    def test_encrypt_decrypt_psk_roundtrip(self):
        """XOR one-time pad: encrypt then decrypt recovers the original PSK."""
        import secrets

        psk = secrets.token_bytes(32)
        salt = secrets.token_bytes(16)
        temp_key = EnrollmentService.derive_temp_key("482917", salt)
        encrypted = EnrollmentService.encrypt_psk(psk, temp_key)
        decrypted = EnrollmentService.encrypt_psk(encrypted, temp_key)
        assert decrypted == psk

    def test_encrypt_psk_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            EnrollmentService.encrypt_psk(b"\x00" * 16, b"\x00" * 32)
        with pytest.raises(ValueError):
            EnrollmentService.encrypt_psk(b"\x00" * 32, b"\x00" * 16)


class TestEnrollmentService:
    """Tests for the EnrollmentService PIN lifecycle and enrollment flow."""

    def _make_service(self, tmp_path, pin_length=6, pin_timeout=300, max_attempts=3):
        """Create an EnrollmentService with a real KeyStore and mock transport."""
        ks = KeyStore(path=tmp_path / "mesh_keys.json")
        transport = MagicMock()
        transport.send = AsyncMock(return_value=True)
        transport.send_to_address = AsyncMock(return_value=True)
        svc = EnrollmentService(
            key_store=ks,
            transport=transport,
            node_id="hub-node",
            pin_length=pin_length,
            pin_timeout=pin_timeout,
            max_attempts=max_attempts,
        )
        return svc, ks, transport

    def test_create_pin(self, tmp_path):
        svc, _, _ = self._make_service(tmp_path)
        pin, expires_at = svc.create_pin()
        assert len(pin) == 6
        assert pin.isdigit()
        assert expires_at > time.time()
        assert svc.is_enrollment_active

    def test_cancel_pin(self, tmp_path):
        svc, _, _ = self._make_service(tmp_path)
        svc.create_pin()
        assert svc.cancel_pin() is True
        assert not svc.is_enrollment_active
        # Cancel again should return False
        assert svc.cancel_pin() is False

    def test_cancel_without_active_pin(self, tmp_path):
        svc, _, _ = self._make_service(tmp_path)
        assert svc.cancel_pin() is False

    def test_pin_replaces_previous(self, tmp_path):
        svc, _, _ = self._make_service(tmp_path)
        pin1, _ = svc.create_pin()
        pin2, _ = svc.create_pin()
        # Second PIN replaces first; first is no longer the active PIN
        assert svc.is_enrollment_active
        # The active PIN is pin2
        assert svc._pending.pin == pin2

    @pytest.mark.asyncio
    async def test_enroll_happy_path(self, tmp_path):
        """Full successful enrollment flow."""
        svc, ks, transport = self._make_service(tmp_path)
        pin, _ = svc.create_pin()
        device_id = "esp32-sensor"
        pin_proof = EnrollmentService.compute_pin_proof(pin, device_id)

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source=device_id,
            target="*",
            payload={"name": "Kitchen Sensor", "pin_proof": pin_proof},
        )
        await svc.handle_enroll_request(env)

        # Device should now be enrolled
        assert ks.has_device(device_id)
        psk = ks.get_psk(device_id)
        assert psk is not None
        assert len(psk) == 64  # 32 bytes = 64 hex chars

        # PIN should be used up
        assert not svc.is_enrollment_active

        # Transport.send should have been called with ENROLL_RESPONSE
        transport.send.assert_called_once()
        response_env = transport.send.call_args[0][0]
        assert response_env.type == MsgType.ENROLL_RESPONSE
        assert response_env.target == device_id
        assert response_env.payload["status"] == "ok"

        # Verify the device can decrypt the PSK
        encrypted_psk_hex = response_env.payload["encrypted_psk"]
        salt_hex = response_env.payload["salt"]
        temp_key = EnrollmentService.derive_temp_key(pin, bytes.fromhex(salt_hex))
        decrypted_psk = EnrollmentService.encrypt_psk(
            bytes.fromhex(encrypted_psk_hex), temp_key
        )
        assert decrypted_psk.hex() == psk

    @pytest.mark.asyncio
    async def test_enroll_wrong_pin(self, tmp_path):
        """Wrong PIN proof should be rejected."""
        svc, ks, transport = self._make_service(tmp_path)
        svc.create_pin()

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="bad-device",
            target="*",
            payload={"name": "Bad", "pin_proof": "wrong_proof"},
        )
        await svc.handle_enroll_request(env)

        assert not ks.has_device("bad-device")
        assert svc._pending.attempts == 1
        assert svc.is_enrollment_active  # Still active, 2 attempts left

        # Check error response
        transport.send.assert_called_once()
        resp = transport.send.call_args[0][0]
        assert resp.payload["status"] == "error"
        assert resp.payload["reason"] == "invalid_pin"

    @pytest.mark.asyncio
    async def test_enroll_max_attempts_lockout(self, tmp_path):
        """After max_attempts failures, PIN is locked."""
        svc, ks, transport = self._make_service(tmp_path, max_attempts=2)
        svc.create_pin()

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="bad-device",
            target="*",
            payload={"name": "Bad", "pin_proof": "wrong"},
        )
        # Attempt 1 → invalid_pin
        await svc.handle_enroll_request(env)
        assert svc.is_enrollment_active  # 1 attempt left
        # Attempt 2 → locked
        await svc.handle_enroll_request(env)
        assert not svc.is_enrollment_active
        resp = transport.send.call_args[0][0]
        assert resp.payload["reason"] == "locked"

    @pytest.mark.asyncio
    async def test_enroll_expired_pin(self, tmp_path):
        """Expired PIN should be rejected."""
        svc, _, transport = self._make_service(tmp_path, pin_timeout=1)
        pin, _ = svc.create_pin()
        # Force expiry
        svc._pending.expires_at = time.time() - 1

        pin_proof = EnrollmentService.compute_pin_proof(pin, "device-1")
        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-1",
            target="*",
            payload={"pin_proof": pin_proof},
        )
        await svc.handle_enroll_request(env)

        resp = transport.send.call_args[0][0]
        assert resp.payload["status"] == "error"
        assert resp.payload["reason"] == "expired"

    @pytest.mark.asyncio
    async def test_enroll_already_used_pin(self, tmp_path):
        """PIN used for a successful enrollment cannot be reused."""
        svc, _, transport = self._make_service(tmp_path)
        pin, _ = svc.create_pin()

        # First enrollment succeeds
        proof1 = EnrollmentService.compute_pin_proof(pin, "device-1")
        env1 = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-1",
            target="*",
            payload={"name": "D1", "pin_proof": proof1},
        )
        await svc.handle_enroll_request(env1)
        assert not svc.is_enrollment_active

        # Second enrollment request with same PIN should fail
        proof2 = EnrollmentService.compute_pin_proof(pin, "device-2")
        env2 = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-2",
            target="*",
            payload={"name": "D2", "pin_proof": proof2},
        )
        await svc.handle_enroll_request(env2)

        # Latest transport.send call should be error
        last_resp = transport.send.call_args[0][0]
        assert last_resp.payload["status"] == "error"
        assert last_resp.payload["reason"] == "already_used"

    @pytest.mark.asyncio
    async def test_enroll_no_active_enrollment(self, tmp_path):
        """Request without any active PIN should be rejected."""
        svc, _, transport = self._make_service(tmp_path)

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-1",
            target="*",
            payload={"pin_proof": "xxx"},
        )
        await svc.handle_enroll_request(env)

        resp = transport.send.call_args[0][0]
        assert resp.payload["status"] == "error"
        assert resp.payload["reason"] == "no_active_enrollment"

    @pytest.mark.asyncio
    async def test_enroll_re_enrollment_rotates_psk(self, tmp_path):
        """Enrolling an already-enrolled device rotates its PSK."""
        svc, ks, _ = self._make_service(tmp_path)

        # First enrollment
        pin1, _ = svc.create_pin()
        proof1 = EnrollmentService.compute_pin_proof(pin1, "device-1")
        env1 = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-1",
            target="*",
            payload={"pin_proof": proof1},
        )
        await svc.handle_enroll_request(env1)
        psk1 = ks.get_psk("device-1")

        # Second enrollment with new PIN
        pin2, _ = svc.create_pin()
        proof2 = EnrollmentService.compute_pin_proof(pin2, "device-1")
        env2 = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="device-1",
            target="*",
            payload={"pin_proof": proof2},
        )
        await svc.handle_enroll_request(env2)
        psk2 = ks.get_psk("device-1")

        assert psk1 != psk2  # PSK was rotated


class TestMsgTypeEnrollment:
    """Tests for ENROLL_REQUEST/ENROLL_RESPONSE message types."""

    def test_enroll_request_type(self):
        assert MsgType.ENROLL_REQUEST == "enroll_request"

    def test_enroll_response_type(self):
        assert MsgType.ENROLL_RESPONSE == "enroll_response"

    def test_enroll_request_roundtrip(self):
        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="esp32-1",
            target="*",
            payload={"name": "Sensor", "pin_proof": "abc123"},
        )
        raw = env.to_bytes()
        restored = MeshEnvelope.from_bytes(raw[4:])
        assert restored.type == MsgType.ENROLL_REQUEST
        assert restored.payload["pin_proof"] == "abc123"


class TestTransportEnrollmentBypass:
    """Tests for transport auth bypass during active enrollment."""

    @pytest.mark.asyncio
    async def test_enroll_request_allowed_when_active(self):
        """ENROLL_REQUEST bypasses auth when enrollment is active."""
        disc = UDPDiscovery(node_id="hub", tcp_port=0, udp_port=0)
        ks = KeyStore(path="/tmp/test_enroll_bypass_keys.json", nonce_window=60)
        transport = MeshTransport(
            node_id="hub",
            discovery=disc,
            tcp_port=0,
            key_store=ks,
            psk_auth_enabled=True,
            allow_unauthenticated=False,
        )

        # Mock enrollment service with active enrollment
        mock_enrollment = MagicMock()
        mock_enrollment.is_enrollment_active = True
        transport.enrollment_service = mock_enrollment

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="new-device",
            target="*",
            payload={"pin_proof": "xxx"},
        )
        assert transport._verify_inbound(env) is True

    @pytest.mark.asyncio
    async def test_enroll_request_blocked_when_inactive(self):
        """ENROLL_REQUEST is blocked when no enrollment is active."""
        disc = UDPDiscovery(node_id="hub", tcp_port=0, udp_port=0)
        ks = KeyStore(path="/tmp/test_enroll_bypass_keys2.json", nonce_window=60)
        transport = MeshTransport(
            node_id="hub",
            discovery=disc,
            tcp_port=0,
            key_store=ks,
            psk_auth_enabled=True,
            allow_unauthenticated=False,
        )

        # No enrollment service set → enrollment inactive
        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="new-device",
            target="*",
            payload={"pin_proof": "xxx"},
        )
        assert transport._verify_inbound(env) is False

    @pytest.mark.asyncio
    async def test_enroll_request_blocked_when_enrollment_expired(self):
        """ENROLL_REQUEST is blocked when enrollment exists but is expired."""
        disc = UDPDiscovery(node_id="hub", tcp_port=0, udp_port=0)
        ks = KeyStore(path="/tmp/test_enroll_bypass_keys3.json", nonce_window=60)
        transport = MeshTransport(
            node_id="hub",
            discovery=disc,
            tcp_port=0,
            key_store=ks,
            psk_auth_enabled=True,
            allow_unauthenticated=False,
        )

        mock_enrollment = MagicMock()
        mock_enrollment.is_enrollment_active = False
        transport.enrollment_service = mock_enrollment

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="new-device",
            target="*",
            payload={"pin_proof": "xxx"},
        )
        assert transport._verify_inbound(env) is False


class TestChannelEnrollment:
    """Tests for MeshChannel enrollment integration."""

    def test_channel_creates_enrollment_service(self):
        """MeshChannel should create an EnrollmentService when PSK auth is enabled."""
        mock_config = MagicMock()
        mock_config.node_id = "hub-1"
        mock_config.tcp_port = 18800
        mock_config.udp_port = 18799
        mock_config.roles = ["nanobot"]
        mock_config.psk_auth_enabled = True
        mock_config.allow_unauthenticated = False
        mock_config.nonce_window = 60
        mock_config.key_store_path = ""
        mock_config._workspace_path = "/tmp/test_channel_enrollment"
        mock_config.enrollment_pin_length = 6
        mock_config.enrollment_pin_timeout = 300
        mock_config.enrollment_max_attempts = 3

        bus = MagicMock()
        ch = MeshChannel(config=mock_config, bus=bus)
        assert ch.enrollment is not None
        assert ch.transport.enrollment_service is ch.enrollment

    def test_channel_no_enrollment_without_psk(self):
        """MeshChannel should NOT create enrollment if PSK auth is disabled."""
        mock_config = MagicMock()
        mock_config.node_id = "hub-1"
        mock_config.tcp_port = 18800
        mock_config.udp_port = 18799
        mock_config.roles = ["nanobot"]
        mock_config.psk_auth_enabled = False
        mock_config.allow_unauthenticated = False
        mock_config.nonce_window = 60
        mock_config.key_store_path = ""
        mock_config._workspace_path = None
        mock_config.enrollment_pin_length = 6
        mock_config.enrollment_pin_timeout = 300
        mock_config.enrollment_max_attempts = 3

        bus = MagicMock()
        ch = MeshChannel(config=mock_config, bus=bus)
        assert ch.enrollment is None

    def test_create_enrollment_pin(self):
        """MeshChannel.create_enrollment_pin() should create a PIN."""
        mock_config = MagicMock()
        mock_config.node_id = "hub-1"
        mock_config.tcp_port = 18800
        mock_config.udp_port = 18799
        mock_config.roles = ["nanobot"]
        mock_config.psk_auth_enabled = True
        mock_config.allow_unauthenticated = False
        mock_config.nonce_window = 60
        mock_config.key_store_path = ""
        mock_config._workspace_path = "/tmp/test_channel_pin"
        mock_config.enrollment_pin_length = 4
        mock_config.enrollment_pin_timeout = 60
        mock_config.enrollment_max_attempts = 3

        bus = MagicMock()
        ch = MeshChannel(config=mock_config, bus=bus)
        result = ch.create_enrollment_pin()
        assert result is not None
        pin, expires_at = result
        assert len(pin) == 4
        assert pin.isdigit()
        assert expires_at > time.time()

    def test_create_enrollment_pin_unavailable(self):
        """create_enrollment_pin returns None when PSK auth is disabled."""
        mock_config = MagicMock()
        mock_config.node_id = "hub-1"
        mock_config.tcp_port = 18800
        mock_config.udp_port = 18799
        mock_config.roles = ["nanobot"]
        mock_config.psk_auth_enabled = False
        mock_config.allow_unauthenticated = False
        mock_config.nonce_window = 60
        mock_config.key_store_path = ""
        mock_config._workspace_path = None
        mock_config.enrollment_pin_length = 6
        mock_config.enrollment_pin_timeout = 300
        mock_config.enrollment_max_attempts = 3

        bus = MagicMock()
        ch = MeshChannel(config=mock_config, bus=bus)
        assert ch.create_enrollment_pin() is None


class TestEnrollmentConfig:
    """Tests for enrollment config fields in MeshConfig."""

    def test_enrollment_defaults(self):
        from nanobot.config.schema import MeshConfig

        mc = MeshConfig()
        assert mc.enrollment_pin_length == 6
        assert mc.enrollment_pin_timeout == 300
        assert mc.enrollment_max_attempts == 3

    def test_enrollment_custom_values(self):
        from nanobot.config.schema import MeshConfig

        mc = MeshConfig(
            enrollment_pin_length=8,
            enrollment_pin_timeout=60,
            enrollment_max_attempts=5,
        )
        assert mc.enrollment_pin_length == 8
        assert mc.enrollment_pin_timeout == 60
        assert mc.enrollment_max_attempts == 5


# ---------------------------------------------------------------------------
# Encryption tests (task 1.11)
# ---------------------------------------------------------------------------


class TestEncryptionAvailability:
    """Verify crypto library detection."""

    def test_is_available(self):
        assert is_available() is True  # cryptography is installed

    def test_has_aesgcm_flag(self):
        assert HAS_AESGCM is True


class TestDeriveEncryptionKey:
    """Tests for PSK → AES key derivation."""

    def test_deterministic(self):
        psk_hex = "ab" * 32
        k1 = derive_encryption_key(psk_hex)
        k2 = derive_encryption_key(psk_hex)
        assert k1 == k2
        assert len(k1) == 32  # 256-bit key

    def test_different_psks_produce_different_keys(self):
        k1 = derive_encryption_key("aa" * 32)
        k2 = derive_encryption_key("bb" * 32)
        assert k1 != k2

    def test_key_differs_from_raw_psk(self):
        psk_hex = "cc" * 32
        enc_key = derive_encryption_key(psk_hex)
        assert enc_key != bytes.fromhex(psk_hex)


class TestBuildAAD:
    """Tests for Additional Authenticated Data construction."""

    def test_format(self):
        aad = build_aad("chat", "node-a", "node-b", 1700000000.0)
        assert aad == b"chat|node-a|node-b|1700000000.0"

    def test_different_metadata_different_aad(self):
        aad1 = build_aad("chat", "a", "b", 1.0)
        aad2 = build_aad("command", "a", "b", 1.0)
        assert aad1 != aad2


class TestEncryptDecryptPayload:
    """Roundtrip and edge-case tests for AES-256-GCM."""

    PSK = "dd" * 32  # 32-byte hex PSK

    def _ctx(self):
        """Common envelope metadata context."""
        return dict(msg_type="chat", source="src", target="tgt", ts=1700000000.0)

    def test_roundtrip_simple(self):
        payload = {"text": "hello world"}
        result = encrypt_payload(payload, self.PSK, **self._ctx())
        assert result is not None
        ct_hex, iv_hex = result
        assert len(iv_hex) == 24  # 12 bytes hex
        decrypted = decrypt_payload(ct_hex, iv_hex, self.PSK, **self._ctx())
        assert decrypted == payload

    def test_roundtrip_empty_payload(self):
        payload = {}
        result = encrypt_payload(payload, self.PSK, **self._ctx())
        assert result is not None
        ct_hex, iv_hex = result
        decrypted = decrypt_payload(ct_hex, iv_hex, self.PSK, **self._ctx())
        assert decrypted == payload

    def test_roundtrip_nested_payload(self):
        payload = {"cmd": "set_temp", "params": {"value": 22.5, "unit": "C"}}
        result = encrypt_payload(payload, self.PSK, **self._ctx())
        assert result is not None
        ct_hex, iv_hex = result
        decrypted = decrypt_payload(ct_hex, iv_hex, self.PSK, **self._ctx())
        assert decrypted == payload

    def test_roundtrip_unicode_payload(self):
        payload = {"text": "你好世界 🌍"}
        result = encrypt_payload(payload, self.PSK, **self._ctx())
        assert result is not None
        ct_hex, iv_hex = result
        decrypted = decrypt_payload(ct_hex, iv_hex, self.PSK, **self._ctx())
        assert decrypted == payload

    def test_different_iv_each_call(self):
        payload = {"text": "same"}
        r1 = encrypt_payload(payload, self.PSK, **self._ctx())
        r2 = encrypt_payload(payload, self.PSK, **self._ctx())
        assert r1 is not None and r2 is not None
        assert r1[1] != r2[1]  # different IVs
        assert r1[0] != r2[0]  # different ciphertexts (probabilistic encryption)

    def test_wrong_psk_fails_decrypt(self):
        payload = {"text": "secret"}
        ct_hex, iv_hex = encrypt_payload(payload, self.PSK, **self._ctx())
        wrong_psk = "ee" * 32
        decrypted = decrypt_payload(ct_hex, iv_hex, wrong_psk, **self._ctx())
        assert decrypted is None

    def test_tampered_ciphertext_fails(self):
        payload = {"text": "secret"}
        ct_hex, iv_hex = encrypt_payload(payload, self.PSK, **self._ctx())
        # Flip one hex char in ciphertext
        tampered = ("0" if ct_hex[0] != "0" else "1") + ct_hex[1:]
        decrypted = decrypt_payload(tampered, iv_hex, self.PSK, **self._ctx())
        assert decrypted is None

    def test_aad_mismatch_fails(self):
        """Changing envelope metadata after encryption must fail decryption."""
        payload = {"text": "secret"}
        ct_hex, iv_hex = encrypt_payload(payload, self.PSK, **self._ctx())
        # Decrypt with different msg_type (AAD mismatch)
        decrypted = decrypt_payload(
            ct_hex, iv_hex, self.PSK,
            msg_type="command", source="src", target="tgt", ts=1700000000.0,
        )
        assert decrypted is None

    def test_aad_different_source_fails(self):
        payload = {"text": "secret"}
        ct_hex, iv_hex = encrypt_payload(payload, self.PSK, **self._ctx())
        decrypted = decrypt_payload(
            ct_hex, iv_hex, self.PSK,
            msg_type="chat", source="attacker", target="tgt", ts=1700000000.0,
        )
        assert decrypted is None

    def test_aad_different_timestamp_fails(self):
        payload = {"text": "secret"}
        ct_hex, iv_hex = encrypt_payload(payload, self.PSK, **self._ctx())
        decrypted = decrypt_payload(
            ct_hex, iv_hex, self.PSK,
            msg_type="chat", source="src", target="tgt", ts=9999999999.0,
        )
        assert decrypted is None


class TestEnvelopeEncryptionFields:
    """Test MeshEnvelope new encryption fields."""

    def test_default_fields_empty(self):
        env = MeshEnvelope(type="chat", source="a", target="b")
        assert env.encrypted_payload == ""
        assert env.iv == ""

    def test_to_dict_omits_empty_encryption_fields(self):
        env = MeshEnvelope(type="chat", source="a", target="b")
        d = env.to_dict()
        assert "encrypted_payload" not in d
        assert "iv" not in d

    def test_to_dict_includes_encryption_fields_when_set(self):
        env = MeshEnvelope(
            type="chat", source="a", target="b",
            encrypted_payload="deadbeef", iv="aabbccdd",
        )
        d = env.to_dict()
        assert d["encrypted_payload"] == "deadbeef"
        assert d["iv"] == "aabbccdd"

    def test_from_bytes_reads_encryption_fields(self):
        data = json.dumps({
            "type": "chat", "source": "a", "target": "b",
            "payload": {}, "ts": 1.0,
            "encrypted_payload": "cafebabe", "iv": "1234abcd",
        }).encode()
        env = MeshEnvelope.from_bytes(data)
        assert env.encrypted_payload == "cafebabe"
        assert env.iv == "1234abcd"

    def test_from_bytes_defaults_missing_fields(self):
        data = json.dumps({
            "type": "chat", "source": "a", "target": "b",
            "payload": {"text": "hi"}, "ts": 1.0,
        }).encode()
        env = MeshEnvelope.from_bytes(data)
        assert env.encrypted_payload == ""
        assert env.iv == ""

    def test_canonical_bytes_includes_encryption_fields(self):
        """HMAC canonical form must cover encrypted_payload + iv."""
        env = MeshEnvelope(
            type="chat", source="a", target="b",
            encrypted_payload="aabb", iv="ccdd",
        )
        canonical = env.canonical_bytes()
        obj = json.loads(canonical)
        assert obj["encrypted_payload"] == "aabb"
        assert obj["iv"] == "ccdd"
        assert "hmac" not in obj
        assert "nonce" not in obj

    def test_roundtrip_with_encryption_fields(self):
        env = MeshEnvelope(
            type="chat", source="a", target="b",
            payload={}, encrypted_payload="deadbeef", iv="112233",
        )
        raw = env.to_bytes()
        length = struct.unpack("!I", raw[:4])[0]
        restored = MeshEnvelope.from_bytes(raw[4:4 + length])
        assert restored.encrypted_payload == "deadbeef"
        assert restored.iv == "112233"
        assert restored.payload == {}


class TestTransportEncryption:
    """Integration tests for encrypt/decrypt in MeshTransport."""

    def _make_transport(self, ks, encryption_enabled=True, psk_auth=True):
        discovery = MagicMock(spec=UDPDiscovery)
        transport = MeshTransport(
            node_id="hub",
            discovery=discovery,
            key_store=ks,
            psk_auth_enabled=psk_auth,
            encryption_enabled=encryption_enabled,
        )
        return transport

    def test_encrypt_outbound_chat(self):
        """CHAT message payload should be encrypted."""
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        psk = ks.add_device("device-1")
        ks.add_device("hub")  # Hub needs PSK for signing
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.CHAT, source="hub", target="device-1",
            payload={"text": "hello"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload != ""
        assert env.iv != ""
        assert env.payload == {}

    def test_encrypt_outbound_command(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("device-1")
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.COMMAND, source="hub", target="device-1",
            payload={"cmd": "on"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload != ""

    def test_encrypt_outbound_response(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("device-1")
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.RESPONSE, source="hub", target="device-1",
            payload={"text": "ok"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload != ""

    def test_no_encrypt_ping(self):
        """PING messages should NOT be encrypted."""
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("device-1")
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.PING, source="hub", target="device-1",
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload == ""
        assert env.iv == ""

    def test_no_encrypt_enroll_request(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST, source="new-device", target="hub",
            payload={"pin_proof": "abc"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload == ""

    def test_no_encrypt_broadcast(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("*")  # Even if * has a key, broadcast shouldn't encrypt
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.CHAT, source="hub", target="*",
            payload={"text": "broadcast"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload == ""

    def test_no_encrypt_when_disabled(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("device-1")
        transport = self._make_transport(ks, encryption_enabled=False)

        env = MeshEnvelope(
            type=MsgType.CHAT, source="hub", target="device-1",
            payload={"text": "plain"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload == ""
        assert env.payload == {"text": "plain"}

    def test_no_encrypt_unknown_target(self):
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        # Don't add device-unknown to key store
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type=MsgType.CHAT, source="hub", target="device-unknown",
            payload={"text": "hi"},
        )
        transport._encrypt_outbound(env)
        assert env.encrypted_payload == ""
        assert env.payload == {"text": "hi"}

    def test_decrypt_inbound(self):
        """Receiver should decrypt an encrypted message."""
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        psk = ks.add_device("device-1")
        transport = self._make_transport(ks)

        # Simulate encrypted inbound from device-1
        payload = {"text": "secret"}
        result = encrypt_payload(
            payload, psk,
            msg_type="chat", source="device-1", target="hub", ts=1.0,
        )
        assert result is not None
        ct_hex, iv_hex = result

        env = MeshEnvelope(
            type="chat", source="device-1", target="hub", ts=1.0,
            payload={}, encrypted_payload=ct_hex, iv=iv_hex,
        )
        transport._decrypt_inbound(env)
        assert env.payload == payload
        assert env.encrypted_payload == ""
        assert env.iv == ""

    def test_decrypt_skips_unencrypted(self):
        """Unencrypted messages pass through untouched."""
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        ks.add_device("device-1")
        transport = self._make_transport(ks)

        env = MeshEnvelope(
            type="chat", source="device-1", target="hub",
            payload={"text": "plain"},
        )
        transport._decrypt_inbound(env)
        assert env.payload == {"text": "plain"}

    def test_encrypt_then_decrypt_roundtrip(self):
        """Full encrypt → decrypt roundtrip via transport methods.

        Hub encrypts for device-1 using device-1's PSK (looked up by target).
        On receive, decryption looks up sender's PSK. Since both directions
        use the same per-device PSK, simulate device→hub direction where
        source=device-1 and target=hub.
        """
        ks = KeyStore(path="/tmp/test_enc_ks.json")
        psk = ks.add_device("device-1")

        # Device sends encrypted message to hub
        sender = self._make_transport(ks)
        sender.node_id = "device-1"
        env = MeshEnvelope(
            type=MsgType.CHAT, source="device-1", target="hub",
            payload={"text": "encrypted roundtrip"},
        )
        # Encryption uses target's PSK — but hub isn't in key store,
        # so we encrypt manually using the shared PSK for the test.
        result = encrypt_payload(
            env.payload, psk,
            msg_type=env.type, source=env.source, target=env.target, ts=env.ts,
        )
        assert result is not None
        env.encrypted_payload, env.iv = result
        env.payload = {}

        # Hub receives and decrypts using source's (device-1's) PSK
        receiver = self._make_transport(ks)
        receiver._decrypt_inbound(env)
        assert env.payload == {"text": "encrypted roundtrip"}
        assert env.encrypted_payload == ""
        assert env.iv == ""


class TestEncryptionConfig:
    """Test encryption_enabled config field."""

    def test_default_enabled(self):
        from nanobot.config.schema import MeshConfig
        mc = MeshConfig()
        assert mc.encryption_enabled is True

    def test_can_disable(self):
        from nanobot.config.schema import MeshConfig
        mc = MeshConfig(encryption_enabled=False)
        assert mc.encryption_enabled is False
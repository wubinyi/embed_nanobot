"""Tests for the LAN mesh communication module."""

import asyncio
import json
import struct
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.mesh.channel import MeshChannel, _default_node_id
from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
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

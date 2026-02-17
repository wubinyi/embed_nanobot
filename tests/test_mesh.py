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

    def test_channels_config_has_mesh(self):
        from nanobot.config.schema import ChannelsConfig
        channels = ChannelsConfig()
        assert hasattr(channels, "mesh")
        assert channels.mesh.enabled is False

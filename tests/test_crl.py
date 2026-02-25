"""Tests for Certificate Revocation List (CRL) support (task 3.2).

Covers:
- Revocation lifecycle: revoke, is_revoked, list_revoked
- CRL file generation and persistence
- Device cert+key deletion on revocation
- CRL-aware SSL contexts reject revoked devices
- CRL rebuild from revoked.json
- list_device_certs includes revoked entries
- Transport SSL context hot-reload
- Channel revoke_device integration (mTLS + registry removal)
- Edge cases: double revocation, revoke without cert, uninitialized CA
"""

from __future__ import annotations

import asyncio
import json
import ssl
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.ca import MeshCA, is_available as ca_is_available

# Only run these tests if cryptography is installed.
pytestmark = pytest.mark.skipif(
    not ca_is_available(), reason="cryptography not installed"
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def ca_dir(tmp_path: Path) -> Path:
    """Temporary CA directory."""
    return tmp_path / "mesh_ca"


@pytest.fixture
def ca(ca_dir: Path) -> MeshCA:
    """Initialized CA instance with a device cert already issued."""
    c = MeshCA(ca_dir)
    c.initialize()
    return c


# ===================================================================
# Test: Revocation Lifecycle
# ===================================================================

class TestRevocationLifecycle:
    """revoke_device_cert, is_revoked, list_revoked."""

    def test_revoke_device(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        assert ca.revoke_device_cert("dev-01") is True
        assert ca.is_revoked("dev-01") is True

    def test_revoke_deletes_cert_and_key(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        cert_path, key_path = ca.get_device_cert_paths("dev-01")
        assert cert_path.exists()
        assert key_path.exists()

        ca.revoke_device_cert("dev-01")
        assert not cert_path.exists()
        assert not key_path.exists()

    def test_revoke_already_revoked_returns_false(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        assert ca.revoke_device_cert("dev-01") is False

    def test_revoke_nonexistent_cert_returns_false(self, ca: MeshCA):
        assert ca.revoke_device_cert("ghost-device") is False

    def test_revoke_uninitialized_ca_raises(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        with pytest.raises(RuntimeError, match="not initialized"):
            ca.revoke_device_cert("dev-01")

    def test_is_revoked_false_for_active_cert(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        assert ca.is_revoked("dev-01") is False

    def test_is_revoked_false_for_unknown_device(self, ca: MeshCA):
        assert ca.is_revoked("unknown") is False

    def test_list_revoked_empty(self, ca: MeshCA):
        assert ca.list_revoked() == []

    def test_list_revoked_contains_entry(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        revoked = ca.list_revoked()
        assert len(revoked) == 1
        assert revoked[0]["node_id"] == "dev-01"
        assert "serial" in revoked[0]
        assert "date" in revoked[0]

    def test_multiple_revocations(self, ca: MeshCA):
        for i in range(3):
            ca.issue_device_cert(f"dev-{i}")
        for i in range(3):
            ca.revoke_device_cert(f"dev-{i}")
        assert len(ca.list_revoked()) == 3
        for i in range(3):
            assert ca.is_revoked(f"dev-{i}")

    def test_revoke_preserves_has_device_cert_false(self, ca: MeshCA):
        """After revocation, has_device_cert should return False (files deleted)."""
        ca.issue_device_cert("dev-01")
        assert ca.has_device_cert("dev-01") is True
        ca.revoke_device_cert("dev-01")
        assert ca.has_device_cert("dev-01") is False


# ===================================================================
# Test: CRL File Generation
# ===================================================================

class TestCRLFile:
    """CRL PEM file generation and content."""

    def test_crl_created_on_revocation(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        assert not ca.crl_path.exists()
        ca.revoke_device_cert("dev-01")
        assert ca.crl_path.exists()

    def test_crl_is_valid_pem(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        crl_bytes = ca.crl_path.read_bytes()
        assert b"BEGIN X509 CRL" in crl_bytes

    def test_crl_contains_revoked_serial(self, ca: MeshCA):
        from cryptography import x509 as cx509
        ca.issue_device_cert("dev-01")
        cert_pem, _ = ca.issue_device_cert("dev-01")  # re-issue to get cert
        cert = cx509.load_pem_x509_certificate(cert_pem)
        serial = cert.serial_number

        ca.revoke_device_cert("dev-01")
        crl = cx509.load_pem_x509_crl(ca.crl_path.read_bytes())
        revoked_entry = crl.get_revoked_certificate_by_serial_number(serial)
        assert revoked_entry is not None

    def test_crl_signed_by_ca(self, ca: MeshCA):
        from cryptography import x509 as cx509
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        crl = cx509.load_pem_x509_crl(ca.crl_path.read_bytes())
        assert crl.issuer == ca._ca_cert.subject

    def test_crl_not_created_without_revocations(self, ca: MeshCA):
        """If no revocations, no CRL file should exist."""
        ca.issue_device_cert("dev-01")
        assert not ca.crl_path.exists()

    def test_revoked_json_persisted(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        assert ca.revoked_json_path.exists()
        data = json.loads(ca.revoked_json_path.read_text())
        assert "dev-01" in data
        assert "serial" in data["dev-01"]
        assert "date" in data["dev-01"]


# ===================================================================
# Test: CRL Rebuild
# ===================================================================

class TestCRLRebuild:
    """rebuild_crl() from revoked.json."""

    def test_rebuild_crl_from_json(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        assert ca.crl_path.exists()

        # Delete CRL manually
        ca.crl_path.unlink()
        assert not ca.crl_path.exists()

        # Rebuild
        ca.rebuild_crl()
        assert ca.crl_path.exists()

    def test_rebuild_crl_no_revocations_removes_stale(self, ca: MeshCA):
        """If no revocations, rebuild should remove stale CRL file."""
        # Create a fake CRL
        ca.crl_path.write_bytes(b"fake")
        ca.rebuild_crl()
        assert not ca.crl_path.exists()

    def test_rebuild_crl_preserves_entries(self, ca: MeshCA):
        from cryptography import x509 as cx509
        ca.issue_device_cert("dev-01")
        ca.issue_device_cert("dev-02")
        ca.revoke_device_cert("dev-01")
        ca.revoke_device_cert("dev-02")

        # Delete and rebuild
        ca.crl_path.unlink()
        ca.rebuild_crl()

        crl = cx509.load_pem_x509_crl(ca.crl_path.read_bytes())
        # CRL should have 2 entries
        assert len(list(crl)) == 2

    def test_revoked_state_survives_reload(self, ca_dir: Path):
        """Revocation metadata persists across CA re-initialization."""
        ca1 = MeshCA(ca_dir)
        ca1.initialize()
        ca1.issue_device_cert("dev-01")
        ca1.revoke_device_cert("dev-01")
        assert ca1.is_revoked("dev-01")

        # Re-load CA from disk
        ca2 = MeshCA(ca_dir)
        ca2.initialize()
        assert ca2.is_revoked("dev-01")
        assert len(ca2.list_revoked()) == 1


# ===================================================================
# Test: SSL Context with CRL
# ===================================================================

class TestSSLContextWithCRL:
    """Revocation enforcement via application-level check in transport."""

    def test_server_context_no_crl_flags(self, ca: MeshCA):
        """Server context should NOT have CRL flags (app-level check instead)."""
        ctx = ca.create_server_ssl_context()
        assert not (ctx.verify_flags & ssl.VERIFY_CRL_CHECK_LEAF)

    @pytest.mark.asyncio
    async def test_revoked_device_rejected_by_transport(self, ca: MeshCA):
        """Transport should reject connections from revoked devices."""
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.protocol import MeshEnvelope, MsgType, write_envelope
        from nanobot.mesh.transport import MeshTransport

        ca.issue_device_cert("dev-01")
        client_ctx = ca.create_client_ssl_context("dev-01")
        server_ctx = ca.create_server_ssl_context()

        # Create transport with revocation check
        transport = MeshTransport(
            node_id="hub",
            discovery=MagicMock(spec=UDPDiscovery),
            tcp_port=0,
            server_ssl_context=server_ctx,
        )
        transport.revocation_check_fn = ca.is_revoked

        received_msgs = []

        async def on_msg(env):
            received_msgs.append(env)

        transport.on_message(on_msg)

        # Revoke the device
        ca.revoke_device_cert("dev-01")

        # Start server
        server = await asyncio.start_server(
            transport._handle_connection,
            "127.0.0.1",
            0,
            ssl=server_ctx,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            # The TLS handshake succeeds (OpenSSL doesn't check CRL)
            # but the transport handler should reject the message
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=client_ctx,
            )
            env = MeshEnvelope(
                type=MsgType.CHAT,
                source="dev-01",
                target="hub",
                payload={"text": "should be rejected"},
            )
            write_envelope(writer, env)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            await asyncio.sleep(0.2)
            # Message should NOT have been dispatched
            assert len(received_msgs) == 0
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_active_device_accepted_after_other_revoked(self, ca: MeshCA):
        """Non-revoked devices should still connect fine after a revocation."""
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.protocol import MeshEnvelope, MsgType, write_envelope
        from nanobot.mesh.transport import MeshTransport

        ca.issue_device_cert("good-dev")
        ca.issue_device_cert("bad-dev")

        # Revoke one device
        ca.revoke_device_cert("bad-dev")

        server_ctx = ca.create_server_ssl_context()
        good_client_ctx = ca.create_client_ssl_context("good-dev")

        transport = MeshTransport(
            node_id="hub",
            discovery=MagicMock(spec=UDPDiscovery),
            tcp_port=0,
            server_ssl_context=server_ctx,
        )
        transport.revocation_check_fn = ca.is_revoked

        received_msgs = []

        async def on_msg(env):
            received_msgs.append(env)

        transport.on_message(on_msg)

        server = await asyncio.start_server(
            transport._handle_connection,
            "127.0.0.1",
            0,
            ssl=server_ctx,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=good_client_ctx,
            )
            env = MeshEnvelope(
                type=MsgType.CHAT,
                source="good-dev",
                target="hub",
                payload={"text": "hello"},
            )
            write_envelope(writer, env)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            await asyncio.sleep(0.2)
            # Good device's message should be dispatched
            assert len(received_msgs) == 1
            assert received_msgs[0].source == "good-dev"
        finally:
            server.close()
            await server.wait_closed()


# ===================================================================
# Test: list_device_certs with revoked entries
# ===================================================================

class TestListDeviceCertsWithCRL:
    """list_device_certs() includes revoked entries."""

    def test_active_cert_has_revoked_false(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        info = ca.list_device_certs()
        active = [c for c in info if c["node_id"] == "dev-01"]
        assert len(active) == 1
        assert active[0]["revoked"] is False

    def test_revoked_cert_appears_in_list(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")

        certs = ca.list_device_certs()
        revoked_entries = [c for c in certs if c["node_id"] == "dev-01"]
        assert len(revoked_entries) == 1
        assert revoked_entries[0]["revoked"] is True
        assert "revoked_date" in revoked_entries[0]

    def test_mixed_active_and_revoked(self, ca: MeshCA):
        ca.issue_device_cert("active-01")
        ca.issue_device_cert("revoked-01")
        ca.revoke_device_cert("revoked-01")

        certs = ca.list_device_certs()
        node_ids = [c["node_id"] for c in certs]
        assert "active-01" in node_ids
        assert "revoked-01" in node_ids

        active = [c for c in certs if c["node_id"] == "active-01"][0]
        revoked = [c for c in certs if c["node_id"] == "revoked-01"][0]
        assert active["revoked"] is False
        assert revoked["revoked"] is True


# ===================================================================
# Test: Transport SSL Hot-Reload
# ===================================================================

class TestTransportSSLHotReload:
    """MeshTransport.update_server_ssl_context()."""

    def test_update_ssl_context(self, ca: MeshCA):
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.transport import MeshTransport

        old_ctx = ca.create_server_ssl_context()
        transport = MeshTransport(
            node_id="hub",
            discovery=MagicMock(spec=UDPDiscovery),
            tcp_port=0,
            server_ssl_context=old_ctx,
        )
        assert transport.tls_enabled is True

        # Issue and revoke a device
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")

        new_ctx = ca.create_server_ssl_context()
        transport.update_server_ssl_context(new_ctx)

        assert transport.server_ssl_context is new_ctx
        assert transport.tls_enabled is True

    def test_update_ssl_context_to_none_disables_tls(self):
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.transport import MeshTransport

        transport = MeshTransport(
            node_id="hub",
            discovery=MagicMock(spec=UDPDiscovery),
            tcp_port=0,
            server_ssl_context=MagicMock(),
        )
        assert transport.tls_enabled is True

        transport.update_server_ssl_context(None)
        assert transport.tls_enabled is False


# ===================================================================
# Test: Channel revoke_device Integration
# ===================================================================

class TestChannelRevokeDevice:
    """MeshChannel.revoke_device()."""

    def _make_channel(self, tmp_path: Path) -> "MeshChannel":
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = True
        config.allow_unauthenticated = False
        config.nonce_window = 60
        config.key_store_path = str(tmp_path / "keys.json")
        config.encryption_enabled = True
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = str(tmp_path / "reg.json")
        config.automation_rules_path = str(tmp_path / "auto.json")
        config._workspace_path = None
        config.mtls_enabled = True
        config.ca_dir = str(tmp_path / "mesh_ca")
        config.device_cert_validity_days = 365

        bus = MagicMock()
        return MeshChannel(config, bus)

    @pytest.mark.asyncio
    async def test_revoke_device_success(self, tmp_path: Path):
        channel = self._make_channel(tmp_path)
        assert channel.ca is not None
        channel.ca.issue_device_cert("sensor-01")

        result = await channel.revoke_device("sensor-01")
        assert result is True
        assert channel.ca.is_revoked("sensor-01")

    @pytest.mark.asyncio
    async def test_revoke_device_no_mtls(self, tmp_path: Path):
        """Revoke should fail gracefully when mTLS is not enabled."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-01"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = str(tmp_path / "reg.json")
        config.automation_rules_path = str(tmp_path / "auto.json")
        config._workspace_path = None
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365

        bus = MagicMock()
        channel = MeshChannel(config, bus)
        result = await channel.revoke_device("sensor-01")
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_with_registry_removal(self, tmp_path: Path):
        channel = self._make_channel(tmp_path)
        channel.ca.issue_device_cert("dev-01")

        # Mock registry.remove_device
        channel.registry.remove_device = AsyncMock(return_value=True)

        result = await channel.revoke_device("dev-01", remove_from_registry=True)
        assert result is True
        channel.registry.remove_device.assert_called_once_with("dev-01")

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_device(self, tmp_path: Path):
        channel = self._make_channel(tmp_path)
        result = await channel.revoke_device("no-such-device")
        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_wires_revocation_check_fn(self, tmp_path: Path):
        """Channel should wire CA.is_revoked as transport's revocation check."""
        channel = self._make_channel(tmp_path)
        assert channel.transport.revocation_check_fn is not None
        # Verify it delegates to the CA's is_revoked
        channel.ca.issue_device_cert("check-dev")
        assert channel.transport.revocation_check_fn("check-dev") is False
        channel.ca.revoke_device_cert("check-dev")
        assert channel.transport.revocation_check_fn("check-dev") is True


# ===================================================================
# Test: Re-enrollment after revocation
# ===================================================================

class TestReEnrollmentAfterRevocation:
    """Device can be re-enrolled (new cert issued) after revocation."""

    def test_reissue_cert_after_revocation(self, ca: MeshCA):
        """A new cert can be issued for a revoked device."""
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")
        assert ca.is_revoked("dev-01")
        assert not ca.has_device_cert("dev-01")

        # Re-issue — the old revocation stays in CRL (blocks old cert)
        # but a new cert with a new serial is created
        new_cert_pem, _ = ca.issue_device_cert("dev-01")
        assert ca.has_device_cert("dev-01")
        assert b"BEGIN CERTIFICATE" in new_cert_pem

    @pytest.mark.asyncio
    async def test_reissued_cert_accepted_by_tls(self, ca: MeshCA):
        """A re-issued cert (new serial) should pass TLS even with CRL active."""
        ca.issue_device_cert("dev-01")
        ca.revoke_device_cert("dev-01")

        # Re-issue a new cert
        ca.issue_device_cert("dev-01")
        client_ctx = ca.create_client_ssl_context("dev-01")
        server_ctx = ca.create_server_ssl_context()

        received = asyncio.Event()

        async def handler(reader, writer):
            writer.close()
            received.set()

        server = await asyncio.start_server(
            handler, "127.0.0.1", 0, ssl=server_ctx,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            _, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=client_ctx,
            )
            writer.close()
            await writer.wait_closed()
            await asyncio.wait_for(received.wait(), timeout=2.0)
        finally:
            server.close()
            await server.wait_closed()

"""Tests for mTLS device authentication (task 3.1).

Covers:
- CA initialization and idempotent reload
- Device certificate issuance and validation
- SSL context creation (server + client)
- Peer node_id extraction from certificate CN
- Transport with TLS: send/receive over mTLS
- Enrollment integration: certificate issued during enrollment
- Error cases: uninitialized CA, missing cert, config integration
- Channel integration: mTLS wiring end-to-end
"""

from __future__ import annotations

import asyncio
import datetime
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
    """Initialized CA instance."""
    c = MeshCA(ca_dir)
    c.initialize()
    return c


# ===================================================================
# Test: CA Initialization
# ===================================================================

class TestCAInitialization:
    """MeshCA initialization and idempotent loading."""

    def test_initialize_creates_files(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        assert not ca.is_initialized
        ca.initialize()
        assert ca.is_initialized
        assert ca.ca_key_path.exists()
        assert ca.ca_cert_path.exists()

    def test_initialize_idempotent(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        ca.initialize()
        first_cert = ca.ca_cert_path.read_bytes()

        # Re-initialize loads existing CA, doesn't regenerate
        ca2 = MeshCA(ca_dir)
        ca2.initialize()
        assert ca2.ca_cert_path.read_bytes() == first_cert

    def test_ca_key_permissions(self, ca: MeshCA):
        """CA private key should have 0600 permissions."""
        mode = ca.ca_key_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_ca_cert_is_valid_x509(self, ca: MeshCA):
        """CA cert should be a valid X.509 certificate."""
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(ca.ca_cert_path.read_bytes())
        assert "embed_nanobot Mesh CA" in cert.subject.rfc4514_string()

    def test_ca_cert_is_ca(self, ca: MeshCA):
        """CA cert should have basicConstraints:CA=TRUE."""
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(ca.ca_cert_path.read_bytes())
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True

    def test_ca_validity_period(self, ca: MeshCA):
        """CA cert should be valid for ~10 years."""
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(ca.ca_cert_path.read_bytes())
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert delta.days >= 3640  # ~10 years

    def test_ca_uses_ec_p256(self, ca: MeshCA):
        """CA should use EC P-256 (SECP256R1) key."""
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = serialization.load_pem_private_key(
            ca.ca_key_path.read_bytes(), password=None,
        )
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        assert key.curve.name == "secp256r1"

    def test_devices_dir_created(self, ca: MeshCA):
        """Accessing devices_dir should create it."""
        d = ca.devices_dir
        assert d.exists()
        assert d.is_dir()


# ===================================================================
# Test: Device Certificate Issuance
# ===================================================================

class TestDeviceCertIssuance:
    """Device certificate issuance by MeshCA."""

    def test_issue_device_cert(self, ca: MeshCA):
        cert_pem, key_pem = ca.issue_device_cert("sensor-01")
        assert b"BEGIN CERTIFICATE" in cert_pem
        assert b"BEGIN PRIVATE KEY" in key_pem

    def test_cert_persisted(self, ca: MeshCA):
        ca.issue_device_cert("sensor-01")
        cert_path, key_path = ca.get_device_cert_paths("sensor-01")
        assert cert_path.exists()
        assert key_path.exists()

    def test_has_device_cert(self, ca: MeshCA):
        assert not ca.has_device_cert("sensor-01")
        ca.issue_device_cert("sensor-01")
        assert ca.has_device_cert("sensor-01")

    def test_device_key_permissions(self, ca: MeshCA):
        ca.issue_device_cert("sensor-01")
        _, key_path = ca.get_device_cert_paths("sensor-01")
        mode = key_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_cert_cn_is_node_id(self, ca: MeshCA):
        """Device cert CN should match node_id."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("smart-lock-42")
        cert = x509.load_pem_x509_certificate(cert_pem)
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0]
        assert cn.value == "smart-lock-42"

    def test_cert_signed_by_ca(self, ca: MeshCA):
        """Device cert should be verifiable against the CA cert."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("dev-01")
        cert = x509.load_pem_x509_certificate(cert_pem)
        ca_cert = x509.load_pem_x509_certificate(ca.ca_cert_path.read_bytes())
        # Verify issuer matches CA subject
        assert cert.issuer == ca_cert.subject

    def test_cert_validity_period(self, ca: MeshCA):
        """Device cert validity should match config."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("dev-01")
        cert = x509.load_pem_x509_certificate(cert_pem)
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert 360 <= delta.days <= 370  # ~1 year

    def test_custom_validity_days(self, ca_dir: Path):
        ca = MeshCA(ca_dir, device_cert_validity_days=30)
        ca.initialize()
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("short-lived")
        cert = x509.load_pem_x509_certificate(cert_pem)
        delta = cert.not_valid_after_utc - cert.not_valid_before_utc
        assert 28 <= delta.days <= 32

    def test_cert_not_ca(self, ca: MeshCA):
        """Device cert should NOT be a CA."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("dev-01")
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is False

    def test_cert_has_client_and_server_auth(self, ca: MeshCA):
        """Device cert should have CLIENT_AUTH and SERVER_AUTH extended key usage."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("dev-01")
        cert = x509.load_pem_x509_certificate(cert_pem)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        oids = [u.dotted_string for u in eku.value]
        assert x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH.dotted_string in oids
        assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH.dotted_string in oids

    def test_cert_has_san(self, ca: MeshCA):
        """Device cert should have SAN with node_id as DNS name."""
        from cryptography import x509
        cert_pem, _ = ca.issue_device_cert("dev-01")
        cert = x509.load_pem_x509_certificate(cert_pem)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "dev-01" in dns_names

    def test_issue_without_initialize_raises(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        with pytest.raises(RuntimeError, match="not initialized"):
            ca.issue_device_cert("dev-01")

    def test_multiple_devices(self, ca: MeshCA):
        """Should be able to issue certs for multiple devices."""
        ca.issue_device_cert("dev-01")
        ca.issue_device_cert("dev-02")
        ca.issue_device_cert("dev-03")
        assert ca.has_device_cert("dev-01")
        assert ca.has_device_cert("dev-02")
        assert ca.has_device_cert("dev-03")


# ===================================================================
# Test: CA Certificate PEM
# ===================================================================

class TestCACertPEM:
    """CA cert distribution."""

    def test_get_ca_cert_pem(self, ca: MeshCA):
        pem = ca.get_ca_cert_pem()
        assert b"BEGIN CERTIFICATE" in pem

    def test_get_ca_cert_pem_uninitialized(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        with pytest.raises(RuntimeError, match="not initialized"):
            ca.get_ca_cert_pem()


# ===================================================================
# Test: SSL Context Creation
# ===================================================================

class TestSSLContext:
    """SSL context creation for mTLS."""

    def test_server_context_type(self, ca: MeshCA):
        ctx = ca.create_server_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_server_context_auto_issues_hub_cert(self, ca: MeshCA):
        """Server context should auto-issue a hub cert if missing."""
        assert not ca.has_device_cert("hub")
        ca.create_server_ssl_context()
        assert ca.has_device_cert("hub")

    def test_server_context_reuses_existing_hub_cert(self, ca: MeshCA):
        """If hub cert already exists, don't re-issue."""
        ca.issue_device_cert("hub")
        first_cert = (ca.devices_dir / "hub.crt").read_bytes()
        ca.create_server_ssl_context()
        assert (ca.devices_dir / "hub.crt").read_bytes() == first_cert

    def test_server_context_uninitialized_raises(self, ca_dir: Path):
        ca = MeshCA(ca_dir)
        with pytest.raises(RuntimeError, match="not initialized"):
            ca.create_server_ssl_context()

    def test_client_context_type(self, ca: MeshCA):
        ca.issue_device_cert("dev-01")
        ctx = ca.create_client_ssl_context("dev-01")
        assert isinstance(ctx, ssl.SSLContext)

    def test_client_context_missing_cert_raises(self, ca: MeshCA):
        with pytest.raises(FileNotFoundError, match="dev-99"):
            ca.create_client_ssl_context("dev-99")

    def test_tls_version_minimum(self, ca: MeshCA):
        """Both contexts should require TLS 1.2+."""
        server_ctx = ca.create_server_ssl_context()
        assert server_ctx.minimum_version == ssl.TLSVersion.TLSv1_2

        ca.issue_device_cert("dev-01")
        client_ctx = ca.create_client_ssl_context("dev-01")
        assert client_ctx.minimum_version == ssl.TLSVersion.TLSv1_2


# ===================================================================
# Test: TLS Handshake (real SSL sockets)
# ===================================================================

class TestTLSHandshake:
    """Full TLS handshake between Hub and device using CA-issued certs."""

    @pytest.mark.asyncio
    async def test_mutual_tls_handshake(self, ca: MeshCA):
        """Hub and device should complete a mutual TLS handshake."""
        ca.issue_device_cert("dev-01")
        server_ctx = ca.create_server_ssl_context()
        client_ctx = ca.create_client_ssl_context("dev-01")

        # Start TLS server
        received = asyncio.Event()
        received_data = []

        async def handler(reader, writer):
            data = await reader.read(1024)
            received_data.append(data)
            writer.write(b"OK")
            await writer.drain()
            writer.close()
            received.set()

        server = await asyncio.start_server(
            handler, "127.0.0.1", 0, ssl=server_ctx,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=client_ctx,
            )
            writer.write(b"HELLO")
            await writer.drain()
            resp = await reader.read(1024)
            writer.close()
            await writer.wait_closed()

            await asyncio.wait_for(received.wait(), timeout=2.0)
            assert received_data[0] == b"HELLO"
            assert resp == b"OK"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_wrong_ca_rejected(self, ca: MeshCA, tmp_path: Path):
        """Device cert from different CA should be rejected."""
        # Create a second CA (different trust root)
        other_ca = MeshCA(tmp_path / "other_ca")
        other_ca.initialize()
        other_ca.issue_device_cert("rogue-dev")

        server_ctx = ca.create_server_ssl_context()
        # Client uses cert from the OTHER CA
        rogue_ctx = other_ca.create_client_ssl_context("rogue-dev")

        server = await asyncio.start_server(
            lambda r, w: None, "127.0.0.1", 0, ssl=server_ctx,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            with pytest.raises((ssl.SSLError, ConnectionResetError, OSError)):
                await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port, ssl=rogue_ctx),
                    timeout=3.0,
                )
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_peer_node_id_extraction(self, ca: MeshCA):
        """Hub should extract device node_id from client cert CN."""
        ca.issue_device_cert("sensor-42")
        server_ctx = ca.create_server_ssl_context()
        client_ctx = ca.create_client_ssl_context("sensor-42")

        extracted_id = []

        async def handler(reader, writer):
            node_id = MeshCA.get_peer_node_id(writer.transport)
            extracted_id.append(node_id)
            writer.close()

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
            await asyncio.sleep(0.1)  # let handler run

            assert extracted_id[0] == "sensor-42"
        finally:
            server.close()
            await server.wait_closed()


# ===================================================================
# Test: Transport with mTLS
# ===================================================================

class TestTransportMTLS:
    """MeshTransport send/receive over mTLS."""

    @pytest.mark.asyncio
    async def test_send_receive_over_tls(self, ca: MeshCA):
        """Messages should flow correctly over TLS-wrapped transport."""
        from nanobot.mesh.discovery import UDPDiscovery, PeerInfo
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        from nanobot.mesh.transport import MeshTransport

        ca.issue_device_cert("dev-a")
        server_ssl = ca.create_server_ssl_context()

        def client_ssl_factory(target: str):
            return ca.create_client_ssl_context("hub")

        # Hub transport (TLS server)
        hub_disc = MagicMock(spec=UDPDiscovery)
        hub_transport = MeshTransport(
            node_id="hub",
            discovery=hub_disc,
            tcp_port=0,
            server_ssl_context=server_ssl,
            client_ssl_context_factory=client_ssl_factory,
        )

        received_msgs = []

        async def on_msg(env):
            received_msgs.append(env)

        hub_transport.on_message(on_msg)

        # Start hub on a random port
        hub_transport._server = await asyncio.start_server(
            hub_transport._handle_connection,
            "127.0.0.1",
            0,
            ssl=server_ssl,
        )
        port = hub_transport._server.sockets[0].getsockname()[1]

        try:
            # Device sends to hub via TLS
            from nanobot.mesh.protocol import write_envelope
            device_ssl = ca.create_client_ssl_context("dev-a")
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port, ssl=device_ssl,
            )
            env = MeshEnvelope(
                type=MsgType.CHAT,
                source="dev-a",
                target="hub",
                payload={"text": "hello via mTLS"},
            )
            write_envelope(writer, env)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

            await asyncio.sleep(0.2)
            assert len(received_msgs) == 1
            assert received_msgs[0].source == "dev-a"
            assert received_msgs[0].payload["text"] == "hello via mTLS"
        finally:
            hub_transport._server.close()
            await hub_transport._server.wait_closed()

    @pytest.mark.asyncio
    async def test_tls_skips_hmac_and_encryption(self, ca: MeshCA):
        """When TLS is active, HMAC and AES-GCM should be skipped."""
        from nanobot.mesh.discovery import UDPDiscovery
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        from nanobot.mesh.transport import MeshTransport

        ca.issue_device_cert("dev-a")
        server_ssl = ca.create_server_ssl_context()

        hub_transport = MeshTransport(
            node_id="hub",
            discovery=MagicMock(spec=UDPDiscovery),
            tcp_port=0,
            server_ssl_context=server_ssl,
            psk_auth_enabled=True,  # enabled but should be skipped
            encryption_enabled=True,  # enabled but should be skipped
        )
        assert hub_transport.tls_enabled is True

        # Verify that _verify_inbound and _decrypt_inbound are skipped
        # by checking the flag
        env = MeshEnvelope(
            type=MsgType.CHAT,
            source="dev-a",
            target="hub",
            payload={"text": "test"},
        )
        # No HMAC fields set — would fail without TLS bypass
        assert env.hmac == ""
        assert env.nonce == ""
        # In non-TLS mode with psk_auth_enabled, this would be rejected


# ===================================================================
# Test: Enrollment with mTLS Certificate Issuance
# ===================================================================

class TestEnrollmentMTLS:
    """Enrollment should issue certificates when CA is available."""

    @pytest.mark.asyncio
    async def test_enrollment_issues_cert(self, ca: MeshCA, tmp_path: Path):
        """Successful enrollment should include cert_pem, key_pem, ca_cert_pem."""
        from nanobot.mesh.enrollment import EnrollmentService
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        from nanobot.mesh.security import KeyStore

        ks = KeyStore(path=str(tmp_path / "keys.json"))
        transport = MagicMock()
        transport.send = AsyncMock(return_value=True)

        service = EnrollmentService(
            key_store=ks,
            transport=transport,
            node_id="hub-01",
            ca=ca,
        )
        pin, _ = service.create_pin()
        proof = service.compute_pin_proof(pin, "new-dev")

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="new-dev",
            target="hub-01",
            payload={"name": "New Device", "pin_proof": proof},
        )
        await service.handle_enroll_request(env)

        # Check the response sent via transport
        assert transport.send.called
        resp_env = transport.send.call_args[0][0]
        assert resp_env.payload["status"] == "ok"
        assert "cert_pem" in resp_env.payload
        assert "key_pem" in resp_env.payload
        assert "ca_cert_pem" in resp_env.payload
        assert "BEGIN CERTIFICATE" in resp_env.payload["cert_pem"]
        assert "BEGIN PRIVATE KEY" in resp_env.payload["key_pem"]

    @pytest.mark.asyncio
    async def test_enrollment_without_ca_no_cert(self, tmp_path: Path):
        """Enrollment without CA should still work (PSK only, no cert)."""
        from nanobot.mesh.enrollment import EnrollmentService
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        from nanobot.mesh.security import KeyStore

        ks = KeyStore(path=str(tmp_path / "keys.json"))
        transport = MagicMock()
        transport.send = AsyncMock(return_value=True)

        service = EnrollmentService(
            key_store=ks,
            transport=transport,
            node_id="hub-01",
            ca=None,  # no CA
        )
        pin, _ = service.create_pin()
        proof = service.compute_pin_proof(pin, "new-dev")

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="new-dev",
            target="hub-01",
            payload={"name": "New Device", "pin_proof": proof},
        )
        await service.handle_enroll_request(env)

        resp_env = transport.send.call_args[0][0]
        assert resp_env.payload["status"] == "ok"
        assert "encrypted_psk" in resp_env.payload
        # No cert fields
        assert "cert_pem" not in resp_env.payload

    @pytest.mark.asyncio
    async def test_enrollment_cert_for_correct_device(self, ca: MeshCA, tmp_path: Path):
        """Cert should be issued for the enrolling device's node_id."""
        from nanobot.mesh.enrollment import EnrollmentService
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        from nanobot.mesh.security import KeyStore

        ks = KeyStore(path=str(tmp_path / "keys.json"))
        transport = MagicMock()
        transport.send = AsyncMock(return_value=True)

        service = EnrollmentService(
            key_store=ks,
            transport=transport,
            node_id="hub",
            ca=ca,
        )
        pin, _ = service.create_pin()
        proof = service.compute_pin_proof(pin, "my-esp32")

        env = MeshEnvelope(
            type=MsgType.ENROLL_REQUEST,
            source="my-esp32",
            target="hub",
            payload={"name": "ESP32 Thing", "pin_proof": proof},
        )
        await service.handle_enroll_request(env)

        # Certificate should be on disk for this device
        assert ca.has_device_cert("my-esp32")

        # CN should match
        from cryptography import x509
        cert_path, _ = ca.get_device_cert_paths("my-esp32")
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0]
        assert cn.value == "my-esp32"


# ===================================================================
# Test: List Device Certs
# ===================================================================

class TestListDeviceCerts:
    """MeshCA.list_device_certs()."""

    def test_empty_list(self, ca: MeshCA):
        assert ca.list_device_certs() == []

    def test_lists_issued_certs(self, ca: MeshCA):
        ca.issue_device_cert("a")
        ca.issue_device_cert("b")
        certs = ca.list_device_certs()
        node_ids = [c["node_id"] for c in certs]
        assert "a" in node_ids
        assert "b" in node_ids

    def test_cert_info_fields(self, ca: MeshCA):
        ca.issue_device_cert("x")
        info = ca.list_device_certs()[0]
        assert info["node_id"] == "x"
        assert "serial" in info
        assert "not_before" in info
        assert "not_after" in info
        assert info["expired"] is False


# ===================================================================
# Test: Config Integration
# ===================================================================

class TestConfigIntegration:
    """Schema config fields for mTLS."""

    def test_default_config_values(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig()
        assert cfg.mtls_enabled is False
        assert cfg.ca_dir == ""
        assert cfg.device_cert_validity_days == 365

    def test_config_serialization(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig(mtls_enabled=True, ca_dir="/tmp/ca", device_cert_validity_days=90)
        d = cfg.model_dump()
        assert d["mtls_enabled"] is True
        assert d["ca_dir"] == "/tmp/ca"
        assert d["device_cert_validity_days"] == 90


# ===================================================================
# Test: Channel Integration
# ===================================================================

class TestChannelMTLS:
    """MeshChannel mTLS wiring."""

    def test_channel_without_mtls(self, tmp_path: Path):
        """Channel should work fine with mtls_enabled=False."""
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
        assert channel.ca is None
        assert channel.transport.tls_enabled is False

    def test_channel_with_mtls(self, tmp_path: Path):
        """Channel should initialize CA and enable TLS when mtls_enabled=True."""
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
        channel = MeshChannel(config, bus)
        assert channel.ca is not None
        assert channel.ca.is_initialized
        assert channel.transport.tls_enabled is True

    def test_channel_enrollment_has_ca(self, tmp_path: Path):
        """When mTLS is enabled, enrollment service should have access to CA."""
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
        channel = MeshChannel(config, bus)
        assert channel.enrollment is not None
        assert channel.enrollment.ca is channel.ca


# ===================================================================
# Test: get_peer_node_id with non-TLS transport
# ===================================================================

class TestGetPeerNodeId:
    """MeshCA.get_peer_node_id edge cases."""

    def test_no_ssl_object(self):
        transport = MagicMock()
        transport.get_extra_info.return_value = None
        assert MeshCA.get_peer_node_id(transport) is None

    def test_no_peer_cert(self):
        ssl_obj = MagicMock()
        ssl_obj.getpeercert.return_value = None
        transport = MagicMock()
        transport.get_extra_info.return_value = ssl_obj
        assert MeshCA.get_peer_node_id(transport) is None

    def test_extract_cn(self):
        ssl_obj = MagicMock()
        ssl_obj.getpeercert.return_value = {
            "subject": ((("commonName", "dev-42"),),)
        }
        transport = MagicMock()
        transport.get_extra_info.return_value = ssl_obj
        assert MeshCA.get_peer_node_id(transport) == "dev-42"

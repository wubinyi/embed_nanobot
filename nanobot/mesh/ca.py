"""Local Certificate Authority for mTLS device authentication.

Provides a self-signed root CA that issues per-device X.509 certificates.
When mTLS is enabled, the Hub's TCP server and all device connections use
mutual TLS — both sides present and verify certificates signed by this CA.

Key choices:
- **EC P-256 (SECP256R1)**: Good performance on constrained devices (ESP32/mbedTLS).
- **Node ID in CN**: Each device cert has ``CN=<node_id>`` for identity binding.
- **Separate hub cert**: The Hub itself gets a cert (``CN=hub``) so devices can
  verify the Hub during the TLS handshake.

Requires the ``cryptography`` package (already a project dependency).
"""

from __future__ import annotations

import datetime
import ssl
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    HAS_CRYPTO = True
except ImportError:  # pragma: no cover
    HAS_CRYPTO = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CA_VALIDITY_DAYS = 3650  # ~10 years
DEVICE_CERT_VALIDITY_DAYS = 365  # 1 year
_KEY_CURVE = "SECP256R1"


def is_available() -> bool:
    """Return ``True`` if the ``cryptography`` library is installed."""
    return HAS_CRYPTO


# ---------------------------------------------------------------------------
# MeshCA
# ---------------------------------------------------------------------------
class MeshCA:
    """Local Certificate Authority for mesh device authentication.

    Parameters
    ----------
    ca_dir:
        Directory where CA key/cert and device certs are stored.
    device_cert_validity_days:
        Validity period for issued device certificates.
    """

    def __init__(
        self,
        ca_dir: Path | str,
        device_cert_validity_days: int = DEVICE_CERT_VALIDITY_DAYS,
    ) -> None:
        if not HAS_CRYPTO:
            raise RuntimeError(
                "cryptography package required for mTLS — "
                "install with: pip install cryptography"
            )
        self.ca_dir = Path(ca_dir)
        self.ca_dir.mkdir(parents=True, exist_ok=True)
        self.device_cert_validity_days = device_cert_validity_days
        self._ca_key: Any = None  # ec.EllipticCurvePrivateKey
        self._ca_cert: Any = None  # x509.Certificate

    # -- paths ---------------------------------------------------------------

    @property
    def ca_key_path(self) -> Path:
        return self.ca_dir / "ca.key"

    @property
    def ca_cert_path(self) -> Path:
        return self.ca_dir / "ca.crt"

    @property
    def devices_dir(self) -> Path:
        d = self.ca_dir / "devices"
        d.mkdir(exist_ok=True)
        return d

    @property
    def is_initialized(self) -> bool:
        """Return ``True`` if CA key and cert exist on disk."""
        return self.ca_key_path.exists() and self.ca_cert_path.exists()

    # -- initialization ------------------------------------------------------

    def initialize(self) -> None:
        """Generate or load the CA key pair and self-signed root certificate.

        Idempotent — if the CA already exists on disk, it is loaded without
        re-generating.
        """
        if self.is_initialized:
            self._load_ca()
            logger.info("[Mesh/CA] loaded existing CA from {}", self.ca_dir)
            return

        key = ec.generate_private_key(ec.SECP256R1())

        now = datetime.datetime.now(datetime.timezone.utc)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "embed_nanobot Mesh CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "embed_nanobot"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=CA_VALIDITY_DAYS))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0), critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )

        # Persist with restricted permissions
        self.ca_key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.ca_key_path.chmod(0o600)
        self.ca_cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        self._ca_key = key
        self._ca_cert = cert
        logger.info("[Mesh/CA] initialized new CA in {}", self.ca_dir)

    def _load_ca(self) -> None:
        """Load existing CA key and certificate from disk."""
        self._ca_key = serialization.load_pem_private_key(
            self.ca_key_path.read_bytes(),
            password=None,
        )
        self._ca_cert = x509.load_pem_x509_certificate(
            self.ca_cert_path.read_bytes(),
        )

    # -- device certificate issuance -----------------------------------------

    def issue_device_cert(self, node_id: str) -> tuple[bytes, bytes]:
        """Issue a certificate for *node_id* signed by this CA.

        Returns ``(cert_pem, key_pem)`` as bytes.  Also persists to
        ``devices_dir/{node_id}.crt`` and ``.key``.

        Raises ``RuntimeError`` if the CA has not been initialized.
        """
        if self._ca_key is None or self._ca_cert is None:
            raise RuntimeError("CA not initialized — call initialize() first")

        device_key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.datetime.now(datetime.timezone.utc)

        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, node_id),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "embed_nanobot"),
        ])

        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(self._ca_cert.subject)
            .public_key(device_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(
                now + datetime.timedelta(days=self.device_cert_validity_days),
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([
                    ExtendedKeyUsageOID.CLIENT_AUTH,
                    ExtendedKeyUsageOID.SERVER_AUTH,
                ]),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(node_id)]),
                critical=False,
            )
        )

        device_cert = builder.sign(self._ca_key, hashes.SHA256())

        cert_pem = device_cert.public_bytes(serialization.Encoding.PEM)
        key_pem = device_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        # Persist
        cert_path = self.devices_dir / f"{node_id}.crt"
        key_path = self.devices_dir / f"{node_id}.key"
        cert_path.write_bytes(cert_pem)
        key_path.write_bytes(key_pem)
        key_path.chmod(0o600)

        logger.info("[Mesh/CA] issued certificate for node {}", node_id)
        return cert_pem, key_pem

    def has_device_cert(self, node_id: str) -> bool:
        """Return ``True`` if a certificate has been issued for *node_id*."""
        return (self.devices_dir / f"{node_id}.crt").exists()

    def get_device_cert_paths(self, node_id: str) -> tuple[Path, Path]:
        """Return ``(cert_path, key_path)`` for *node_id*."""
        return (
            self.devices_dir / f"{node_id}.crt",
            self.devices_dir / f"{node_id}.key",
        )

    def get_ca_cert_pem(self) -> bytes:
        """Return the CA certificate as PEM bytes (for distributing to devices)."""
        if self._ca_cert is None:
            raise RuntimeError("CA not initialized")
        return self._ca_cert.public_bytes(serialization.Encoding.PEM)

    # -- SSL context creation ------------------------------------------------

    def create_server_ssl_context(self) -> ssl.SSLContext:
        """Create an SSL context for the Hub's TCP server (mTLS).

        The context requires client certificates signed by this CA.
        """
        if not self.is_initialized:
            raise RuntimeError("CA not initialized")

        # Ensure Hub has a cert
        if not self.has_device_cert("hub"):
            self.issue_device_cert("hub")

        hub_cert, hub_key = self.get_device_cert_paths("hub")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(hub_cert), str(hub_key))
        ctx.load_verify_locations(str(self.ca_cert_path))
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = False  # node_ids are not DNS hostnames
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def create_client_ssl_context(self, node_id: str) -> ssl.SSLContext:
        """Create an SSL context for a device connecting to the Hub.

        The device presents its certificate; the Hub's cert is verified
        against the CA.

        Raises ``FileNotFoundError`` if *node_id* does not have a cert.
        """
        cert_path, key_path = self.get_device_cert_paths(node_id)
        if not cert_path.exists():
            raise FileNotFoundError(f"No certificate for device {node_id!r}")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        ctx.load_verify_locations(str(self.ca_cert_path))
        ctx.check_hostname = False  # node_ids are not DNS hostnames
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    # -- certificate inspection ----------------------------------------------

    @staticmethod
    def get_peer_node_id(
        transport: Any,  # asyncio.Transport with SSL
    ) -> str | None:
        """Extract node_id (CN) from the peer's certificate.

        Works with ``asyncio.Transport`` objects that have an underlying
        SSL socket (i.e., from connections started with ``ssl=``).
        """
        ssl_object = transport.get_extra_info("ssl_object")
        if ssl_object is None:
            return None
        cert = ssl_object.getpeercert()
        if not cert:
            return None
        for rdn in cert.get("subject", ()):
            for attr_type, value in rdn:
                if attr_type == "commonName":
                    return value
        return None

    def list_device_certs(self) -> list[dict[str, Any]]:
        """List all issued device certificates with metadata."""
        certs: list[dict[str, Any]] = []
        for cert_file in sorted(self.devices_dir.glob("*.crt")):
            node_id = cert_file.stem
            try:
                cert_data = x509.load_pem_x509_certificate(cert_file.read_bytes())
                certs.append({
                    "node_id": node_id,
                    "serial": cert_data.serial_number,
                    "not_before": cert_data.not_valid_before_utc.isoformat(),
                    "not_after": cert_data.not_valid_after_utc.isoformat(),
                    "expired": (
                        cert_data.not_valid_after_utc
                        < datetime.datetime.now(datetime.timezone.utc)
                    ),
                })
            except Exception as exc:
                logger.warning("[Mesh/CA] failed to read cert {}: {}", cert_file, exc)
        return certs

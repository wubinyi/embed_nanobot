"""TCP transport layer for reliable LAN mesh messaging.

Each node runs a TCP server.  To send a message, the sender opens a short-lived
TCP connection to the target peer (looked up via the discovery module), writes
one length-prefixed JSON envelope, and closes the connection.

This intentionally simple design avoids the complexity of persistent
connections, reconnect logic, and multiplexing — all of which are unnecessary
on a low-latency LAN.
"""

from __future__ import annotations

import asyncio
import ssl as _ssl
from typing import Awaitable, Callable

from loguru import logger

from nanobot.mesh import encryption
from nanobot.mesh.resilience import DEFAULT_RETRY, RetryPolicy, retry_send
from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
from nanobot.mesh.protocol import MeshEnvelope, MsgType, read_envelope, write_envelope
from nanobot.mesh.security import KeyStore

# Avoid circular imports; enrollment is only needed for type checking.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.mesh.enrollment import EnrollmentService

# Callback type: receives a MeshEnvelope and returns nothing.
MessageHandler = Callable[[MeshEnvelope], Awaitable[None]]


class MeshTransport:
    """TCP transport for sending and receiving mesh envelopes.

    Parameters
    ----------
    node_id:
        This node's unique identifier.
    discovery:
        A started ``UDPDiscovery`` instance for peer lookup.
    host:
        Interface to bind the TCP server on (default ``"0.0.0.0"``).
    tcp_port:
        TCP port to listen on (default 18800).
    """

    def __init__(
        self,
        node_id: str,
        discovery: UDPDiscovery,
        host: str = "0.0.0.0",
        tcp_port: int = 18800,
        key_store: KeyStore | None = None,
        psk_auth_enabled: bool = True,
        allow_unauthenticated: bool = False,
        encryption_enabled: bool = True,
        server_ssl_context: _ssl.SSLContext | None = None,
        client_ssl_context_factory: Callable[[str], _ssl.SSLContext | None] | None = None,
    ):
        self.node_id = node_id
        self.discovery = discovery
        self.host = host
        self.tcp_port = tcp_port
        self._server: asyncio.Server | None = None
        self._handlers: list[MessageHandler] = []
        # --- embed_nanobot extensions (PSK auth, task 1.9) ---
        self.key_store = key_store
        self.psk_auth_enabled = psk_auth_enabled
        self.allow_unauthenticated = allow_unauthenticated
        # --- embed_nanobot extensions: payload encryption (task 1.11) ---
        self.encryption_enabled = encryption_enabled
        # --- embed_nanobot extensions: device enrollment (task 1.10) ---
        self.enrollment_service: EnrollmentService | None = None
        # --- embed_nanobot extensions: mTLS (task 3.1) ---
        self.server_ssl_context = server_ssl_context
        self._client_ssl_factory = client_ssl_context_factory
        self.tls_enabled = server_ssl_context is not None
        # --- embed_nanobot extensions: CRL revocation check (task 3.2) ---
        self.revocation_check_fn: Callable[[str], bool] | None = None

    # -- handler registration ------------------------------------------------

    def on_message(self, handler: MessageHandler) -> None:
        """Register a callback that is invoked for every received envelope."""
        self._handlers.append(handler)

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the TCP listener."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.tcp_port,
            ssl=self.server_ssl_context,
        )
        tls_tag = " (mTLS)" if self.tls_enabled else ""
        logger.info(
            f"[Mesh/Transport] listening on {self.host}:{self.tcp_port} "
            f"as node={self.node_id}{tls_tag}"
        )

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("[Mesh/Transport] stopped")

    # -- receiving -----------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle one inbound TCP connection (one envelope per connection)."""
        try:
            # --- embed_nanobot: CRL revocation check (task 3.2) ---
            # Check if the peer's certificate has been revoked before
            # processing any data.  Done at application level because
            # Python's ssl module doesn't support CRL file loading.
            if self.tls_enabled and self.revocation_check_fn is not None:
                from nanobot.mesh.ca import MeshCA
                peer_id = MeshCA.get_peer_node_id(writer.transport)
                if peer_id and self.revocation_check_fn(peer_id):
                    logger.warning(
                        "[Mesh/Transport] rejected connection from revoked node {}",
                        peer_id,
                    )
                    return

            env = await asyncio.wait_for(read_envelope(reader), timeout=10.0)
            if env is None:
                return
            # --- embed_nanobot: PSK authentication check ---
            # When TLS is active, transport-level auth is already done;
            # skip HMAC verification and AES-GCM decryption.
            if not self.tls_enabled:
                if not self._verify_inbound(env):
                    return
                # --- embed_nanobot: decrypt payload after auth verification ---
                self._decrypt_inbound(env)
            logger.debug(
                f"[Mesh/Transport] received {env.type} from {env.source}"
            )
            # Auto-reply with PONG when we receive a PING
            if env.type == MsgType.PING:
                pong = MeshEnvelope(
                    type=MsgType.PONG,
                    source=self.node_id,
                    target=env.source,
                )
                write_envelope(writer, pong)
                await writer.drain()
            # Dispatch to handlers
            for handler in self._handlers:
                try:
                    await handler(env)
                except Exception as exc:
                    logger.error(f"[Mesh/Transport] handler error: {exc}")
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError) as exc:
            logger.debug(f"[Mesh/Transport] connection error: {exc}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # -- sending -------------------------------------------------------------

    async def send(self, env: MeshEnvelope) -> bool:
        """Send an envelope to the target peer.

        Returns ``True`` on success, ``False`` if the peer is unreachable.
        """
        peer = self.discovery.get_peer(env.target)
        if peer is None:
            logger.warning(
                f"[Mesh/Transport] peer {env.target!r} not found or offline"
            )
            return False
        return await self._send_to(peer, env)

    # --- embed_nanobot: resilience (task 3.5) ---
    async def send_with_retry(
        self,
        env: MeshEnvelope,
        policy: RetryPolicy = DEFAULT_RETRY,
    ) -> bool:
        """Send an envelope with exponential-backoff retries.

        Falls back to ``retry_send`` wrapping :meth:`send`.
        """
        return await retry_send(
            self.send, env,
            policy=policy,
            label=f"send→{env.target}",
        )

    async def send_to_address(
        self,
        ip: str,
        port: int,
        env: MeshEnvelope,
    ) -> bool:
        """Send an envelope to an explicit IP:port."""
        peer = PeerInfo(node_id=env.target, ip=ip, tcp_port=port)
        return await self._send_to(peer, env)

    async def _send_to(self, peer: PeerInfo, env: MeshEnvelope) -> bool:
        try:
            # --- embed_nanobot: encrypt then sign outbound envelopes ---
            # When TLS is active, skip HMAC/AES-GCM (TLS handles both).
            if not self.tls_enabled:
                self._encrypt_outbound(env)
                self._sign_outbound(env)
            client_ssl = self._get_client_ssl(env.target) if self.tls_enabled else None
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.ip, peer.tcp_port, ssl=client_ssl),
                timeout=5.0,
            )
            write_envelope(writer, env)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError) as exc:
            logger.warning(
                f"[Mesh/Transport] failed to send to {peer.node_id} "
                f"@ {peer.ip}:{peer.tcp_port}: {exc}"
            )
            return False

    # -- embed_nanobot: mTLS helpers (task 3.1) ------------------------------

    def _get_client_ssl(self, target_node_id: str) -> _ssl.SSLContext | None:
        """Return an SSL context for connecting to *target_node_id*.

        Uses the factory callback set by the channel, which queries the CA
        for the device's certificate.
        """
        if self._client_ssl_factory is None:
            return None
        try:
            return self._client_ssl_factory(target_node_id)
        except Exception as exc:
            logger.warning(
                "[Mesh/Transport] failed to create client SSL for {}: {}",
                target_node_id, exc,
            )
            return None

    # -- embed_nanobot: CRL hot-reload (task 3.2) ----------------------------

    def update_server_ssl_context(self, ctx: _ssl.SSLContext) -> None:
        """Replace the server SSL context (e.g. after CRL update).

        Only affects new incoming connections — existing connections are not
        forcibly terminated.
        """
        self.server_ssl_context = ctx
        self.tls_enabled = ctx is not None
        logger.info("[Mesh/Transport] server SSL context updated")

    # -- embed_nanobot: PSK authentication helpers (task 1.9) ----------------

    def _verify_inbound(self, env: MeshEnvelope) -> bool:
        """Verify HMAC signature on an inbound envelope.

        Returns ``True`` if the message should be processed, ``False`` to drop.
        """
        if not self.psk_auth_enabled or self.key_store is None:
            return True  # auth disabled — pass through

        # --- embed_nanobot: allow ENROLL_REQUEST when enrollment is active ---
        if env.type == MsgType.ENROLL_REQUEST:
            if self.enrollment_service and self.enrollment_service.is_enrollment_active:
                logger.debug(
                    f"[Mesh/Security] allowing ENROLL_REQUEST from {env.source} "
                    "(enrollment active)"
                )
                return True
            logger.warning(
                f"[Mesh/Security] REJECTED ENROLL_REQUEST from {env.source} "
                "(no active enrollment)"
            )
            return False

        # Check if the message carries auth fields
        if not env.hmac or not env.nonce:
            if self.allow_unauthenticated:
                logger.warning(
                    f"[Mesh/Security] UNSIGNED message from {env.source} — "
                    "allow_unauthenticated=True, processing anyway"
                )
                return True
            logger.warning(
                f"[Mesh/Security] REJECTED unsigned message from {env.source}"
            )
            return False

        # Look up PSK
        psk = self.key_store.get_psk(env.source)
        if psk is None:
            logger.warning(
                f"[Mesh/Security] REJECTED message from unknown node {env.source!r}"
            )
            return False

        # Verify HMAC
        canonical = env.canonical_bytes()
        if not KeyStore.verify_hmac(canonical, env.nonce, psk, env.hmac):
            logger.warning(
                f"[Mesh/Security] REJECTED message from {env.source} — "
                "HMAC verification failed"
            )
            return False

        # Timestamp window check
        if not self.key_store.check_timestamp(env.ts):
            logger.warning(
                f"[Mesh/Security] REJECTED message from {env.source} — "
                f"timestamp {env.ts} outside window"
            )
            return False

        # Nonce replay check
        if not self.key_store.check_and_record_nonce(env.nonce):
            logger.warning(
                f"[Mesh/Security] REJECTED replay from {env.source} — "
                f"nonce {env.nonce!r} already seen"
            )
            return False

        logger.debug(f"[Mesh/Security] authenticated message from {env.source}")
        return True

    def _sign_outbound(self, env: MeshEnvelope) -> None:
        """Sign an outbound envelope with this node's PSK (if available)."""
        if not self.psk_auth_enabled or self.key_store is None:
            return

        psk = self.key_store.get_psk(self.node_id)
        if psk is None:
            return  # Hub's own node might not be in the key store

        env.nonce = KeyStore.generate_nonce()
        canonical = env.canonical_bytes()
        env.hmac = KeyStore.compute_hmac(canonical, env.nonce, psk)

    # -- embed_nanobot: AES-256-GCM encryption helpers (task 1.11) -----------

    # Message types whose payloads carry user/device data worth encrypting.
    _ENCRYPTED_TYPES = {MsgType.CHAT, MsgType.COMMAND, MsgType.RESPONSE}

    def _encrypt_outbound(self, env: MeshEnvelope) -> None:
        """Encrypt the envelope payload with AES-256-GCM (if enabled).

        Only encrypts actionable message types (CHAT, COMMAND, RESPONSE).
        Enrollment, heartbeat, and broadcast messages are left in plaintext.
        Must be called **before** ``_sign_outbound`` (Encrypt-then-MAC).
        """
        if not self.encryption_enabled or self.key_store is None:
            return
        if not encryption.is_available():
            return
        if env.type not in self._ENCRYPTED_TYPES:
            return
        if env.target == "*":
            return  # Cannot encrypt broadcast — no single shared key

        psk = self.key_store.get_psk(env.target)
        if psk is None:
            return  # Unknown target — send unencrypted

        result = encryption.encrypt_payload(
            payload=env.payload,
            psk_hex=psk,
            msg_type=env.type,
            source=env.source,
            target=env.target,
            ts=env.ts,
        )
        if result:
            env.encrypted_payload, env.iv = result
            env.payload = {}  # Clear plaintext

    def _decrypt_inbound(self, env: MeshEnvelope) -> None:
        """Decrypt the envelope payload if it carries AES-256-GCM ciphertext.

        Must be called **after** ``_verify_inbound`` (Encrypt-then-MAC).
        If the message is not encrypted, this is a no-op.
        """
        if not env.encrypted_payload or not env.iv:
            return  # Not encrypted — nothing to do
        if self.key_store is None:
            return

        psk = self.key_store.get_psk(env.source)
        if psk is None:
            logger.warning(
                f"[Mesh/Encryption] cannot decrypt from {env.source} — "
                "PSK not found"
            )
            return

        payload = encryption.decrypt_payload(
            encrypted_payload_hex=env.encrypted_payload,
            iv_hex=env.iv,
            psk_hex=psk,
            msg_type=env.type,
            source=env.source,
            target=env.target,
            ts=env.ts,
        )
        if payload is not None:
            env.payload = payload
            env.encrypted_payload = ""
            env.iv = ""
        else:
            logger.warning(
                f"[Mesh/Encryption] failed to decrypt message from {env.source}"
            )

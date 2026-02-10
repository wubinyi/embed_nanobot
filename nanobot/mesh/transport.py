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
from typing import Awaitable, Callable

from loguru import logger

from nanobot.mesh.discovery import PeerInfo, UDPDiscovery
from nanobot.mesh.protocol import MeshEnvelope, MsgType, read_envelope, write_envelope

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
    ):
        self.node_id = node_id
        self.discovery = discovery
        self.host = host
        self.tcp_port = tcp_port
        self._server: asyncio.Server | None = None
        self._handlers: list[MessageHandler] = []

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
        )
        logger.info(
            f"[Mesh/Transport] listening on {self.host}:{self.tcp_port} "
            f"as node={self.node_id}"
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
            env = await asyncio.wait_for(read_envelope(reader), timeout=10.0)
            if env is None:
                return
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
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.ip, peer.tcp_port),
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

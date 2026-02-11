"""UDP broadcast discovery for LAN mesh peers.

How it works
------------
1. Each node periodically broadcasts a small JSON beacon on a well-known UDP
   port (default 18799).
2. Every node listens on the same port and maintains a peer table that maps
   ``node_id`` → ``(ip, tcp_port, last_seen)``.
3. Peers that haven't been seen for ``timeout`` seconds are considered offline.

The beacon payload:
    {"node_id": "...", "tcp_port": 18800, "roles": ["nanobot"]}
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class PeerInfo:
    """Metadata about a discovered peer."""

    node_id: str
    ip: str
    tcp_port: int
    roles: list[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)


class UDPDiscovery:
    """Broadcast-based peer discovery over UDP.

    Parameters
    ----------
    node_id:
        This node's unique identifier.
    tcp_port:
        The TCP port where this node's mesh transport is listening.
    udp_port:
        The shared UDP port for discovery beacons (default 18799).
    broadcast_interval:
        Seconds between beacon broadcasts (default 10).
    peer_timeout:
        Seconds after which a silent peer is considered offline (default 30).
    roles:
        Tags describing this node (e.g. ``["nanobot"]``, ``["device", "vacuum"]``).
    """

    def __init__(
        self,
        node_id: str,
        tcp_port: int,
        udp_port: int = 18799,
        broadcast_interval: float = 10.0,
        peer_timeout: float = 30.0,
        roles: list[str] | None = None,
    ):
        self.node_id = node_id
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.broadcast_interval = broadcast_interval
        self.peer_timeout = peer_timeout
        self.roles = roles or ["nanobot"]

        # node_id → PeerInfo
        self.peers: dict[str, PeerInfo] = {}
        self._running = False
        self._sock: socket.socket | None = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the beacon broadcaster and listener."""
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self._sock.bind(("", self.udp_port))
        self._sock.setblocking(False)

        loop = asyncio.get_running_loop()
        asyncio.ensure_future(self._broadcast_loop(loop))
        asyncio.ensure_future(self._listen_loop(loop))
        logger.info(
            f"[Mesh/Discovery] started: node={self.node_id} udp={self.udp_port} "
            f"tcp={self.tcp_port}"
        )

    async def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
            self._sock = None
        logger.info("[Mesh/Discovery] stopped")

    # -- beacon broadcast ----------------------------------------------------

    async def _broadcast_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        beacon = json.dumps({
            "node_id": self.node_id,
            "tcp_port": self.tcp_port,
            "roles": self.roles,
        }).encode()
        while self._running:
            try:
                await loop.sock_sendto(
                    self._sock, beacon, ("255.255.255.255", self.udp_port)   # type: ignore[arg-type]
                )
            except OSError as exc:
                logger.debug(f"[Mesh/Discovery] broadcast error: {exc}")
            await asyncio.sleep(self.broadcast_interval)

    # -- beacon listener -----------------------------------------------------

    async def _listen_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(self._sock, 1024)  # type: ignore[arg-type]
                self._handle_beacon(data, addr[0])
            except OSError:
                if not self._running:
                    break
                await asyncio.sleep(0.1)

    def _handle_beacon(self, data: bytes, ip: str) -> None:
        try:
            info: dict[str, Any] = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        nid = info.get("node_id", "")
        if not nid or nid == self.node_id:
            return  # ignore own beacons

        tcp_port = int(info.get("tcp_port", 0))
        roles = info.get("roles", [])

        if nid not in self.peers:
            logger.info(f"[Mesh/Discovery] new peer: {nid} @ {ip}:{tcp_port} roles={roles}")

        self.peers[nid] = PeerInfo(
            node_id=nid,
            ip=ip,
            tcp_port=tcp_port,
            roles=roles,
            last_seen=time.time(),
        )

    # -- queries -------------------------------------------------------------

    def get_peer(self, node_id: str) -> PeerInfo | None:
        """Return info for a specific peer, or None if unknown / offline."""
        peer = self.peers.get(node_id)
        if peer and (time.time() - peer.last_seen) < self.peer_timeout:
            return peer
        return None

    def online_peers(self) -> list[PeerInfo]:
        """Return all currently-online peers."""
        now = time.time()
        return [
            p for p in self.peers.values()
            if (now - p.last_seen) < self.peer_timeout
        ]

    def prune(self) -> None:
        """Remove peers that have not been seen within the timeout."""
        now = time.time()
        stale = [nid for nid, p in self.peers.items() if (now - p.last_seen) >= self.peer_timeout]
        for nid in stale:
            logger.debug(f"[Mesh/Discovery] pruning stale peer: {nid}")
            del self.peers[nid]

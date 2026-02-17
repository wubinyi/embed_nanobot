"""Wire-level protocol for LAN mesh messages.

Every mesh message is a JSON envelope sent over TCP with a 4-byte big-endian
length prefix so the receiver knows exactly how many bytes to read.

Envelope format
---------------
{
    "type": "...",         # message type (see MsgType)
    "source": "node-id",  # sender node ID
    "target": "node-id",  # receiver node ID ("*" for broadcast)
    "payload": { ... },   # type-specific body
    "ts": 1700000000.0    # Unix timestamp
}
"""

from __future__ import annotations

import json
import struct
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MsgType(str, Enum):
    """Recognised mesh message types."""

    # Chat / command messages between nodes
    CHAT = "chat"
    # Command directed at a device (e.g. "turn on AC")
    COMMAND = "command"
    # Acknowledgement / response from a device
    RESPONSE = "response"
    # Heartbeat for presence tracking
    PING = "ping"
    PONG = "pong"


@dataclass
class MeshEnvelope:
    """One mesh message."""

    type: str
    source: str
    target: str  # "*" means broadcast
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    # --- embed_nanobot extensions (PSK auth, task 1.9) ---
    nonce: str = ""   # Random 16-hex-char nonce for replay protection
    hmac: str = ""    # HMAC-SHA256 hex digest for authentication

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the envelope as a plain dict (includes hmac/nonce if set)."""
        d = asdict(self)
        # Omit empty auth fields for backward compatibility
        if not d.get("nonce"):
            d.pop("nonce", None)
        if not d.get("hmac"):
            d.pop("hmac", None)
        return d

    def to_bytes(self) -> bytes:
        """Serialise to length-prefixed JSON bytes."""
        body = json.dumps(self.to_dict(), ensure_ascii=False).encode()
        return struct.pack("!I", len(body)) + body

    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshEnvelope":
        """Deserialise from raw JSON bytes (no length prefix)."""
        obj = json.loads(data)
        return cls(
            type=obj.get("type", ""),
            source=obj.get("source", ""),
            target=obj.get("target", ""),
            payload=obj.get("payload", {}),
            ts=obj.get("ts", 0.0),
            nonce=obj.get("nonce", ""),
            hmac=obj.get("hmac", ""),
        )

    def canonical_bytes(self) -> bytes:
        """Return canonical JSON bytes for HMAC computation.

        Excludes ``hmac`` and ``nonce`` fields, serialises with sorted keys.
        """
        d = asdict(self)
        d.pop("hmac", None)
        d.pop("nonce", None)
        return json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")


async def read_envelope(reader: Any) -> MeshEnvelope | None:
    """Read one length-prefixed envelope from an ``asyncio.StreamReader``.

    Returns *None* on EOF / connection reset.
    """
    header = await reader.readexactly(4)
    (length,) = struct.unpack("!I", header)
    body = await reader.readexactly(length)
    return MeshEnvelope.from_bytes(body)


def write_envelope(writer: Any, env: MeshEnvelope) -> None:
    """Write one length-prefixed envelope to an ``asyncio.StreamWriter``."""
    writer.write(env.to_bytes())

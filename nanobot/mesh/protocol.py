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

    # -- serialisation -------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialise to length-prefixed JSON bytes."""
        body = json.dumps(asdict(self), ensure_ascii=False).encode()
        return struct.pack("!I", len(body)) + body

    @classmethod
    def from_bytes(cls, data: bytes) -> "MeshEnvelope":
        """Deserialise from raw JSON bytes (no length prefix)."""
        obj = json.loads(data)
        return cls(**obj)


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

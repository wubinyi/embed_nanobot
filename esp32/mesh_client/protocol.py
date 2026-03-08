"""protocol.py — Wire framing for the embed_nanobot mesh protocol.

Every message is a 4-byte big-endian length prefix followed by UTF-8 JSON.

Envelope schema (matches nanobot/mesh/protocol.py on the hub):
  {
    "type":    str,    # message type
    "source":  str,    # sender node_id
    "target":  str,    # receiver node_id or "*" for broadcast
    "payload": dict,
    "ts":      float,  # unix timestamp
    "nonce":   str,    # 16 hex chars, random per message
    "hmac":    str     # HMAC-SHA256 signature (empty string if no PSK yet)
  }
"""

import json
import struct
import time
import os
import ubinascii


def encode(envelope: dict) -> bytes:
    """Serialize an envelope to a length-prefixed byte frame."""
    data = json.dumps(envelope).encode("utf-8")
    header = struct.pack(">I", len(data))
    return header + data


def decode(sock) -> dict:
    """Read exactly one envelope from *sock*. Blocks until complete."""
    # Read 4-byte length header
    header = _recv_exact(sock, 4)
    (length,) = struct.unpack(">I", header)
    # Read message body
    body = _recv_exact(sock, length)
    return json.loads(body.decode("utf-8"))


def _recv_exact(sock, n: int) -> bytes:
    """Read exactly n bytes from sock, handling partial reads."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("Connection closed by remote")
        buf += chunk
    return buf


def make_nonce() -> str:
    """Return a fresh 16-hex-char random nonce."""
    return ubinascii.hexlify(os.urandom(8)).decode()


def build_envelope(msg_type: str, source: str, target: str,
                   payload: dict, psk: bytes | None = None) -> dict:
    """Create a signed envelope ready to send.

    If *psk* is provided the HMAC field is filled; otherwise it is empty
    (acceptable only during enrollment before a PSK is established).
    """
    from security import sign_envelope   # local import to avoid circular refs
    nonce = make_nonce()
    env = {
        "type":    msg_type,
        "source":  source,
        "target":  target,
        "payload": payload,
        "ts":      time.time(),
        "nonce":   nonce,
        "hmac":    "",
    }
    if psk is not None:
        env["hmac"] = sign_envelope(env, psk)
    return env

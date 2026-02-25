"""OTA (Over-The-Air) firmware update protocol for mesh devices.

Manages firmware images and orchestrates chunked push-based updates
to devices over the existing mesh transport layer.

Architecture
------------
- ``FirmwareInfo``  — metadata for one firmware image
- ``FirmwareStore`` — directory-based storage with JSON manifest
- ``OTASession``    — state machine tracking one active transfer
- ``OTAManager``    — orchestrates updates, processes OTA messages

Protocol summary
----------------
Hub sends OTA_OFFER → device replies OTA_ACCEPT/OTA_REJECT → Hub
sends OTA_CHUNK (×N with ACKs) → device sends OTA_VERIFY → Hub
sends OTA_COMPLETE or OTA_ABORT.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.mesh.protocol import MeshEnvelope, MsgType

# Default chunk size (bytes).  Small enough for ESP32 SRAM.
DEFAULT_CHUNK_SIZE = 4096

# Timeout for each protocol phase (seconds).
OFFER_TIMEOUT = 60
CHUNK_ACK_TIMEOUT = 30
VERIFY_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FirmwareInfo:
    """Metadata for one firmware image stored on the Hub."""

    firmware_id: str       # Unique ID (e.g. "sensor-v1.2.0")
    version: str           # Semantic version string
    device_type: str       # Target device type (matches DeviceInfo.device_type)
    filename: str          # File name inside firmware_dir
    size: int = 0          # File size in bytes
    sha256: str = ""       # Hex SHA-256 digest
    added_date: str = ""   # ISO date string

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FirmwareInfo:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class UpdateState(str, Enum):
    """State machine states for an OTA session."""

    OFFERED = "offered"          # OTA_OFFER sent, waiting for ACCEPT/REJECT
    TRANSFERRING = "transferring"  # Sending chunks
    VERIFYING = "verifying"      # All chunks sent, waiting for device OTA_VERIFY
    COMPLETE = "complete"        # Device verified, OTA_COMPLETE sent
    FAILED = "failed"            # Transfer aborted
    REJECTED = "rejected"        # Device rejected the offer


@dataclass
class OTASession:
    """Tracks one active firmware transfer to one device."""

    node_id: str
    firmware: FirmwareInfo
    chunk_size: int = DEFAULT_CHUNK_SIZE
    state: UpdateState = UpdateState.OFFERED
    total_chunks: int = 0
    next_seq: int = 0        # Next chunk sequence number to send
    acked_up_to: int = -1    # Highest contiguous ACK'd seq
    started_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    error: str = ""

    def __post_init__(self) -> None:
        self.total_chunks = max(1, -(-self.firmware.size // self.chunk_size))  # ceil div

    @property
    def progress(self) -> float:
        """Return transfer progress as a fraction 0.0–1.0."""
        if self.total_chunks == 0:
            return 1.0
        return min(1.0, (self.acked_up_to + 1) / self.total_chunks)

    def to_status(self) -> dict[str, Any]:
        """Return a summary dict for external consumers."""
        return {
            "node_id": self.node_id,
            "firmware_id": self.firmware.firmware_id,
            "version": self.firmware.version,
            "state": self.state.value,
            "progress": round(self.progress, 3),
            "total_chunks": self.total_chunks,
            "acked_up_to": self.acked_up_to,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Firmware store
# ---------------------------------------------------------------------------

class FirmwareStore:
    """Directory-based firmware image storage with JSON manifest.

    Parameters
    ----------
    firmware_dir:
        Path to the directory holding firmware binaries and manifest.
    """

    MANIFEST_NAME = "firmware_manifest.json"

    def __init__(self, firmware_dir: str) -> None:
        self._dir = Path(firmware_dir)
        self._manifest: dict[str, FirmwareInfo] = {}

    @property
    def path(self) -> Path:
        return self._dir

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Load manifest from disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._dir / self.MANIFEST_NAME
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text())
                self._manifest = {
                    k: FirmwareInfo.from_dict(v) for k, v in data.items()
                }
                logger.info(
                    "[OTA/Store] loaded {} firmware entries from {}",
                    len(self._manifest), manifest_path,
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("[OTA/Store] failed to load manifest: {}", exc)
                self._manifest = {}
        else:
            self._manifest = {}

    def _save_manifest(self) -> None:
        """Persist manifest to disk."""
        manifest_path = self._dir / self.MANIFEST_NAME
        data = {k: v.to_dict() for k, v in self._manifest.items()}
        manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # -- CRUD ----------------------------------------------------------------

    def add_firmware(
        self,
        firmware_id: str,
        version: str,
        device_type: str,
        data: bytes,
    ) -> FirmwareInfo:
        """Store a firmware image and register it in the manifest.

        Parameters
        ----------
        firmware_id:
            Unique identifier (e.g. "sensor-v1.2.0").
        version:
            Semantic version string.
        device_type:
            Target device type.
        data:
            Raw firmware binary.

        Returns the ``FirmwareInfo`` for the new entry.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        filename = f"{firmware_id}.bin"
        filepath = self._dir / filename
        filepath.write_bytes(data)

        sha256 = hashlib.sha256(data).hexdigest()
        info = FirmwareInfo(
            firmware_id=firmware_id,
            version=version,
            device_type=device_type,
            filename=filename,
            size=len(data),
            sha256=sha256,
            added_date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._manifest[firmware_id] = info
        self._save_manifest()
        logger.info(
            "[OTA/Store] added firmware {!r} v{} ({} bytes, sha256={}…)",
            firmware_id, version, len(data), sha256[:12],
        )
        return info

    def remove_firmware(self, firmware_id: str) -> bool:
        """Remove a firmware image. Returns True if found."""
        info = self._manifest.pop(firmware_id, None)
        if info is None:
            return False
        filepath = self._dir / info.filename
        if filepath.exists():
            filepath.unlink()
        self._save_manifest()
        logger.info("[OTA/Store] removed firmware {!r}", firmware_id)
        return True

    def get_firmware(self, firmware_id: str) -> FirmwareInfo | None:
        """Return metadata for a firmware or None."""
        return self._manifest.get(firmware_id)

    def list_firmware(self) -> list[FirmwareInfo]:
        """Return all tracked firmware entries."""
        return list(self._manifest.values())

    def read_chunk(self, firmware_id: str, offset: int, size: int) -> bytes:
        """Read *size* bytes from the firmware binary at *offset*.

        Returns empty bytes if the firmware_id is unknown or the offset
        is beyond the file end.
        """
        info = self._manifest.get(firmware_id)
        if info is None:
            return b""
        filepath = self._dir / info.filename
        if not filepath.exists():
            return b""
        with open(filepath, "rb") as fh:
            fh.seek(offset)
            return fh.read(size)


# ---------------------------------------------------------------------------
# OTA manager
# ---------------------------------------------------------------------------

class OTAManager:
    """Orchestrates OTA firmware updates across devices.

    One session per device (not one global). Multiple concurrent
    updates to different devices are supported.

    Parameters
    ----------
    store:
        A loaded ``FirmwareStore``.
    send_fn:
        Async function to send a ``MeshEnvelope`` to a device.
        Typically ``MeshTransport.send``.
    node_id:
        Hub's node_id (used as ``source`` in envelopes).
    chunk_size:
        Default chunk size in bytes.
    chunk_ack_timeout:
        Seconds to wait for a chunk ACK before resending.
    """

    def __init__(
        self,
        store: FirmwareStore,
        send_fn: Callable[[MeshEnvelope], Any],
        node_id: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_ack_timeout: int = CHUNK_ACK_TIMEOUT,
    ) -> None:
        self.store = store
        self._send = send_fn
        self.node_id = node_id
        self.chunk_size = chunk_size
        self.chunk_ack_timeout = chunk_ack_timeout
        self._sessions: dict[str, OTASession] = {}  # node_id → session
        self._progress_callbacks: list[Callable[[OTASession], Any]] = []

    # -- progress callbacks --------------------------------------------------

    def on_progress(self, callback: Callable[[OTASession], Any]) -> None:
        """Register a callback invoked on every state/progress change."""
        self._progress_callbacks.append(callback)

    def _notify_progress(self, session: OTASession) -> None:
        for cb in self._progress_callbacks:
            try:
                cb(session)
            except Exception as exc:
                logger.warning("[OTA] progress callback error: {}", exc)

    # -- public API ----------------------------------------------------------

    async def start_update(
        self,
        node_id: str,
        firmware_id: str,
        *,
        chunk_size: int | None = None,
    ) -> OTASession | None:
        """Initiate an OTA update for *node_id*.

        Returns the ``OTASession`` or ``None`` if preconditions fail
        (unknown firmware, already updating this device).
        """
        firmware = self.store.get_firmware(firmware_id)
        if firmware is None:
            logger.warning("[OTA] firmware {!r} not found", firmware_id)
            return None

        if node_id in self._sessions:
            existing = self._sessions[node_id]
            if existing.state in (UpdateState.OFFERED, UpdateState.TRANSFERRING, UpdateState.VERIFYING):
                logger.warning(
                    "[OTA] device {} already has an active OTA session (state={})",
                    node_id, existing.state.value,
                )
                return None

        cs = chunk_size or self.chunk_size
        session = OTASession(
            node_id=node_id,
            firmware=firmware,
            chunk_size=cs,
        )
        self._sessions[node_id] = session

        # Send OTA_OFFER
        offer = MeshEnvelope(
            type=MsgType.OTA_OFFER,
            source=self.node_id,
            target=node_id,
            payload={
                "firmware_id": firmware.firmware_id,
                "version": firmware.version,
                "device_type": firmware.device_type,
                "size": firmware.size,
                "sha256": firmware.sha256,
                "chunk_size": cs,
                "total_chunks": session.total_chunks,
            },
        )
        await self._send(offer)
        logger.info(
            "[OTA] sent offer to {} for firmware {!r} v{} ({} chunks)",
            node_id, firmware.firmware_id, firmware.version, session.total_chunks,
        )
        self._notify_progress(session)
        return session

    async def abort_update(self, node_id: str, reason: str = "cancelled") -> bool:
        """Abort an active OTA session for *node_id*. Returns True if found."""
        session = self._sessions.get(node_id)
        if session is None:
            return False
        if session.state in (UpdateState.COMPLETE, UpdateState.FAILED, UpdateState.REJECTED):
            return False

        session.state = UpdateState.FAILED
        session.error = reason

        abort = MeshEnvelope(
            type=MsgType.OTA_ABORT,
            source=self.node_id,
            target=node_id,
            payload={
                "firmware_id": session.firmware.firmware_id,
                "reason": reason,
            },
        )
        await self._send(abort)
        logger.info("[OTA] aborted update for {}: {}", node_id, reason)
        self._notify_progress(session)
        return True

    def get_session(self, node_id: str) -> OTASession | None:
        """Return the current OTA session for a device, or None."""
        return self._sessions.get(node_id)

    def get_status(self, node_id: str) -> dict[str, Any] | None:
        """Return a status dict for a device's OTA session, or None."""
        session = self._sessions.get(node_id)
        return session.to_status() if session else None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return status dicts for all active sessions."""
        return [s.to_status() for s in self._sessions.values()]

    # --- embed_nanobot: resilience (task 3.5) ---

    def check_timeouts(self) -> list[str]:
        """Check for stalled sessions and mark them as failed.

        Returns list of node_ids whose sessions were timed out.
        """
        now = time.time()
        timed_out: list[str] = []
        for nid, session in self._sessions.items():
            if session.state in (UpdateState.COMPLETE, UpdateState.FAILED, UpdateState.REJECTED):
                continue
            # Determine the appropriate timeout for the current phase
            if session.state == UpdateState.OFFERED:
                timeout = OFFER_TIMEOUT
            elif session.state == UpdateState.VERIFYING:
                timeout = VERIFY_TIMEOUT
            else:  # TRANSFERRING
                timeout = self.chunk_ack_timeout
            if (now - session.last_activity) > timeout:
                session.state = UpdateState.FAILED
                session.error = f"timeout in {session.state.value} state"
                logger.warning(
                    "[OTA] session for {} timed out in {} state after {:.0f}s",
                    nid, session.state.value, now - session.last_activity,
                )
                self._notify_progress(session)
                timed_out.append(nid)
        return timed_out

    def cleanup_completed(self, max_age: float = 300.0) -> int:
        """Remove terminal sessions older than *max_age* seconds.

        Returns the number of sessions removed.
        """
        now = time.time()
        terminal = {UpdateState.COMPLETE, UpdateState.FAILED, UpdateState.REJECTED}
        to_remove = [
            nid for nid, s in self._sessions.items()
            if s.state in terminal and (now - s.last_activity) > max_age
        ]
        for nid in to_remove:
            del self._sessions[nid]
        if to_remove:
            logger.debug("[OTA] cleaned up {} completed sessions", len(to_remove))
        return len(to_remove)

    # -- message handling (called by channel) --------------------------------

    async def handle_ota_message(self, env: MeshEnvelope) -> None:
        """Process an OTA-related message from a device."""
        source = env.source
        msg_type = env.type
        payload = env.payload

        session = self._sessions.get(source)
        if session is None:
            logger.warning(
                "[OTA] received {} from {} but no active session", msg_type, source,
            )
            return

        firmware_id = payload.get("firmware_id", "")
        if firmware_id and firmware_id != session.firmware.firmware_id:
            logger.warning(
                "[OTA] firmware_id mismatch from {}: expected {!r}, got {!r}",
                source, session.firmware.firmware_id, firmware_id,
            )
            return

        session.last_activity = time.time()

        if msg_type == MsgType.OTA_ACCEPT:
            await self._on_accept(session)
        elif msg_type == MsgType.OTA_REJECT:
            self._on_reject(session, payload.get("reason", "unknown"))
        elif msg_type == MsgType.OTA_CHUNK_ACK:
            await self._on_chunk_ack(session, payload)
        elif msg_type == MsgType.OTA_VERIFY:
            await self._on_verify(session, payload)
        elif msg_type == MsgType.OTA_ABORT:
            self._on_device_abort(session, payload.get("reason", "unknown"))
        else:
            logger.warning("[OTA] unexpected message type {} from {}", msg_type, source)

    # -- internal state machine transitions ----------------------------------

    async def _on_accept(self, session: OTASession) -> None:
        if session.state != UpdateState.OFFERED:
            logger.warning(
                "[OTA] {} sent ACCEPT but state is {}", session.node_id, session.state.value,
            )
            return
        session.state = UpdateState.TRANSFERRING
        session.next_seq = 0
        session.acked_up_to = -1
        logger.info("[OTA] {} accepted, starting chunk transfer", session.node_id)
        self._notify_progress(session)
        await self._send_next_chunk(session)

    def _on_reject(self, session: OTASession, reason: str) -> None:
        session.state = UpdateState.REJECTED
        session.error = reason
        logger.info("[OTA] {} rejected offer: {}", session.node_id, reason)
        self._notify_progress(session)

    async def _on_chunk_ack(self, session: OTASession, payload: dict) -> None:
        if session.state != UpdateState.TRANSFERRING:
            return
        seq = payload.get("seq", -1)
        if not isinstance(seq, int) or seq < 0:
            return
        # Update ACK watermark
        if seq > session.acked_up_to:
            session.acked_up_to = seq
        self._notify_progress(session)
        # If all chunks ACK'd, transition to verifying
        if session.acked_up_to >= session.total_chunks - 1:
            session.state = UpdateState.VERIFYING
            logger.info(
                "[OTA] all {} chunks ACK'd by {}, waiting for verify",
                session.total_chunks, session.node_id,
            )
            self._notify_progress(session)
            return
        # Send next chunk
        await self._send_next_chunk(session)

    async def _on_verify(self, session: OTASession, payload: dict) -> None:
        if session.state != UpdateState.VERIFYING:
            logger.warning(
                "[OTA] {} sent VERIFY but state is {}", session.node_id, session.state.value,
            )
            return

        device_hash = payload.get("sha256", "")
        expected_hash = session.firmware.sha256

        if device_hash == expected_hash:
            session.state = UpdateState.COMPLETE
            complete = MeshEnvelope(
                type=MsgType.OTA_COMPLETE,
                source=self.node_id,
                target=session.node_id,
                payload={"firmware_id": session.firmware.firmware_id},
            )
            await self._send(complete)
            logger.info(
                "[OTA] {} verified OK — update complete (firmware {!r})",
                session.node_id, session.firmware.firmware_id,
            )
        else:
            session.state = UpdateState.FAILED
            session.error = f"hash mismatch: expected {expected_hash[:12]}…, got {device_hash[:12]}…"
            abort = MeshEnvelope(
                type=MsgType.OTA_ABORT,
                source=self.node_id,
                target=session.node_id,
                payload={
                    "firmware_id": session.firmware.firmware_id,
                    "reason": "hash_mismatch",
                },
            )
            await self._send(abort)
            logger.warning(
                "[OTA] {} hash mismatch — aborting (expected {}, got {})",
                session.node_id, expected_hash[:12], device_hash[:12],
            )
        self._notify_progress(session)

    def _on_device_abort(self, session: OTASession, reason: str) -> None:
        session.state = UpdateState.FAILED
        session.error = f"device aborted: {reason}"
        logger.warning("[OTA] {} aborted: {}", session.node_id, reason)
        self._notify_progress(session)

    # -- chunk sending -------------------------------------------------------

    async def _send_next_chunk(self, session: OTASession) -> None:
        """Read and send the next chunk to the device."""
        if session.state != UpdateState.TRANSFERRING:
            return
        seq = session.acked_up_to + 1
        if seq >= session.total_chunks:
            return

        offset = seq * session.chunk_size
        data = self.store.read_chunk(
            session.firmware.firmware_id, offset, session.chunk_size,
        )
        if not data:
            session.state = UpdateState.FAILED
            session.error = "failed to read firmware chunk"
            self._notify_progress(session)
            return

        data_b64 = base64.b64encode(data).decode("ascii")

        chunk = MeshEnvelope(
            type=MsgType.OTA_CHUNK,
            source=self.node_id,
            target=session.node_id,
            payload={
                "firmware_id": session.firmware.firmware_id,
                "seq": seq,
                "total_chunks": session.total_chunks,
                "data": data_b64,
            },
        )
        await self._send(chunk)
        session.next_seq = seq + 1
        logger.debug(
            "[OTA] sent chunk {}/{} to {}", seq + 1, session.total_chunks, session.node_id,
        )

"""Hub-side partition manifest for dual-partition OTA (task 5.2.1).

Tracks the firmware state of each managed device:
- **Core partition**: read-only, immutable (mesh client + bootloader + safety monitor).
- **App partition**: read-write, remotely updatable by the Hub.

Each device entry records:
- Core and app versions, hashes, and deployment timestamps
- Boot state (normal / crash-loop / rollback / bare)
- Crash counter (how many consecutive app crashes)
- Last-known-good app hash for rollback

This module is Hub-only — ESP32 side is in ``esp32/mesh_client/boot_manager.py``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


class BootState:
    """Recognised device boot states."""
    NORMAL = "normal"          # App running, no issues
    CRASH_LOOP = "crash_loop"  # App crashed N+ times, watchdog may trigger
    ROLLBACK = "rollback"      # Core reverted to last-known-good app
    BARE = "bare"              # No app installed — core only


@dataclass
class PartitionEntry:
    """Partition state for one device."""

    node_id: str

    # Core partition (read-only on device)
    core_version: str = "unknown"
    core_hash: str = ""

    # App partition (read-write, OTA-updatable)
    app_version: str = ""
    app_hash: str = ""
    app_deployed_at: float = 0.0        # Unix timestamp of last deployment

    # Safety state
    boot_state: str = BootState.BARE
    crash_count: int = 0
    max_crash_count: int = 3            # Threshold before rollback

    # Rollback target
    last_good_app_hash: str = ""
    last_good_app_version: str = ""

    # Metadata
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "core_version": self.core_version,
            "core_hash": self.core_hash,
            "app_version": self.app_version,
            "app_hash": self.app_hash,
            "app_deployed_at": self.app_deployed_at,
            "boot_state": self.boot_state,
            "crash_count": self.crash_count,
            "max_crash_count": self.max_crash_count,
            "last_good_app_hash": self.last_good_app_hash,
            "last_good_app_version": self.last_good_app_version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PartitionEntry:
        return cls(
            node_id=d.get("node_id", ""),
            core_version=d.get("core_version", "unknown"),
            core_hash=d.get("core_hash", ""),
            app_version=d.get("app_version", ""),
            app_hash=d.get("app_hash", ""),
            app_deployed_at=d.get("app_deployed_at", 0.0),
            boot_state=d.get("boot_state", BootState.BARE),
            crash_count=d.get("crash_count", 0),
            max_crash_count=d.get("max_crash_count", 3),
            last_good_app_hash=d.get("last_good_app_hash", ""),
            last_good_app_version=d.get("last_good_app_version", ""),
            updated_at=d.get("updated_at", 0.0),
        )


class PartitionManifest:
    """Hub-side database of per-device partition states.

    Persists to JSON alongside the firmware store.
    """

    def __init__(self, path: str | Path = ""):
        self._path = Path(path) if path else None
        self._entries: dict[str, PartitionEntry] = {}
        if self._path:
            self._load()

    # -- CRUD ----------------------------------------------------------------

    def get(self, node_id: str) -> PartitionEntry | None:
        return self._entries.get(node_id)

    def get_or_create(self, node_id: str) -> PartitionEntry:
        if node_id not in self._entries:
            self._entries[node_id] = PartitionEntry(node_id=node_id, updated_at=time.time())
        return self._entries[node_id]

    def remove(self, node_id: str) -> bool:
        if node_id in self._entries:
            del self._entries[node_id]
            self._save()
            return True
        return False

    def all_entries(self) -> list[PartitionEntry]:
        return list(self._entries.values())

    # -- State updates -------------------------------------------------------

    def record_deployment(
        self,
        node_id: str,
        app_version: str,
        app_hash: str,
    ) -> PartitionEntry:
        """Record a successful OTA deployment to a device's app partition."""
        entry = self.get_or_create(node_id)

        # If the current app was running fine, it becomes the rollback target
        if entry.boot_state == BootState.NORMAL and entry.app_hash:
            entry.last_good_app_hash = entry.app_hash
            entry.last_good_app_version = entry.app_version

        entry.app_version = app_version
        entry.app_hash = app_hash
        entry.app_deployed_at = time.time()
        entry.crash_count = 0
        entry.boot_state = BootState.NORMAL
        entry.updated_at = time.time()
        self._save()
        return entry

    def record_partition_report(
        self,
        node_id: str,
        report: dict[str, Any],
    ) -> PartitionEntry:
        """Update manifest from a PARTITION_REPORT message from the device."""
        entry = self.get_or_create(node_id)
        entry.core_version = report.get("core_version", entry.core_version)
        entry.core_hash = report.get("core_hash", entry.core_hash)
        entry.app_version = report.get("app_version", entry.app_version)
        entry.app_hash = report.get("app_hash", entry.app_hash)
        entry.boot_state = report.get("boot_state", entry.boot_state)
        entry.crash_count = report.get("crash_count", entry.crash_count)
        entry.updated_at = time.time()
        self._save()
        return entry

    def record_crash(self, node_id: str) -> PartitionEntry:
        """Increment crash counter. Returns updated entry."""
        entry = self.get_or_create(node_id)
        entry.crash_count += 1
        if entry.crash_count >= entry.max_crash_count:
            entry.boot_state = BootState.CRASH_LOOP
        entry.updated_at = time.time()
        self._save()
        return entry

    def record_rollback(self, node_id: str) -> PartitionEntry:
        """Record that the device rolled back to last-known-good."""
        entry = self.get_or_create(node_id)
        if entry.last_good_app_hash:
            entry.app_hash = entry.last_good_app_hash
            entry.app_version = entry.last_good_app_version
        entry.boot_state = BootState.ROLLBACK
        entry.crash_count = 0
        entry.updated_at = time.time()
        self._save()
        return entry

    # -- Query ---------------------------------------------------------------

    def devices_in_state(self, state: str) -> list[PartitionEntry]:
        return [e for e in self._entries.values() if e.boot_state == state]

    def devices_needing_attention(self) -> list[PartitionEntry]:
        """Return devices in crash_loop, rollback, or bare state."""
        return [
            e for e in self._entries.values()
            if e.boot_state in (BootState.CRASH_LOOP, BootState.ROLLBACK, BootState.BARE)
        ]

    def summary(self) -> str:
        """LLM-friendly text summary of partition states."""
        entries = self.all_entries()
        if not entries:
            return "No device partition data available."
        lines = ["## Device Partition Status"]
        for e in entries:
            app_info = f"v{e.app_version}" if e.app_version else "none"
            state_marker = ""
            if e.boot_state == BootState.CRASH_LOOP:
                state_marker = " ⚠️ CRASH LOOP"
            elif e.boot_state == BootState.ROLLBACK:
                state_marker = " ↩️ ROLLED BACK"
            elif e.boot_state == BootState.BARE:
                state_marker = " 📦 NO APP"
            lines.append(f"- {e.node_id}: core={e.core_version}, app={app_info}{state_marker}")
        attention = self.devices_needing_attention()
        if attention:
            lines.append(f"\n**{len(attention)} device(s) need attention.**")
        return "\n".join(lines)

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for d in data.get("entries", []):
                entry = PartitionEntry.from_dict(d)
                self._entries[entry.node_id] = entry
            logger.debug("Loaded {} partition entries from {}", len(self._entries), self._path)
        except Exception as e:
            logger.warning("Failed to load partition manifest: {}", e)

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"entries": [e.to_dict() for e in self._entries.values()]}
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save partition manifest: {}", e)

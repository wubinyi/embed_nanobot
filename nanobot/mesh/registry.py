"""Device capability registry and state management.

Tracks all enrolled/discovered devices, their capabilities (sensors, actuators,
properties), and their current state (online/offline, last reported values).

Architecture
------------
- ``DeviceCapability`` describes one thing a device can do/report.
- ``DeviceInfo`` holds identity, capabilities, and current state for one device.
- ``DeviceRegistry`` is the central singleton that manages all devices:
  - persists to a JSON file in the workspace (like ``mesh_keys.json``)
  - provides async-safe CRUD operations
  - exposes event hooks for state changes and online/offline transitions
  - integrates with ``UDPDiscovery`` for automatic peer tracking

Usage from MeshChannel
----------------------
>>> registry = DeviceRegistry(path="/workspace/device_registry.json")
>>> registry.load()
>>> registry.register_device("sensor-01", "temperature_sensor", capabilities=[...])
>>> registry.update_state("sensor-01", {"temperature": 23.5})
>>> info = registry.get_device("sensor-01")
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from loguru import logger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CapabilityType(str, Enum):
    """What kind of capability a device exposes."""
    SENSOR = "sensor"         # Read-only data source (temperature, humidity)
    ACTUATOR = "actuator"     # Controllable output (switch, motor, valve)
    PROPERTY = "property"     # Read-write attribute (brightness, thermostat setpoint)


class DataType(str, Enum):
    """Data types supported by capabilities."""
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    ENUM = "enum"             # One of a fixed set of string values


@dataclass
class DeviceCapability:
    """One thing a device can do or report.

    Examples
    --------
    - Temperature sensor: name="temperature", cap_type=SENSOR, data_type=FLOAT, unit="°C"
    - Light switch:       name="power", cap_type=ACTUATOR, data_type=BOOL
    - Brightness:         name="brightness", cap_type=PROPERTY, data_type=INT, value_range=(0, 100)
    - Mode selector:      name="mode", cap_type=PROPERTY, data_type=ENUM, enum_values=["auto","cool","heat"]
    """
    name: str
    cap_type: str             # CapabilityType value
    data_type: str            # DataType value
    unit: str = ""            # Physical unit (°C, %, lux, etc.)
    value_range: tuple[float, float] | None = None   # (min, max) for numeric types
    enum_values: list[str] = field(default_factory=list)  # Valid values for ENUM type
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "cap_type": self.cap_type,
            "data_type": self.data_type,
        }
        if self.unit:
            d["unit"] = self.unit
        if self.value_range is not None:
            d["value_range"] = list(self.value_range)
        if self.enum_values:
            d["enum_values"] = self.enum_values
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceCapability:
        vr = d.get("value_range")
        return cls(
            name=d["name"],
            cap_type=d.get("cap_type", CapabilityType.PROPERTY),
            data_type=d.get("data_type", DataType.STRING),
            unit=d.get("unit", ""),
            value_range=tuple(vr) if vr and len(vr) == 2 else None,
            enum_values=d.get("enum_values", []),
            description=d.get("description", ""),
        )


@dataclass
class DeviceInfo:
    """Full record for one registered device."""
    node_id: str
    device_type: str                       # e.g. "temperature_sensor", "smart_light", "relay"
    name: str = ""                         # Human-friendly name
    capabilities: list[DeviceCapability] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)  # capability_name → current value
    online: bool = False
    last_seen: float = 0.0                 # Unix timestamp
    registered_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)  # Firmware version, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "device_type": self.device_type,
            "name": self.name,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "state": self.state,
            "online": self.online,
            "last_seen": self.last_seen,
            "registered_at": self.registered_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceInfo:
        return cls(
            node_id=d["node_id"],
            device_type=d.get("device_type", "unknown"),
            name=d.get("name", ""),
            capabilities=[
                DeviceCapability.from_dict(c) for c in d.get("capabilities", [])
            ],
            state=d.get("state", {}),
            online=d.get("online", False),
            last_seen=d.get("last_seen", 0.0),
            registered_at=d.get("registered_at", 0.0),
            metadata=d.get("metadata", {}),
        )

    def get_capability(self, name: str) -> DeviceCapability | None:
        """Look up a capability by name."""
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None

    def capability_names(self) -> list[str]:
        """Return names of all capabilities."""
        return [c.name for c in self.capabilities]


# Callback type for device events
DeviceEventCallback = Callable[["DeviceInfo", str], Any]
# event types: "registered", "updated", "removed", "online", "offline", "state_changed"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class DeviceRegistry:
    """Central registry for all mesh devices.

    Persistence
    -----------
    Device data is stored in a JSON file (``path``). The registry loads on init
    and writes through on every mutation.

    Thread / async safety
    ---------------------
    All file writes are guarded by an ``asyncio.Lock`` so concurrent state
    updates from multiple devices don't corrupt the file.

    Integration
    -----------
    - Call ``register_device()`` when a new device enrolls or is discovered.
    - Call ``update_state()`` when a STATE_REPORT message arrives.
    - Call ``mark_online()`` / ``mark_offline()`` based on discovery heartbeats.
    - Call ``on_event()`` to subscribe to device lifecycle events.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._devices: dict[str, DeviceInfo] = {}  # node_id → DeviceInfo
        self._lock = asyncio.Lock()
        self._event_callbacks: list[DeviceEventCallback] = []

    # -- event system --------------------------------------------------------

    def on_event(self, callback: DeviceEventCallback) -> None:
        """Register a callback for device events.

        The callback receives ``(device_info, event_type)`` where event_type
        is one of: ``"registered"``, ``"updated"``, ``"removed"``,
        ``"online"``, ``"offline"``, ``"state_changed"``.
        """
        self._event_callbacks.append(callback)

    def _fire_event(self, device: DeviceInfo, event: str) -> None:
        """Notify all registered callbacks of a device event."""
        for cb in self._event_callbacks:
            try:
                cb(device, event)
            except Exception as exc:
                logger.error(f"[DeviceRegistry] event callback error: {exc}")

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Load device registry from disk. Missing file → empty registry."""
        if not self.path.exists():
            logger.debug(f"[DeviceRegistry] no file at {self.path}, starting fresh")
            return

        try:
            text = self.path.read_text(encoding="utf-8").strip()
            if not text:
                logger.debug(f"[DeviceRegistry] empty file at {self.path}, starting fresh")
                return
            data = json.loads(text)
            for d in data.get("devices", []):
                try:
                    info = DeviceInfo.from_dict(d)
                    # All devices start offline on load — discovery will update
                    info.online = False
                    self._devices[info.node_id] = info
                except (KeyError, TypeError) as exc:
                    logger.warning(f"[DeviceRegistry] skipping malformed device entry: {exc}")
            logger.info(
                f"[DeviceRegistry] loaded {len(self._devices)} devices from {self.path}"
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"[DeviceRegistry] failed to load {self.path}: {exc}")

    async def _save(self) -> None:
        """Persist registry to disk (async-safe)."""
        async with self._lock:
            self._save_sync()

    def _save_sync(self) -> None:
        """Synchronous save — call only if you already hold the lock or are
        in a non-async context (e.g., during initial setup)."""
        data = {
            "version": 1,
            "updated_at": time.time(),
            "devices": [d.to_dict() for d in self._devices.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(self.path))
        except OSError as exc:
            logger.error(f"[DeviceRegistry] failed to save: {exc}")

    # -- CRUD ----------------------------------------------------------------

    async def register_device(
        self,
        node_id: str,
        device_type: str,
        *,
        name: str = "",
        capabilities: list[DeviceCapability] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DeviceInfo:
        """Register a new device or update an existing one.

        If the device already exists, its type, capabilities, and metadata
        are updated (state and registration time are preserved).
        """
        existing = self._devices.get(node_id)
        if existing:
            existing.device_type = device_type
            if name:
                existing.name = name
            if capabilities is not None:
                existing.capabilities = capabilities
            if metadata is not None:
                existing.metadata.update(metadata)
            existing.last_seen = time.time()
            await self._save()
            self._fire_event(existing, "updated")
            logger.info(f"[DeviceRegistry] updated device {node_id} ({device_type})")
            return existing

        info = DeviceInfo(
            node_id=node_id,
            device_type=device_type,
            name=name or node_id,
            capabilities=capabilities or [],
            metadata=metadata or {},
            last_seen=time.time(),
        )
        self._devices[node_id] = info
        await self._save()
        self._fire_event(info, "registered")
        logger.info(
            f"[DeviceRegistry] registered new device {node_id} ({device_type}) "
            f"with {len(info.capabilities)} capabilities"
        )
        return info

    async def remove_device(self, node_id: str) -> bool:
        """Remove a device from the registry. Returns True if it existed."""
        info = self._devices.pop(node_id, None)
        if info is None:
            return False
        await self._save()
        self._fire_event(info, "removed")
        logger.info(f"[DeviceRegistry] removed device {node_id}")
        return True

    def get_device(self, node_id: str) -> DeviceInfo | None:
        """Look up a device by node_id."""
        return self._devices.get(node_id)

    def get_all_devices(self) -> list[DeviceInfo]:
        """Return all registered devices."""
        return list(self._devices.values())

    def get_online_devices(self) -> list[DeviceInfo]:
        """Return only devices currently marked as online."""
        return [d for d in self._devices.values() if d.online]

    def get_devices_by_type(self, device_type: str) -> list[DeviceInfo]:
        """Return all devices of a specific type."""
        return [d for d in self._devices.values() if d.device_type == device_type]

    def get_devices_with_capability(self, capability_name: str) -> list[DeviceInfo]:
        """Return devices that have a specific capability."""
        return [
            d for d in self._devices.values()
            if capability_name in d.capability_names()
        ]

    @property
    def device_count(self) -> int:
        return len(self._devices)

    @property
    def online_count(self) -> int:
        return sum(1 for d in self._devices.values() if d.online)

    # -- state management ----------------------------------------------------

    async def update_state(
        self,
        node_id: str,
        state_updates: dict[str, Any],
    ) -> bool:
        """Update the state of a device (partial update).

        Parameters
        ----------
        node_id:
            Device identifier.
        state_updates:
            Dict of ``{capability_name: new_value}``.

        Returns True if the device exists and state was updated.
        """
        info = self._devices.get(node_id)
        if info is None:
            logger.warning(f"[DeviceRegistry] state update for unknown device {node_id}")
            return False

        changed = False
        for key, value in state_updates.items():
            if info.state.get(key) != value:
                info.state[key] = value
                changed = True

        if changed:
            info.last_seen = time.time()
            await self._save()
            self._fire_event(info, "state_changed")
            logger.debug(
                f"[DeviceRegistry] state updated for {node_id}: "
                f"{state_updates}"
            )
        return True

    # -- online/offline tracking ---------------------------------------------

    def mark_online(self, node_id: str) -> None:
        """Mark a device as online (called when discovery sees a beacon)."""
        info = self._devices.get(node_id)
        if info is None:
            return
        was_offline = not info.online
        info.online = True
        info.last_seen = time.time()
        if was_offline:
            self._fire_event(info, "online")
            logger.info(f"[DeviceRegistry] device {node_id} is online")

    def mark_offline(self, node_id: str) -> None:
        """Mark a device as offline (called when discovery prunes a peer)."""
        info = self._devices.get(node_id)
        if info is None:
            return
        was_online = info.online
        info.online = False
        if was_online:
            self._fire_event(info, "offline")
            logger.info(f"[DeviceRegistry] device {node_id} is offline")

    def sync_with_discovery(self, online_node_ids: set[str]) -> None:
        """Bulk sync online/offline status from discovery peer list.

        Call this periodically to reconcile registry with discovery state.
        """
        for node_id, info in self._devices.items():
            if node_id in online_node_ids:
                self.mark_online(node_id)
            else:
                self.mark_offline(node_id)

    # -- query helpers for LLM context ---------------------------------------

    def summary(self) -> str:
        """Return a human-readable summary suitable for LLM context injection.

        Example output::

            Connected devices (2 online / 3 total):
            - sensor-01 (temperature_sensor) [ONLINE] — temperature: 23.5°C
            - light-01 (smart_light) [ONLINE] — power: on, brightness: 80%
            - relay-01 (smart_relay) [OFFLINE] — last seen 5 min ago
        """
        if not self._devices:
            return "No devices registered."

        lines = [
            f"Connected devices ({self.online_count} online / {self.device_count} total):"
        ]
        for d in self._devices.values():
            status = "ONLINE" if d.online else "OFFLINE"
            state_parts = []
            for cap in d.capabilities:
                val = d.state.get(cap.name)
                if val is not None:
                    unit = f"{cap.unit}" if cap.unit else ""
                    state_parts.append(f"{cap.name}: {val}{unit}")
            state_str = ", ".join(state_parts) if state_parts else "no state reported"
            if not d.online and d.last_seen > 0:
                ago = int(time.time() - d.last_seen)
                if ago < 60:
                    time_str = f"{ago}s ago"
                elif ago < 3600:
                    time_str = f"{ago // 60}min ago"
                else:
                    time_str = f"{ago // 3600}h ago"
                state_str += f" — last seen {time_str}"
            lines.append(f"  - {d.name} ({d.device_type}) [{status}] — {state_str}")
        return "\n".join(lines)

    def to_dict_for_llm(self) -> list[dict[str, Any]]:
        """Return a structured list suitable for injecting into LLM context.

        Each device is a dict with keys: node_id, name, device_type, online,
        capabilities (list of names), current_state.
        """
        result = []
        for d in self._devices.values():
            result.append({
                "node_id": d.node_id,
                "name": d.name,
                "device_type": d.device_type,
                "online": d.online,
                "capabilities": [
                    {
                        "name": c.name,
                        "type": c.cap_type,
                        "data_type": c.data_type,
                        "unit": c.unit,
                    }
                    for c in d.capabilities
                ],
                "current_state": d.state,
            })
        return result

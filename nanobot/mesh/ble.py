"""BLE bridge — passive BLE advertisement scanning for battery-powered sensors.

Scans for Bluetooth Low Energy advertisements, decodes sensor data using
configurable device profiles, and feeds readings into the standard device
registry and sensor pipeline.

Key classes
-----------
- ``BLEScanner``       — Abstract scanner interface.
- ``BleakScanner``     — Real scanner using the ``bleak`` library.
- ``StubScanner``      — Testing stub that returns configured dummy data.
- ``BLEDeviceProfile`` — Decoder rules for one device type.
- ``BLEBridge``        — Orchestrator: scan loop, profile matching, registry
  integration, state update dispatch.

Optional dependency
-------------------
``bleak`` — install with ``pip install bleak``.  When unavailable the bridge
falls back to ``StubScanner`` (no-op, for unit testing).

Configuration
-------------
See ``MeshConfig.ble_config_path``.
"""

from __future__ import annotations

import abc
import asyncio
import json
import re
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceRegistry,
)

# ---------------------------------------------------------------------------
# Optional dependency: bleak
# ---------------------------------------------------------------------------

try:
    import bleak
    HAS_BLEAK = True
except ImportError:
    HAS_BLEAK = False


# ---------------------------------------------------------------------------
# Data model — advertisement result
# ---------------------------------------------------------------------------

@dataclass
class BLEAdvertisement:
    """Parsed BLE advertisement data from a single scan result."""

    address: str                         # MAC address or UUID
    name: str                            # Local device name (may be empty)
    rssi: int                            # Signal strength in dBm
    manufacturer_data: dict[int, bytes]  # company_id → payload
    service_data: dict[str, bytes]       # service_uuid → payload

    @property
    def node_id(self) -> str:
        """Derive a mesh-compatible node ID from the BLE address."""
        return f"ble-{self.address.replace(':', '').lower()}"


# ---------------------------------------------------------------------------
# Data model — capability decode definition
# ---------------------------------------------------------------------------

# Struct format codes for each data type
_STRUCT_FORMATS: dict[str, str] = {
    "uint8": "B",
    "int8": "b",
    "uint16": "<H",
    "int16": "<h",
    "uint32": "<I",
    "int32": "<i",
    "float32": "<f",
}


@dataclass
class BLECapabilityDef:
    """Declaration of how to extract one capability from advertisement data."""

    name: str               # Capability name (e.g. "temperature")
    data_source: str        # "manufacturer" or "service"
    company_id: int = 0     # BLE company ID (for manufacturer data)
    service_uuid: str = ""  # GATT service UUID (for service data)
    byte_offset: int = 0
    byte_length: int = 2
    data_type: str = "int16"
    scale: float = 1.0      # raw_value * scale = final value
    unit: str = ""
    cap_type: str = "sensor"

    @classmethod
    def from_dict(cls, d: dict) -> "BLECapabilityDef":
        return cls(
            name=d["name"],
            data_source=d.get("data_source", "manufacturer"),
            company_id=d.get("company_id", 0),
            service_uuid=d.get("service_uuid", ""),
            byte_offset=d.get("byte_offset", 0),
            byte_length=d.get("byte_length", 2),
            data_type=d.get("data_type", "int16"),
            scale=d.get("scale", 1.0),
            unit=d.get("unit", ""),
            cap_type=d.get("cap_type", "sensor"),
        )


def decode_value(raw: bytes, cap: BLECapabilityDef) -> float | None:
    """Decode a raw byte slice into a scaled numeric value.

    Returns ``None`` if the data is too short or the format is unknown.
    """
    start = cap.byte_offset
    end = start + cap.byte_length
    if len(raw) < end:
        return None
    chunk = raw[start:end]
    fmt = _STRUCT_FORMATS.get(cap.data_type)
    if fmt is None:
        return None
    try:
        (value,) = struct.unpack(fmt, chunk)
        return round(value * cap.scale, 4)
    except struct.error:
        return None


# ---------------------------------------------------------------------------
# Data model — device profile
# ---------------------------------------------------------------------------

@dataclass
class BLEDeviceProfile:
    """Decoder profile for one class of BLE device."""

    name: str                               # Human-readable profile name
    name_pattern: str                       # Regex to match BLE device name
    device_type: str                        # Device type for registry
    capabilities: list[BLECapabilityDef] = field(default_factory=list)
    _compiled_re: re.Pattern | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            self._compiled_re = re.compile(self.name_pattern, re.IGNORECASE)
        except re.error:
            self._compiled_re = None

    def matches(self, device_name: str) -> bool:
        """Check if *device_name* matches this profile's pattern."""
        if self._compiled_re is None:
            return False
        return bool(self._compiled_re.search(device_name))

    @classmethod
    def from_dict(cls, d: dict) -> "BLEDeviceProfile":
        caps = [BLECapabilityDef.from_dict(c) for c in d.get("capabilities", [])]
        return cls(
            name=d.get("name", ""),
            name_pattern=d.get("name_pattern", ""),
            device_type=d.get("device_type", "ble_device"),
            capabilities=caps,
        )


# ---------------------------------------------------------------------------
# Data model — BLE config
# ---------------------------------------------------------------------------

@dataclass
class BLEConfig:
    """Top-level BLE bridge configuration."""

    scan_interval: int = 30      # seconds between scans
    scan_duration: int = 10      # seconds per scan window
    device_timeout: int = 120    # seconds before device marked offline
    profiles: list[BLEDeviceProfile] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "BLEConfig":
        profiles = [BLEDeviceProfile.from_dict(p) for p in d.get("profiles", [])]
        return cls(
            scan_interval=d.get("scan_interval", 30),
            scan_duration=d.get("scan_duration", 10),
            device_timeout=d.get("device_timeout", 120),
            profiles=profiles,
        )


# ---------------------------------------------------------------------------
# BLE scanner — abstract base
# ---------------------------------------------------------------------------

class BLEScanner(abc.ABC):
    """Abstract BLE advertisement scanner."""

    @abc.abstractmethod
    async def scan(self, duration: float) -> list[BLEAdvertisement]:
        """Scan for BLE advertisements for *duration* seconds.

        Returns a list of advertisements discovered during the scan.
        """

    async def stop(self) -> None:
        """Stop any in-progress scan (best-effort)."""


# ---------------------------------------------------------------------------
# Bleak-based scanner (real hardware)
# ---------------------------------------------------------------------------

class BleakBLEScanner(BLEScanner):
    """BLE scanner using the ``bleak`` library.

    Requires ``bleak`` to be installed.  On Linux, also requires BlueZ.
    """

    async def scan(self, duration: float) -> list[BLEAdvertisement]:
        if not HAS_BLEAK:
            logger.warning("[BLE] bleak not installed, returning empty scan")
            return []
        try:
            devices = await bleak.BleakScanner.discover(timeout=duration)
            results: list[BLEAdvertisement] = []
            for d in devices:
                adv = BLEAdvertisement(
                    address=d.address,
                    name=d.name or "",
                    rssi=d.rssi if hasattr(d, "rssi") else -100,
                    manufacturer_data=dict(d.metadata.get("manufacturer_data", {})) if hasattr(d, "metadata") else {},
                    service_data=dict(d.metadata.get("service_data", {})) if hasattr(d, "metadata") else {},
                )
                results.append(adv)
            return results
        except Exception as exc:
            logger.error("[BLE] bleak scan failed: {}", exc)
            return []


# ---------------------------------------------------------------------------
# Stub scanner (testing)
# ---------------------------------------------------------------------------

class StubScanner(BLEScanner):
    """BLE scanner stub for testing. Returns pre-configured advertisements."""

    def __init__(self) -> None:
        self.advertisements: list[BLEAdvertisement] = []

    async def scan(self, duration: float) -> list[BLEAdvertisement]:
        return list(self.advertisements)

    def add_advertisement(self, adv: BLEAdvertisement) -> None:
        """Add a fake advertisement to be returned by the next scan."""
        self.advertisements.append(adv)

    def clear(self) -> None:
        """Remove all fake advertisements."""
        self.advertisements.clear()


# ---------------------------------------------------------------------------
# BLE Bridge — orchestrator
# ---------------------------------------------------------------------------

class BLEBridge:
    """Orchestrates BLE scanning, profile matching, and registry integration.

    Parameters
    ----------
    config_path:
        Path to the BLE configuration JSON file.
    registry:
        The device registry for auto-registering BLE devices.
    on_state_update:
        Callback ``(node_id: str, state: dict) -> None`` invoked after
        each successful scan with decoded sensor readings.
    scanner:
        Optional scanner override (default: auto-select BleakBLEScanner or
        StubScanner based on bleak availability).
    """

    def __init__(
        self,
        config_path: str,
        registry: DeviceRegistry,
        on_state_update: Callable[[str, dict[str, Any]], None] | None = None,
        scanner: BLEScanner | None = None,
    ) -> None:
        self.config_path = config_path
        self.registry = registry
        self.on_state_update = on_state_update
        self.scanner = scanner or (BleakBLEScanner() if HAS_BLEAK else StubScanner())
        self.config: BLEConfig | None = None
        self._scan_task: asyncio.Task | None = None
        self._running = False
        # node_id → last_seen timestamp
        self._device_last_seen: dict[str, float] = {}
        # node_id → set of known node_ids managed by this bridge
        self._managed_devices: set[str] = set()

    # -- config loading ------------------------------------------------------

    def load(self) -> int:
        """Load and parse the BLE configuration.

        Returns the number of profiles loaded.
        """
        p = Path(self.config_path)
        if not p.exists():
            logger.warning("[BLE] config not found: {}", self.config_path)
            self.config = BLEConfig()
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.config = BLEConfig.from_dict(data)
            logger.info(
                "[BLE] loaded {} profiles from {}",
                len(self.config.profiles), self.config_path,
            )
            return len(self.config.profiles)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("[BLE] failed to parse config: {}", exc)
            self.config = BLEConfig()
            return 0

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the periodic BLE scan loop."""
        if self.config is None:
            self.load()
        self._running = True
        self._scan_task = asyncio.ensure_future(self._scan_loop())
        logger.info(
            "[BLE] started (interval={}s duration={}s profiles={})",
            self.config.scan_interval if self.config else 30,
            self.config.scan_duration if self.config else 10,
            len(self.config.profiles) if self.config else 0,
        )

    async def stop(self) -> None:
        """Stop the scan loop."""
        self._running = False
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except (asyncio.CancelledError, Exception):
                pass
        await self.scanner.stop()
        logger.info("[BLE] stopped")

    async def _scan_loop(self) -> None:
        """Periodically scan for BLE advertisements."""
        cfg = self.config or BLEConfig()
        try:
            while self._running:
                try:
                    results = await self.scanner.scan(float(cfg.scan_duration))
                    await self._process_advertisements(results)
                except Exception as exc:
                    logger.error("[BLE] scan error: {}", exc)

                # Prune stale devices
                self._prune_stale_devices(cfg.device_timeout)

                await asyncio.sleep(float(cfg.scan_interval))
        except asyncio.CancelledError:
            pass

    # -- scan processing -----------------------------------------------------

    async def _process_advertisements(
        self,
        advertisements: list[BLEAdvertisement],
    ) -> None:
        """Process a batch of BLE advertisements."""
        cfg = self.config or BLEConfig()
        for adv in advertisements:
            profile = self._match_profile(adv.name, cfg.profiles)
            if profile is None:
                continue

            # Decode capabilities from advertisement data
            state = self._decode_advertisement(adv, profile)
            if not state:
                continue

            node_id = adv.node_id
            now = time.time()
            self._device_last_seen[node_id] = now

            # Auto-register if new
            if node_id not in self._managed_devices:
                caps = [
                    DeviceCapability(
                        name=c.name,
                        cap_type=c.cap_type or CapabilityType.SENSOR,
                        data_type=self._map_data_type(c.data_type),
                        unit=c.unit,
                    )
                    for c in profile.capabilities
                ]
                try:
                    await self.registry.register_device(
                        node_id,
                        profile.device_type,
                        capabilities=caps,
                        metadata={
                            "ble_address": adv.address,
                            "ble_name": adv.name,
                            "ble_profile": profile.name,
                            "rssi": adv.rssi,
                        },
                    )
                except Exception as exc:
                    logger.error("[BLE] failed to register {}: {}", node_id, exc)
                    continue
                self._managed_devices.add(node_id)
                logger.info(
                    "[BLE] registered {} ({}) via profile '{}'",
                    node_id, adv.name, profile.name,
                )

            # Mark online and update state
            self.registry.mark_online(node_id)

            # Add RSSI as a state value
            state["rssi"] = adv.rssi

            try:
                await self.registry.update_state(node_id, state)
            except Exception as exc:
                logger.error("[BLE] state update failed for {}: {}", node_id, exc)
                continue

            # Notify callback
            if self.on_state_update:
                try:
                    self.on_state_update(node_id, state)
                except Exception as exc:
                    logger.error("[BLE] state callback error: {}", exc)

    def _match_profile(
        self,
        device_name: str,
        profiles: list[BLEDeviceProfile],
    ) -> BLEDeviceProfile | None:
        """Find the first profile whose name_pattern matches *device_name*."""
        if not device_name:
            return None
        for profile in profiles:
            if profile.matches(device_name):
                return profile
        return None

    def _decode_advertisement(
        self,
        adv: BLEAdvertisement,
        profile: BLEDeviceProfile,
    ) -> dict[str, Any]:
        """Decode all capabilities from an advertisement using a profile."""
        state: dict[str, Any] = {}
        for cap_def in profile.capabilities:
            raw = self._get_raw_data(adv, cap_def)
            if raw is None:
                continue
            value = decode_value(raw, cap_def)
            if value is not None:
                state[cap_def.name] = value
        return state

    def _get_raw_data(
        self,
        adv: BLEAdvertisement,
        cap_def: BLECapabilityDef,
    ) -> bytes | None:
        """Extract the raw byte payload for a capability definition."""
        if cap_def.data_source == "manufacturer":
            return adv.manufacturer_data.get(cap_def.company_id)
        elif cap_def.data_source == "service":
            return adv.service_data.get(cap_def.service_uuid)
        return None

    @staticmethod
    def _map_data_type(dt_str: str) -> str:
        """Map BLE data type string to DataType enum values."""
        if dt_str in ("float32",):
            return DataType.FLOAT
        if dt_str in ("uint8", "int8", "uint16", "int16", "uint32", "int32"):
            return DataType.INT
        return DataType.FLOAT  # default

    def _prune_stale_devices(self, timeout: int) -> None:
        """Mark devices as offline if not seen within *timeout* seconds."""
        now = time.time()
        stale: list[str] = []
        for node_id, last_seen in self._device_last_seen.items():
            if now - last_seen > timeout:
                stale.append(node_id)
        for node_id in stale:
            self.registry.mark_offline(node_id)
            del self._device_last_seen[node_id]
            logger.debug("[BLE] device {} went offline (timeout)", node_id)

    # -- queries -------------------------------------------------------------

    def is_ble_device(self, node_id: str) -> bool:
        """Check if *node_id* is a BLE device managed by this bridge."""
        return node_id in self._managed_devices

    def list_devices(self) -> list[str]:
        """Return all BLE device node IDs."""
        return list(self._managed_devices)

    def get_device_rssi(self, node_id: str) -> int | None:
        """Return the last known RSSI for a BLE device."""
        dev = self.registry.get_device(node_id)
        if dev is None:
            return None
        return dev.state.get("rssi")

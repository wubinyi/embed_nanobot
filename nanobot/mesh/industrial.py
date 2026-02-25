"""Industrial protocol adapter framework for PLC/SCADA integration.

Bridges industrial devices (Modbus TCP, OPC-UA, etc.) into the nanobot
mesh ecosystem.  PLC data points are mapped to standard DeviceCapability
entries in the device registry so that the LLM, automation engine, and
dashboard treat them identically to ESP32-style mesh devices.

Key classes
-----------
- ``IndustrialProtocol``  — Abstract base class for protocol adapters.
- ``ModbusTCPAdapter``    — Concrete adapter for Modbus TCP (requires
  ``pymodbus``; optional dependency, graceful degradation).
- ``PLCPointConfig``      — Declares one PLC register → capability mapping.
- ``PLCDeviceConfig``     — Groups points into a logical device.
- ``BridgeConfig``        — One PLC connection with its device mappings.
- ``IndustrialBridge``    — Orchestrator: manages adapters, polling loops,
  registry integration, and command dispatch.
"""

from __future__ import annotations

import abc
import asyncio
import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceRegistry,
)

# ---------------------------------------------------------------------------
# Optional dependency: pymodbus
# ---------------------------------------------------------------------------

try:
    from pymodbus.client import AsyncModbusTcpClient  # pymodbus >= 3.x
    HAS_PYMODBUS = True
except ImportError:
    HAS_PYMODBUS = False


# ---------------------------------------------------------------------------
# Data type helpers
# ---------------------------------------------------------------------------

# Modbus register data types and their byte widths (in 16-bit registers)
_REGISTER_COUNT: dict[str, int] = {
    "bool": 1,
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
    "float64": 4,
}

_STRUCT_FMT: dict[str, str] = {
    "uint16": ">H",
    "int16": ">h",
    "uint32": ">I",
    "int32": ">i",
    "float32": ">f",
    "float64": ">d",
}


def _to_device_data_type(plc_type: str) -> str:
    """Map PLC data type string to registry DataType value."""
    if plc_type == "bool":
        return DataType.BOOL
    if plc_type in ("uint16", "int16", "uint32", "int32"):
        return DataType.INT
    if plc_type in ("float32", "float64"):
        return DataType.FLOAT
    return DataType.STRING  # fallback


def _to_cap_type(raw: str) -> str:
    """Map config string to CapabilityType value."""
    mapping = {"sensor": CapabilityType.SENSOR, "actuator": CapabilityType.ACTUATOR,
               "property": CapabilityType.PROPERTY}
    return mapping.get(raw, CapabilityType.PROPERTY)


def decode_registers(registers: list[int], plc_type: str) -> Any:
    """Decode a list of 16-bit register values to a Python value.

    Parameters
    ----------
    registers:
        Raw 16-bit register values from Modbus read.
    plc_type:
        One of the keys in ``_REGISTER_COUNT``.

    Returns the decoded Python value (int, float, or bool).
    """
    if plc_type == "bool":
        return bool(registers[0])

    fmt = _STRUCT_FMT.get(plc_type)
    if fmt is None:
        return registers[0]

    # Pack 16-bit registers into bytes, then unpack
    raw_bytes = b""
    for r in registers:
        raw_bytes += struct.pack(">H", r & 0xFFFF)
    return struct.unpack(fmt, raw_bytes)[0]


def encode_value(value: Any, plc_type: str) -> list[int]:
    """Encode a Python value to a list of 16-bit register values.

    Inverse of ``decode_registers``.
    """
    if plc_type == "bool":
        return [1 if value else 0]

    fmt = _STRUCT_FMT.get(plc_type)
    if fmt is None:
        return [int(value) & 0xFFFF]

    raw_bytes = struct.pack(fmt, value)
    regs = []
    for i in range(0, len(raw_bytes), 2):
        regs.append(struct.unpack(">H", raw_bytes[i:i + 2])[0])
    return regs


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PLCPointConfig:
    """Maps one PLC register to a device capability."""
    capability: str               # e.g. "temperature", "fan_speed"
    cap_type: str = "sensor"      # "sensor" | "actuator" | "property"
    register_type: str = "holding"  # "holding" | "input" | "coil" | "discrete"
    address: int = 0              # Register address
    data_type: str = "uint16"     # "bool" | "uint16" | "int16" | "uint32" | "int32" | "float32" | "float64"
    unit: str = ""
    scale: float = 1.0            # Multiply raw value by this (e.g. 0.1 for 1 decimal)
    value_range: tuple[float, float] | None = None

    def to_device_capability(self) -> DeviceCapability:
        """Convert to a standard DeviceCapability for the registry."""
        return DeviceCapability(
            name=self.capability,
            cap_type=_to_cap_type(self.cap_type),
            data_type=_to_device_data_type(self.data_type),
            unit=self.unit,
            value_range=self.value_range,
        )

    @staticmethod
    def from_dict(d: dict) -> PLCPointConfig:
        vr = d.get("range") or d.get("value_range")
        if isinstance(vr, (list, tuple)) and len(vr) == 2:
            vr = (float(vr[0]), float(vr[1]))
        else:
            vr = None
        return PLCPointConfig(
            capability=d["capability"],
            cap_type=d.get("cap_type", "sensor"),
            register_type=d.get("register_type", "holding"),
            address=d.get("address", 0),
            data_type=d.get("data_type", "uint16"),
            unit=d.get("unit", ""),
            scale=d.get("scale", 1.0),
            value_range=vr,
        )


@dataclass
class PLCDeviceConfig:
    """A logical device mapped from PLC register points."""
    node_id: str
    device_type: str = "plc_device"
    name: str = ""
    points: list[PLCPointConfig] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> PLCDeviceConfig:
        return PLCDeviceConfig(
            node_id=d["node_id"],
            device_type=d.get("device_type", "plc_device"),
            name=d.get("name", ""),
            points=[PLCPointConfig.from_dict(p) for p in d.get("points", [])],
        )

    def to_capabilities(self) -> list[DeviceCapability]:
        return [p.to_device_capability() for p in self.points]


@dataclass
class BridgeConfig:
    """Configuration for one PLC connection."""
    bridge_id: str
    protocol: str = "modbus_tcp"  # Protocol identifier
    host: str = "127.0.0.1"
    port: int = 502
    unit_id: int = 1              # Modbus unit/slave ID
    poll_interval: float = 5.0    # Seconds between polling cycles
    devices: list[PLCDeviceConfig] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> BridgeConfig:
        return BridgeConfig(
            bridge_id=d["bridge_id"],
            protocol=d.get("protocol", "modbus_tcp"),
            host=d.get("host", "127.0.0.1"),
            port=d.get("port", 502),
            unit_id=d.get("unit_id", 1),
            poll_interval=d.get("poll_interval", 5.0),
            devices=[PLCDeviceConfig.from_dict(dev) for dev in d.get("devices", [])],
        )


# ---------------------------------------------------------------------------
# Abstract protocol adapter
# ---------------------------------------------------------------------------

class IndustrialProtocol(abc.ABC):
    """Abstract base for industrial protocol adapters."""

    @abc.abstractmethod
    async def connect(self) -> bool:
        """Establish connection. Return True on success."""
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close connection gracefully."""
        ...

    @abc.abstractmethod
    async def read_point(self, point: PLCPointConfig, unit_id: int = 1) -> Any | None:
        """Read a single point. Return decoded value or None on failure."""
        ...

    @abc.abstractmethod
    async def write_point(self, point: PLCPointConfig, value: Any, unit_id: int = 1) -> bool:
        """Write a value to a point. Return True on success."""
        ...

    @property
    @abc.abstractmethod
    def connected(self) -> bool:
        """Return True if the adapter has an active connection."""
        ...


# ---------------------------------------------------------------------------
# Modbus TCP adapter
# ---------------------------------------------------------------------------

class ModbusTCPAdapter(IndustrialProtocol):
    """Modbus TCP protocol adapter.

    Requires ``pymodbus >= 3.0`` (optional dependency).
    Uses ``asyncio.to_thread()`` for sync operations when necessary.
    """

    def __init__(self, host: str, port: int = 502) -> None:
        self.host = host
        self.port = port
        self._client: Any = None  # AsyncModbusTcpClient or None

    async def connect(self) -> bool:
        if not HAS_PYMODBUS:
            logger.error("[ModbusTCP] pymodbus not installed — pip install pymodbus")
            return False
        try:
            self._client = AsyncModbusTcpClient(self.host, port=self.port)
            ok = await self._client.connect()
            if ok:
                logger.info("[ModbusTCP] connected to {}:{}", self.host, self.port)
            else:
                logger.warning("[ModbusTCP] connection failed to {}:{}", self.host, self.port)
            return bool(ok)
        except Exception as exc:
            logger.error("[ModbusTCP] connect error: {}", exc)
            self._client = None
            return False

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            logger.info("[ModbusTCP] disconnected from {}:{}", self.host, self.port)

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    async def read_point(self, point: PLCPointConfig, unit_id: int = 1) -> Any | None:
        if not self.connected:
            return None

        count = _REGISTER_COUNT.get(point.data_type, 1)
        try:
            if point.register_type == "coil":
                result = await self._client.read_coils(point.address, count=1, slave=unit_id)
                if result.isError():
                    return None
                return bool(result.bits[0])
            elif point.register_type == "discrete":
                result = await self._client.read_discrete_inputs(point.address, count=1, slave=unit_id)
                if result.isError():
                    return None
                return bool(result.bits[0])
            elif point.register_type == "input":
                result = await self._client.read_input_registers(point.address, count=count, slave=unit_id)
                if result.isError():
                    return None
                return decode_registers(result.registers, point.data_type) * point.scale
            else:  # "holding" (default)
                result = await self._client.read_holding_registers(point.address, count=count, slave=unit_id)
                if result.isError():
                    return None
                value = decode_registers(result.registers, point.data_type)
                return value * point.scale if isinstance(value, (int, float)) and not isinstance(value, bool) else value
        except Exception as exc:
            logger.debug("[ModbusTCP] read error at {}:{} - {}", point.register_type, point.address, exc)
            return None

    async def write_point(self, point: PLCPointConfig, value: Any, unit_id: int = 1) -> bool:
        if not self.connected:
            return False

        try:
            # Undo scale for writing
            if point.scale and point.scale != 1.0 and isinstance(value, (int, float)):
                value = value / point.scale

            if point.register_type == "coil":
                result = await self._client.write_coil(point.address, bool(value), slave=unit_id)
                return not result.isError()
            elif point.register_type in ("holding",):
                regs = encode_value(value, point.data_type)
                if len(regs) == 1:
                    result = await self._client.write_register(point.address, regs[0], slave=unit_id)
                else:
                    result = await self._client.write_registers(point.address, regs, slave=unit_id)
                return not result.isError()
            else:
                logger.warning("[ModbusTCP] cannot write to {} registers", point.register_type)
                return False
        except Exception as exc:
            logger.debug("[ModbusTCP] write error at {}:{} - {}", point.register_type, point.address, exc)
            return False


# ---------------------------------------------------------------------------
# Stub adapter (when no protocol library is available)
# ---------------------------------------------------------------------------

class StubAdapter(IndustrialProtocol):
    """No-op adapter used when the real protocol library is unavailable.

    Always reports disconnected.  Useful for testing config parsing
    without needing pymodbus installed.
    """

    async def connect(self) -> bool:
        logger.warning("[StubAdapter] no protocol library available")
        return False

    async def disconnect(self) -> None:
        pass

    async def read_point(self, point: PLCPointConfig, unit_id: int = 1) -> Any | None:
        return None

    async def write_point(self, point: PLCPointConfig, value: Any, unit_id: int = 1) -> bool:
        return False

    @property
    def connected(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Protocol registry — maps protocol name → adapter class
# ---------------------------------------------------------------------------

_PROTOCOL_REGISTRY: dict[str, type[IndustrialProtocol]] = {}


def register_protocol(name: str, cls: type[IndustrialProtocol]) -> None:
    """Register a protocol adapter class."""
    _PROTOCOL_REGISTRY[name] = cls


def get_protocol_adapter(name: str) -> type[IndustrialProtocol] | None:
    """Look up a protocol adapter class by name."""
    return _PROTOCOL_REGISTRY.get(name)


# Register built-in protocols
if HAS_PYMODBUS:
    register_protocol("modbus_tcp", ModbusTCPAdapter)


# ---------------------------------------------------------------------------
# Industrial Bridge — orchestrator
# ---------------------------------------------------------------------------

class IndustrialBridge:
    """Manages industrial protocol connections, polling, and command dispatch.

    One bridge instance manages *all* PLC connections defined in the config.
    Each ``BridgeConfig`` gets its own protocol adapter and polling task.

    Parameters
    ----------
    config_path:
        Path to the industrial config JSON file.
    registry:
        The shared DeviceRegistry for registering PLC devices.
    on_state_update:
        Optional callback ``(node_id, state_dict)`` called after each poll.
    """

    def __init__(
        self,
        config_path: str,
        registry: DeviceRegistry,
        on_state_update: Any | None = None,
    ) -> None:
        self.config_path = config_path
        self.registry = registry
        self._on_state_update = on_state_update

        self._bridges: list[BridgeConfig] = []
        self._adapters: dict[str, IndustrialProtocol] = {}  # bridge_id → adapter
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._running = False

        # Build lookup: node_id → (bridge_id, PLCDeviceConfig)
        self._device_map: dict[str, tuple[str, PLCDeviceConfig]] = {}
        # Build lookup: (node_id, capability) → PLCPointConfig
        self._point_map: dict[tuple[str, str], tuple[str, PLCPointConfig]] = {}

    def load(self) -> int:
        """Load bridge configurations from JSON. Returns number of bridges loaded."""
        path = Path(self.config_path)
        if not path.exists():
            logger.debug("[Industrial] no config at {}, starting with no bridges", self.config_path)
            return 0

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("[Industrial] failed to load config: {}", exc)
            return 0

        bridges_data = data.get("bridges", [])
        self._bridges = [BridgeConfig.from_dict(b) for b in bridges_data]
        self._build_lookups()
        logger.info("[Industrial] loaded {} bridge(s) from {}", len(self._bridges), self.config_path)
        return len(self._bridges)

    def _build_lookups(self) -> None:
        self._device_map.clear()
        self._point_map.clear()
        for bc in self._bridges:
            for dev in bc.devices:
                self._device_map[dev.node_id] = (bc.bridge_id, dev)
                for pt in dev.points:
                    self._point_map[(dev.node_id, pt.capability)] = (bc.bridge_id, pt)

    async def start(self) -> None:
        """Connect all adapters, register devices, start polling."""
        self._running = True

        for bc in self._bridges:
            adapter = self._create_adapter(bc)
            self._adapters[bc.bridge_id] = adapter

            ok = await adapter.connect()
            if ok:
                # Register devices in the shared registry
                await self._register_devices(bc)
                # Start polling loop
                task = asyncio.create_task(
                    self._poll_loop(bc),
                    name=f"industrial-poll-{bc.bridge_id}",
                )
                self._poll_tasks[bc.bridge_id] = task
            else:
                logger.warning("[Industrial] could not connect bridge {}", bc.bridge_id)

    async def stop(self) -> None:
        """Stop all polling and disconnect adapters."""
        self._running = False

        for task in self._poll_tasks.values():
            task.cancel()

        for task in self._poll_tasks.values():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._poll_tasks.clear()

        for bid, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
            except Exception as exc:
                logger.debug("[Industrial] disconnect error for {}: {}", bid, exc)
        self._adapters.clear()

    def _create_adapter(self, bc: BridgeConfig) -> IndustrialProtocol:
        """Create the appropriate protocol adapter for a bridge config."""
        cls = get_protocol_adapter(bc.protocol)
        if cls is None:
            logger.warning(
                "[Industrial] protocol '{}' not available, using stub", bc.protocol
            )
            return StubAdapter()

        if bc.protocol == "modbus_tcp":
            return cls(host=bc.host, port=bc.port)  # type: ignore[call-arg]

        # Generic: try host/port constructor
        try:
            return cls(host=bc.host, port=bc.port)  # type: ignore[call-arg]
        except TypeError:
            return cls()  # type: ignore[call-arg]

    async def _register_devices(self, bc: BridgeConfig) -> None:
        """Register PLC devices in the shared registry."""
        for dev in bc.devices:
            caps = dev.to_capabilities()
            await self.registry.register_device(
                node_id=dev.node_id,
                device_type=dev.device_type,
                name=dev.name,
                capabilities=caps,
                metadata={"bridge_id": bc.bridge_id, "protocol": bc.protocol,
                          "plc_host": bc.host, "plc_port": bc.port},
            )
            self.registry.mark_online(dev.node_id)
            logger.info("[Industrial] registered PLC device: {} ({})", dev.node_id, dev.name)

    async def _poll_loop(self, bc: BridgeConfig) -> None:
        """Continuously poll all points for a bridge."""
        adapter = self._adapters.get(bc.bridge_id)
        if adapter is None:
            return

        while self._running:
            try:
                await asyncio.sleep(bc.poll_interval)
            except asyncio.CancelledError:
                return

            if not adapter.connected:
                logger.debug("[Industrial] {} disconnected, attempting reconnect", bc.bridge_id)
                ok = await adapter.connect()
                if not ok:
                    continue

            for dev in bc.devices:
                state: dict[str, Any] = {}
                for pt in dev.points:
                    value = await adapter.read_point(pt, unit_id=bc.unit_id)
                    if value is not None:
                        state[pt.capability] = value

                if state:
                    await self.registry.update_state(dev.node_id, state)
                    self.registry.mark_online(dev.node_id)
                    if self._on_state_update:
                        try:
                            self._on_state_update(dev.node_id, state)
                        except Exception:
                            pass

    async def execute_command(
        self, node_id: str, capability: str, value: Any,
    ) -> bool:
        """Write a value to a PLC point via the appropriate adapter.

        Returns True on success.
        """
        key = (node_id, capability)
        if key not in self._point_map:
            logger.warning("[Industrial] unknown point: {}.{}", node_id, capability)
            return False

        bridge_id, point = self._point_map[key]
        adapter = self._adapters.get(bridge_id)
        if adapter is None or not adapter.connected:
            logger.warning("[Industrial] adapter not connected for bridge {}", bridge_id)
            return False

        bridge_cfg = next((b for b in self._bridges if b.bridge_id == bridge_id), None)
        unit_id = bridge_cfg.unit_id if bridge_cfg else 1

        ok = await adapter.write_point(point, value, unit_id=unit_id)
        if ok:
            logger.info("[Industrial] wrote {}.{} = {}", node_id, capability, value)
            # Update registry state
            await self.registry.update_state(node_id, {capability: value})
        return ok

    def is_industrial_device(self, node_id: str) -> bool:
        """Check if a node_id belongs to an industrial/PLC device."""
        return node_id in self._device_map

    def list_bridges(self) -> list[dict[str, Any]]:
        """Return bridge status for dashboard/monitoring."""
        result = []
        for bc in self._bridges:
            adapter = self._adapters.get(bc.bridge_id)
            result.append({
                "bridge_id": bc.bridge_id,
                "protocol": bc.protocol,
                "host": bc.host,
                "port": bc.port,
                "connected": adapter.connected if adapter else False,
                "device_count": len(bc.devices),
                "poll_interval": bc.poll_interval,
            })
        return result

    @property
    def bridge_count(self) -> int:
        return len(self._bridges)

    @property
    def device_count(self) -> int:
        return len(self._device_map)

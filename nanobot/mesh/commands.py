"""Standardized device command schema and validation.

Defines the format for commands sent to mesh devices and responses
received from them. Commands are validated against the device registry
to ensure the target device exists, has the referenced capability,
and the provided value is within the allowed range/type.

Command format
--------------
{
    "device": "light-01",          # Target device node_id
    "action": "set",               # Action type
    "capability": "brightness",    # Which capability to target
    "params": {"value": 80}        # Action parameters
}

Response format
---------------
{
    "device": "light-01",
    "status": "ok",                # "ok" or "error"
    "capability": "brightness",
    "value": 80,                   # Current value after action
    "error": null                  # Error message if status == "error"
}

Usage
-----
>>> schema = CommandSchema(registry)
>>> cmd = DeviceCommand(device="light-01", action="set", capability="brightness", params={"value": 80})
>>> errors = schema.validate(cmd)
>>> if not errors:
...     envelope = schema.to_mesh_envelope(cmd, source="hub-01")
...     response = schema.parse_response(response_envelope)
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.mesh.protocol import MeshEnvelope, MsgType
from nanobot.mesh.registry import (
    CapabilityType,
    DataType,
    DeviceCapability,
    DeviceInfo,
)

if TYPE_CHECKING:
    from nanobot.mesh.registry import DeviceRegistry


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

class Action(str, Enum):
    """Supported command actions."""
    SET = "set"           # Set a capability value (actuator/property)
    GET = "get"           # Query current value (any capability)
    TOGGLE = "toggle"     # Toggle a boolean capability
    EXECUTE = "execute"   # Run a custom device function


class CommandStatus(str, Enum):
    """Command response status codes."""
    OK = "ok"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Command data model
# ---------------------------------------------------------------------------

@dataclass
class DeviceCommand:
    """A command to be sent to a device.

    Examples
    --------
    Set brightness:
        DeviceCommand(device="light-01", action="set", capability="brightness", params={"value": 80})

    Query temperature:
        DeviceCommand(device="sensor-01", action="get", capability="temperature")

    Toggle power:
        DeviceCommand(device="light-01", action="toggle", capability="power")

    Execute custom:
        DeviceCommand(device="robot-01", action="execute", capability="move", params={"direction": "forward", "distance": 1.0})
    """
    device: str                                    # Target device node_id
    action: str                                    # Action type (see Action enum)
    capability: str = ""                           # Target capability name
    params: dict[str, Any] = field(default_factory=dict)  # Action-specific parameters

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "device": self.device,
            "action": self.action,
        }
        if self.capability:
            d["capability"] = self.capability
        if self.params:
            d["params"] = self.params
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceCommand:
        return cls(
            device=d.get("device", ""),
            action=d.get("action", ""),
            capability=d.get("capability", ""),
            params=d.get("params", {}),
        )


@dataclass
class CommandResponse:
    """Response from a device after executing a command."""
    device: str
    status: str                                     # "ok" or "error"
    capability: str = ""
    value: Any = None                               # Current value after action
    error: str | None = None                        # Error message if status == "error"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "device": self.device,
            "status": self.status,
        }
        if self.capability:
            d["capability"] = self.capability
        if self.value is not None:
            d["value"] = self.value
        if self.error is not None:
            d["error"] = self.error
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommandResponse:
        return cls(
            device=d.get("device", ""),
            status=d.get("status", CommandStatus.ERROR),
            capability=d.get("capability", ""),
            value=d.get("value"),
            error=d.get("error"),
        )

    @property
    def is_ok(self) -> bool:
        return self.status == CommandStatus.OK


@dataclass
class BatchCommand:
    """A batch of commands to execute atomically.

    If ``stop_on_error`` is True, execution stops at the first failure.
    """
    commands: list[DeviceCommand] = field(default_factory=list)
    stop_on_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "commands": [c.to_dict() for c in self.commands],
            "stop_on_error": self.stop_on_error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BatchCommand:
        return cls(
            commands=[DeviceCommand.from_dict(c) for c in d.get("commands", [])],
            stop_on_error=d.get("stop_on_error", False),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_command(
    cmd: DeviceCommand,
    registry: DeviceRegistry,
) -> list[str]:
    """Validate a command against the device registry.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # 1. Check action type
    valid_actions = {a.value for a in Action}
    if cmd.action not in valid_actions:
        errors.append(f"Unknown action '{cmd.action}'. Valid: {sorted(valid_actions)}")

    # 2. Check device exists
    device = registry.get_device(cmd.device)
    if device is None:
        errors.append(f"Device '{cmd.device}' not found in registry")
        return errors  # Can't validate further without device

    # 3. Check device is online (warning, not error)
    if not device.online:
        errors.append(f"Device '{cmd.device}' is offline")

    # 4. Check capability exists (if specified)
    if cmd.capability:
        cap = device.get_capability(cmd.capability)
        if cap is None:
            errors.append(
                f"Device '{cmd.device}' has no capability '{cmd.capability}'. "
                f"Available: {device.capability_names()}"
            )
            return errors

        # 5. Validate action vs capability type
        if cmd.action == Action.SET:
            if cap.cap_type == CapabilityType.SENSOR:
                errors.append(
                    f"Cannot 'set' a sensor capability '{cmd.capability}'. "
                    "Use 'get' instead."
                )

        if cmd.action == Action.TOGGLE:
            if cap.data_type != DataType.BOOL:
                errors.append(
                    f"Cannot 'toggle' non-boolean capability '{cmd.capability}' "
                    f"(data_type={cap.data_type})"
                )

        # 6. Validate value range/type for SET action
        if cmd.action == Action.SET and "value" in cmd.params:
            value = cmd.params["value"]
            _validate_value(value, cap, errors)

    elif cmd.action != Action.EXECUTE:
        # Non-execute commands should specify a capability
        errors.append("Missing 'capability' field (required for set/get/toggle)")

    return errors


def _validate_value(
    value: Any,
    cap: DeviceCapability,
    errors: list[str],
) -> None:
    """Validate a value against a capability's data type and constraints."""
    # Type validation
    if cap.data_type == DataType.BOOL:
        if not isinstance(value, bool):
            errors.append(
                f"Value for '{cap.name}' must be bool, got {type(value).__name__}"
            )
    elif cap.data_type == DataType.INT:
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(
                f"Value for '{cap.name}' must be int, got {type(value).__name__}"
            )
    elif cap.data_type == DataType.FLOAT:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(
                f"Value for '{cap.name}' must be float, got {type(value).__name__}"
            )
    elif cap.data_type == DataType.STRING:
        if not isinstance(value, str):
            errors.append(
                f"Value for '{cap.name}' must be str, got {type(value).__name__}"
            )
    elif cap.data_type == DataType.ENUM:
        if value not in cap.enum_values:
            errors.append(
                f"Value '{value}' not in allowed values for '{cap.name}': "
                f"{cap.enum_values}"
            )

    # Range validation for numeric types
    if cap.value_range is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi = cap.value_range
        if value < lo or value > hi:
            errors.append(
                f"Value {value} for '{cap.name}' out of range [{lo}, {hi}]"
            )


# ---------------------------------------------------------------------------
# Mesh envelope conversion
# ---------------------------------------------------------------------------

def command_to_envelope(
    cmd: DeviceCommand,
    source: str,
) -> MeshEnvelope:
    """Convert a DeviceCommand into a mesh COMMAND envelope."""
    return MeshEnvelope(
        type=MsgType.COMMAND,
        source=source,
        target=cmd.device,
        payload=cmd.to_dict(),
        ts=time.time(),
    )


def parse_command_from_envelope(env: MeshEnvelope) -> DeviceCommand | None:
    """Extract a DeviceCommand from a COMMAND envelope payload."""
    if env.type != MsgType.COMMAND:
        return None
    try:
        return DeviceCommand.from_dict(env.payload)
    except (KeyError, TypeError) as exc:
        logger.warning(f"[Commands] failed to parse command from envelope: {exc}")
        return None


def response_to_envelope(
    resp: CommandResponse,
    source: str,
    target: str,
) -> MeshEnvelope:
    """Convert a CommandResponse into a RESPONSE envelope."""
    return MeshEnvelope(
        type=MsgType.RESPONSE,
        source=source,
        target=target,
        payload=resp.to_dict(),
        ts=time.time(),
    )


def parse_response_from_envelope(env: MeshEnvelope) -> CommandResponse | None:
    """Extract a CommandResponse from a RESPONSE envelope payload."""
    if env.type != MsgType.RESPONSE:
        return None
    try:
        return CommandResponse.from_dict(env.payload)
    except (KeyError, TypeError) as exc:
        logger.warning(f"[Commands] failed to parse response from envelope: {exc}")
        return None


# ---------------------------------------------------------------------------
# Command description generator (for LLM context)
# ---------------------------------------------------------------------------

def describe_device_commands(
    registry: DeviceRegistry,
) -> str:
    """Generate a description of available device commands for LLM context.

    Produces instructions the LLM can follow to generate valid commands.
    """
    devices = registry.get_all_devices()
    if not devices:
        return "No devices available for commands."

    lines = [
        "## Available Device Commands",
        "",
        "To control a device, output a JSON command block:",
        "```json",
        '{"device": "<node_id>", "action": "<set|get|toggle>", '
        '"capability": "<name>", "params": {"value": <val>}}',
        "```",
        "",
        "### Devices and Capabilities:",
        "",
    ]

    for d in devices:
        status = "ONLINE" if d.online else "OFFLINE"
        lines.append(f"**{d.name}** (`{d.node_id}`, {d.device_type}) [{status}]")
        if not d.capabilities:
            lines.append("  - No capabilities registered")
        for cap in d.capabilities:
            parts = [f"  - `{cap.name}` ({cap.cap_type})"]
            if cap.data_type == DataType.BOOL:
                parts.append("— true/false")
            elif cap.data_type == DataType.ENUM:
                parts.append(f"— one of: {cap.enum_values}")
            elif cap.value_range is not None:
                lo, hi = cap.value_range
                unit = f" {cap.unit}" if cap.unit else ""
                parts.append(f"— {lo}–{hi}{unit}")
            elif cap.unit:
                parts.append(f"— {cap.unit}")
            # Show current state if available
            current = d.state.get(cap.name)
            if current is not None:
                parts.append(f"[current: {current}]")
            lines.append(" ".join(parts))
        lines.append("")

    lines.extend([
        "### Action Reference:",
        "- `set`: Set a value — `{\"action\": \"set\", \"capability\": \"brightness\", \"params\": {\"value\": 80}}`",
        "- `get`: Query value — `{\"action\": \"get\", \"capability\": \"temperature\"}`",
        "- `toggle`: Toggle boolean — `{\"action\": \"toggle\", \"capability\": \"power\"}`",
        "- `execute`: Custom action — `{\"action\": \"execute\", \"params\": {...}}`",
    ])

    return "\n".join(lines)

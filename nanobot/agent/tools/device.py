"""Device control tool — bridges LLM agent to mesh device commands.

Provides the agent with the ability to:
- List all registered devices and their capabilities
- Send validated commands to devices through the mesh transport
- Query individual device state
- Get structured capability descriptions for reasoning

This tool is registered conditionally when the mesh channel is enabled.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.mesh.commands import (
    Action,
    DeviceCommand,
    command_to_envelope,
    describe_device_commands,
    validate_command,
)

if TYPE_CHECKING:
    from nanobot.mesh.registry import DeviceRegistry
    from nanobot.mesh.transport import MeshTransport


class DeviceControlTool(Tool):
    """Agent tool for controlling IoT devices via the LAN mesh.

    Actions
    -------
    list
        Return a summary of all registered devices (name, type, status).
    command
        Validate and send a command to a device.
    state
        Get the current state of a specific device.
    describe
        Generate a detailed capability description for LLM reasoning.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        transport: MeshTransport,
        node_id: str,
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._node_id = node_id

    # -- Tool interface ------------------------------------------------------

    @property
    def name(self) -> str:
        return "device_control"

    @property
    def description(self) -> str:
        return (
            "Control IoT devices on the LAN mesh. "
            "Actions: 'list' (show devices), 'command' (send a command), "
            "'state' (query device state), 'describe' (detailed capabilities)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "command", "state", "describe"],
                    "description": (
                        "Action to perform: "
                        "'list' shows all devices, "
                        "'command' sends a device command, "
                        "'state' gets a device's current state, "
                        "'describe' returns full capability reference."
                    ),
                },
                "device": {
                    "type": "string",
                    "description": "Target device node_id (required for 'command' and 'state').",
                },
                "command_action": {
                    "type": "string",
                    "enum": ["set", "get", "toggle", "execute"],
                    "description": "Command type (required for 'command' action).",
                },
                "capability": {
                    "type": "string",
                    "description": "Device capability name (e.g. 'power', 'brightness', 'temperature').",
                },
                "value": {
                    "description": "Value to set — boolean, number, or string depending on capability.",
                },
                "params": {
                    "type": "object",
                    "description": "Additional parameters for 'execute' actions.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        if action == "list":
            return self._list_devices()
        elif action == "command":
            return await self._send_command(kwargs)
        elif action == "state":
            return self._get_state(kwargs.get("device", ""))
        elif action == "describe":
            return self._describe()
        else:
            return f"Unknown action '{action}'. Use: list, command, state, describe."

    # -- Action implementations ----------------------------------------------

    def _list_devices(self) -> str:
        """Return a concise device list."""
        devices = self._registry.get_all_devices()
        if not devices:
            return "No devices registered on the mesh."

        lines = [f"Registered devices ({len(devices)}):"]
        for d in devices:
            status = "ONLINE" if d.online else "OFFLINE"
            cap_names = ", ".join(d.capability_names()) if d.capabilities else "none"
            lines.append(f"  • {d.name} ({d.node_id}) [{status}] — {d.device_type}, caps: {cap_names}")
        return "\n".join(lines)

    async def _send_command(self, kwargs: dict[str, Any]) -> str:
        """Validate and dispatch a device command."""
        device = kwargs.get("device", "")
        cmd_action = kwargs.get("command_action", "")
        capability = kwargs.get("capability", "")
        value = kwargs.get("value")
        params = kwargs.get("params", {})

        if not device:
            return "Error: 'device' is required for the 'command' action."
        if not cmd_action:
            return "Error: 'command_action' is required (set, get, toggle, execute)."

        # Build params dict — merge explicit value into params
        if value is not None and "value" not in params:
            params = {**params, "value": value}

        cmd = DeviceCommand(
            device=device,
            action=cmd_action,
            capability=capability,
            params=params,
        )

        # Validate against registry
        errors = validate_command(cmd, self._registry)
        if errors:
            return "Command validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        # Create mesh envelope and dispatch
        envelope = command_to_envelope(cmd, source=self._node_id)
        ok = await self._transport.send(envelope)
        if ok:
            logger.info(f"[DeviceControlTool] sent {cmd_action} {capability} to {device}")
            parts = [f"Command sent to {device}: {cmd_action}"]
            if capability:
                parts.append(capability)
            if value is not None:
                parts.append(f"= {value}")
            return " ".join(parts)
        else:
            logger.warning(f"[DeviceControlTool] failed to deliver to {device}")
            return f"Failed to deliver command to {device} — device may be unreachable."

    def _get_state(self, device_id: str) -> str:
        """Return the current state of a specific device."""
        if not device_id:
            return "Error: 'device' is required for the 'state' action."

        device = self._registry.get_device(device_id)
        if device is None:
            return f"Device '{device_id}' not found in registry."

        status = "ONLINE" if device.online else "OFFLINE"
        lines = [f"{device.name} ({device.node_id}) — {device.device_type} [{status}]"]

        if device.state:
            lines.append("Current state:")
            for key, val in device.state.items():
                cap = device.get_capability(key)
                unit = f" {cap.unit}" if cap and cap.unit else ""
                lines.append(f"  • {key}: {val}{unit}")
        else:
            lines.append("No state reported yet.")

        if device.capabilities:
            lines.append("Capabilities:")
            for cap in device.capabilities:
                parts = [f"  • {cap.name} ({cap.cap_type})"]
                if cap.value_range:
                    lo, hi = cap.value_range
                    parts.append(f"range {lo}–{hi}")
                if cap.unit:
                    parts.append(cap.unit)
                if cap.enum_values:
                    parts.append(f"values: {cap.enum_values}")
                lines.append(" ".join(parts))

        return "\n".join(lines)

    def _describe(self) -> str:
        """Return the full command description for LLM reasoning."""
        return describe_device_commands(self._registry)

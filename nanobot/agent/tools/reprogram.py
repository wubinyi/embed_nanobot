"""Device reprogram tool — AI-assisted code generation and OTA deployment.

Provides the agent with the ability to:
- List available code templates for embedded devices
- Generate MicroPython firmware from templates or raw code
- Validate generated code for safety (AST-based analysis)
- Deploy generated code to devices via OTA

This tool is registered conditionally when mesh channel + OTA are enabled.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.mesh.codegen import CodeGenerator, CodePackage

if TYPE_CHECKING:
    from nanobot.mesh.ota import FirmwareStore, OTAManager
    from nanobot.mesh.registry import DeviceRegistry
    from nanobot.mesh.transport import MeshTransport


class ReprogramTool(Tool):
    """Agent tool for generating and deploying device firmware.

    Actions
    -------
    templates
        List available code templates.
    generate
        Generate code from a template with parameters.
    validate
        Validate raw code for safety.
    deploy
        Package code and deploy to a device via OTA.
    status
        Check OTA deployment status.
    """

    def __init__(
        self,
        generator: CodeGenerator,
        firmware_store: FirmwareStore,
        ota_manager: OTAManager,
        registry: DeviceRegistry,
        transport: MeshTransport,
        node_id: str,
    ) -> None:
        self._generator = generator
        self._firmware_store = firmware_store
        self._ota_manager = ota_manager
        self._registry = registry
        self._transport = transport
        self._node_id = node_id

    # -- Tool interface ------------------------------------------------------

    @property
    def name(self) -> str:
        return "device_reprogram"

    @property
    def description(self) -> str:
        return (
            "Generate and deploy MicroPython firmware to IoT devices. "
            "Actions: 'templates' (list code templates), "
            "'generate' (create code from template), "
            "'validate' (safety-check raw code), "
            "'deploy' (package + OTA push to device), "
            "'status' (check OTA progress)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["templates", "generate", "validate", "deploy", "status"],
                    "description": (
                        "'templates' lists available code templates, "
                        "'generate' fills a template with params, "
                        "'validate' checks raw code for safety, "
                        "'deploy' packages and pushes code via OTA, "
                        "'status' checks OTA progress."
                    ),
                },
                "template_name": {
                    "type": "string",
                    "description": "Template name for 'generate' action (e.g. 'sensor_reader').",
                },
                "params": {
                    "type": "object",
                    "description": "Template parameters (e.g. {\"pin\": 36, \"sensor_type\": \"temperature\"}).",
                },
                "code": {
                    "type": "string",
                    "description": "Raw MicroPython code for 'validate' or 'deploy' actions.",
                },
                "device": {
                    "type": "string",
                    "description": "Target device node_id for 'deploy' and 'status' actions.",
                },
                "device_type": {
                    "type": "string",
                    "description": "Device type hint for code generation.",
                },
                "version": {
                    "type": "string",
                    "description": "Firmware version string (default: '0.1.0').",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of what the code does.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        if action == "templates":
            return self._list_templates()
        elif action == "generate":
            return self._generate(kwargs)
        elif action == "validate":
            return self._validate(kwargs)
        elif action == "deploy":
            return await self._deploy(kwargs)
        elif action == "status":
            return self._status(kwargs.get("device", ""))
        else:
            return (
                f"Unknown action '{action}'. "
                "Use: templates, generate, validate, deploy, status."
            )

    # -- Action implementations ----------------------------------------------

    def _list_templates(self) -> str:
        """Return available code templates."""
        return self._generator.describe_templates()

    def _generate(self, kwargs: dict[str, Any]) -> str:
        """Generate code from a template."""
        template_name = kwargs.get("template_name", "")
        if not template_name:
            return "Error: 'template_name' is required for 'generate' action."

        params = kwargs.get("params", {})
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except json.JSONDecodeError:
                return "Error: 'params' must be a valid JSON object."

        device_type = kwargs.get("device_type", "")
        description = kwargs.get("description", "")
        version = kwargs.get("version", "0.1.0")

        pkg = self._generator.generate_from_template(
            template_name=template_name,
            params=params,
            device_type=device_type,
            description=description,
            version=version,
        )

        return self._format_package(pkg)

    def _validate(self, kwargs: dict[str, Any]) -> str:
        """Validate raw code for safety."""
        code = kwargs.get("code", "")
        if not code:
            return "Error: 'code' is required for 'validate' action."

        device_type = kwargs.get("device_type", "unknown")
        description = kwargs.get("description", "")
        version = kwargs.get("version", "0.1.0")

        pkg = self._generator.generate_from_code(
            code=code,
            device_type=device_type,
            version=version,
            description=description,
        )

        return self._format_package(pkg)

    async def _deploy(self, kwargs: dict[str, Any]) -> str:
        """Package code and deploy via OTA."""
        device = kwargs.get("device", "")
        if not device:
            return "Error: 'device' is required for 'deploy' action."

        # Get device info
        device_info = self._registry.get_device(device)
        if not device_info:
            return f"Error: Device '{device}' not found in registry."
        if not device_info.online:
            return f"Error: Device '{device}' is offline."

        # Get code — either from raw code or generate from template
        code = kwargs.get("code", "")
        device_type = kwargs.get("device_type", device_info.device_type)
        version = kwargs.get("version", "0.1.0")
        description = kwargs.get("description", "")

        if not code:
            template_name = kwargs.get("template_name", "")
            params = kwargs.get("params", {})
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    return "Error: 'params' must be a valid JSON object."

            if template_name:
                pkg = self._generator.generate_from_template(
                    template_name=template_name,
                    params=params,
                    device_type=device_type,
                    description=description,
                    version=version,
                )
            else:
                return (
                    "Error: 'deploy' requires either 'code' (raw MicroPython) "
                    "or 'template_name' + 'params' to generate code."
                )
        else:
            pkg = self._generator.generate_from_code(
                code=code,
                device_type=device_type,
                version=version,
                description=description,
            )

        # Validate
        if not pkg.validation_passed:
            errors = "\n".join(f"  - {e}" for e in pkg.validation_errors)
            return (
                f"Safety validation FAILED — cannot deploy:\n{errors}\n\n"
                "Fix the issues and try again."
            )

        # Package as firmware and add to store
        firmware_id = f"codegen-{device}-{version}"
        code_bytes = pkg.code.encode("utf-8")

        try:
            self._firmware_store.add_firmware(
                firmware_id=firmware_id,
                version=version,
                device_type=device_type,
                data=code_bytes,
            )
        except Exception as exc:
            return f"Error adding firmware to store: {exc}"

        # Start OTA update
        try:
            session = await self._ota_manager.start_update(
                device_id=device,
                firmware_id=firmware_id,
                transport=self._transport,
                source_node=self._node_id,
            )
        except Exception as exc:
            return f"Error starting OTA update: {exc}"

        logger.info(
            "[reprogram] deployed codegen package to {} (firmware={}, v{})",
            device, firmware_id, version,
        )

        return (
            f"Code deployed to '{device}' via OTA.\n"
            f"- Firmware ID: {firmware_id}\n"
            f"- Version: {version}\n"
            f"- Size: {len(code_bytes)} bytes\n"
            f"- Session: {session.session_id if session else 'started'}\n"
            f"Use action 'status' with device='{device}' to track progress."
        )

    def _status(self, device: str) -> str:
        """Check OTA deployment status for a device."""
        if not device:
            # Show all active sessions
            sessions = self._ota_manager.get_all_sessions()
            if not sessions:
                return "No active OTA sessions."
            lines = ["Active OTA sessions:"]
            for s in sessions:
                lines.append(
                    f"  - {s.device_id}: {s.state.value} "
                    f"(firmware={s.firmware_id})"
                )
            return "\n".join(lines)

        session = self._ota_manager.get_session(device)
        if not session:
            return f"No active OTA session for device '{device}'."

        return (
            f"OTA status for '{device}':\n"
            f"- State: {session.state.value}\n"
            f"- Firmware: {session.firmware_id}\n"
            f"- Chunks sent: {session.chunks_sent}/{session.total_chunks}\n"
            f"- Progress: {session.progress_pct:.0f}%"
        )

    @staticmethod
    def _format_package(pkg: CodePackage) -> str:
        """Format a CodePackage as a readable response."""
        status = "PASSED" if pkg.validation_passed else "FAILED"
        lines = [
            f"**Code Generation Result** ({status})",
            f"- Platform: {pkg.platform}",
            f"- Device type: {pkg.device_type}",
            f"- Version: {pkg.version}",
        ]
        if pkg.template_name:
            lines.append(f"- Template: {pkg.template_name}")
        if pkg.description:
            lines.append(f"- Description: {pkg.description}")

        if pkg.validation_errors:
            lines.append("\n**Validation Errors:**")
            for err in pkg.validation_errors:
                lines.append(f"  - {err}")

        if pkg.code:
            lines.append(f"\n**Generated Code** ({len(pkg.code)} bytes):")
            lines.append("```python")
            lines.append(pkg.code)
            lines.append("```")

        return "\n".join(lines)

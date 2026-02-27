"""Device code generation — AI-assisted firmware creation for embedded devices.

Generates MicroPython code from natural language descriptions, validates
for safety, and packages for OTA deployment via the existing firmware
update infrastructure.

Architecture
------------
- ``CodeTemplate``   — platform-specific code skeleton with placeholders
- ``CodeValidator``  — AST-based safety analysis for generated code
- ``CodeGenerator``  — template selection + placeholder filling
- ``CodePackage``    — bundle of generated code ready for OTA

Safety model
------------
All generated code passes through ``CodeValidator`` which performs:
1. AST parsing (syntax check)
2. Import whitelist enforcement
3. Dangerous builtin/attribute blocklist
4. Required structure check (setup/loop or main)
5. Size limit enforcement
6. Network server pattern detection
"""

from __future__ import annotations

import ast
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CODE_SIZE = 65_536  # 64 KB source text

# MicroPython-safe imports (subset of stdlib + hardware APIs)
ALLOWED_IMPORTS: frozenset[str] = frozenset({
    # Hardware
    "machine", "esp", "esp32", "neopixel", "onewire", "ds18x20",
    # Timing / scheduling
    "time", "utime", "asyncio", "uasyncio",
    # Data
    "json", "ujson", "struct", "ubinascii", "binascii", "hashlib",
    "uhashlib", "collections", "ucollections", "array", "math",
    # Networking (client only)
    "network", "urequests", "requests", "usocket", "socket",
    "umqtt", "umqtt.simple", "umqtt.robust", "ssl", "ussl",
    # I/O
    "io", "uio", "os", "uos", "gc", "micropython",
    # String / regex
    "re", "ure",
})

# Imports that are absolutely blocked regardless of context
BLOCKED_IMPORTS: frozenset[str] = frozenset({
    "subprocess", "shutil", "pathlib", "ctypes",
    "multiprocessing", "threading", "signal",
    "importlib", "code", "codeop", "compileall",
})

# Builtin calls that must never appear
BLOCKED_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "breakpoint",
})

# Attribute access patterns that indicate sandbox escapes
BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__class__", "__subclasses__", "__bases__", "__mro__",
    "__globals__", "__builtins__", "__code__", "__func__",
})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CodeTemplate:
    """Platform-specific code skeleton with placeholders.

    Templates contain ``{placeholder}`` markers that get filled by the
    code generator (either from user parameters or LLM output).
    """

    platform: str              # "micropython"
    name: str                  # e.g. "sensor_reader", "actuator_switch"
    description: str           # Human-readable purpose
    template: str              # Code body with {placeholders}
    required_params: list[str] = field(default_factory=list)
    device_type: str = ""      # Target device type hint

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CodeTemplate:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CodePackage:
    """Bundle of generated code ready for OTA deployment."""

    code: str                           # Generated source code
    platform: str                       # Target platform ("micropython")
    device_type: str                    # Target device type
    version: str                        # Version string
    template_name: str = ""             # Template used (if any)
    description: str = ""               # Original NL description
    validation_passed: bool = False     # Whether safety checks passed
    validation_errors: list[str] = field(default_factory=list)
    created_at: str = ""                # ISO timestamp

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CodePackage:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES: list[CodeTemplate] = [
    CodeTemplate(
        platform="micropython",
        name="sensor_reader",
        description="Periodic sensor reading with mesh reporting",
        device_type="sensor",
        required_params=["pin", "sensor_type", "read_interval_ms"],
        template="""\
# Auto-generated MicroPython firmware: sensor reader
# Device type: {device_type}
# Description: {description}

import machine
import time
import json

# --- Configuration ---
SENSOR_PIN = {pin}
SENSOR_TYPE = "{sensor_type}"
READ_INTERVAL_MS = {read_interval_ms}

# --- Setup ---
def setup():
    \"\"\"Initialize hardware peripherals.\"\"\"
    global sensor
    sensor = machine.ADC(machine.Pin(SENSOR_PIN))
    sensor.atten(machine.ADC.ATTN_11DB)
    print("[sensor] initialized on pin", SENSOR_PIN)

# --- Main loop ---
def loop():
    \"\"\"Read sensor and report state.\"\"\"
    value = sensor.read()
    print(json.dumps({{"type": "STATE_REPORT", "capability": SENSOR_TYPE, "value": value}}))
    time.sleep_ms(READ_INTERVAL_MS)

# --- Entry point ---
if __name__ == "__main__":
    setup()
    while True:
        loop()
""",
    ),
    CodeTemplate(
        platform="micropython",
        name="actuator_switch",
        description="Digital output control (relay, LED, motor driver)",
        device_type="actuator",
        required_params=["pin", "actuator_name"],
        template="""\
# Auto-generated MicroPython firmware: actuator switch
# Device type: {device_type}
# Description: {description}

import machine
import time
import json

# --- Configuration ---
OUTPUT_PIN = {pin}
ACTUATOR_NAME = "{actuator_name}"

# --- Setup ---
def setup():
    \"\"\"Initialize output pin.\"\"\"
    global output
    output = machine.Pin(OUTPUT_PIN, machine.Pin.OUT, value=0)
    print("[actuator] initialized on pin", OUTPUT_PIN)

# --- Command handler ---
def handle_command(cmd):
    \"\"\"Process incoming command.\"\"\"
    action = cmd.get("action", "")
    if action == "set":
        value = int(cmd.get("value", 0))
        output.value(value)
        return {{"status": "ok", "value": value}}
    elif action == "toggle":
        current = output.value()
        output.value(1 - current)
        return {{"status": "ok", "value": 1 - current}}
    elif action == "get":
        return {{"status": "ok", "value": output.value()}}
    return {{"status": "error", "error": "unknown action"}}

# --- Main loop ---
def loop():
    \"\"\"Check for commands (placeholder — real impl reads from mesh).\"\"\"
    time.sleep_ms(100)

# --- Entry point ---
if __name__ == "__main__":
    setup()
    while True:
        loop()
""",
    ),
    CodeTemplate(
        platform="micropython",
        name="pwm_controller",
        description="PWM output for dimmable LEDs, servo motors, or fans",
        device_type="actuator",
        required_params=["pin", "frequency", "device_name"],
        template="""\
# Auto-generated MicroPython firmware: PWM controller
# Device type: {device_type}
# Description: {description}

import machine
import time
import json

# --- Configuration ---
PWM_PIN = {pin}
PWM_FREQ = {frequency}
DEVICE_NAME = "{device_name}"

# --- Setup ---
def setup():
    \"\"\"Initialize PWM output.\"\"\"
    global pwm
    pwm = machine.PWM(machine.Pin(PWM_PIN), freq=PWM_FREQ, duty=0)
    print("[pwm] initialized on pin", PWM_PIN, "at", PWM_FREQ, "Hz")

# --- Command handler ---
def handle_command(cmd):
    \"\"\"Process incoming command. Value 0-1023 for duty cycle.\"\"\"
    action = cmd.get("action", "")
    if action == "set":
        value = max(0, min(1023, int(cmd.get("value", 0))))
        pwm.duty(value)
        return {{"status": "ok", "value": value}}
    elif action == "get":
        return {{"status": "ok", "value": pwm.duty()}}
    return {{"status": "error", "error": "unknown action"}}

# --- Main loop ---
def loop():
    \"\"\"Main loop (placeholder).\"\"\"
    time.sleep_ms(100)

# --- Entry point ---
if __name__ == "__main__":
    setup()
    while True:
        loop()
""",
    ),
    CodeTemplate(
        platform="micropython",
        name="i2c_sensor",
        description="I2C sensor reader (temperature, humidity, pressure)",
        device_type="sensor",
        required_params=["sda_pin", "scl_pin", "i2c_address", "sensor_name", "read_interval_ms"],
        template="""\
# Auto-generated MicroPython firmware: I2C sensor reader
# Device type: {device_type}
# Description: {description}

import machine
import time
import json
import struct

# --- Configuration ---
SDA_PIN = {sda_pin}
SCL_PIN = {scl_pin}
I2C_ADDR = {i2c_address}
SENSOR_NAME = "{sensor_name}"
READ_INTERVAL_MS = {read_interval_ms}

# --- Setup ---
def setup():
    \"\"\"Initialize I2C bus.\"\"\"
    global i2c
    i2c = machine.I2C(0, sda=machine.Pin(SDA_PIN), scl=machine.Pin(SCL_PIN), freq=400000)
    devices = i2c.scan()
    if I2C_ADDR not in devices:
        print("[i2c] WARNING: device not found at address", hex(I2C_ADDR))
    else:
        print("[i2c] sensor found at", hex(I2C_ADDR))

# --- Reading ---
def read_sensor():
    \"\"\"Read raw bytes from I2C device. Override for specific sensor.\"\"\"
    try:
        data = i2c.readfrom(I2C_ADDR, 2)
        value = struct.unpack(">h", data)[0]
        return value
    except OSError:
        return None

# --- Main loop ---
def loop():
    \"\"\"Read and report.\"\"\"
    value = read_sensor()
    if value is not None:
        print(json.dumps({{"type": "STATE_REPORT", "capability": SENSOR_NAME, "value": value}}))
    time.sleep_ms(READ_INTERVAL_MS)

# --- Entry point ---
if __name__ == "__main__":
    setup()
    while True:
        loop()
""",
    ),
]


# ---------------------------------------------------------------------------
# Code validator
# ---------------------------------------------------------------------------

class CodeValidator:
    """AST-based safety validator for generated MicroPython code.

    Checks
    ------
    1. Syntax correctness (AST parse)
    2. Import whitelist / blocklist
    3. Dangerous builtin call blocklist
    4. Dangerous attribute access blocklist
    5. Required structure (setup/loop or main)
    6. Source size limit
    7. Network server pattern detection (bind/listen/accept)
    """

    def __init__(
        self,
        allowed_imports: frozenset[str] | None = None,
        blocked_imports: frozenset[str] | None = None,
        blocked_calls: frozenset[str] | None = None,
        blocked_attrs: frozenset[str] | None = None,
        max_code_size: int = MAX_CODE_SIZE,
        require_structure: bool = True,
    ) -> None:
        self._allowed_imports = allowed_imports or ALLOWED_IMPORTS
        self._blocked_imports = blocked_imports or BLOCKED_IMPORTS
        self._blocked_calls = blocked_calls or BLOCKED_CALLS
        self._blocked_attrs = blocked_attrs or BLOCKED_ATTRS
        self._max_code_size = max_code_size
        self._require_structure = require_structure

    def validate(self, code: str) -> tuple[bool, list[str]]:
        """Validate code for safety.

        Returns ``(passed, errors)`` where ``errors`` is a list of
        human-readable issue descriptions.
        """
        errors: list[str] = []

        # 1. Size check
        if len(code) > self._max_code_size:
            errors.append(
                f"Code exceeds size limit: {len(code)} > {self._max_code_size} bytes"
            )

        # 2. Empty check
        if not code.strip():
            errors.append("Code is empty")
            return False, errors

        # 3. AST parse
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            errors.append(f"Syntax error: {exc}")
            return False, errors

        # 4. Walk AST for safety checks
        self._check_imports(tree, errors)
        self._check_calls(tree, errors)
        self._check_attrs(tree, errors)
        self._check_network_server(tree, errors)

        # 5. Structure check
        if self._require_structure:
            self._check_structure(tree, errors)

        passed = len(errors) == 0
        return passed, errors

    def _check_imports(self, tree: ast.AST, errors: list[str]) -> None:
        """Check all imports against allowed/blocked lists."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._validate_module_name(alias.name, errors)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._validate_module_name(node.module, errors)

    def _validate_module_name(self, name: str, errors: list[str]) -> None:
        """Check a single module name."""
        top_level = name.split(".")[0]
        if top_level in self._blocked_imports:
            errors.append(f"Blocked import: '{name}' (security risk)")
        elif top_level not in self._allowed_imports:
            errors.append(
                f"Disallowed import: '{name}' (not in allowed list for embedded devices)"
            )

    def _check_calls(self, tree: ast.AST, errors: list[str]) -> None:
        """Check for dangerous function calls."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._get_call_name(node)
                if name and name in self._blocked_calls:
                    errors.append(f"Blocked call: '{name}()' (security risk)")

    @staticmethod
    def _get_call_name(node: ast.Call) -> str | None:
        """Extract the function name from a Call node."""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None

    def _check_attrs(self, tree: ast.AST, errors: list[str]) -> None:
        """Check for dangerous attribute access (sandbox escapes)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in self._blocked_attrs:
                    errors.append(
                        f"Blocked attribute access: '.{node.attr}' (potential sandbox escape)"
                    )

    def _check_network_server(self, tree: ast.AST, errors: list[str]) -> None:
        """Detect network server patterns (bind/listen/accept)."""
        server_methods = {"bind", "listen", "accept"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in server_methods:
                errors.append(
                    f"Network server pattern detected: '.{node.attr}()' "
                    f"(devices should not run servers)"
                )

    def _check_structure(self, tree: ast.AST, errors: list[str]) -> None:
        """Verify required structure: setup+loop or main function."""
        top_functions = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top_functions.add(node.name)

        has_setup_loop = "setup" in top_functions and "loop" in top_functions
        has_main = "main" in top_functions
        if not has_setup_loop and not has_main:
            errors.append(
                "Missing required structure: code must define "
                "setup()+loop() or main() at module level"
            )


# ---------------------------------------------------------------------------
# Code generator
# ---------------------------------------------------------------------------

class CodeGenerator:
    """Generates device firmware code from templates and user parameters.

    Templates can be loaded from disk (JSON) or from the built-in set.
    The generator fills template placeholders with user-provided params
    and returns a ``CodePackage`` for validation and deployment.
    """

    def __init__(
        self,
        templates_path: str = "",
        validator: CodeValidator | None = None,
    ) -> None:
        self._templates: dict[str, CodeTemplate] = {}
        self._validator = validator or CodeValidator()
        self._templates_path = templates_path

        # Load built-in templates
        for t in BUILTIN_TEMPLATES:
            self._templates[t.name] = t

        # Load custom templates from disk
        if templates_path:
            self._load_templates(templates_path)

    def _load_templates(self, path: str) -> None:
        """Load custom templates from a JSON file."""
        p = Path(path)
        if not p.exists():
            logger.info("[codegen] templates file not found: {}", path)
            return
        try:
            data = json.loads(p.read_text())
            for item in data:
                t = CodeTemplate.from_dict(item)
                self._templates[t.name] = t
            logger.info("[codegen] loaded {} custom templates from {}", len(data), path)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("[codegen] failed to load templates: {}", exc)

    def list_templates(self, platform: str = "") -> list[CodeTemplate]:
        """List available templates, optionally filtered by platform."""
        templates = list(self._templates.values())
        if platform:
            templates = [t for t in templates if t.platform == platform]
        return templates

    def get_template(self, name: str) -> CodeTemplate | None:
        """Get a template by name."""
        return self._templates.get(name)

    def generate_from_template(
        self,
        template_name: str,
        params: dict[str, Any],
        device_type: str = "",
        description: str = "",
        version: str = "0.1.0",
    ) -> CodePackage:
        """Generate code by filling a template with parameters.

        Parameters
        ----------
        template_name:
            Name of the template to use.
        params:
            Key-value pairs matching the template's ``required_params``.
        device_type:
            Target device type (overrides template default).
        description:
            Human-readable description stored in the package.
        version:
            Version string for the generated firmware.

        Returns a validated ``CodePackage``.
        """
        template = self._templates.get(template_name)
        if not template:
            return CodePackage(
                code="",
                platform="micropython",
                device_type=device_type,
                version=version,
                template_name=template_name,
                description=description,
                validation_passed=False,
                validation_errors=[f"Template not found: '{template_name}'"],
                created_at=_now(),
            )

        # Check required params
        missing = [p for p in template.required_params if p not in params]
        if missing:
            return CodePackage(
                code="",
                platform=template.platform,
                device_type=device_type or template.device_type,
                version=version,
                template_name=template_name,
                description=description,
                validation_passed=False,
                validation_errors=[
                    f"Missing required parameters: {', '.join(missing)}"
                ],
                created_at=_now(),
            )

        # Fill template
        fill_params = {**params}
        fill_params.setdefault("device_type", device_type or template.device_type)
        fill_params.setdefault("description", description)

        try:
            code = template.template.format(**fill_params)
        except KeyError as exc:
            return CodePackage(
                code="",
                platform=template.platform,
                device_type=device_type or template.device_type,
                version=version,
                template_name=template_name,
                description=description,
                validation_passed=False,
                validation_errors=[f"Template placeholder error: {exc}"],
                created_at=_now(),
            )

        # Validate
        passed, errors = self._validator.validate(code)

        return CodePackage(
            code=code,
            platform=template.platform,
            device_type=device_type or template.device_type,
            version=version,
            template_name=template_name,
            description=description,
            validation_passed=passed,
            validation_errors=errors,
            created_at=_now(),
        )

    def generate_from_code(
        self,
        code: str,
        device_type: str,
        version: str = "0.1.0",
        description: str = "",
    ) -> CodePackage:
        """Validate and package raw code (e.g. from LLM output).

        Parameters
        ----------
        code:
            Raw MicroPython source code.
        device_type:
            Target device type.
        version:
            Firmware version string.
        description:
            Human-readable description.

        Returns a validated ``CodePackage``.
        """
        passed, errors = self._validator.validate(code)

        return CodePackage(
            code=code,
            platform="micropython",
            device_type=device_type,
            version=version,
            template_name="",
            description=description,
            validation_passed=passed,
            validation_errors=errors,
            created_at=_now(),
        )

    def describe_templates(self) -> str:
        """Generate LLM-friendly Markdown describing available templates."""
        if not self._templates:
            return "No code templates available."

        lines = ["## Available Code Templates", ""]
        for t in sorted(self._templates.values(), key=lambda x: x.name):
            lines.append(f"### {t.name}")
            lines.append(f"- **Platform**: {t.platform}")
            lines.append(f"- **Description**: {t.description}")
            if t.device_type:
                lines.append(f"- **Device type**: {t.device_type}")
            if t.required_params:
                lines.append(
                    f"- **Required params**: {', '.join(t.required_params)}"
                )
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    """ISO timestamp string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

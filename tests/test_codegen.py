"""Tests for device code generation module (task 4.3).

Covers: CodeTemplate, CodePackage, CodeValidator (AST-based safety analysis),
CodeGenerator (template management, generation, validation), ReprogramTool
(all 5 actions, error handling).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.codegen import (
    ALLOWED_IMPORTS,
    BLOCKED_ATTRS,
    BLOCKED_CALLS,
    BLOCKED_IMPORTS,
    BUILTIN_TEMPLATES,
    MAX_CODE_SIZE,
    CodeGenerator,
    CodePackage,
    CodeTemplate,
    CodeValidator,
    _now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_MINIMAL_CODE = """\
import machine
import time

def setup():
    pass

def loop():
    time.sleep_ms(100)

if __name__ == "__main__":
    setup()
    while True:
        loop()
"""

VALID_MAIN_CODE = """\
import machine

def main():
    while True:
        pass
"""


# ---------------------------------------------------------------------------
# CodeTemplate
# ---------------------------------------------------------------------------

class TestCodeTemplate:
    def test_to_dict_roundtrip(self):
        t = CodeTemplate(
            platform="micropython",
            name="test_tpl",
            description="A test template",
            template="import machine\n{code_body}",
            required_params=["code_body"],
            device_type="sensor",
        )
        d = t.to_dict()
        restored = CodeTemplate.from_dict(d)
        assert restored.name == "test_tpl"
        assert restored.platform == "micropython"
        assert restored.required_params == ["code_body"]
        assert restored.device_type == "sensor"

    def test_from_dict_ignores_extra_keys(self):
        d = {
            "platform": "micropython",
            "name": "t1",
            "description": "x",
            "template": "",
            "extra_key": "should_be_ignored",
        }
        t = CodeTemplate.from_dict(d)
        assert t.name == "t1"
        assert not hasattr(t, "extra_key")

    def test_default_values(self):
        t = CodeTemplate(platform="micropython", name="x", description="y", template="z")
        assert t.required_params == []
        assert t.device_type == ""


# ---------------------------------------------------------------------------
# CodePackage
# ---------------------------------------------------------------------------

class TestCodePackage:
    def test_to_dict_roundtrip(self):
        pkg = CodePackage(
            code="# test",
            platform="micropython",
            device_type="actuator",
            version="1.0.0",
            template_name="tpl",
            description="desc",
            validation_passed=True,
            validation_errors=[],
            created_at="2026-01-01T00:00:00Z",
        )
        d = pkg.to_dict()
        restored = CodePackage.from_dict(d)
        assert restored.code == "# test"
        assert restored.validation_passed is True
        assert restored.version == "1.0.0"

    def test_defaults(self):
        pkg = CodePackage(code="x", platform="mp", device_type="d", version="0.1")
        assert pkg.template_name == ""
        assert pkg.description == ""
        assert pkg.validation_passed is False
        assert pkg.validation_errors == []
        assert pkg.created_at == ""


# ---------------------------------------------------------------------------
# CodeValidator — AST-based safety analysis
# ---------------------------------------------------------------------------

class TestCodeValidator:
    """Tests for the AST-based safety validator."""

    def setup_method(self):
        self.validator = CodeValidator()

    # -- Syntax checks --

    def test_valid_code_passes(self):
        passed, errors = self.validator.validate(VALID_MINIMAL_CODE)
        assert passed is True
        assert errors == []

    def test_valid_main_structure(self):
        passed, errors = self.validator.validate(VALID_MAIN_CODE)
        assert passed is True
        assert errors == []

    def test_syntax_error_rejected(self):
        passed, errors = self.validator.validate("def foo(\n")
        assert passed is False
        assert any("Syntax error" in e for e in errors)

    def test_empty_code_rejected(self):
        passed, errors = self.validator.validate("")
        assert passed is False
        assert any("empty" in e.lower() for e in errors)

    def test_whitespace_only_rejected(self):
        passed, errors = self.validator.validate("   \n  \n  ")
        assert passed is False
        assert any("empty" in e.lower() for e in errors)

    # -- Size limit --

    def test_oversized_code_rejected(self):
        code = "# " + "x" * (MAX_CODE_SIZE + 100)
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("size limit" in e.lower() for e in errors)

    def test_exactly_at_size_limit_ok(self):
        # Build valid code exactly at the limit
        header = "import machine\ndef setup():\n    pass\ndef loop():\n    pass\n"
        padding_len = MAX_CODE_SIZE - len(header) - 5  # allow for "# " + newlines
        code = header + "# " + "x" * max(0, padding_len) + "\n"
        # Just check it doesn't fail the size check (may fail structure check depending on size)
        v = CodeValidator(max_code_size=len(code), require_structure=False)
        passed, errors = v.validate(code)
        assert not any("size limit" in e.lower() for e in errors)

    # -- Import whitelist/blocklist --

    def test_allowed_import_passes(self):
        code = "import machine\nimport time\nimport json\ndef setup():\n    pass\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is True

    def test_blocked_import_rejected(self):
        for mod in ["subprocess", "shutil", "ctypes", "multiprocessing"]:
            code = f"import {mod}\ndef setup():\n    pass\ndef loop():\n    pass\n"
            passed, errors = self.validator.validate(code)
            assert passed is False, f"import {mod} should be blocked"
            assert any("Blocked import" in e for e in errors)

    def test_unknown_import_rejected(self):
        code = "import numpy\ndef setup():\n    pass\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Disallowed import" in e for e in errors)

    def test_from_import_checked(self):
        code = "from subprocess import run\ndef setup():\n    pass\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked import" in e for e in errors)

    def test_dotted_import_uses_top_level(self):
        code = "import umqtt.simple\ndef setup():\n    pass\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is True

    def test_from_dotted_import(self):
        code = "from umqtt.robust import MQTTClient\ndef setup():\n    pass\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is True

    # -- Blocked calls --

    def test_eval_blocked(self):
        code = "def setup():\n    eval('1+1')\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked call" in e and "eval" in e for e in errors)

    def test_exec_blocked(self):
        code = "def setup():\n    exec('pass')\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked call" in e and "exec" in e for e in errors)

    def test_compile_blocked(self):
        code = "def setup():\n    compile('', '', 'exec')\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked call" in e and "compile" in e for e in errors)

    def test_getattr_blocked(self):
        code = "import machine\ndef setup():\n    getattr(machine, 'Pin')\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked call" in e and "getattr" in e for e in errors)

    # -- Blocked attributes --

    def test_dunder_class_blocked(self):
        code = "def setup():\n    x = ''.__class__\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked attribute" in e for e in errors)

    def test_dunder_subclasses_blocked(self):
        code = "def setup():\n    x = object.__subclasses__\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked attribute" in e for e in errors)

    def test_dunder_globals_blocked(self):
        code = "def setup():\n    x = foo.__globals__\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("Blocked attribute" in e for e in errors)

    # -- Network server pattern detection --

    def test_bind_detected(self):
        code = "import usocket\ndef setup():\n    s = usocket.socket()\n    s.bind(('0.0.0.0', 80))\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("server pattern" in e.lower() for e in errors)

    def test_listen_detected(self):
        code = "import usocket\ndef setup():\n    s = usocket.socket()\n    s.listen(5)\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("server pattern" in e.lower() for e in errors)

    def test_accept_detected(self):
        code = "import usocket\ndef setup():\n    s = usocket.socket()\n    s.accept()\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("server pattern" in e.lower() for e in errors)

    # -- Structure checks --

    def test_no_functions_rejected(self):
        code = "import machine\nprint('hi')\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("structure" in e.lower() for e in errors)

    def test_only_setup_no_loop_rejected(self):
        code = "import machine\ndef setup():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("structure" in e.lower() for e in errors)

    def test_only_loop_no_setup_rejected(self):
        code = "import machine\ndef loop():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        assert any("structure" in e.lower() for e in errors)

    def test_main_function_accepted(self):
        code = "def main():\n    pass\n"
        passed, errors = self.validator.validate(code)
        assert passed is True

    def test_structure_check_disabled(self):
        v = CodeValidator(require_structure=False)
        code = "import machine\nprint('hello')\n"
        passed, errors = v.validate(code)
        assert passed is True

    # -- Custom configuration --

    def test_custom_allowed_imports(self):
        v = CodeValidator(
            allowed_imports=frozenset({"machine", "custom_lib"}),
            require_structure=False,
        )
        passed, _ = v.validate("import custom_lib\n")
        assert passed is True
        passed, _ = v.validate("import time\n")
        assert passed is False

    def test_custom_max_code_size(self):
        v = CodeValidator(max_code_size=50, require_structure=False)
        passed, errors = v.validate("x" * 60)
        assert passed is False
        assert any("size limit" in e.lower() for e in errors)

    # -- Multiple errors --

    def test_multiple_issues_all_reported(self):
        code = "import subprocess\nimport shutil\neval('bad')\n"
        passed, errors = self.validator.validate(code)
        assert passed is False
        # Should have at least: 2 blocked imports + 1 blocked call + 1 structure
        assert len(errors) >= 3


# ---------------------------------------------------------------------------
# CodeGenerator
# ---------------------------------------------------------------------------

class TestCodeGenerator:
    """Tests for template management and code generation."""

    def setup_method(self):
        self.gen = CodeGenerator()

    # -- Template management --

    def test_builtin_templates_loaded(self):
        templates = self.gen.list_templates()
        assert len(templates) == len(BUILTIN_TEMPLATES)
        names = {t.name for t in templates}
        assert "sensor_reader" in names
        assert "actuator_switch" in names
        assert "pwm_controller" in names
        assert "i2c_sensor" in names

    def test_filter_by_platform(self):
        templates = self.gen.list_templates(platform="micropython")
        assert len(templates) > 0
        for t in templates:
            assert t.platform == "micropython"

    def test_filter_nonexistent_platform(self):
        templates = self.gen.list_templates(platform="arduino")
        assert templates == []

    def test_get_template_by_name(self):
        t = self.gen.get_template("sensor_reader")
        assert t is not None
        assert t.name == "sensor_reader"

    def test_get_template_nonexistent(self):
        assert self.gen.get_template("nonexistent") is None

    def test_describe_templates_markdown(self):
        md = self.gen.describe_templates()
        assert "## Available Code Templates" in md
        assert "sensor_reader" in md
        assert "actuator_switch" in md
        assert "Required params" in md

    def test_describe_templates_empty(self):
        gen = CodeGenerator.__new__(CodeGenerator)
        gen._templates = {}
        gen._validator = CodeValidator()
        result = gen.describe_templates()
        assert "No code templates" in result

    # -- Template generation (sensor_reader) --

    def test_generate_sensor_reader(self):
        pkg = self.gen.generate_from_template(
            template_name="sensor_reader",
            params={"pin": 36, "sensor_type": "temperature", "read_interval_ms": 1000},
            device_type="sensor",
            description="Read temperature every second",
        )
        assert pkg.validation_passed is True
        assert pkg.template_name == "sensor_reader"
        assert "SENSOR_PIN = 36" in pkg.code
        assert 'SENSOR_TYPE = "temperature"' in pkg.code
        assert "READ_INTERVAL_MS = 1000" in pkg.code
        assert pkg.platform == "micropython"
        assert pkg.created_at  # not empty

    def test_generate_actuator_switch(self):
        pkg = self.gen.generate_from_template(
            template_name="actuator_switch",
            params={"pin": 5, "actuator_name": "relay1"},
            device_type="actuator",
        )
        assert pkg.validation_passed is True
        assert "OUTPUT_PIN = 5" in pkg.code
        assert 'ACTUATOR_NAME = "relay1"' in pkg.code

    def test_generate_pwm_controller(self):
        pkg = self.gen.generate_from_template(
            template_name="pwm_controller",
            params={"pin": 13, "frequency": 5000, "device_name": "fan"},
        )
        assert pkg.validation_passed is True
        assert "PWM_PIN = 13" in pkg.code
        assert "PWM_FREQ = 5000" in pkg.code

    def test_generate_i2c_sensor(self):
        pkg = self.gen.generate_from_template(
            template_name="i2c_sensor",
            params={
                "sda_pin": 21, "scl_pin": 22,
                "i2c_address": 0x76, "sensor_name": "bme280",
                "read_interval_ms": 2000,
            },
        )
        assert pkg.validation_passed is True
        assert "SDA_PIN = 21" in pkg.code
        assert "SCL_PIN = 22" in pkg.code

    # -- Error cases --

    def test_generate_missing_template(self):
        pkg = self.gen.generate_from_template(
            template_name="nonexistent",
            params={},
        )
        assert pkg.validation_passed is False
        assert "Template not found" in pkg.validation_errors[0]
        assert pkg.code == ""

    def test_generate_missing_required_params(self):
        pkg = self.gen.generate_from_template(
            template_name="sensor_reader",
            params={"pin": 36},  # missing sensor_type, read_interval_ms
        )
        assert pkg.validation_passed is False
        assert any("Missing required" in e for e in pkg.validation_errors)
        assert pkg.code == ""

    def test_generate_template_placeholder_error(self):
        # Add a template with an extra placeholder not in required_params
        self.gen._templates["broken"] = CodeTemplate(
            platform="micropython",
            name="broken",
            description="Broken template",
            template="value = {nonexistent_param}",
            required_params=[],
        )
        pkg = self.gen.generate_from_template(
            template_name="broken",
            params={},
        )
        assert pkg.validation_passed is False
        assert any("placeholder" in e.lower() for e in pkg.validation_errors)

    # -- generate_from_code --

    def test_generate_from_code_valid(self):
        pkg = self.gen.generate_from_code(
            code=VALID_MINIMAL_CODE,
            device_type="sensor",
            version="1.2.3",
            description="test code",
        )
        assert pkg.validation_passed is True
        assert pkg.code == VALID_MINIMAL_CODE
        assert pkg.device_type == "sensor"
        assert pkg.version == "1.2.3"
        assert pkg.template_name == ""

    def test_generate_from_code_invalid(self):
        pkg = self.gen.generate_from_code(
            code="import subprocess\nprint('hack')\n",
            device_type="sensor",
        )
        assert pkg.validation_passed is False
        assert len(pkg.validation_errors) > 0

    # -- Custom templates from disk --

    def test_load_custom_templates(self, tmp_path: Path):
        custom = [
            {
                "platform": "micropython",
                "name": "custom_sensor",
                "description": "Custom sensor template",
                "template": "import machine\ndef setup():\n    pass\ndef loop():\n    pass\n",
                "required_params": [],
            },
        ]
        tpl_file = tmp_path / "templates.json"
        tpl_file.write_text(json.dumps(custom))

        gen = CodeGenerator(templates_path=str(tpl_file))
        t = gen.get_template("custom_sensor")
        assert t is not None
        assert t.description == "Custom sensor template"
        # Builtins should still be present
        assert gen.get_template("sensor_reader") is not None

    def test_load_templates_file_missing(self, tmp_path: Path):
        gen = CodeGenerator(templates_path=str(tmp_path / "missing.json"))
        # Should still have builtins
        assert len(gen.list_templates()) == len(BUILTIN_TEMPLATES)

    def test_load_templates_invalid_json(self, tmp_path: Path):
        tpl_file = tmp_path / "bad.json"
        tpl_file.write_text("{not valid json")
        gen = CodeGenerator(templates_path=str(tpl_file))
        # Should still have builtins
        assert len(gen.list_templates()) == len(BUILTIN_TEMPLATES)

    def test_custom_template_overrides_builtin(self, tmp_path: Path):
        """Custom template with same name as builtin should override it."""
        custom = [
            {
                "platform": "micropython",
                "name": "sensor_reader",
                "description": "Overridden sensor reader",
                "template": "import machine\ndef setup():\n    pass\ndef loop():\n    pass\n",
                "required_params": [],
            },
        ]
        tpl_file = tmp_path / "templates.json"
        tpl_file.write_text(json.dumps(custom))

        gen = CodeGenerator(templates_path=str(tpl_file))
        t = gen.get_template("sensor_reader")
        assert t is not None
        assert t.description == "Overridden sensor reader"


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------

class TestConstants:
    def test_allowed_imports_contains_essentials(self):
        for mod in ["machine", "time", "json", "network", "gc"]:
            assert mod in ALLOWED_IMPORTS

    def test_blocked_imports_contains_dangerous(self):
        for mod in ["subprocess", "ctypes", "multiprocessing"]:
            assert mod in BLOCKED_IMPORTS

    def test_no_overlap_allowed_blocked(self):
        overlap = ALLOWED_IMPORTS & BLOCKED_IMPORTS
        assert overlap == set(), f"Overlap between allowed and blocked: {overlap}"

    def test_blocked_calls_contains_eval_exec(self):
        assert "eval" in BLOCKED_CALLS
        assert "exec" in BLOCKED_CALLS
        assert "compile" in BLOCKED_CALLS

    def test_blocked_attrs_contains_sandbox_escapes(self):
        assert "__class__" in BLOCKED_ATTRS
        assert "__subclasses__" in BLOCKED_ATTRS

    def test_max_code_size_reasonable(self):
        assert MAX_CODE_SIZE == 65_536

    def test_builtin_templates_nonempty(self):
        assert len(BUILTIN_TEMPLATES) >= 4


# ---------------------------------------------------------------------------
# _now helper
# ---------------------------------------------------------------------------

class TestNowHelper:
    def test_returns_iso_format(self):
        result = _now()
        assert result.endswith("Z")
        assert "T" in result


# ---------------------------------------------------------------------------
# ReprogramTool
# ---------------------------------------------------------------------------

class TestReprogramTool:
    """Tests for the agent tool wrapper around codegen."""

    def _make_tool(self) -> Any:
        from nanobot.agent.tools.reprogram import ReprogramTool

        gen = CodeGenerator()
        firmware_store = MagicMock()
        ota_manager = MagicMock()
        registry = MagicMock()
        transport = MagicMock()

        tool = ReprogramTool(
            generator=gen,
            firmware_store=firmware_store,
            ota_manager=ota_manager,
            registry=registry,
            transport=transport,
            node_id="hub-01",
        )
        return tool, firmware_store, ota_manager, registry

    # -- Properties --

    def test_name(self):
        tool, *_ = self._make_tool()
        assert tool.name == "device_reprogram"

    def test_description_nonempty(self):
        tool, *_ = self._make_tool()
        assert len(tool.description) > 20

    def test_parameters_schema(self):
        tool, *_ = self._make_tool()
        params = tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert "required" in params
        assert "action" in params["required"]

    # -- templates action --

    @pytest.mark.asyncio
    async def test_templates_action(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="templates")
        assert "sensor_reader" in result
        assert "actuator_switch" in result

    # -- generate action --

    @pytest.mark.asyncio
    async def test_generate_action(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(
            action="generate",
            template_name="sensor_reader",
            params={"pin": 36, "sensor_type": "temp", "read_interval_ms": 1000},
            device_type="sensor",
            description="Read temperature",
        )
        assert "PASSED" in result
        assert "SENSOR_PIN = 36" in result

    @pytest.mark.asyncio
    async def test_generate_missing_template_name(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="generate")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_generate_string_params_json_parsed(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(
            action="generate",
            template_name="actuator_switch",
            params='{"pin": 5, "actuator_name": "relay"}',
        )
        assert "PASSED" in result

    @pytest.mark.asyncio
    async def test_generate_invalid_json_params(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(
            action="generate",
            template_name="actuator_switch",
            params="{bad json}",
        )
        assert "Error" in result

    # -- validate action --

    @pytest.mark.asyncio
    async def test_validate_valid_code(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="validate", code=VALID_MINIMAL_CODE)
        assert "PASSED" in result

    @pytest.mark.asyncio
    async def test_validate_dangerous_code(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(
            action="validate",
            code="import subprocess\neval('rm -rf /')\n",
        )
        assert "FAILED" in result

    @pytest.mark.asyncio
    async def test_validate_missing_code(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="validate")
        assert "Error" in result

    # -- deploy action --

    @pytest.mark.asyncio
    async def test_deploy_missing_device(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="deploy", code=VALID_MINIMAL_CODE)
        assert "Error" in result
        assert "device" in result.lower()

    @pytest.mark.asyncio
    async def test_deploy_device_not_found(self):
        tool, _, _, registry = self._make_tool()
        registry.get_device.return_value = None
        result = await tool.execute(
            action="deploy", device="dev-99", code=VALID_MINIMAL_CODE,
        )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_deploy_device_offline(self):
        tool, _, _, registry = self._make_tool()
        dev = MagicMock()
        dev.online = False
        registry.get_device.return_value = dev
        result = await tool.execute(
            action="deploy", device="dev-01", code=VALID_MINIMAL_CODE,
        )
        assert "offline" in result.lower()

    @pytest.mark.asyncio
    async def test_deploy_unsafe_code_rejected(self):
        tool, _, _, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            code="import subprocess\neval('bad')\n",
        )
        assert "FAILED" in result

    @pytest.mark.asyncio
    async def test_deploy_no_code_no_template(self):
        tool, _, _, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        result = await tool.execute(action="deploy", device="dev-01")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_deploy_from_template_success(self):
        tool, firmware_store, ota_manager, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        session = MagicMock()
        session.session_id = "sess-001"
        ota_manager.start_update = AsyncMock(return_value=session)

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            template_name="sensor_reader",
            params={"pin": 36, "sensor_type": "temp", "read_interval_ms": 1000},
        )
        assert "deployed" in result.lower()
        firmware_store.add_firmware.assert_called_once()
        ota_manager.start_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_deploy_from_raw_code_success(self):
        tool, firmware_store, ota_manager, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        session = MagicMock()
        session.session_id = "sess-002"
        ota_manager.start_update = AsyncMock(return_value=session)

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            code=VALID_MINIMAL_CODE,
        )
        assert "deployed" in result.lower()
        firmware_store.add_firmware.assert_called_once()

    @pytest.mark.asyncio
    async def test_deploy_firmware_store_error(self):
        tool, firmware_store, _, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        firmware_store.add_firmware.side_effect = RuntimeError("disk full")

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            code=VALID_MINIMAL_CODE,
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_deploy_ota_start_error(self):
        tool, firmware_store, ota_manager, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        ota_manager.start_update = AsyncMock(side_effect=RuntimeError("timeout"))

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            code=VALID_MINIMAL_CODE,
        )
        assert "Error" in result

    # -- status action --

    @pytest.mark.asyncio
    async def test_status_no_device_shows_all(self):
        tool, _, ota_manager, _ = self._make_tool()
        ota_manager.get_all_sessions.return_value = []
        result = await tool.execute(action="status")
        assert "No active" in result

    @pytest.mark.asyncio
    async def test_status_with_active_sessions(self):
        tool, _, ota_manager, _ = self._make_tool()

        session = MagicMock()
        session.device_id = "dev-01"
        session.firmware_id = "fw-001"
        session.state = MagicMock()
        session.state.value = "transferring"
        ota_manager.get_all_sessions.return_value = [session]

        result = await tool.execute(action="status")
        assert "dev-01" in result
        assert "transferring" in result

    @pytest.mark.asyncio
    async def test_status_specific_device(self):
        tool, _, ota_manager, _ = self._make_tool()

        session = MagicMock()
        session.device_id = "dev-01"
        session.firmware_id = "fw-001"
        session.state = MagicMock()
        session.state.value = "complete"
        session.chunks_sent = 10
        session.total_chunks = 10
        session.progress_pct = 100.0
        ota_manager.get_session.return_value = session

        result = await tool.execute(action="status", device="dev-01")
        assert "complete" in result
        assert "100%" in result

    @pytest.mark.asyncio
    async def test_status_device_no_session(self):
        tool, _, ota_manager, _ = self._make_tool()
        ota_manager.get_session.return_value = None
        result = await tool.execute(action="status", device="dev-99")
        assert "No active OTA session" in result

    # -- unknown action --

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        tool, *_ = self._make_tool()
        result = await tool.execute(action="foobar")
        assert "Unknown action" in result

    # -- deploy with string params JSON --

    @pytest.mark.asyncio
    async def test_deploy_template_string_params(self):
        tool, firmware_store, ota_manager, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        session = MagicMock()
        session.session_id = "sess-003"
        ota_manager.start_update = AsyncMock(return_value=session)

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            template_name="actuator_switch",
            params='{"pin": 5, "actuator_name": "relay"}',
        )
        assert "deployed" in result.lower()

    @pytest.mark.asyncio
    async def test_deploy_invalid_json_params(self):
        tool, _, _, registry = self._make_tool()
        dev = MagicMock()
        dev.online = True
        dev.device_type = "sensor"
        registry.get_device.return_value = dev

        result = await tool.execute(
            action="deploy",
            device="dev-01",
            template_name="actuator_switch",
            params="{not valid}",
        )
        assert "Error" in result

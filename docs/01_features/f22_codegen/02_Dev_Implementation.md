# f22 Device Code Generation — Dev Implementation

**Task**: 4.3 Device reprogramming — AI code generation + OTA deploy
**Branch**: `copilot/device-codegen`
**Date**: 2026-02-27

## Summary

Implemented an AST-based code generation and safety validation system that
enables the LLM agent to generate MicroPython firmware from templates, validate
it against security constraints, and deploy it to devices via the existing OTA
infrastructure.

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/codegen.py` | ~700 | Core code generation: templates, validator, generator, packaging |
| `nanobot/agent/tools/reprogram.py` | ~346 | Agent tool with 5 actions: templates, generate, validate, deploy, status |
| `nanobot/skills/device-reprogram/SKILL.md` | ~40 | Always-active skill for LLM context |
| `tests/test_codegen.py` | ~550 | 78 tests covering validator, generator, tool |

## Files Modified

| File | Change |
|------|--------|
| `nanobot/cli/commands.py` | Appended ReprogramTool registration in `gateway()` mesh block |
| `nanobot/config/schema.py` | Appended `codegen_templates_path` field to MeshConfig |

## Architecture

```
User NL description
        │
        ▼
  ReprogramTool (agent tool)
        │
        ├─ "templates" → CodeGenerator.describe_templates()
        ├─ "generate"  → CodeGenerator.generate_from_template()
        ├─ "validate"  → CodeGenerator.generate_from_code()
        ├─ "deploy"    → CodeGenerator → FirmwareStore → OTAManager
        └─ "status"    → OTAManager.get_session()
```

### CodeValidator Safety Model

Seven-point AST-based analysis:

1. **Source size** — max 64 KB
2. **Empty check** — reject blank input
3. **Syntax** — `ast.parse()` must succeed
4. **Import whitelist** — only MicroPython-safe modules (30+ allowed)
5. **Blocked calls** — `eval`, `exec`, `compile`, `__import__`, etc.
6. **Blocked attributes** — `__class__`, `__subclasses__`, `__globals__`, etc.
7. **Network server detection** — `bind`, `listen`, `accept` patterns blocked
8. **Structure check** — requires `setup()+loop()` or `main()` at module level

### Built-in Templates

| Template | Device Type | Params |
|----------|------------|--------|
| `sensor_reader` | sensor | pin, sensor_type, read_interval_ms |
| `actuator_switch` | actuator | pin, actuator_name |
| `pwm_controller` | actuator | pin, frequency, device_name |
| `i2c_sensor` | sensor | sda_pin, scl_pin, i2c_address, sensor_name, read_interval_ms |

Custom templates can be loaded from a JSON file via `codegen_templates_path` config.

## Key Design Decisions

1. **AST-based validation** (not regex): More robust, catches obfuscation attempts,
   handles nested scopes correctly.

2. **Whitelist-first for imports**: Only known-safe MicroPython modules are allowed.
   Unknown modules are rejected by default, which is safer for IoT devices.

3. **Template + raw code paths**: Templates provide structured generation for common
   patterns; raw code path allows LLM creativity with safety validation.

4. **No compilation step**: MicroPython runs source directly, so we validate and
   push `.py` files via OTA. No cross-compiler needed.

5. **Conditional registration**: ReprogramTool only registers when mesh + OTA are
   both enabled, preventing tool availability without infrastructure.

## Deviations from Design

None — implementation follows the Phase 1 design log.

## Documentation Freshness Check
- architecture.md: OK — codegen uses existing mesh transport, no new module directory
- configuration.md: Updated — `codegen_templates_path` field documented below
- customization.md: OK — follows existing Tool base class pattern
- PRD.md: OK — will be updated in Phase 3
- agent.md: OK — no upstream convention changes

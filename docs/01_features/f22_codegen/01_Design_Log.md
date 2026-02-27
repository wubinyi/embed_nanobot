# Design Log — f22: Device Reprogramming (AI Code Generation + OTA Deploy)

**Task**: 4.3 — Device reprogramming (AI-generated code push)
**Date**: 2026-02-27
**Status**: Design Phase

---

## Architect/Reviewer Debate

### [Architect] Proposal

Device reprogramming = LLM generates embedded code from natural language → validates for safety → packages as firmware → deploys via existing OTA infrastructure.

**Target platform**: MicroPython on ESP32 (most practical for AI-generated code — interpreted, no cross-compilation needed).

**Pipeline**:
```
User NL description
  → LLM generates MicroPython code (with platform templates)
    → Safety validator (pattern blocklist + structure check)
      → Code packager (bundles as .py firmware)
        → FirmwareStore.add_firmware()
          → OTAManager.start_update()
```

### [Reviewer] Challenges

1. **Security**: Generated code runs on physical devices. What prevents `import os; os.system("rm -rf /")`?
   - **Mitigation**: Extensive blocklist of dangerous patterns (os.system, subprocess, socket bind, file I/O outside sandbox). AST-level validation, not just regex.

2. **Quality**: LLM-generated code may have bugs. What about runtime errors on the device?
   - **Mitigation**: Required structure enforcement (setup/loop pattern), type checking where possible, dry-run validation. The device should have a watchdog that reverts to previous firmware on crash.

3. **Scope creep**: XL task could grow unboundedly. Where do we stop?
   - **Mitigation**: Scope to MicroPython only. No C++ cross-compilation (that's a separate epic). Focus on the generation + validation + deploy pipeline.

4. **Rollback**: What if deployed code bricks a device?
   - **Mitigation**: OTA already supports firmware versioning. We add rollback tracking to CodePackage.

### Consensus

- Scope: MicroPython-only code generation with safety validation and OTA deployment
- Safety first: AST-based validation with comprehensive blocklist
- Integration: Reuse FirmwareStore/OTAManager for deployment
- Agent tool: ReprogramTool with generate/validate/deploy/rollback actions
- Always-active skill: device-reprogram skill with prompt templates

---

## Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/codegen.py` | Core code generation module (~400 LOC): CodeTemplate, CodeValidator, CodeGenerator, CodePackage |
| `nanobot/agent/tools/reprogram.py` | Agent tool (~180 LOC): ReprogramTool with generate/validate/deploy/rollback actions |
| `nanobot/skills/device-reprogram/SKILL.md` | Always-active skill with code generation prompts |
| `tests/test_codegen.py` | Tests for codegen module |
| `docs/01_features/f22_codegen/01_Design_Log.md` | This file |
| `docs/01_features/f22_codegen/02_Dev_Implementation.md` | Implementation notes |
| `docs/01_features/f22_codegen/03_Test_Report.md` | Test report |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/cli/commands.py` | Register ReprogramTool when mesh+OTA enabled (append-only) |
| `nanobot/config/schema.py` | Add `codegen_templates_path` to MeshConfig (1 field) |

### Dependencies

- Existing: FirmwareStore, OTAManager (from ota.py), DeviceRegistry (from registry.py)
- No new external dependencies (ast module is stdlib)

### Upstream Impact

- Zero impact — all new code in separate files
- 2 shared-file modifications (commands.py, schema.py) — append-only convention
- Conflict surface increase: minimal (+1 field in schema.py, +5 lines in commands.py)

### Data Model

```python
@dataclass
class CodeTemplate:
    """Platform-specific code template."""
    platform: str          # "micropython", "arduino"
    name: str              # Template name (e.g. "sensor_reader", "actuator")
    description: str       # Human-readable description
    template: str          # Template code with {placeholders}
    required_params: list  # Parameters the template expects

@dataclass
class CodePackage:
    """Bundled code ready for OTA deployment."""
    code: str              # Generated code
    platform: str          # Target platform
    device_type: str       # Target device type
    version: str           # Version string
    validation_passed: bool
    validation_errors: list[str]

class CodeValidator:
    """AST-based safety validator for generated code."""
    BLOCKED_IMPORTS: set     # os, subprocess, socket (server), etc.
    BLOCKED_CALLS: set       # eval, exec, compile, __import__
    BLOCKED_ATTRS: set       # __class__, __subclasses__
    MAX_CODE_SIZE: int       # 64KB default
    
    def validate(code: str) -> tuple[bool, list[str]]

class CodeGenerator:
    """Generates device code from templates + LLM."""
    def generate(description: str, device_type: str, ...) -> CodePackage
    def list_templates() -> list[CodeTemplate]
```

### Safety Rules (CodeValidator)

1. **Blocked imports**: os, subprocess, sys, socket (as server), shutil, pathlib write ops
2. **Blocked builtins**: eval(), exec(), compile(), __import__(), globals(), locals()
3. **Blocked attributes**: __class__, __subclasses__, __bases__, __mro__
4. **Required structure**: Must have `setup()` and `loop()` functions (or `main()`)
5. **Size limit**: Max 64KB source code
6. **Network restriction**: Can import `urequests` (client), `usocket` (client-only patterns), but not bind/listen
7. **Allowed imports whitelist**: machine, time, ujson, ubinascii, network (WiFi client), umqtt, urequests

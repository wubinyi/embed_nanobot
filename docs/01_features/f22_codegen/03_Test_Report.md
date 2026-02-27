# f22 Device Code Generation — Test Report

**Task**: 4.3 Device reprogramming — AI code generation + OTA deploy
**Date**: 2026-02-27
**Test file**: `tests/test_codegen.py`
**Result**: 78/78 passed

## Test Coverage

### CodeTemplate (3 tests)
| Test | Description | Result |
|------|-------------|--------|
| `test_to_dict_roundtrip` | Serialize → deserialize preserves all fields | ✅ |
| `test_from_dict_ignores_extra_keys` | Unknown keys silently dropped | ✅ |
| `test_default_values` | Empty required_params and device_type defaults | ✅ |

### CodePackage (2 tests)
| Test | Description | Result |
|------|-------------|--------|
| `test_to_dict_roundtrip` | Full roundtrip serialization | ✅ |
| `test_defaults` | Default validation_passed=False, empty errors | ✅ |

### CodeValidator (23 tests)
| Category | Tests | Description |
|----------|-------|-------------|
| Syntax | 5 | Valid code, syntax error, empty, whitespace, main structure |
| Size | 2 | Oversized rejected, at-limit accepted |
| Imports | 5 | Allowed, blocked (4 modules), unknown, from-import, dotted |
| Calls | 4 | eval, exec, compile, getattr blocked |
| Attributes | 3 | __class__, __subclasses__, __globals__ blocked |
| Network | 3 | bind, listen, accept server patterns detected |
| Structure | 4 | No funcs, only setup, only loop, main ok |
| Config | 2 | Custom allowed imports, custom max size |
| Multiple | 1 | Multiple errors all reported in single pass |

### CodeGenerator (16 tests)
| Category | Tests | Description |
|----------|-------|-------------|
| Templates | 5 | Builtins loaded, filter by platform, get by name, nonexistent |
| Describe | 2 | Markdown output, empty templates |
| Generate | 4 | All 4 builtin templates (sensor, actuator, PWM, I2C) |
| Errors | 3 | Missing template, missing params, placeholder error |
| From code | 2 | Valid code packaging, invalid code rejection |
| Disk load | 4 | Custom file, missing file, invalid JSON, override builtin |

### Constants (7 tests)
| Test | Description | Result |
|------|-------------|--------|
| Essentials in allowed | machine, time, json, network, gc | ✅ |
| Dangerous in blocked | subprocess, ctypes, multiprocessing | ✅ |
| No overlap | allowed ∩ blocked = ∅ | ✅ |
| Eval/exec in calls | Core dangerous calls present | ✅ |
| Sandbox attrs | __class__, __subclasses__ present | ✅ |
| Max size | 65536 bytes | ✅ |
| Builtins count | ≥ 4 templates | ✅ |

### ReprogramTool (22 tests)
| Category | Tests | Description |
|----------|-------|-------------|
| Properties | 3 | name, description, parameters schema |
| Templates | 1 | Lists all available templates |
| Generate | 4 | Success, missing name, JSON string params, invalid JSON |
| Validate | 3 | Valid code, dangerous code, missing code |
| Deploy | 10 | Missing device, not found, offline, unsafe code, no code/template, template success, raw code success, store error, OTA error, string params JSON, invalid JSON |
| Status | 4 | No sessions, active sessions, specific device, no session for device |
| Unknown | 1 | Unknown action error message |

## Edge Cases Covered

- Empty/whitespace code → rejected
- Oversized code → rejected with size info
- Blocked imports from multiple modules simultaneously
- Sandbox escape patterns (__class__, __subclasses__)
- Network server patterns (bind/listen/accept)
- Template placeholder mismatches
- JSON string-to-dict params coercion in tool
- Invalid JSON params
- Device offline/not-found during deploy
- FirmwareStore write errors
- OTAManager start errors
- Multiple validation errors reported together

## Known Gaps

- No end-to-end integration test (would require real mesh transport)
- No fuzz testing of validator with adversarial inputs
- No performance test for large template sets
- Cross-compilation (C++/Arduino) not yet supported (MicroPython only)

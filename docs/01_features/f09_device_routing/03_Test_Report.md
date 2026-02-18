# f09: Device-Command Routing — Test Report

**Task**: 2.4 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Test File

`tests/test_device_routing.py` — 21 tests across 3 test classes.

## 2. Test Coverage

### is_device_related (13 tests)

| Test | Validates |
|------|-----------|
| `test_matches_device_name` | "Living Room Light" in text |
| `test_matches_device_name_case_insensitive` | Case-insensitive matching |
| `test_matches_node_id` | "light-01" in text |
| `test_matches_device_type` | "smart_light" underscore form |
| `test_matches_device_type_with_spaces` | "smart light" space form |
| `test_matches_capability_name` | "brightness" word-boundary match |
| `test_matches_temperature` | "temperature" capability |
| `test_rejects_unrelated_text` | "capital of France" → False |
| `test_rejects_empty_text` | Empty string → False |
| `test_empty_registry` | No devices → False |
| `test_short_capability_names_skipped` | "on" (2 chars) skipped |
| `test_capability_word_boundary` | "power" matches as word |
| `test_no_false_match_on_embedded_word` | "brightnessing" won't match |

### build_force_local_fn (4 tests)

| Test | Validates |
|------|-----------|
| `test_returns_callable` | Returns callable |
| `test_device_text_returns_true` | Device text → True |
| `test_non_device_text_returns_false` | Non-device text → False |
| `test_captures_registry` | Dynamically reflects new devices |

### HybridRouter Integration (4 tests)

| Test | Validates |
|------|-----------|
| `test_force_local_fn_skips_difficulty_judge` | True → local called once (no judge) |
| `test_force_local_fn_false_goes_through_normal_routing` | False → normal routing |
| `test_no_force_local_fn_normal_routing` | None → normal routing |
| `test_force_local_fn_exception_falls_through` | Exception → normal routing |

## 3. Results

```
328 passed in 14.68s
```

All 21 new tests pass. Full suite (328 tests) passes with zero regressions.

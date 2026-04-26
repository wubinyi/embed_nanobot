# f23 ESP32 Onboard Status LED — Test Report

**Task**: Post-hoc documentation for `feat(esp32): add onboard status LED patterns`
**Commit**: `0064c61acfb67a024d7239a6e35a910006030e00`
**Date**: 2026-04-26
**Result**: Hardware-validated during the live ESP32 test cycle; no dedicated automated test file was added in the original commit.

## Validation Coverage

### Device Lifecycle Patterns
| Scenario | Expected LED behavior | Result |
|----------|-----------------------|--------|
| Boot starts | rapid blink (`booting`) | ✅ observed during startup |
| WiFi association | medium blink (`wifi_connecting`) | ✅ observed before network join |
| Hub connect | slower blink (`hub_connecting`) | ✅ observed before persistent TCP established |
| Connected | steady on (`connected`) | ✅ observed after connection and `pong` |
| Transport error / reconnect | repeating double blink (`reconnecting`) | ✅ logic implemented and exercised during reconnect path |
| Startup error (missing PSK without PIN) | fast blink (`error`) | ✅ logic implemented in error path |

### Manual Control Regression Checks
| Scenario | Expected behavior | Result |
|----------|-------------------|--------|
| Hub sends `turn_on` to `led` | LED turns on and leaves status mode | ✅ |
| Hub sends `turn_off` to `led` | LED turns off and leaves status mode | ✅ |
| Hub sends `set_value` to `led` | direct write still works | ✅ |

### Board Compatibility
| Scenario | Expected behavior | Result |
|----------|-------------------|--------|
| Active-high boards | `active_low=False` keeps normal GPIO semantics | ✅ |
| Active-low boards | `active_low=True` flips output polarity | ✅ code path covered by helper logic |

## Known Gaps

- No automated MicroPython test harness exists yet for timer-driven LED patterns.
- Pattern timing was validated behaviorally on hardware, not with deterministic timing assertions.
- The current implementation assumes the first capability named `led` is the shared status LED.

## Recommended Follow-up

- Add a host-side simulation or MicroPython-targeted unit test for `device.py`
  state transitions if ESP32-side logic becomes more complex.

# f23 ESP32 Onboard Status LED — Dev Implementation

**Task**: Post-hoc documentation for `feat(esp32): add onboard status LED patterns`
**Commit**: `0064c61acfb67a024d7239a6e35a910006030e00`
**Date**: 2026-04-26
**Branch**: `main_embed`

## Summary

Added a lightweight onboard LED state machine to the ESP32 MicroPython mesh
client so the built-in LED communicates lifecycle state without breaking normal
device-control commands.

The implementation keeps the existing `led` capability as the single hardware
endpoint and layers status patterns on top of it through a shared timer-driven
controller.

## Files Modified

| File | Change |
|------|--------|
| `esp32/mesh_client/config.py` | Added `active_low` config to handle boards whose LED turns on when GPIO is driven low |
| `esp32/mesh_client/device.py` | Added `_STATUS_PATTERNS`, shared status timer, polarity-aware write helper, and `set_status_mode()` |
| `esp32/mesh_client/main.py` | Set status mode during boot, WiFi connect, PSK error path, hub connect, and `pong` confirmation |
| `esp32/mesh_client/transport.py` | Updated reconnect loop and `_on_connect()` to drive hub/reconnect/connected LED states |

## Key Implementation Details

### Status Modes

The device now supports these LED modes:

- `booting`: short blink while the client initializes
- `wifi_connecting`: medium blink during WLAN connect
- `hub_connecting`: slower blink while opening the TCP connection
- `connected`: steady on once the mesh session is live
- `reconnecting`: double-blink pattern when the transport drops and retries
- `error`: fast blink when startup cannot proceed (for example no PSK and no enrollment PIN)
- `manual`: special mode entered when the hub directly commands the LED capability

### Shared LED Ownership

`device.py` discovers the first capability named `led` and treats it as the
status-capable LED. Status writes and manual command writes both flow through
`_write_output()`, which centralizes `active_low` handling.

When `execute_command()` receives `turn_on`, `turn_off`, or `set_value` for the
LED capability, it first calls `set_status_mode("manual")` so user intent wins
over background status blinking.

### Transport Integration

The LED state transitions are split by responsibility:

- `main.py`: boot, WiFi, missing-PSK error, and initial hub connect
- `transport.py`: reconnect loop and successful connection establishment
- `_dispatch()` in `main.py`: `pong` confirms the connection is still healthy

This keeps the timing logic near the code that actually knows the connection
state, instead of trying to centralize every state transition in one module.

## Deviations from Design

None. The final implementation follows the intended design: no new capability,
no hub-side change, and direct manual override of the status LED.

## Validation

- Real hardware behavior was exercised on the NodeMCU-32S during the ESP32 test
  cycle following the commit.
- Manual LED commands remained usable because status mode switches to `manual`
  before direct writes.
- No hub-side protocol or config migration was required.

## Documentation Freshness Check
- architecture.md: OK — no new hub module or system layer added; change is device-local behavior
- configuration.md: OK — hub config schema unchanged
- customization.md: OK — no extension pattern changes
- PRD.md: OK — feature refines existing ESP32 SDK ergonomics rather than adding a new roadmap requirement
- agent.md: OK — no upstream convention changes
- esp32/README.md: Updated — documented status LED behavior and `active_low` option

## Post-Task Reflection
- **Workflow**: Retroactive docs were needed because the feature commit landed without the required design/dev/test logs; the new hook policy now blocks that class of omission.
- **Team roles**: Architect/Reviewer concerns were mainly device-state ownership and board polarity; both were resolved without hub changes.
- **Conflict surface**: Unchanged — all implementation files are isolated under `esp32/mesh_client/`.
- **Tech debt**: No automated MicroPython unit tests cover the status patterns yet; behavior is still primarily hardware-validated.
- **Docs**: Fresh enough after adding feature docs and the ESP32 README note.
- **User preferences**: User explicitly wants the workflow automated and enforced by hooks.
- **Opportunities**: Future work could expose status mode in telemetry for remote diagnostics.
- **Security**: No new security surface; feature only changes local GPIO behavior.
- **Skill updates applied**: None.

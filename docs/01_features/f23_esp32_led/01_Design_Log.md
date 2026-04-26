# Design Log — f23: ESP32 Onboard Status LED Patterns

**Task**: Post-hoc documentation for `feat(esp32): add onboard status LED patterns`
**Commit**: `0064c61acfb67a024d7239a6e35a910006030e00`
**Date**: 2026-04-26
**Status**: Implemented before docs; this log reconstructs the final design.

---

## Architect/Reviewer Debate

### [Architect] Proposal

Reuse the existing onboard LED capability as a device lifecycle indicator so an
ESP32 can show useful local state without adding new hardware.

Target states:

- `booting`
- `wifi_connecting`
- `hub_connecting`
- `connected`
- `reconnecting`
- `error`
- `manual`

The LED should automatically reflect startup and reconnect state, but explicit
hub commands such as "turn on the LED" must still work.

### [Reviewer] Challenges

1. **Shared hardware ownership**: If the LED is both a capability and a status
   indicator, how do we prevent status blinking from fighting user commands?
   - **Resolution**: Introduce a `manual` mode. When the hub directly controls
     the LED capability, the status timer is stopped and the capability value is
     written directly.

2. **Board polarity differences**: Some ESP32 dev boards wire the onboard LED
   as active-low rather than active-high.
   - **Resolution**: Add `active_low` to the LED capability config and route all
     writes through a polarity-aware helper.

3. **MicroPython constraints**: Keep the implementation compatible with the
   existing MicroPython environment and avoid extra dependencies.
   - **Resolution**: Use `machine.Timer` with a small pattern table and avoid
     new modules beyond what already ships on the device.

4. **Connection-state handoff**: Which module should own each state change?
   - **Resolution**: `main.py` sets early boot/WiFi/PSK error states; the
     transport layer sets hub connection and reconnect states; receipt of `pong`
     reconfirms `connected`.

### Consensus

- The LED remains the user-visible `led` capability.
- Status indication is best-effort and yields immediately to manual control.
- `active_low` is the minimal config extension needed for hardware portability.
- The feature stays device-side only; no hub protocol changes are required.

---

## Implementation Plan

### Modified Files

| File | Change |
|------|--------|
| `esp32/mesh_client/config.py` | Added `active_low` to LED capability config |
| `esp32/mesh_client/device.py` | Added shared status LED state machine, pattern timer, polarity-aware writes, manual override |
| `esp32/mesh_client/main.py` | Set boot/WiFi/hub/error/connected states during lifecycle transitions |
| `esp32/mesh_client/transport.py` | Set `hub_connecting`, `reconnecting`, and `connected` from transport events |

### Data Flow

```text
boot.py/main.run()
  -> set_status_mode("booting")
  -> set_status_mode("wifi_connecting")
  -> connect_wifi()
  -> set_status_mode("hub_connecting")
  -> MeshTransport.start()
      -> _on_connect() => set_status_mode("connected")
      -> reconnect loop => set_status_mode("reconnecting")
      -> pong => set_status_mode("connected")

Hub LED command
  -> execute_command("led", ...)
  -> set_status_mode("manual")
  -> direct GPIO write
```

### Upstream Impact

- No upstream-shared files changed.
- Conflict surface unchanged because all edits are in `esp32/mesh_client/`.

### Test Plan

- Manual hardware validation on NodeMCU-32S:
  - boot blink visible during startup
  - slower blink during WiFi and hub connect
  - steady on after persistent connection established
  - reconnect blink on transport error
  - explicit LED commands still force manual state

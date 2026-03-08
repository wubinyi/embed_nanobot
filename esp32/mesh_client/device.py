"""device.py — Hardware abstraction layer for ESP32 peripherals.

Reads cfg.CAPABILITIES and maps each capability to the actual GPIO pin
declared there.  The hub sends "command" messages with payload:
  { "action": "turn_on" | "turn_off" | "set_value",
    "capability": "led",
    "value": ... }

Extend this file to support new hardware (relay boards, sensors, servos…).
"""

import machine
import config as cfg

# Map capability name → MicroPython Pin object (for switch/dimmer types)
_pins: dict = {}

# Map capability name → current value
_state: dict = {}


def _init_hardware() -> None:
    """Initialize GPIO for every declared capability."""
    for cap in cfg.CAPABILITIES:
        name = cap["name"]
        pin  = cap.get("gpio_pin")
        _state[name] = cap.get("current_value", None)

        if cap["type"] in ("switch", "dimmer") and pin is not None:
            _pins[name] = machine.Pin(pin, machine.Pin.OUT)
            # Set pin to reflect initial state
            _pins[name].value(1 if _state[name] else 0)


_init_hardware()


# ------------------------------------------------------------------
# Public API — called by main.py dispatch
# ------------------------------------------------------------------

def get_state_report_payload() -> dict:
    """Build the payload for a STATE_REPORT message."""
    caps = []
    for cap in cfg.CAPABILITIES:
        c = dict(cap)
        c["current_value"] = _state.get(cap["name"], c.get("current_value"))
        c.pop("gpio_pin", None)   # don't send internal implementation details
        caps.append(c)
    return {
        "capabilities":     caps,
        "firmware_version": cfg.FIRMWARE_VERSION,
    }


def execute_command(capability: str, action: str, value=None) -> dict:
    """Execute a command from the hub and return a result dict.

    Returns {"status": "ok"} or {"status": "error", "detail": str}.
    """
    cap_cfg = next((c for c in cfg.CAPABILITIES if c["name"] == capability), None)
    if cap_cfg is None:
        return {"status": "error", "detail": "unknown capability: " + capability}

    cap_type = cap_cfg["type"]

    # ------ switch: turn_on / turn_off ------
    if cap_type == "switch":
        if action == "turn_on":
            if capability in _pins:
                _pins[capability].value(1)
            _state[capability] = True
            return {"status": "ok"}
        elif action == "turn_off":
            if capability in _pins:
                _pins[capability].value(0)
            _state[capability] = False
            return {"status": "ok"}

    # ------ sensor: read current value ------
    if cap_type == "sensor" and action == "read":
        v = _read_sensor(capability, cap_cfg)
        _state[capability] = v
        return {"status": "ok", "value": v}

    # ------ set_value (generic) ------
    if action == "set_value" and value is not None:
        _state[capability] = value
        if capability in _pins:
            _pins[capability].value(1 if value else 0)
        return {"status": "ok"}

    return {"status": "error", "detail": "unhandled action '{}' for type '{}'".format(action, cap_type)}


def _read_sensor(name: str, cap_cfg: dict):
    """Read a sensor value.  Extend this for real sensor libraries."""
    # DS18B20 one-wire temperature (requires onewire + ds18x20 libraries)
    pin_num = cap_cfg.get("gpio_pin")
    if pin_num is not None:
        try:
            import onewire
            import ds18x20
            ow  = onewire.OneWire(machine.Pin(pin_num))
            ds  = ds18x20.DS18X20(ow)
            roms = ds.scan()
            if roms:
                ds.convert_temp()
                import time; time.sleep_ms(750)
                return ds.read_temp(roms[0])
        except ImportError:
            pass
    # Fallback: return the last known state
    return _state.get(name, 0.0)

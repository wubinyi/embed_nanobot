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
_pins = {}

# Map capability name → current value
_state = {}

# Shared status LED state (reuses the existing onboard LED capability if present)
_status_capability = None
_status_timer = None
_status_mode = "off"
_status_step = 0

_STATUS_PATTERNS = {
    "off": [(False, 0)],
    "booting": [(True, 120), (False, 120)],
    "wifi_connecting": [(True, 200), (False, 200)],
    "hub_connecting": [(True, 350), (False, 350)],
    "connected": [(True, 0)],
    "reconnecting": [(True, 80), (False, 80), (True, 80), (False, 500)],
    "error": [(True, 50), (False, 50)],
    "manual": [(False, 0)],
}


def _capability_cfg(name):
    for cap in cfg.CAPABILITIES:
        if cap["name"] == name:
            return cap
    return None


def _logical_to_pin_value(cap_cfg, enabled):
    active_low = bool(cap_cfg.get("active_low", False))
    if active_low:
        return 0 if enabled else 1
    return 1 if enabled else 0


def _write_output(name, enabled):
    pin = _pins.get(name)
    cap_cfg = _capability_cfg(name)
    if pin is None or cap_cfg is None:
        return
    pin.value(_logical_to_pin_value(cap_cfg, enabled))


def _status_timer_stop():
    global _status_timer
    if _status_timer is not None:
        try:
            _status_timer.deinit()
        except Exception:
            pass


def _status_apply_current_step():
    if _status_capability is None:
        return

    pattern = _STATUS_PATTERNS.get(_status_mode, _STATUS_PATTERNS["off"])
    enabled, duration_ms = pattern[_status_step]
    _write_output(_status_capability, enabled)

    if duration_ms <= 0 or len(pattern) == 1:
        _status_timer_stop()
        return

    if _status_timer is None:
        return

    _status_timer.init(
        period=duration_ms,
        mode=machine.Timer.ONE_SHOT,
        callback=_status_tick,
    )


def _status_tick(_timer):
    global _status_step
    pattern = _STATUS_PATTERNS.get(_status_mode, _STATUS_PATTERNS["off"])
    if len(pattern) <= 1:
        return
    _status_step = (_status_step + 1) % len(pattern)
    _status_apply_current_step()


def _init_hardware() -> None:
    """Initialize GPIO for every declared capability."""
    global _status_capability, _status_timer

    for cap in cfg.CAPABILITIES:
        name = cap["name"]
        pin  = cap.get("gpio_pin")
        _state[name] = cap.get("current_value", None)

        if cap["type"] in ("switch", "dimmer") and pin is not None:
            _pins[name] = machine.Pin(pin, machine.Pin.OUT)
            _write_output(name, bool(_state[name]))

            if _status_capability is None and name == "led":
                _status_capability = name

    if _status_capability is not None:
        try:
            _status_timer = machine.Timer(-1)
        except Exception:
            _status_timer = None


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
        "state": {
            "capabilities":     caps,
            "firmware_version": cfg.FIRMWARE_VERSION,
        },
    }


def set_status_mode(mode):
    """Drive the onboard LED with a status pattern, if available."""
    global _status_mode, _status_step
    if _status_capability is None:
        return
    if mode not in _STATUS_PATTERNS:
        mode = "error"
    _status_mode = mode
    _status_step = 0
    _status_timer_stop()
    _status_apply_current_step()


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
            if capability == _status_capability:
                set_status_mode("manual")
            _write_output(capability, True)
            _state[capability] = True
            return {"status": "ok"}
        elif action == "turn_off":
            if capability == _status_capability:
                set_status_mode("manual")
            _write_output(capability, False)
            _state[capability] = False
            return {"status": "ok"}

    # ------ sensor: read current value ------
    if cap_type == "sensor" and action == "read":
        v = _read_sensor(capability, cap_cfg)
        _state[capability] = v
        return {"status": "ok", "value": v}

    # ------ set_value (generic) ------
    if action == "set_value" and value is not None:
        if capability == _status_capability:
            set_status_mode("manual")
        _state[capability] = value
        _write_output(capability, bool(value))
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

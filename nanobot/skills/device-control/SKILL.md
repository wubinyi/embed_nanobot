---
name: device-control
description: Control IoT devices on the LAN mesh — translate natural language to device commands.
always: true
metadata: {"nanobot":{"emoji":"🏠"}}
---

# Device Control

You can control IoT devices connected to the local mesh network using the `device_control` tool.

## Quick Reference

| Action | Tool call |
|--------|-----------|
| List all devices | `device_control(action="list")` |
| Turn on a light | `device_control(action="command", device="light-01", command_action="set", capability="power", value=true)` |
| Set brightness | `device_control(action="command", device="light-01", command_action="set", capability="brightness", value=80)` |
| Read temperature | `device_control(action="command", device="sensor-01", command_action="get", capability="temperature")` |
| Toggle power | `device_control(action="command", device="light-01", command_action="toggle", capability="power")` |
| Check device state | `device_control(action="state", device="light-01")` |
| Full capabilities | `device_control(action="describe")` |

## How to Handle Device Requests

When a user asks you to control a device:

1. **Identify the device**: Match the user's description (e.g., "living room light") to a registered device. If unsure, call `device_control(action="list")` first.
2. **Determine the action**: Map the request to set/get/toggle/execute:
   - "turn on/off" → `set` with `value=true/false` on a `power` capability
   - "set ... to ..." → `set` with the value
   - "what is the ..." → `get` on the relevant capability
   - "toggle the ..." → `toggle` on a boolean capability
3. **Send the command**: Call `device_control(action="command", ...)`.
4. **Report the result**: Tell the user what happened.

## Command Actions

- **set**: Set a capability value (actuators and properties only, not sensors)
- **get**: Query current value of any capability
- **toggle**: Flip a boolean capability (power, enabled, etc.)
- **execute**: Run a custom device function with arbitrary params

## Important Notes

- Commands are **validated** against the device registry before dispatch. If a device doesn't have the capability, or the value is out of range, the tool will return an error message.
- **Offline devices**: Commands to offline devices will be flagged. You can inform the user the device is unreachable.
- **Sensors are read-only**: You cannot `set` a sensor capability (like temperature). Use `get` instead.
- **Boolean toggles**: Only `bool` capabilities (like power) can be toggled.
- If you don't know the exact device ID or capabilities, use `action="list"` or `action="describe"` first.

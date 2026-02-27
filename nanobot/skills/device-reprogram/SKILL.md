---
always: true
---

# Device Reprogram Skill

You can generate and deploy MicroPython firmware to IoT devices using `device_reprogram`.

## Actions
| Action | Purpose |
|--------|---------|
| templates | List available code templates (sensor_reader, actuator_switch, etc.) |
| generate | Fill a template with params → get validated code |
| validate | Safety-check raw MicroPython code |
| deploy | Package code + push to device via OTA |
| status | Check OTA deployment progress |

## Quick Reference
- **Generate from template**: `{"action":"generate","template_name":"sensor_reader","params":{"pin":36,"sensor_type":"temperature","read_interval_ms":5000}}`
- **Validate code**: `{"action":"validate","code":"import machine\ndef setup(): ...\ndef loop(): ..."}`
- **Deploy**: `{"action":"deploy","device":"esp32-01","template_name":"actuator_switch","params":{"pin":2,"actuator_name":"relay"},"version":"1.0.0"}`

## Safety Rules
Generated code MUST pass safety validation:
- Only whitelisted MicroPython imports allowed (machine, time, json, network, etc.)
- No eval/exec/compile/__import__
- No sandbox escape attributes (__class__, __subclasses__)
- No network server patterns (bind/listen/accept)
- Must define setup()+loop() or main()
- Max 64KB source code

## Important
- Always validate before deploying
- Use templates when possible — they're pre-validated
- Devices must be online for OTA deployment
- Check OTA status after deploy to confirm success

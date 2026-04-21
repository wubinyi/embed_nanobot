# MicroPython & mpremote Guide

A practical reference for working with the ESP32 MicroPython environment
in the embed_nanobot project.

---

## Table of Contents

1. [What is MicroPython?](#what-is-micropython)
2. [What is mpremote?](#what-is-mpremote)
3. [Setup & Prerequisites](#setup--prerequisites)
4. [Connecting to ESP32](#connecting-to-esp32)
5. [mpremote Command Reference](#mpremote-command-reference)
6. [File Management](#file-management)
7. [Running Code](#running-code)
8. [Interactive REPL](#interactive-repl)
9. [Installing Packages](#installing-packages)
10. [Device Info & Diagnostics](#device-info--diagnostics)
11. [Working with boot.py](#working-with-bootpy)
12. [Common Workflows](#common-workflows)
13. [Troubleshooting](#troubleshooting)
14. [MicroPython Coding Rules (ESP32)](#micropython-coding-rules-esp32)
15. [Operations FAQ](#operations-faq)

---

## What is MicroPython?

MicroPython is a lean implementation of Python 3 optimized for microcontrollers.
It runs on the ESP32's dual-core Xtensa processor with ~520KB RAM. Unlike
standard Python, MicroPython has:

- **No pip** — use `mip` or `mpremote mip` to install packages
- **Limited stdlib** — no `pathlib`, `dataclasses`, `typing`, `enum`, `abc`
- **Hardware access** — `machine` module for GPIO, I2C, SPI, PWM, ADC
- **Networking** — `network`, `socket`, `ssl` modules for WiFi and TCP/UDP
- **Filesystem** — small flash filesystem (typically 2-4MB) at `/`

## What is mpremote?

`mpremote` is the official MicroPython remote control tool. It communicates
with the ESP32 over USB serial and lets you:

- **Copy files** to/from the device
- **Run Python code** remotely
- **Open an interactive REPL** (Read-Eval-Print Loop)
- **Install packages** from micropython-lib
- **Mount local directories** as a virtual filesystem on the device
- **Manage the filesystem** (ls, cat, rm, mkdir, etc.)
- **Reset the device** (soft or hard)

Install: `pip install mpremote`

---

## Setup & Prerequisites

### Hardware

- ESP32 dev board (NodeMCU-32S, ESP32-DevKitC, etc.)
- USB cable (must be data-capable, not charge-only)

### Software

```bash
# Install mpremote
pip install mpremote

# Flash MicroPython firmware (first time only)
bash esp32/tools/flash.sh /dev/ttyUSB0
```

### Platform: USB Access

**[Radxa 5T / Debian]** — The ESP32 is directly accessible at `/dev/ttyUSB0`. No extra setup needed.

```bash
# Verify immediately:
mpremote connect /dev/ttyUSB0 exec "print('alive')"
```

**[WSL2 (Windows)]** — ESP32 USB access requires USB/IP passthrough:

```powershell
# On Windows PowerShell (admin)
winget install usbipd

# List USB devices
usbipd list

# Attach ESP32 to WSL (find bus-id from list above, e.g. 1-3)
usbipd attach --wsl --busid 1-3
```

After attaching, the device appears as `/dev/ttyUSB0` in WSL.

---

## Connecting to ESP32

### Auto-detect

```bash
# List available serial ports
mpremote devs
```

### Explicit connection

All commands use `connect` as the first argument:

```bash
mpremote connect /dev/ttyUSB0 <command>
```

### Shortcut aliases

```bash
mpremote u0 <command>    # shortcut for connect /dev/ttyUSB0
mpremote a0 <command>    # shortcut for connect /dev/ttyACM0
```

---

## mpremote Command Reference

### File Operations

| Command | Description | Example |
|---------|-------------|---------|
| `ls` | List files on device | `mpremote connect /dev/ttyUSB0 ls :/` |
| `cat` | Read a file | `mpremote connect /dev/ttyUSB0 cat :config.py` |
| `cp` | Copy files | `mpremote connect /dev/ttyUSB0 cp local.py :remote.py` |
| `rm` | Delete a file | `mpremote connect /dev/ttyUSB0 rm :old_file.py` |
| `mkdir` | Create directory | `mpremote connect /dev/ttyUSB0 mkdir :lib` |
| `rmdir` | Remove directory | `mpremote connect /dev/ttyUSB0 rmdir :lib` |
| `tree` | Show file tree | `mpremote connect /dev/ttyUSB0 tree :/` |
| `touch` | Create empty file | `mpremote connect /dev/ttyUSB0 touch :flag` |
| `df` | Disk free space | `mpremote connect /dev/ttyUSB0 df` |
| `sha256sum` | File checksum | `mpremote connect /dev/ttyUSB0 sha256sum :main.py` |

### Code Execution

| Command | Description | Example |
|---------|-------------|---------|
| `exec` | Run a Python string | `mpremote connect /dev/ttyUSB0 exec "print('hi')"` |
| `eval` | Evaluate & print | `mpremote connect /dev/ttyUSB0 eval "2+2"` |
| `run` | Run a local .py file | `mpremote connect /dev/ttyUSB0 run test.py` |
| `repl` | Interactive REPL | `mpremote connect /dev/ttyUSB0 repl` |

### Device Control

| Command | Description | Example |
|---------|-------------|---------|
| `reset` | Hard reset | `mpremote connect /dev/ttyUSB0 reset` |
| `soft-reset` | Soft reset (re-import) | `mpremote connect /dev/ttyUSB0 soft-reset` |
| `resume` | Connect without reset | `mpremote connect /dev/ttyUSB0 resume` |
| `bootloader` | Enter bootloader mode | `mpremote connect /dev/ttyUSB0 bootloader` |
| `rtc` | Get/set real-time clock | `mpremote connect /dev/ttyUSB0 rtc` |

### Package Management

| Command | Description | Example |
|---------|-------------|---------|
| `mip install` | Install a package | `mpremote connect /dev/ttyUSB0 mip install aiohttp` |

### Advanced

| Command | Description | Example |
|---------|-------------|---------|
| `mount` | Mount local dir on device | `mpremote connect /dev/ttyUSB0 mount .` |
| `umount` | Unmount | `mpremote connect /dev/ttyUSB0 umount` |

---

## File Management

### Copy files to ESP32

```bash
# Copy a single file
mpremote connect /dev/ttyUSB0 cp local_file.py :remote_file.py

# The : prefix means "on device". Without : means local.
# Copy from device to local:
mpremote connect /dev/ttyUSB0 cp :config.py ./config_backup.py
```

### Deploy the mesh client

```bash
# Use the deploy script (copies all mesh_client files)
bash esp32/tools/deploy.sh /dev/ttyUSB0

# Force-update config.py too (normally skipped to preserve credentials)
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

### Check what's on the device

```bash
# List root directory
mpremote connect /dev/ttyUSB0 ls :/

# Show full file tree
mpremote connect /dev/ttyUSB0 tree :/

# Read a specific file
mpremote connect /dev/ttyUSB0 cat :main.py

# Check free space
mpremote connect /dev/ttyUSB0 df
```

### Delete files

```bash
# Remove a single file
mpremote connect /dev/ttyUSB0 rm :old_module.py

# Remove compiled bytecode (can cause stale imports)
mpremote connect /dev/ttyUSB0 rm :module.mpy
```

---

## Running Code

### Execute a one-liner

```bash
mpremote connect /dev/ttyUSB0 exec "print('Hello from ESP32!')"
```

### Execute a multi-line script

```bash
mpremote connect /dev/ttyUSB0 exec "
import machine
led = machine.Pin(2, machine.Pin.OUT)
led.value(1)
print('LED on')
"
```

### Run a local Python file on the device

```bash
# Runs local_script.py on the ESP32 (file stays on your PC)
mpremote connect /dev/ttyUSB0 run my_test_script.py
```

### Evaluate an expression

```bash
mpremote connect /dev/ttyUSB0 eval "import machine; machine.freq()"
# Output: 240000000
```

### Using `resume` to bypass boot.py

When `boot.py` auto-starts the mesh client, normal `mpremote` commands
trigger a soft-reset which re-runs `boot.py`. Use `resume` to skip the reset:

```bash
# Connect without soft-reset (continues existing session)
mpremote connect /dev/ttyUSB0 resume exec "print('alive')"
mpremote connect /dev/ttyUSB0 resume cp new_file.py :new_file.py
mpremote connect /dev/ttyUSB0 resume ls :/
```

---

## Interactive REPL

The REPL gives you a live Python prompt on the ESP32:

```bash
mpremote connect /dev/ttyUSB0 repl
```

### REPL keyboard shortcuts

| Key | Action |
|-----|--------|
| **Ctrl-X** | Exit REPL (return to host) |
| **Ctrl-C** | Interrupt running code |
| **Ctrl-D** | Soft-reset the device |
| **Ctrl-A** | Enter raw REPL mode |
| **Ctrl-B** | Exit raw REPL mode |

### Example REPL session

```python
>>> import machine
>>> pin2 = machine.Pin(2, machine.Pin.OUT)
>>> pin2.value(1)   # Turn on built-in LED
>>> pin2.value(0)   # Turn off built-in LED

>>> import network
>>> sta = network.WLAN(network.STA_IF)
>>> sta.active(True)
>>> sta.connect("MySSID", "MyPassword")
>>> sta.ifconfig()
('192.168.1.100', '255.255.255.0', '192.168.1.1', '8.8.8.8')

>>> import os
>>> os.listdir("/")
['boot.py', 'main.py', 'config.py', 'protocol.py', ...]

>>> import gc
>>> gc.collect()
>>> gc.mem_free()
112384
```

---

## Installing Packages

MicroPython has its own package index (`micropython-lib`):

```bash
# Install a package to the device
mpremote connect /dev/ttyUSB0 mip install <package-name>

# Examples:
mpremote connect /dev/ttyUSB0 mip install aiohttp
mpremote connect /dev/ttyUSB0 mip install logging
```

You can also install from a URL:

```bash
mpremote connect /dev/ttyUSB0 mip install https://example.com/my_module.py
```

---

## Device Info & Diagnostics

### System info

```bash
mpremote connect /dev/ttyUSB0 exec "
import sys, gc, machine, os
print(f'Platform:  {sys.platform}')
print(f'Version:   {sys.version}')
print(f'CPU freq:  {machine.freq() // 1_000_000} MHz')
gc.collect()
print(f'Free RAM:  {gc.mem_free()} bytes')
st = os.statvfs('/')
free_flash = st[0] * st[3]
total_flash = st[0] * st[2]
print(f'Flash:     {free_flash // 1024}KB free / {total_flash // 1024}KB total')
"
```

### Network status

```bash
mpremote connect /dev/ttyUSB0 exec "
import network
sta = network.WLAN(network.STA_IF)
print(f'Connected: {sta.isconnected()}')
print(f'IP config: {sta.ifconfig()}')
print(f'RSSI:      {sta.status(\"rssi\")} dBm')
"
```

### GPIO pin states

```bash
mpremote connect /dev/ttyUSB0 exec "
import machine
# Read built-in LED (GPIO 2 on most ESP32 boards)
pin2 = machine.Pin(2, machine.Pin.IN)
print(f'GPIO 2: {pin2.value()}')
"
```

### RTC (Real-Time Clock)

```bash
# Read current RTC time
mpremote connect /dev/ttyUSB0 rtc

# Set RTC from host clock
mpremote connect /dev/ttyUSB0 rtc --set
```

---

## Working with boot.py

The embed_nanobot mesh client includes a `boot.py` that auto-starts
the mesh connection on power-up.

### How boot.py works

1. Prints a 3-second countdown: `[boot] Auto-start in 3s... (Ctrl-C to cancel)`
2. Checks for `/no_autostart` flag file — if present, skips auto-start
3. Imports `main` and calls `main.run()`
4. Catches `KeyboardInterrupt` for clean abort

### Bypass boot.py for development

```bash
# Method 1: Use 'resume' to skip soft-reset (avoids boot.py)
mpremote connect /dev/ttyUSB0 resume exec "print('hello')"
mpremote connect /dev/ttyUSB0 resume cp new_file.py :new_file.py

# Method 2: Create the no_autostart flag file
mpremote connect /dev/ttyUSB0 resume exec "
f = open('/no_autostart', 'w')
f.close()
print('auto-start disabled')
"
# Then reset — boot.py will skip main.run()
mpremote connect /dev/ttyUSB0 reset

# Method 3: Remove boot.py entirely (not recommended for production)
mpremote connect /dev/ttyUSB0 resume rm :boot.py
```

### Re-enable auto-start

```bash
mpremote connect /dev/ttyUSB0 resume exec "
import os
try:
    os.remove('/no_autostart')
    print('auto-start re-enabled')
except:
    print('already enabled')
"
```

---

## Common Workflows

### Deploy code and test

```bash
# 1. Deploy all files
bash esp32/tools/deploy.sh /dev/ttyUSB0

# 2. Reset to run boot.py → auto-connect to hub
mpremote connect /dev/ttyUSB0 reset

# 3. Check gateway log for connection
tail -f ~/gateway.log | grep esp32
```

### Quick edit-test cycle (without full deploy)

```bash
# Copy just the file you changed
mpremote connect /dev/ttyUSB0 resume cp esp32/mesh_client/main.py :main.py

# Reset to reload modules
mpremote connect /dev/ttyUSB0 reset
```

### Debug a crash

```bash
# 1. Disable auto-start so you get a clean REPL
mpremote connect /dev/ttyUSB0 resume exec "open('/no_autostart','w').close()"
mpremote connect /dev/ttyUSB0 reset

# 2. Open REPL and manually import
mpremote connect /dev/ttyUSB0 repl
# >>> import main
# >>> main.run()
# (see the error traceback)

# 3. Fix the code, re-deploy, re-enable auto-start
bash esp32/tools/deploy.sh /dev/ttyUSB0
mpremote connect /dev/ttyUSB0 resume exec "import os; os.remove('/no_autostart')"
mpremote connect /dev/ttyUSB0 reset
```

### Test enrollment (first-time device setup)

```bash
# 1. Start gateway with enrollment
nanobot gateway --enroll -v

# 2. Read the PIN from gateway output
#    Enter on ESP32 REPL: import main; main.run(enrollment_pin='XXXXXX')

# 3. Open REPL and enroll
mpremote connect /dev/ttyUSB0 repl
# >>> import main
# >>> main.run(enrollment_pin='482193')

# 4. After success, future boots auto-connect (PSK saved to /psk.bin)
```

### Mount local directory for rapid prototyping

```bash
# Mount current directory — ESP32 reads files from your PC over USB
mpremote connect /dev/ttyUSB0 mount . repl
# >>> import my_local_module  # reads from your PC, no copy needed!
```

> **Note**: Mounted files run slower (USB latency). Use for prototyping only.

---

## Troubleshooting

### `/dev/ttyUSB0` not found

- **Check USB cable**: Must be data-capable, not charge-only
- **WSL users**: Attach USB via usbipd (see Setup section)
- **Permissions**: `sudo usermod -a -G dialout $USER` then re-login

### "could not enter raw repl"

The ESP32 is busy (running boot.py or mesh client). Use `resume`:

```bash
mpremote connect /dev/ttyUSB0 resume exec "print('ok')"
```

### Module still cached after code change

MicroPython caches imported modules. After updating a file:

```bash
# Option 1: Hard reset (re-runs boot.py)
mpremote connect /dev/ttyUSB0 reset

# Option 2: Delete .mpy compiled files
mpremote connect /dev/ttyUSB0 resume rm :module.mpy
```

### WiFi won't connect

```bash
mpremote connect /dev/ttyUSB0 resume exec "
import network
sta = network.WLAN(network.STA_IF)
sta.active(True)
sta.connect('YOUR_SSID', 'YOUR_PASS')
import time; time.sleep(3)
print(f'Connected: {sta.isconnected()}')
print(f'Status: {sta.status()}')
"
```

WiFi status codes: 0=idle, 1=connecting, 2=wrong_password, 3=no_AP_found,
4=connect_fail, 5=got_ip (1010=connected on some boards)

### Out of memory

```bash
mpremote connect /dev/ttyUSB0 exec "
import gc
gc.collect()
print(f'Free: {gc.mem_free()} bytes')
"
```

If free RAM is very low (<20KB), reduce imported modules or use
`gc.collect()` frequently in your code.

### Hub connection fails

Check `config.py` on the device:

```bash
mpremote connect /dev/ttyUSB0 cat :config.py
```

Verify `HUB_IP` matches the hub machine's LAN IP (not localhost).

---

## MicroPython Coding Rules (ESP32)

When writing code for the ESP32 mesh client, follow these constraints
(MicroPython ≠ CPython):

| Rule | Wrong | Right |
|------|-------|-------|
| No union types | `x: str \| None = None` | `x = None` |
| No dict unpacking | `{**other}` | `d = {}; d.update(other)` |
| No numeric separators | `100_000` | `100000` |
| No `hmac` module | `import hmac` | `security.hmac_sha256()` |
| No `hashlib.pbkdf2_hmac` | `hashlib.pbkdf2_hmac(...)` | `enrollment._pbkdf2_sha256()` |
| No `typing` module | `from typing import ...` | (just omit type hints) |
| No `dataclasses` | `@dataclass` | Use plain dicts or classes |
| No `pathlib` | `Path(...)` | `open(...)` |
| No `enum` / `abc` | `class Foo(Enum)` | Use string constants |
| No annotated variables | `x: dict = {}` | `x = {}` |
| Return annotations OK | `def f() -> None:` | ✓ (recent MicroPython) |
| Complex returns not OK | `def f() -> dict \| None:` | `def f():` |

### Available MicroPython modules (safe to import)

- `machine` — GPIO, Pin, PWM, ADC, I2C, SPI, UART, Timer
- `network` — WiFi STA/AP, Ethernet
- `socket` — TCP/UDP sockets
- `ssl` — TLS/SSL wrapping
- `time` — sleep, ticks_ms, ticks_diff
- `json` — loads, dumps
- `os` — listdir, remove, stat, statvfs
- `gc` — collect, mem_free
- `struct` — pack, unpack
- `hashlib` — sha256 (no PBKDF2)
- `binascii` — hexlify, unhexlify, b2a_base64
- `sys` — platform, version, exit
- `uasyncio` — asyncio equivalent for MicroPython
- `micropython` — mem_info, schedule, opt_level

---

## Operations FAQ

Practical answers for day-to-day operation of the nanobot gateway and ESP32 mesh devices.

### Q1: How do I check if nanobot is working? How do I enable it?

**Check if the gateway process is running:**

```bash
# Check for running gateway process
pgrep -af "nanobot gateway"

# Quick status check (shows config, workspace, model, API keys)
nanobot status
```

**Start the gateway:**

```bash
# Start with verbose logging (recommended for testing)
nanobot gateway -v 2>&1 | tee ~/gateway.log

# Start with enrollment enabled (for new devices)
nanobot gateway --enroll -v 2>&1 | tee ~/gateway.log

# Start with a custom config file
nanobot gateway -c /path/to/config.json -v
```

**Gateway startup — what to look for in the log:**

```
🤖 Starting nanobot gateway...
✓ Channels enabled: mesh
[Mesh/Transport] TCP server listening on 0.0.0.0:18800
[Mesh/Transport] UDP discovery listening on port 18799
```

If you see `✓ Channels enabled: mesh`, the mesh transport is active and waiting for ESP32 connections.

**Configuration location:**

The gateway reads config from `~/.embed_nanobot/config.json`. Key fields:

```json
{
  "channels": {
    "mesh": {
      "enabled": true,
      "tcp_port": 18800,
      "discovery_port": 18799,
      "registry_path": "~/.nanobot/workspace/device_registry.json"
    }
  }
}
```

---

### Q2: How do I check if ESP32 is working? How do I enable it?

**Check if ESP32 is reachable via USB:**

```bash
# List connected MicroPython devices
mpremote devs

# Quick alive check
mpremote connect /dev/ttyUSB0 exec "print('alive')"
```

**Check WiFi connection on ESP32:**

```bash
mpremote connect /dev/ttyUSB0 exec "
import network
sta = network.WLAN(network.STA_IF)
print('Connected:', sta.isconnected())
if sta.isconnected():
    print('IP:', sta.ifconfig()[0])
"
```

**Check if PSK (pre-shared key) exists (device is enrolled):**

```bash
mpremote connect /dev/ttyUSB0 exec "
import os
files = os.listdir('/')
print('PSK exists:', 'psk.key' in files)
"
```

**Deploy the mesh client to ESP32:**

```bash
# Full deploy (all mesh_client files)
bash esp32/tools/deploy.sh /dev/ttyUSB0

# Force update config.py too
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

**Start the mesh client manually (for debugging):**

```bash
# Run the mesh client manually (see output in terminal)
mpremote connect /dev/ttyUSB0 exec "import main; main.run()"

# First-time enrollment (gateway must be running with --enroll)
mpremote connect /dev/ttyUSB0 exec "import main; main.run(enrollment_pin='XXXX')"
```

**ESP32 automatic startup:**

After deployment, `boot.py` auto-starts the mesh client with a 3-second
grace period. To disable auto-start:

```bash
# Create the no-autostart flag
mpremote connect /dev/ttyUSB0 exec "open('/no_autostart','w').close()"

# Re-enable auto-start (delete the flag)
mpremote connect /dev/ttyUSB0 exec "import os; os.remove('/no_autostart')"
```

**ESP32 startup sequence (what you see in the serial log):**

```
[wifi] Connected — IP: 192.168.5.72
[security] PSK loaded (32 bytes)
[transport] Connecting to hub 192.168.5.1:18800...
[transport] Hub connected
[transport] STATE_REPORT sent
```

**ESP32 config reference (`config.py` on device):**

```python
WIFI_SSID = "YourSSID"
WIFI_PASS = "YourPassword"
HUB_HOST = "192.168.5.1"       # Gateway machine IP (not localhost)
HUB_PORT = 18800
NODE_ID = "esp32-01"
DEVICE_TYPE = "esp32"
CAPABILITIES = "led"
RECONNECT_DELAY_S = 5
```

---

### Q3: How do I verify they are connected? How to check via nanobot?

**Gateway log patterns confirming ESP32 connected:**

```
[Mesh/Transport] persistent connection from esp32-01
[MeshChannel] received state_report from esp32-01
[DeviceRegistry] auto-registered device esp32-01 (type=esp32, caps=['led'])
[DeviceRegistry] device esp32-01 is online
```

**Ask the nanobot agent (in chat/CLI):**

```
You: "List all connected devices"
→ Agent calls device_control(action="list")
→ Output:
   Registered devices (1):
     • esp32-01 (esp32-01) [ONLINE] — esp32, caps: led

You: "What is the state of esp32-01?"
→ Agent calls device_control(action="state", device="esp32-01")
→ Output:
   esp32-01 (esp32-01) — esp32 [ONLINE]
   Current state:
     • led: True
   Capabilities:
     • led (actuator)
```

**Check the device registry file directly:**

```bash
cat ~/.nanobot/workspace/device_registry.json | python3 -m json.tool
```

The JSON shows each device with its `online` status, `last_seen` timestamp,
capabilities, and current state.

---

### Q4: How do I know if ESP32 can't be accessed? Which devices are connected and which are not?

**Use `device_control(action="list")` — shows ALL devices with ONLINE/OFFLINE status:**

```
You: "List all devices"
→ Registered devices (3):
    • esp32-01 (esp32-01) [ONLINE] — esp32, caps: led
    • sensor-02 (sensor-02) [OFFLINE] — temperature_sensor, caps: temperature
    • relay-03 (relay-03) [OFFLINE] — smart_relay, caps: relay
```

**Gateway log patterns when a device goes offline:**

```
[Mesh/Transport] esp32-01 idle timeout          # 90s no data on TCP
[Mesh/Transport] esp32-01 disconnected
[DeviceRegistry] device esp32-01 is offline
```

**When a command fails to reach an offline device:**

```
[DeviceControlTool] esp32-01 is offline, attempting delivery anyway
[DeviceControlTool] failed to deliver to esp32-01
→ "Failed to deliver command to esp32-01 — device may be unreachable."
```

**On gateway restart**: All devices start as `offline`. They go `online`
only when they reconnect and send a STATE_REPORT. This is by design —
the gateway doesn't assume a previous connection is still valid.

**Check the registry summary (via agent):**

```
You: "Show device status summary"
→ Connected devices (1 online / 3 total):
    - esp32-01 (esp32) [ONLINE] — led: True
    - sensor-02 (temperature_sensor) [OFFLINE] — last seen 5min ago
    - relay-03 (smart_relay) [OFFLINE] — last seen 2h ago
```

---

### Q5: If ESP32 has errors, how do I get them?

**Method 1: Read errors via USB serial (best for debugging):**

```bash
# Open interactive REPL — see live errors in real-time (Ctrl-X to exit)
mpremote connect /dev/ttyUSB0 repl

# Import and run manually to see full traceback
mpremote connect /dev/ttyUSB0 exec "import main; main.run()"

# Test a specific module for import errors
mpremote connect /dev/ttyUSB0 exec "import device; print('OK')"

# Soft-reset first to clear cached modules
mpremote connect /dev/ttyUSB0 reset
```

**Method 2: Check command responses via gateway log:**

When the ESP32 executes a command, it sends a RESPONSE back to the gateway.
The gateway logs it:

```
[MeshChannel] RESPONSE from esp32-01: led → ok          # Success
[MeshChannel] RESPONSE from esp32-01: temperature → error  # Failure
```

The error detail is included in the response payload:

```json
{"status": "error", "detail": "unknown capability: xxx"}
{"status": "error", "detail": "unhandled action 'yyy' for type 'zzz'"}
```

**Method 3: Detect crashes via connection drop:**

If ESP32 crashes before sending a response, the gateway only sees the
TCP disconnection:

```
[Mesh/Transport] esp32-01 disconnected
[DeviceRegistry] device esp32-01 is offline
```

This means the ESP32 hit an unhandled exception. Connect via USB and
check the REPL for the traceback.

**ESP32 transport-level errors (shown on ESP32 serial):**

```
[transport] Error: [Errno 104] ECONNRESET — reconnecting in 5 s
[transport] Error: [Errno 113] EHOSTUNREACH — reconnecting in 5 s
```

The ESP32 reconnects automatically after `RECONNECT_DELAY_S` seconds.

---

### Q6: How do I update ESP32 firmware via OTA?

**Method 1: USB deploy (recommended for development):**

```bash
# Deploy all mesh_client files via USB
bash esp32/tools/deploy.sh /dev/ttyUSB0

# Force config update too
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

**Method 2: OTA via the nanobot agent (over WiFi, no USB needed):**

The agent has a `device_reprogram` tool that pushes code updates to
ESP32 devices over the mesh network.

```
You: "Deploy a sensor reader to esp32-01 that reads temperature on pin 36 every 5 seconds"
→ Agent calls device_reprogram(action="deploy", device="esp32-01",
     template_name="sensor_reader",
     params={"pin": 36, "sensor_type": "temperature", "read_interval_ms": 5000})
```

**Available `device_reprogram` actions:**

| Action | Purpose |
|--------|---------|
| `templates` | List available code templates |
| `generate` | Fill a template with parameters → validated code |
| `validate` | Safety-check raw MicroPython code |
| `deploy` | Package code + push to device via OTA |
| `status` | Check OTA progress for a device |

**OTA protocol flow:**

```
Hub sends OTA_OFFER → ESP32 replies OTA_ACCEPT →
Hub sends OTA_CHUNK (×N with ACKs) → ESP32 sends OTA_VERIFY →
Hub sends OTA_COMPLETE
```

**OTA requirements:**

- The device must be **online** (connected to the gateway)
- The gateway config must have `firmware_dir` set:
  ```json
  { "channels": { "mesh": { "firmware_dir": "~/.embed_nanobot/firmware" } } }
  ```
- Code is safety-validated: only whitelisted MicroPython imports, no `eval`/`exec`,
  max 64KB, must define `setup()+loop()` or `main()`

**OTA timeouts:**

| Phase | Timeout |
|-------|---------|
| Offer → Accept/Reject | 60s |
| Chunk → ACK | 30s |
| Verify | 60s |
| Chunk size | 4096 bytes |

**Check OTA status:**

```
You: "Check OTA status for esp32-01"
→ Agent calls device_reprogram(action="status", device="esp32-01")
```

---

*Last updated: 2026-03-28*

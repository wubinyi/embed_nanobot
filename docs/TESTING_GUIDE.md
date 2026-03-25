# embed_nanobot Testing Guide

> **Last updated**: 2026-03-25
>
> This guide covers how to test all embed_nanobot features — from Python unit
> tests (no hardware) to flashing an ESP32 and running live mesh end-to-end.
>
> **Note**: The HybridRouter / local LLM provider is **not required** for most
> testing.  Without a local LLM, all unit tests still pass (they use mocks),
> and the mesh channel works independently.

---

## A. Hub-Side Unit Tests (no hardware, no local LLM)

The project contains **1400+ tests**.  The embed_nanobot-specific tests are
the top-level `tests/test_*.py` files plus `tests/security/`.

### Run all embed_nanobot feature tests (logged to file)

```bash
cd ~/workspace/embed_nanobot

pytest tests/test_mesh.py tests/test_device_registry.py tests/test_device_commands.py \
  tests/test_device_control_tool.py tests/test_device_routing.py tests/test_automation.py \
  tests/test_hybrid_router.py tests/test_mtls.py tests/test_crl.py tests/test_ota.py \
  tests/test_groups.py tests/test_industrial.py tests/test_federation.py \
  tests/test_pipeline.py tests/test_codegen.py tests/test_dashboard.py \
  tests/test_ble.py tests/test_resilience.py \
  tests/security/test_security_network.py \
  -v --tb=short 2>&1 | tee ~/embed_tests.log
```

### Or run the entire test suite

```bash
pytest tests/ -v --tb=short 2>&1 | tee ~/embed_tests_all.log
```

### What the unit tests cover
This covers:
    - Mesh transport, protocol, discovery, PSK auth, encryption
    - Device registry, commands, routing, grouping, automation
    - mTLS CA, CRL, OTA firmware state machine
    - PLC/industrial bridge, hub federation, sensor pipeline
    - BLE, code generation, dashboard, resilience
    - Hybrid router (difficulty scoring, PII sanitization, circuit breaker — all mocked, no real LLM)

| Test File | Feature |
|-----------|---------|
| `test_mesh.py` | TCP/UDP transport, protocol framing, discovery, PSK auth |
| `test_device_registry.py` | Device CRUD, state persistence, online/offline events |
| `test_device_commands.py` | Command schema, validation, routing |
| `test_device_control_tool.py` | LLM device-control tool integration |
| `test_device_routing.py` | Device-command → local LLM forcing |
| `test_automation.py` | Rule engine, conditions, actions, cooldown |
| `test_hybrid_router.py` | Difficulty scoring, PII sanitization, circuit breaker (all mocked) |
| `test_mtls.py` | mTLS CA, EC P-256 cert issuance, revocation |
| `test_crl.py` | Certificate revocation list |
| `test_ota.py` | OTA chunked transfer, integrity, state machine |
| `test_groups.py` | Device grouping, scenes, fan-out commands |
| `test_industrial.py` | PLC/Modbus TCP adapters, polling |
| `test_federation.py` | Hub-to-hub registry sync, command forwarding |
| `test_pipeline.py` | Sensor time-series recording, flush, analytics |
| `test_codegen.py` | MicroPython code generation, AST safety checks |
| `test_dashboard.py` | HTTP monitoring server |
| `test_ble.py` | BLE sensor support |
| `test_resilience.py` | Supervised tasks, retry policies |
| `test_security_network.py` | Network security helpers |

---

## B. Flash & Deploy to ESP32

### Prerequisites

The ESP32 board uses a **CP2102 or CH9102** USB-serial chip (identified as
"CP2101/CH9102 Arduino/NodeMCU" in system info).

Your ESP32 board has a CP2102 or CH9102 USB-serial chip. I didn't detect /dev/ttyUSB0 — this is likely because you're connected via SSH/VS Code Remote. The device will show up on the physical host machine, not inside a remote SSH session.

### Step 1: Install tools

```bash
pip install esptool mpremote pyserial
```

### Step 2: Identify the serial port

Plug in the ESP32 via USB, then:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
# Usually /dev/ttyUSB0 for CP2102/CH9102
```

**If using VS Code Remote SSH**: the USB device is on the physical host,
not inside the remote session.  You need to run flash/deploy commands on
the machine where the USB cable is physically connected.

On Windows, check Device Manager → Ports (COM & LPT) → it'll show as COMx. On native Linux, it's /dev/ttyUSB0.

**If you get permission errors**:

```bash
sudo usermod -a -G dialout $USER
# Log out and back in, or temporarily:
sudo chmod 666 /dev/ttyUSB0
```

### Step 3: Download MicroPython firmware

1. Go to <https://micropython.org/download/ESP32_GENERIC/>
2. Download the latest stable `.bin` file
3. Place it in the firmware directory:

```bash
mkdir -p esp32/tools/firmware/
# Copy the downloaded file there, e.g.:
cp ~/Downloads/ESP32_GENERIC-*.bin esp32/tools/firmware/
```

### Step 4: Flash MicroPython

```bash
# Replace /dev/ttyUSB0 with your actual port
bash esp32/tools/flash.sh /dev/ttyUSB0
```

This does two things:
1. Erases the entire flash
2. Writes the MicroPython firmware at address 0x1000

### Step 5: Edit WiFi config

Edit `esp32/mesh_client/config.py`:

```python
WIFI_SSID     = "YourActualSSID"
WIFI_PASSWORD = "YourActualPassword"
HUB_IP        = "192.168.x.x"     # PC's LAN IP (run: ip addr show | grep inet)
HUB_PORT      = 18800             # must match mesh.tcpPort in config.json
NODE_ID        = "esp32-01"
```

### Step 6: Deploy code to ESP32

```bash
bash esp32/tools/deploy.sh /dev/ttyUSB0
```

This copies all `mesh_client/*.py` files to the ESP32 filesystem via `mpremote`.

### Step 7: Verify via REPL

```bash
mpremote connect /dev/ttyUSB0 repl
```

At the MicroPython `>>>` prompt:

```python
import os
os.listdir('/')
# Should show: ['main.py', 'config.py', 'protocol.py', 'security.py', ...]
```

Press `Ctrl-X` to exit the REPL.

---

## C. Live End-to-End Mesh Test

### Step 1: Enable mesh in config

Edit `~/.embed_nanobot/config.json`:

```json
"mesh": {
    "enabled": true,
    "nodeId": "hub-01",
    "tcpPort": 18800,
    "udpPort": 18799,
    "pskAuthEnabled": true,
    "encryptionEnabled": true,
    ...
}
```

### Step 2: Start the gateway with verbose logging

```bash
cd ~/workspace/embed_nanobot
nanobot gateway -v 2>&1 | tee ~/gateway.log
```

All `[MeshChannel]`, `[Transport]`, `[Discovery]`, `[Enrollment]` log lines
will be captured in `~/gateway.log`.

### Step 3: Generate enrollment PIN

In a **second terminal**:

```bash
nanobot gateway --enroll
# Output: PIN: 482193  (expires in 5 minutes)
```

### Step 4: Enroll the ESP32

On the ESP32 REPL (`mpremote connect /dev/ttyUSB0 repl`):

```python
import main
main.run(enrollment_pin="482193")   # use the PIN from step 3
```

If enrollment succeeds, the ESP32 receives a PSK saved to `/psk.bin` and
connects to the hub.  You should see in `~/gateway.log`:

```
[MeshChannel] Enrollment request from esp32-01
[MeshChannel] Device esp32-01 enrolled successfully
[Transport] New connection from esp32-01
```

### Step 5: Test device interaction via chat

In a **third terminal**, interact with the AI:

```bash
nanobot agent -m "What devices are connected?" 2>&1 | tee ~/agent_device.log
nanobot agent -m "Turn on the LED on esp32-01" 2>&1 | tee -a ~/agent_device.log
nanobot agent -m "What is the state of esp32-01?" 2>&1 | tee -a ~/agent_device.log
```

> **Note**: The `DeviceControlTool` is only registered when both mesh AND
> HybridRouter are active (see `nanobot/cli/commands.py` ~line 719).
> Without a local LLM, the device tool won't be registered.  You can still
> verify mesh connectivity, enrollment, and transport through the gateway logs.

Since you don't have a local LLM, the HybridRouter won't be active — the agent will use your configured remote provider (OpenRouter/stepfun). The device control tool is only registered when both mesh AND HybridRouter are enabled (see commands.py line ~719). So for pure device testing without local LLM, you can interact with the mesh channel directly through the protocol.

### Step 6: Set auto-start on ESP32

Once enrollment works, configure automatic boot:

```python
# In ESP32 REPL:
f = open('/boot.py', 'w')
f.write('import main\nmain.run()\n')
f.close()
```

Future power-ons will automatically connect to the hub.

---

## D. Log File Summary

| Log File | Content |
|----------|---------|
| `~/embed_tests.log` | Unit test results (pass/fail/errors) |
| `~/embed_tests_all.log` | Full test suite results |
| `~/gateway.log` | Hub runtime: mesh transport, discovery, enrollment, device connections |
| `~/agent_device.log` | Agent chat interactions with device tool responses |

---

## E. Feature Testability Matrix (without local LLM)

| Feature | Testable? | Method |
|---------|-----------|--------|
| Unit tests (all 800+ embed tests) | **Yes** | `pytest` — all use mocks |
| Mesh transport (TCP/UDP) | **Yes** | Enable mesh, connect ESP32 |
| PSK auth & enrollment | **Yes** | PIN flow with ESP32 |
| AES-256 encryption | **Yes** | Unit tests + live mesh (transparent) |
| Device registry | **Yes** | Devices appear on enrollment |
| Device commands (raw) | **Yes** | Send mesh COMMAND messages from ESP32 |
| Automation rules | **Yes** | Unit tests; live when devices report state |
| mTLS, CRL, OTA | **Yes** | Unit tests cover fully |
| HybridRouter routing | **No** | Needs local LLM running |
| NL device control tool | **No** | Needs HybridRouter active |
| Device → local routing | **No** | Needs local LLM running |

---

## F. Troubleshooting

### ESP32 not detected (`/dev/ttyUSB0` missing)

```bash
# Check kernel messages
dmesg | grep -i -E "cp210|ch910|usb.*serial|ttyUSB"

# Check if driver is loaded
lsmod | grep -E "cp210x|ch341"

# Install driver if missing (Ubuntu/Debian)
sudo apt install linux-modules-extra-$(uname -r)
```

### Flash fails with "A fatal error occurred: Failed to connect"

- Hold the **BOOT** button on the ESP32 while running the flash command
- Some boards require holding BOOT, pressing EN/RST, then releasing BOOT
- Try a lower baud rate: edit `flash.sh` to use `--baud 115200`

### mpremote can't connect

```bash
# Verify the port is accessible
python3 -c "import serial; s = serial.Serial('/dev/ttyUSB0', 115200); print('OK'); s.close()"

# If busy, another process may hold the port
fuser /dev/ttyUSB0
```

### Enrollment PIN expired

PINs expire after 5 minutes (configurable via `enrollmentPinTimeout`).
Generate a new one with `nanobot gateway --enroll`.

### Tests fail with import errors

```bash
# Make sure dev dependencies are installed
pip install -e ".[dev]"
```

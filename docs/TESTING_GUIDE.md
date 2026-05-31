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

For f26 RKNN Toolkit2 installation details and the current RK3588 compile-status log, see:
`docs/01_features/f26_hybrid_npu_inference/04_RKNN_Toolkit2_Install.md`

---

## B. Flash & Deploy to ESP32

### Platform Note

| Platform | USB situation | Port-forward needed? |
|----------|---------------|----------------------|
| **Radxa 5T (current, Debian 13)** | ESP32 directly at `/dev/ttyUSB0` — no usbipd needed | No |
| **WSL2 (Windows)** | Requires `usbipd-win` passthrough | Yes (NAT) |

**[Radxa 5T users]**: Skip Options 1 and 2 below. Just run:
```bash
# Verify ESP32 is connected
mpremote connect /dev/ttyUSB0 exec "print('alive')"
# Flash / deploy
bash esp32/tools/flash.sh /dev/ttyUSB0        # first-time firmware flash
bash esp32/tools/deploy.sh /dev/ttyUSB0       # deploy mesh_client code
```

The rest of this section documents the WSL2 workflow for reference.

---

This project was originally developed in **WSL (Windows Subsystem for Linux)** while the
ESP32 board was physically connected to the **Windows 10 host** via USB.
WSL does not have native access to USB serial devices.

There are **two approaches** to flash and communicate with the ESP32:

| Approach | Pros | Cons |
|----------|------|------|
| **Option 1: Use Windows tools directly** | Simple, no WSL USB config | Must install Python + esptool on Windows side |
| **Option 2: Attach USB to WSL via usbipd** | All commands stay in WSL | Requires usbipd-win install + admin rights |

---

### Option 1: Flash & Deploy from Windows (Recommended)

This is the simplest approach — run `esptool` and `mpremote` from
Windows PowerShell/CMD, since the USB port is natively visible there.

#### Step 1a: Install Python + tools on Windows

1. Install Python 3.11+ for Windows from <https://www.python.org/downloads/>
   (check "Add to PATH" during install)
2. Open **PowerShell** and install the tools:

```powershell
pip install esptool mpremote pyserial
```

#### Step 2a: Identify the COM port

1. Open **Device Manager** (Win+X → Device Manager)
2. Expand **Ports (COM & LPT)**
3. Look for "Silicon Labs CP210x" or "CH9102" — note the port (e.g., `COM3`)

Or from PowerShell:

```powershell
# List serial ports
[System.IO.Ports.SerialPort]::GetPortNames()
```

#### Step 3a: Download MicroPython firmware

1. Go to <https://micropython.org/download/ESP32_GENERIC/>
2. Download the latest stable `.bin` file
3. Save it somewhere accessible, e.g., `C:\Users\<you>\Downloads\`

#### Step 4a: Flash MicroPython from Windows

In **PowerShell**:

```powershell
# Replace COM3 with your actual port, and adjust the .bin path
esptool.py --chip esp32 --port COM3 erase_flash
esptool.py --chip esp32 --port COM3 --baud 460800 write_flash -z 0x1000 C:\Users\<you>\Downloads\ESP32_GENERIC-20260101-v1.24.1.bin
```

If `esptool.py` is not found as a command, try:

```powershell
python -m esptool --chip esp32 --port COM3 erase_flash
python -m esptool --chip esp32 --port COM3 --baud 460800 write_flash -z 0x1000 <path-to-firmware>.bin
```

#### Step 5a: Deploy mesh_client code from Windows

The mesh_client source lives in your WSL filesystem.  Access it from Windows
via the `\\wsl$\` network path:

```powershell
# Navigate to the project in WSL filesystem
cd \\wsl$\Ubuntu\home\wubinyi\workspace\embed_nanobot

# Copy files one by one (mpremote on Windows)
mpremote connect COM3 cp esp32/mesh_client/main.py :main.py
mpremote connect COM3 cp esp32/mesh_client/protocol.py :protocol.py
mpremote connect COM3 cp esp32/mesh_client/security.py :security.py
mpremote connect COM3 cp esp32/mesh_client/enrollment.py :enrollment.py
mpremote connect COM3 cp esp32/mesh_client/transport.py :transport.py
mpremote connect COM3 cp esp32/mesh_client/device.py :device.py
mpremote connect COM3 cp esp32/mesh_client/config.py :config.py
```

#### Step 6a: Open REPL from Windows

```powershell
mpremote connect COM3 repl
```

At the MicroPython `>>>` prompt:

```python
import os
os.listdir('/')
# Should show: ['main.py', 'config.py', 'protocol.py', 'security.py', ...]
```

Press `Ctrl-X` to exit.

---

### Option 2: Attach USB to WSL via usbipd-win

This makes `/dev/ttyUSB0` appear inside WSL so you can use the project's
`flash.sh` and `deploy.sh` scripts directly.

#### Step 1b: Install usbipd-win on Windows

1. Install from <https://github.com/dorssel/usbipd-win/releases> (latest `.msi`)
2. Reboot if prompted

#### Step 2b: Install USB support in WSL

In your **WSL terminal**:

```bash
sudo apt update
sudo apt install linux-tools-generic hwdata
sudo update-alternatives --install /usr/local/bin/usbip usbip \
  /usr/lib/linux-tools/*/usbip 20
```
#### Step 2.5b: Install Driver and Find ESP32 Device
If the device doesn't appear in Device Manager at all (not even as an unknown device with a yellow icon), the most common causes are:

1. Check if Windows sees ANY USB device
   - Open Device Manager, click View → Show hidden devices
   - Plug/unplug the ESP32 and watch if anything flashes or appears under:
      - Ports (COM & LPT)
      - Other devices (yellow warning icon)
      - Universal Serial Bus controllers
2. Most likely cause: charge-only USB cable \
This is the #1 issue. Many micro-USB / USB-C cables are charge-only — they have no data wires. The CP2102 chip won't be detected at all. \
Test: Try a different USB cable. A cable that came with an Android phone or data-transfer device is more likely to have data lines.\
Quick check: If you have another device (phone, Arduino) that shows up in Device Manager with the same cable, the cable is fine.

3. Verify in PowerShell \
Run this in PowerShell to check if the USB device is detected at the bus level:
   ```bash
   # List all USB 
   devicesGet-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'Ports' -or $_.Class -eq 'USB' } | Format-Table Name, Status, DeviceID -AutoSize
   ```
   Or even more directly — check if the CP2102 VID/PID appears:
   ```bash
   # CP2102 vendor/product ID = 10C4:EA60
   Get-PnpDevice | Where-Object { $_.DeviceID -like '*10C4*' } | Format-Table Name, Status
   ```
4. Try a different USB port \
   - Use a port directly on the PC (not a hub)
   - Try both USB 2.0 (usually black inside) and USB 3.0 (blue inside) ports
5. If device shows as "Unknown" under Other devices \
Right-click → Update driver → Browse my computer → Let me pick → Select "Silicon Labs CP210x USB to UART Bridge" from the list.
----
Bottom line: If nothing at all appears in Device Manager when you plug/unplug — swap the USB cable first. That solves this problem ~80% of the time with NodeMCU boards.

#### Step 3b: Attach the ESP32 to WSL

In **PowerShell (Run as Administrator)**:

```powershell
# List USB devices
usbipd list
# Find the CP2102/CH9102 device — note the BUSID (e.g., 1-3)

# Bind it (one-time)
usbipd bind --busid 1-3

# Attach to WSL
usbipd attach --wsl --busid 1-3
```

Back in **WSL terminal**, verify:

```bash
ls /dev/ttyUSB*
# Should show: /dev/ttyUSB0
```

#### Step 4b: Install tools in WSL

```bash
pip install esptool mpremote pyserial
```

#### Step 5b: Download firmware & flash

```bash
mkdir -p esp32/tools/firmware/
# Download from https://micropython.org/download/ESP32_GENERIC/
# Copy the .bin into esp32/tools/firmware/

bash esp32/tools/flash.sh /dev/ttyUSB0
```
Below is the output:
```bash
(embed_nanobot) wubinyi@DESKTOP-HJFROP3:~/workspace/embed_nanobot$ bash esp32/tools/flash.sh /dev/ttyUSB0
==> Port:     /dev/ttyUSB0
==> Firmware: esp32/tools/firmware/ESP32_GENERIC-20251209-v1.27.0.bin

==> Step 1: Erasing flash...
Warning: DEPRECATED: 'esptool.py' is deprecated. Please use 'esptool' instead. The '.py' suffix will be removed in a future major release.
Warning: Deprecated: Command 'erase_flash' is deprecated. Use 'erase-flash' instead.
esptool v5.2.0
Connected to ESP32 on /dev/ttyUSB0:
Chip type:          ESP32-D0WD-V3 (revision v3.1)
Features:           Wi-Fi, BT, Dual Core + LP Core, 240MHz, Vref calibration in eFuse, Coding Scheme None
Crystal frequency:  40MHz
MAC:                f4:65:0b:d7:82:b4

Stub flasher running.

Flash memory erased successfully in 8.6 seconds.

Hard resetting via RTS pin...
==> Step 2: Flashing MicroPython...
Warning: DEPRECATED: 'esptool.py' is deprecated. Please use 'esptool' instead. The '.py' suffix will be removed in a future major release.
Warning: Deprecated: Command 'write_flash' is deprecated. Use 'write-flash' instead.
esptool v5.2.0
Connected to ESP32 on /dev/ttyUSB0:
Chip type:          ESP32-D0WD-V3 (revision v3.1)
Features:           Wi-Fi, BT, Dual Core + LP Core, 240MHz, Vref calibration in eFuse, Coding Scheme None
Crystal frequency:  40MHz
MAC:                f4:65:0b:d7:82:b4

Stub flasher running.
Changing baud rate to 460800...
Changed.

Configuring flash size...
Flash will be erased from 0x00001000 to 0x001aefff...
Wrote 1759456 bytes (1152383 compressed) at 0x00001000 in 28.2 seconds (498.9 kbit/s).
Hash of data verified.

Hard resetting via RTS pin...

✓ Done. MicroPython flashed to /dev/ttyUSB0
  Connect with: python3 -m serial.tools.miniterm /dev/ttyUSB0 115200
  Or:           mpremote connect /dev/ttyUSB0
```

#### Step 6b: Deploy & verify

```bash
bash esp32/tools/deploy.sh /dev/ttyUSB0
mpremote connect /dev/ttyUSB0 repl
```

Notes:

- `deploy.sh` now interrupts the running ESP32 app before copying files, so deployment still works even if `boot.py` auto-started the mesh client.
- `config.py` is preserved by default. To overwrite it too, run:

```bash
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

The output of `bash esp32/tools/deploy.sh /dev/ttyUSB0` is shown below:
```bash
(embed_nanobot) wubinyi@DESKTOP-HJFROP3:~/workspace/embed_nanobot$ bash esp32/tools/deploy.sh /dev/ttyUSB0
==> Deploying mesh_client to ESP32 on /dev/ttyUSB0

==> Interrupting running app to enter REPL
  -> ESP32 interrupted

  -> protocol.py
cp esp32/mesh_client/protocol.py :protocol.py
  -> security.py                        
cp esp32/mesh_client/security.py :security.py
  -> enrollment.py                      
cp esp32/mesh_client/enrollment.py :enrollment.py
  -> transport.py                       
cp esp32/mesh_client/transport.py :transport.py
  -> device.py                          
cp esp32/mesh_client/device.py :device.py
  -> main.py                            
cp esp32/mesh_client/main.py :main.py
...
  -- config.py already exists on device (skipping, use FORCE_CONFIG=1 to overwrite)
                                        
✓ Deploy complete.

Next steps:
  1. Open REPL:  mpremote connect /dev/ttyUSB0 repl
  2. First boot: >>> import main; main.run(enrollment_pin='YOUR_PIN')
  3. After enrollment the device will run automatically on future boots.

To set auto-start on boot, run in REPL:
  >>> f = open('/boot.py','w'); f.write('import main\nmain.run()\n'); f.close()
```

```python
import os
os.listdir('/')
# Should show: ['main.py', 'config.py', 'protocol.py', 'security.py', ...]
```

Press `Ctrl-X` to exit.

> **Note**: After each Windows reboot or USB re-plug, you need to re-run
> `usbipd attach --wsl --busid <BUSID>` from an admin PowerShell.

---

### Common Steps (both options)

#### Edit WiFi config before deploying

Edit `esp32/mesh_client/config.py` in WSL:

```python
WIFI_SSID     = "YourActualSSID"
WIFI_PASSWORD = "YourActualPassword"
HUB_IP        = "192.168.x.x"     # Windows WiFi IP (NOT WSL IP — see below)
HUB_PORT      = 18800             # must match mesh.tcpPort in config.json
NODE_ID        = "esp32-01"
```

> **ESP32 only supports 2.4 GHz WiFi**. If your router broadcasts both 2.4G
> and 5G SSIDs (e.g., `MyNet` and `MyNet-5G`), use the 2.4G one.

#### Known WiFi networks

Reference table of WiFi credentials used during testing:

| Name | Location | SSID | Password | Notes |
|------|----------|------|----------|-------|
| ShenZhen Home | ShenZhen | PPAY | PP&AY1023 | 2.4 GHz, primary dev location |
| DongGuan ZhongXi | DongGuan | 1704 | 17041014 | 2.4 GHz, secondary location |

When switching locations, update `esp32/mesh_client/config.py` with the
correct SSID/password and re-deploy with `FORCE_CONFIG=1`.
`HUB_IP` must also be updated to match the new LAN IP.

Then deploy with force-config:

```bash
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

#### Network topology: ESP32 → Windows → WSL

WSL2 uses NAT networking by default. The ESP32 connects over WiFi to your
**Windows LAN IP**, not the WSL internal IP. The gateway runs inside WSL,
so Windows must port-forward traffic from the WiFi interface into WSL:

```
ESP32 (WiFi 192.168.5.x)
    │
    │ TCP connect to 192.168.5.57:18800  (Windows WiFi IP)
    ▼
Windows (port-forward 18800 → WSL)
    │
    │ netsh portproxy forwards to 172.27.x.x:18800
    ▼
WSL (nanobot gateway listening on 0.0.0.0:18800)
```

**Finding your Windows WiFi IP**: In PowerShell, run `ipconfig` and look for
"Wireless LAN adapter WLAN" → IPv4 Address (e.g., `192.168.5.57`).

#### Setting up port forwarding (one-time, as Administrator)

```powershell
# 1. Find WSL IP (or run `wsl hostname -I` from PowerShell)
#    Example: 172.27.167.162

# 2. Forward port 18800 from all Windows interfaces → WSL
netsh interface portproxy add v4tov4 listenport=18800 listenaddress=0.0.0.0 connectport=18800 connectaddress=172.27.167.162

# 3. Open Windows Firewall
netsh advfirewall firewall add rule name="Nanobot Mesh (18800)" dir=in action=allow protocol=TCP localport=18800

# 4. Verify
netsh interface portproxy show v4tov4
# Should show:
# Listen on ipv4:             Connect to ipv4:
# Address         Port        Address         Port
# 0.0.0.0         18800       172.27.167.162  18800
```

> **WSL IP changes on reboot**: Re-run step 2 with the new IP after each
> Windows restart. Check with `wsl hostname -I` from PowerShell.
>
> **Alternative**: If your WSL uses **mirrored networking**
> (`networkingMode=mirrored` in `.wslconfig`), the WSL IP equals the Windows
> IP and no port forwarding is needed.

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
    "allowFrom": ["*"],
    "pskAuthEnabled": true,
    "encryptionEnabled": true,
    ...
}
```

> **Important**: `allowFrom` must be set to `["*"]` (or specific device IDs).
> The default `[]` denies all connections.

### Step 2: Start the gateway with enrollment

```bash
cd ~/workspace/embed_nanobot
nanobot gateway --enroll -v 2>&1 | tee ~/gateway.log
```

All `[MeshChannel]`, `[Transport]`, `[Discovery]`, `[Enrollment]` log lines
will be captured in `~/gateway.log`.  The `--enroll` flag generates an
enrollment PIN and displays it at startup:

```
📌 Enrollment PIN: 482193
   Expires at 23:05:31 (in 300s)
   Enter on ESP32 REPL: import main; main.run(enrollment_pin='482193')
```

### Step 3: Enroll the ESP32

On the ESP32 REPL (from Windows: `mpremote connect COM3 repl`,
or from WSL with usbipd: `mpremote connect /dev/ttyUSB0 repl`):

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

### Step 4: Test device interaction via chat

In a **second terminal**, interact with the AI:

```bash
nanobot agent -m "What devices are connected?" 2>&1 | tee ~/agent_device.log
nanobot agent -m "Turn on the LED on esp32-01" 2>&1 | tee -a ~/agent_device.log
nanobot agent -m "What is the state of esp32-01?" 2>&1 | tee -a ~/agent_device.log
```

> **Note**: The `DeviceControlTool` is only registered when both mesh AND
> HybridRouter are active (see `nanobot/cli/commands.py` ~line 719).
> Without a local LLM, the device tool won't be registered.  You can still
> verify mesh connectivity, enrollment, and transport through the gateway logs.

### Step 4b: Test local vs remote LLM with real `nanobot agent`

On the Radxa 5T, use the dedicated `local_llm/` workspace:

```bash
# Install local runtime
bash local_llm/scripts/install_ollama.sh
export PATH=/home/wubinyi/workspace/embed_nanobot/local_llm/runtime/bin:$PATH

# Pull the validated small model suitable for RK3588 CPU inference
ollama pull qwen2.5:0.5b
cat > local_llm/runtime/Modelfile.qwen2.5-0.5b-nb <<'EOF'
FROM qwen2.5:0.5b
PARAMETER num_ctx 8192
EOF
ollama create qwen2.5:0.5b-nb -f local_llm/runtime/Modelfile.qwen2.5-0.5b-nb

# Render runtime configs from ~/.embed_nanobot/config.json
/home/wubinyi/miniforge3/envs/embed_nanobot/bin/python local_llm/scripts/render_agent_configs.py

# Real agent checks
bash local_llm/scripts/run_agent_smoke.sh --mode local
bash local_llm/scripts/run_agent_smoke.sh --mode remote
```

Captured logs go to `local_llm/logs/`, and the validation record belongs in
`local_llm/docs/AGENT_VALIDATION.md`.

On Radxa CPU, the local smoke check can take about 6 minutes. The helper now
defaults to `600s` for `--mode local`.

### Step 5: Set auto-start on ESP32

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

### ESP32 not detected on Windows

1. Open **Device Manager** → check under **Ports (COM & LPT)**
2. If the device shows with a yellow warning icon, install the driver:
   - **CP2102**: Download from <https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers>
   - **CH9102/CH340**: Download from <https://www.wch-ic.com/downloads/CH341SER_EXE.html>
3. After driver install, unplug and re-plug the ESP32

### ESP32 not detected in WSL (`/dev/ttyUSB0` missing)

WSL does not see USB devices by default.  You must use `usbipd` (see
Option 2 above).  Verify:

```powershell
# In admin PowerShell:
usbipd list          # device should show as "Attached"
```

```bash
# In WSL:
ls /dev/ttyUSB*      # should show /dev/ttyUSB0
dmesg | tail -10     # should show cp210x or ch341 driver loaded
```

If `/dev/ttyUSB0` still doesn't appear after `usbipd attach`:

```bash
# WSL may lack the driver module
sudo apt install linux-tools-generic hwdata
# Then re-attach from PowerShell
```

### Flash fails with "A fatal error occurred: Failed to connect"

- Hold the **BOOT** button on the ESP32 while running the flash command
- Some boards require holding BOOT, pressing EN/RST, then releasing BOOT
- Try a lower baud rate: `--baud 115200` instead of `460800`
- On Windows, make sure no other program (Arduino IDE, PuTTY, serial
  monitor) is holding the COM port open

### ESP32 can't connect to hub (mesh enrollment timeout)

This usually means the ESP32 can reach your WiFi but not the nanobot
gateway port inside WSL.

1. Verify the gateway is running: check `~/gateway.log` for
   `Listening on 0.0.0.0:18800`
2. Check Windows firewall: ensure port 18800/TCP is allowed inbound
3. Check port forwarding (WSL2 NAT mode):

```powershell
# Verify the proxy exists
netsh interface portproxy show v4tov4

# If missing, add it (admin PowerShell):
netsh interface portproxy add v4tov4 listenport=18800 listenaddress=0.0.0.0 connectport=18800 connectaddress=$(wsl hostname -I | ForEach-Object { $_.Trim() })
```

4. Test from Windows: `curl http://localhost:18800` — should get a
   connection (even if the response is an error, it means the port is
   forwarded)

### mpremote can't connect

On **Windows**:

```powershell
# Verify the port is accessible
python -c "import serial; s = serial.Serial('COM3', 115200); print('OK'); s.close()"
```

On **WSL** (with usbipd):

```bash
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

### WSL IP changes after reboot

WSL2's internal IP changes on each reboot.  If you use port forwarding,
re-run the `netsh interface portproxy` command after each Windows restart.
Consider adding it to a startup script, or switch to WSL mirrored
networking mode (add to `%USERPROFILE%\.wslconfig`):

```ini
[wsl2]
networkingMode=mirrored
```

With mirrored mode, WSL shares the host's IP and no port forwarding is
needed.

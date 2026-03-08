# ESP32 MicroPython Mesh Client

This directory contains the embedded-side (device-side) code for connecting
an ESP32 Dev Board to the embed_nanobot AI Hub over the LAN mesh protocol.

## Directory Structure

```
esp32/
├── README.md               ← This file
├── mesh_client/
│   ├── config.py           ← WiFi credentials + hub address (user edits this)
│   ├── protocol.py         ← Wire framing (4-byte length prefix + JSON)
│   ├── security.py         ← HMAC-SHA256 signing + PSK management
│   ├── enrollment.py       ← One-time PIN enrollment to get PSK from hub
│   ├── transport.py        ← TCP connection management + reconnect loop
│   ├── device.py           ← Declare this device's capabilities to the hub
│   └── main.py             ← Entry point (copy all files to ESP32, run this)
└── tools/
    ├── flash.sh            ← Helper script: erase + flash MicroPython
    └── deploy.sh           ← Helper script: copy mesh_client/ to ESP32 via mpremote
```

## Quick Start

See [docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md) Section 5 for the
complete walkthrough. Short version:

### 1. Flash MicroPython

```bash
bash esp32/tools/flash.sh /dev/ttyUSB0
```

### 2. Edit config

```python
# esp32/mesh_client/config.py
WIFI_SSID     = "YourSSID"
WIFI_PASSWORD = "YourPassword"
HUB_IP        = "192.168.1.100"   # your hub machine's LAN IP
HUB_PORT      = 9000
NODE_ID       = "esp32-01"        # must be unique per device
```

### 3. Deploy to ESP32

```bash
bash esp32/tools/deploy.sh /dev/ttyUSB0
```

### 4. Get enrollment PIN from Hub

```bash
# on the hub machine
nanobot gateway --enroll
# prints: "PIN: 482193  (expires in 5 minutes)"
```

### 5. Complete enrollment

On the ESP32 REPL:

```python
import main
main.run(enrollment_pin="482193")   # use the PIN from step 4
```

After enrollment the PSK is saved to flash (`/psk.bin`). Future reboots
start automatically without a PIN.

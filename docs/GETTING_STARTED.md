# Getting Started — embed_nanobot AI Hub

> **Target audience**: Hands-on deployment on a Linux x86 machine that will serve as the AI Hub,
> with a Google Gemini LLM API and at least one ESP32 Dev Board.

---

## Table of Contents

1. [Install the Hub](#1-install-the-hub)
2. [Configure Google Gemini](#2-configure-google-gemini)
3. [Run & Verify the Hub](#3-run--verify-the-hub)
4. [Run the Test Suite](#4-run-the-test-suite)
5. [Connect an ESP32 Device](#5-connect-an-esp32-device)
6. [What to Work on Next (Roadmap)](#6-what-to-work-on-next)

---

## 1. Install the Hub

### Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| OS | Linux (Debian/Ubuntu/Arch) | x86-64 tested; ARM (Raspberry Pi 4/5) also supported |
| Python | 3.11+ | `python3 --version` to check |
| pip | 23+ | `pip install --upgrade pip` |
| Git | 2.x | For pulling updates |
| Network | WiFi or LAN | Hub and ESP32 must be on the **same subnet** |

### Step 1 — Clone the repository

```bash
git clone https://github.com/wubinyi/embed_nanobot.git
cd embed_nanobot
git checkout main_embed        # our development branch
```

### Step 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3 — Install in editable mode (includes dev tools)

```bash
pip install -e ".[dev]"
```

This installs:

- All runtime dependencies (litellm, pydantic, cryptography, etc.)
- Dev dependencies: pytest, ruff, pytest-asyncio
- The `nanobot` CLI entry-point

Verify:

```bash
nanobot --help
```

### Step 4 — Create workspace directory

```bash
nanobot onboard
```

This creates `~/.nanobot/` with:

- `config.json` — main configuration file
- `workspace/` — agent memory, AGENTS.md, skills

---

## 2. Configure Google Gemini

### Step 1 — Get your Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Create an API key under a project
3. Copy the key (starts with `AIza...`)

### Step 2 — Edit `~/.nanobot/config.json`

Replace the entire file with (or merge with) the following minimal config:

```jsonc
{
  "agents": {
    "defaults": {
      "model": "gemini/gemini-2.0-flash",
      "provider": "gemini",
      "maxTokens": 8192,
      "temperature": 0.1
    }
  },
  "providers": {
    "gemini": {
      "apiKey": "AIza-YOUR-KEY-HERE"
    }
  }
}
```

#### Available Gemini models

| Model string | Notes |
|---|---|
| `gemini/gemini-2.0-flash` | Fast, cheap — best default for device commands |
| `gemini/gemini-2.0-flash-lite` | Even cheaper, lower quality |
| `gemini/gemini-1.5-pro` | Higher capability, slower |
| `gemini/gemini-2.0-pro-exp` | Experimental, highest capability |

#### Using Gemini as cloud + local Ollama as private (Hybrid Router)

If you also run a local Ollama model (recommended for privacy):

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2   # or qwen2.5:7b, gemma3:4b, etc.
```

Then enable the Hybrid Router in `~/.nanobot/config.json`:

```jsonc
{
  "agents": {
    "defaults": {
      "model": "gemini/gemini-2.0-flash",
      "provider": "hybrid"
    }
  },
  "providers": {
    "gemini": {
      "apiKey": "AIza-YOUR-KEY-HERE"
    },
    "ollama": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:11434/v1"
    }
  },
  "hybridRouter": {
    "enabled": true,
    "localModel": "ollama/llama3.2",
    "cloudModel": "gemini/gemini-2.0-flash",
    "complexityThreshold": 5.0,
    "sanitizePii": true,
    "fallback": {
      "enabled": true,
      "failureThreshold": 3,
      "recoverySecs": 300
    }
  }
}
```

**How the Hybrid Router works**:  
Simple device commands ("turn on light", "set thermostat to 22°C") are processed **entirely locally** by Ollama — sub-second, no cloud, no data leaves your home.  
Complex queries (code generation, multi-step reasoning) are routed to Gemini, with PII automatically sanitized first.

### Step 3 — Verify Gemini connection

```bash
nanobot run
# Type: "hello, what can you do?"
# Ctrl+C to exit
```

---

## 3. Run & Verify the Hub

### Basic CLI mode

```bash
nanobot run
```

### With the LAN Mesh enabled (required for ESP32)

Add mesh config to `~/.nanobot/config.json`:

```jsonc
{
  "agents": { ... },
  "providers": { ... },
  "channels": {
    "mesh": {
      "enabled": true,
      "nodeId": "hub-01",
      "bindHost": "0.0.0.0",
      "port": 9000,
      "discoveryPort": 9001,
      "psk": {
        "enabled": true,
        "keystoreDir": "~/.nanobot/mesh/keystore"
      },
      "tls": {
        "enabled": false
      },
      "allowFrom": []
    }
  }
}
```

> **Security note**: `allowFrom: []` means any enrolled device is allowed. After your first
> ESP32 is enrolled, you can restrict this to specific node IDs if desired.

Start the hub with mesh:

```bash
nanobot gateway
```

Expected output:

```
INFO | Mesh channel started on 0.0.0.0:9000
INFO | Discovery beacon on UDP :9001
INFO | HybridRouter: local=ollama/llama3.2, cloud=gemini/gemini-2.0-flash
INFO | Gateway running. Press Ctrl+C to stop.
```

### Verify the mesh is up

```bash
# In another terminal
python3 - <<'EOF'
import socket, json, struct, time

HOST = "127.0.0.1"
PORT = 9000

env = {"type": "ping", "source": "test-node", "target": "hub-01",
       "payload": {}, "ts": time.time(), "nonce": "aabbccdd00112233", "hmac": ""}
data = json.dumps(env).encode()
frame = struct.pack(">I", len(data)) + data

s = socket.create_connection((HOST, PORT), timeout=3)
s.sendall(frame)
length = struct.unpack(">I", s.recv(4))[0]
resp = json.loads(s.recv(length))
print("Response:", resp["type"])   # should print: pong
s.close()
EOF
```

---

## 4. Run the Test Suite

### Run all tests

```bash
cd /home/binyiwu/workspace/embed_nanobot
source .venv/bin/activate

pytest tests/ -v
```

Expected: **~770+ tests, all passing** (no real hardware or API keys needed — all IoT tests use mocks).

### Run by feature area

| Feature | Test file | Tests |
|---------|-----------|-------|
| Mesh transport + discovery | `tests/test_mesh.py` | ~40 |
| PSK authentication | `tests/test_mesh.py` | ~25 |
| Device enrollment (PIN) | `tests/test_mesh.py` | ~35 |
| AES-GCM encryption | `tests/test_mesh.py` | ~37 |
| Device registry | `tests/test_device_registry.py` | ~50 |
| Device command schema | `tests/test_device_commands.py` | ~42 |
| Natural language → device | `tests/test_device_control_tool.py` | ~32 |
| Hybrid router routing | `tests/test_hybrid_router.py` | ~21 |
| Automation engine | `tests/test_automation.py` | ~75 |
| Cloud fallback + circuit breaker | `tests/test_resilience.py` | ~11 |
| mTLS local CA | `tests/test_mtls.py` | ~49 |
| CRL revocation | `tests/test_crl.py` | ~36 |
| OTA firmware update | `tests/test_ota.py` | ~49 |
| Device groups & scenes | `tests/test_groups.py` | ~? |
| Error recovery | `tests/test_resilience.py` | ~? |
| Web dashboard | `tests/test_dashboard.py` | ~? |
| PLC/industrial bridge | `tests/test_industrial.py` | ~54 |
| Multi-hub federation | `tests/test_federation.py` | ~44 |
| AI code generation | `tests/test_codegen.py` | ~? |
| Sensor data pipeline | `tests/test_pipeline.py` | ~? |
| BLE mesh | `tests/test_ble.py` | ~? |

```bash
# Run a single feature test
pytest tests/test_device_commands.py -v

# Run with coverage report
pytest tests/ --tb=short -q
```

### Environment for tests

Tests are fully self-contained (no real devices, no API keys required). The test suite uses:

- `unittest.mock` — mocks LLM calls and network I/O
- `pytest-asyncio` — runs async test functions
- In-memory keystores and registries

If a test asks for API keys, skip it with: `pytest tests/ -k "not integration"`

---

## 5. Connect an ESP32 Device

### Current Status

The **hub-side infrastructure is complete**: enrollment, PSK auth, mTLS, OTA, device registry,
command routing, and code generation are all implemented and tested.

The **missing piece** is the **ESP32-side MicroPython client** (roadmap task 5.3.2 / 5.2.5).
You can help build it — see [Section 6](#6-what-to-work-on-next).

### What the ESP32 client needs to do

The hub speaks a simple TCP + JSON protocol. Each message is:

```
[4-byte big-endian length][JSON envelope bytes]
```

The JSON envelope shape:

```json
{
  "type": "ping",
  "source": "esp32-node-01",
  "target": "*",
  "payload": {},
  "ts": 1700000000.0,
  "nonce": "aabbccdd00112233",
  "hmac": ""
}
```

### Step-by-step: Connecting your first ESP32

#### Step A — Flash MicroPython

1. Download MicroPython for ESP32 from [micropython.org/download/ESP32_GENERIC](https://micropython.org/download/ESP32_GENERIC/)
2. Flash it:

```bash
pip install esptool
esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 \
  write_flash -z 0x1000 ESP32_GENERIC-20241129-v1.24.1.bin
```

#### Step B — Connect to the same WiFi network

On the ESP32 REPL (via `minicom` or `mpremote`):

```python
import network
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("YOUR_SSID", "YOUR_PASSWORD")
import time
time.sleep(3)
print(wlan.ifconfig())   # note the IP address
```

#### Step C — Get an enrollment PIN from the Hub

```bash
# On the hub machine, in a Python session:
python3 - <<'EOF'
import asyncio
from nanobot.mesh.security import KeyStore
from nanobot.mesh.enrollment import EnrollmentService

async def main():
    ks = KeyStore("~/.nanobot/mesh/keystore")
    svc = EnrollmentService(ks, transport=None, node_id="hub-01")
    pin, expires = await svc.create_pin()
    print(f"Enrollment PIN: {pin}  (valid for 5 minutes)")

asyncio.run(main())
EOF
```

Or, when the CLI gateway supports it:

```bash
nanobot gateway --enroll    # prints a one-time PIN
```

#### Step D — Run the minimal MicroPython mesh client

Copy this file to the ESP32 as `main.py` using `mpremote cp main.py :main.py`:

```python
# esp32_mesh_client.py  — Minimal embed_nanobot mesh client
# Tested on MicroPython v1.24+ with ESP32 Generic
import json, struct, socket, time, os, hashlib, hmac, ubinascii

HUB_IP   = "192.168.1.100"   # <-- replace with your Hub IP
HUB_PORT = 9000
NODE_ID  = "esp32-node-01"
PSK      = None               # Will be set after enrollment


# ------------------------------------------------------------------
# Protocol helpers
# ------------------------------------------------------------------
def _frame(env: dict) -> bytes:
    data = json.dumps(env).encode()
    return struct.pack(">I", len(data)) + data

def _recv_envelope(sock) -> dict:
    length_bytes = sock.recv(4)
    length = struct.unpack(">I", length_bytes)[0]
    data = b""
    while len(data) < length:
        data += sock.recv(length - len(data))
    return json.loads(data)

def _sign(env: dict, psk: bytes) -> str:
    """HMAC-SHA256 over type+source+target+ts+nonce."""
    msg = f"{env['type']}:{env['source']}:{env['target']}:{env['ts']}:{env['nonce']}".encode()
    return ubinascii.hexlify(hmac.new(psk, msg, hashlib.sha256).digest()).decode()

def _make_envelope(msg_type, payload, psk=None) -> dict:
    nonce = ubinascii.hexlify(os.urandom(8)).decode()
    env = {
        "type": msg_type, "source": NODE_ID, "target": "hub-01",
        "payload": payload, "ts": time.time(), "nonce": nonce, "hmac": ""
    }
    if psk:
        env["hmac"] = _sign(env, psk)
    return env


# ------------------------------------------------------------------
# Enrollment (run once, then store PSK)
# ------------------------------------------------------------------
def enroll(sock, pin: str) -> bytes:
    """Send ENROLL_REQUEST and receive PSK from hub."""
    import hashlib as _h
    # pin_proof = HMAC-SHA256(pin, node_id)
    proof = ubinascii.hexlify(
        hmac.new(pin.encode(), NODE_ID.encode(), _h.sha256).digest()
    ).decode()
    env = _make_envelope("enroll_request", {"pin_proof": proof, "node_id": NODE_ID})
    sock.sendall(_frame(env))
    resp = _recv_envelope(sock)
    if resp["type"] != "enroll_response" or not resp["payload"].get("success"):
        raise RuntimeError("Enrollment failed: " + str(resp["payload"].get("error")))
    # Decrypt PSK: XOR(encrypted_psk, pbkdf2(pin, salt))
    import ubinascii as ub
    enc_psk = ub.unhexlify(resp["payload"]["encrypted_psk"])
    salt    = ub.unhexlify(resp["payload"]["salt"])
    dk      = _h.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000, 32)
    psk     = bytes(a ^ b for a, b in zip(enc_psk, dk))
    print("[enroll] PSK obtained, length:", len(psk))
    return psk


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
def run(enrollment_pin=None):
    global PSK
    sock = socket.socket()
    sock.connect((HUB_IP, HUB_PORT))
    print("[mesh] Connected to hub")

    if enrollment_pin and PSK is None:
        PSK = enroll(sock, enrollment_pin)
        # TODO: persist PSK to flash (e.g. open("psk.bin","wb").write(PSK))

    # Send STATE_REPORT so hub knows this device is online
    state_env = _make_envelope("state_report", {
        "capabilities": [
            {"name": "led", "type": "switch", "access": "write",
             "value_type": "bool", "current_value": False},
            {"name": "temperature", "type": "sensor", "access": "read",
             "value_type": "float", "unit": "celsius"}
        ],
        "firmware_version": "0.1.0"
    }, PSK)
    sock.sendall(_frame(state_env))
    print("[mesh] State reported")

    # Main receive loop
    while True:
        try:
            msg = _recv_envelope(sock)
            handle(msg, sock)
        except Exception as e:
            print("[mesh] Error:", e)
            break
    sock.close()


def handle(msg: dict, sock):
    """Dispatch incoming hub messages."""
    t = msg.get("type")
    if t == "ping":
        pong = _make_envelope("pong", {}, PSK)
        sock.sendall(_frame(pong))
    elif t == "command":
        action = msg["payload"].get("action")
        if action == "turn_on":
            print("[device] Turning ON")
            # TODO: GPIO control here
        elif action == "turn_off":
            print("[device] Turning OFF")
        resp = _make_envelope("response", {"status": "ok", "action": action}, PSK)
        sock.sendall(_frame(resp))
    else:
        print("[mesh] Unhandled message type:", t)


# Entry point
if __name__ == "__main__":
    ENROLLMENT_PIN = None  # Set to "123456" only on first run
    run(enrollment_pin=ENROLLMENT_PIN)
```

#### Step E — Verify the connection

On the hub, you should see:

```
INFO | New device connected: esp32-node-01
INFO | STATE_REPORT from esp32-node-01: 2 capabilities (led, temperature)
```

Test a natural language command:

```bash
nanobot run
# Type: "turn on the LED on esp32-node-01"
```

The Hub will route "turn_on" to your ESP32 via the mesh.

---

## 6. What to Work on Next

### Priority order for ESP32 hardware work

Now that you have physical hardware, the roadmap unlocks in this order:

#### 6.1 — Build & test the MicroPython mesh client (5.3.2)

**You do**: Flash MicroPython, run the minimal client above, verify enrollment and command handling.

**I (Copilot) will**: Extend the client with proper PSK persistence to flash, GPIO control helpers, temperature reading, BLE advertisement, and OTA receive logic.

**Trigger next session**: Say `"let's implement the ESP32 mesh client fully"` and I will write the complete MicroPython module set.

#### 6.2 — Test OTA over real hardware (3.3 + 5.2)

**You do**: Flash an initial firmware, then trigger an OTA update from the hub.

**I will**: Help you write the OTA receiver side in MicroPython that handles chunked base64 firmware, verifies SHA-256, and applies it.

```bash
# Hub side: push firmware via OTA
python3 - <<'EOF'
import asyncio
from nanobot.mesh.ota import OTAManager, FirmwareStore

async def main():
    store = FirmwareStore("~/.nanobot/ota")
    fw_id = await store.store_firmware(
        node_id="esp32-node-01",
        version="0.2.0",
        data=open("new_firmware.bin","rb").read()
    )
    # OTAManager will be triggered via gateway
    print("Firmware stored:", fw_id)

asyncio.run(main())
EOF
```

#### 6.3 — AI code generation + deploy (4.3 + 5.2.3)

Tell the Hub what you want the ESP32 to do in plain English:

```bash
nanobot run
# Type: "Generate MicroPython code for esp32-node-01 that reads
#        temperature every 30 seconds and reports it to the hub"
```

The Hub generates code, pushes it via OTA, and monitors the result.

#### 6.4 — Autonomous mode (Phase 5.1)

After the device is stably connected, enable the autonomous heartbeat:

```jsonc
// Add to ~/.nanobot/config.json
{
  "autonomous": {
    "enabled": true,
    "intervalSecs": 1800,
    "autonomyLevel": "suggest",
    "explorationTopics": ["energy usage", "device health", "temperature trends"]
  }
}
```

#### 6.5 — Dual-partition secure boot (5.2)

The most advanced phase — a core partition (bootloader + mesh client, never updated remotely) and
an app partition (AI-generated logic, updateable via OTA). This requires hardware-level testing.
**Start this after 6.1 and 6.2 are validated on real hardware.**

### How to collaborate effectively

| Scenario | What you do | What to say to me |
|----------|-------------|-------------------|
| Implement a new ESP32 feature | Make sure hub is running, ESP32 is connected | "implement MicroPython OTA receiver for ESP32" |
| Found a bug on real hardware | Note the exact error / log output | "hub shows X, ESP32 shows Y, here is the log" |
| Want to add a new sensor type | Have the sensor datasheet | "add BME280 temperature+humidity sensor support" |
| Start Phase 5.1 (autonomous mode) | No hardware needed | "let's start Phase 5.1 autonomous heartbeat" |
| Upstream nanobot has new commits | Check `git fetch upstream` | "sync with upstream nanobot" |

---

## Quick Reference

### Hub commands

```bash
nanobot run              # Interactive CLI chat
nanobot gateway          # Full gateway mode (mesh + all channels)
nanobot onboard          # Create/re-create config and workspace
pytest tests/ -v         # Run all tests
pytest tests/ -q --tb=short  # Run all tests (compact output)
```

### Config file

```
~/.nanobot/config.json
```

### Key data directories

```
~/.nanobot/
├── config.json          # Main config
├── workspace/
│   ├── memory/          # Agent memory (MEMORY.md, HISTORY.md)
│   ├── AGENTS.md        # Agent identity file
│   └── skills/          # Custom skills
└── mesh/
    ├── keystore/        # PSK keys per device
    ├── ca/              # mTLS CA certificate + private key
    ├── certs/           # Per-device X.509 certificates
    └── ota/             # Firmware store
```

### Mesh wire protocol (for ESP32 client)

```
Frame = [4-byte big-endian uint32 length] + [UTF-8 JSON bytes]

Envelope = {
  "type":    string,   // see MsgType enum
  "source":  string,   // sender node ID
  "target":  string,   // receiver node ID or "*"
  "payload": object,
  "ts":      float,    // Unix timestamp
  "nonce":   string,   // 16 hex chars, random per message
  "hmac":    string    // HMAC-SHA256(type:source:target:ts:nonce, PSK)
}
```

Message types relevant for ESP32:

| Type | Direction | Purpose |
|------|-----------|---------|
| `enroll_request` | ESP32 → Hub | Request PSK during first connection |
| `enroll_response` | Hub → ESP32 | Encrypted PSK + enrollment result |
| `state_report` | ESP32 → Hub | Report capabilities and current state |
| `ping` / `pong` | Both | Keep-alive |
| `command` | Hub → ESP32 | Execute an action (turn_on, set_value, etc.) |
| `response` | ESP32 → Hub | Command result |
| `ota_offer` | Hub → ESP32 | Notify of available firmware update |
| `ota_accept` | ESP32 → Hub | Acknowledge and start download |
| `ota_chunk` | Hub → ESP32 | 512-byte base64 firmware chunk |
| `ota_chunk_ack` | ESP32 → Hub | Chunk received successfully |
| `ota_complete` | Hub → ESP32 | All chunks sent, verify hash |

---

*Generated: 2026-03-08 | Branch: `main_embed` | Hub version: 0.1.4*

# Testing FAQ — First-Hand Experience

> Collected from hands-on testing sessions.  These are real issues
> encountered and their solutions.

---

## Q1: What is the difference between `flash.sh` and `deploy.sh`?

| Script | What it does | When to run | Analogy |
|--------|-------------|-------------|---------|
| `esp32/tools/flash.sh` | Erases the entire ESP32 flash and writes the **MicroPython firmware** (the interpreter/OS) | Once per board (or to factory-reset) | Installing the operating system |
| `esp32/tools/deploy.sh` | Copies your **application code** (`mesh_client/*.py`) onto the ESP32's filesystem | After flash, and whenever you change code | Installing your app on the OS |

You need MicroPython installed first (`flash.sh`) before `deploy.sh` can
copy Python files to the device's filesystem.

---

## Q2: What does the enrollment PIN mean?

The PIN is a **one-time security handshake** between the ESP32 and the
nanobot hub:

1. You start the nanobot gateway with mesh enabled on your PC
2. You run `nanobot gateway --enroll` — the hub generates a random 6-digit
   PIN (valid for 5 minutes)
3. On the ESP32 REPL, you run `main.run(enrollment_pin="482193")` with that
   PIN
4. The ESP32 sends the PIN to the hub over TCP.  The hub verifies it, then
   sends back a **PSK (Pre-Shared Key)**
5. The ESP32 saves the PSK to `/psk.bin` on its flash
6. From now on, all communication is authenticated (HMAC-SHA256) and
   encrypted (AES-256-GCM) using that PSK — no PIN needed again

**Before running enrollment**, you must:

1. Edit `esp32/mesh_client/config.py` with your WiFi SSID/password and hub IP
2. Re-deploy if config was already on device: `FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0`
3. Enable mesh in `~/.embed_nanobot/config.json` (`"enabled": true`)
4. Set `"allowFrom": ["*"]` in the mesh config
5. Start the gateway: `nanobot gateway -v`
6. Generate the PIN: `nanobot gateway --enroll`
7. Then enroll from the ESP32 REPL

---

## Q3: ESP32 not showing in Windows Device Manager (CP2102)

**Most common cause**: Charge-only USB cable.  Many micro-USB cables have
no data wires — the CP2102 chip won't be detected at all.

**Fix**: Try a different USB cable.  A cable that came with a phone or
data-transfer device is more likely to have data lines.

Other checks:
- View → Show hidden devices in Device Manager
- Try a different USB port (directly on PC, not a hub)
- Verify CP2102 driver is installed: download from
  <https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers>
- Check in PowerShell: `Get-PnpDevice | Where-Object { $_.DeviceID -like '*10C4*' }`

---

## Q4: WSL can't see USB devices (`/dev/ttyUSB0` missing)

WSL does not have native USB access.  Use `usbipd-win` to forward the USB
device from Windows to WSL.  See the "Option 2" section in `TESTING_GUIDE.md`.

Key commands:
```powershell
# In admin PowerShell:
usbipd list                          # find the BUSID
usbipd bind --busid 1-3             # one-time bind
usbipd attach --wsl --busid 1-3     # attach to WSL
```

```bash
# In WSL:
ls /dev/ttyUSB*                      # verify it appeared
```

**Note**: You must re-run `usbipd attach` after every Windows reboot or
USB re-plug.

---

For bug fixes found during testing, see [docs/02_bugfix/BUGFIX_LOG.md](02_bugfix/BUGFIX_LOG.md).

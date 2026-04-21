# Location Change & Reboot Recovery Guide

What to do when you move to a different WiFi network, reboot your machine,
or need to re-deploy the ESP32 over USB.

This guide covers **two platforms**. Use the relevant section for your setup.

| Platform | Hub machine | USB situation | Port-forward needed? |
|----------|------------|---------------|----------------------|
| **Radxa 5T (ShenZhen Home)** | Debian 13 on Radxa Rock 5T, `192.168.5.199` (fixed) | ESP32 directly on `/dev/ttyUSB0` | No |
| **WSL2 (DongGuan / other)** | Ubuntu WSL2 on Windows 10 | usbipd-win required | Yes (NAT) |

---

## Quick Checklist — Radxa 5T (Debian)

After a location change or reboot:

1. **Find your new WiFi subnet IP** (usually `192.168.5.199` — fixed at ShenZhen Home)
2. **Update ESP32 config** with new WiFi SSID + `HUB_IP`
3. **Re-deploy to ESP32** via USB
4. **Start the gateway**

### Step 1 (Radxa 5T): Confirm hub IP

```bash
# The hub IP is FIXED at ShenZhen Home:
echo "Hub IP: 192.168.5.199"

# To find your actual IP at a different location:
ip addr show | grep 'inet ' | grep -v 127
```

### Step 2 (Radxa 5T): Update ESP32 Config

Edit `esp32/mesh_client/config.py`:

```python
WIFI_SSID     = "PPAY"          # ShenZhen Home WiFi
WIFI_PASSWORD = "PP&AY1023"
HUB_IP        = "192.168.5.199" # Fixed IP of Radxa 5T hub
```

> See [Known WiFi Networks](#known-wifi-networks) for other locations.

### Step 3 (Radxa 5T): Deploy to ESP32

```bash
# ESP32 is directly at /dev/ttyUSB0 — no usbipd needed
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
mpremote connect /dev/ttyUSB0 reset
```

### Step 4 (Radxa 5T): Start the Gateway

```bash
conda activate embed_nanobot
nanobot gateway -v 2>&1 | tee ~/gateway.log
# Or with enrollment (for new devices):
nanobot gateway --enroll -v 2>&1 | tee ~/gateway.log
```

---

## Quick Checklist — WSL2 (Windows)

1. **Attach ESP32 USB to WSL** (if using WSL)
## Quick Checklist — WSL2 (Windows)

After a PC reboot or location change on Windows + WSL2, run through these steps:

1. **Attach ESP32 USB to WSL** (via usbipd-win)
2. **Find the Windows WiFi IP** (changes per network)
3. **Update ESP32 config** with new WiFi + HUB_IP
4. **Re-deploy to ESP32**
5. **Re-create port forwarding** (WSL IP changes on reboot)
6. **Start the gateway**

---

## Step 1: Attach ESP32 USB to WSL

On every PC reboot, USB devices detach from WSL. Re-attach in **Windows
PowerShell (Admin)**:

```powershell
# List USB devices — find the ESP32 (CP2102 or CH340)
usbipd list

# Attach to WSL (replace X-Y with actual bus-id from list above)
usbipd attach --wsl --busid X-Y
```

Verify in WSL:

```bash
ls /dev/ttyUSB0    # Should exist after attach
mpremote connect /dev/ttyUSB0 exec "print('alive')"
```

> **Tip**: The bus-id may change if you plug into a different USB port.
> Always run `usbipd list` to check.

---

## Step 2: Find Your Windows WiFi IP

The ESP32 connects to the **Windows WiFi IP** (not the WSL IP).
This IP changes when you switch networks.

In **Windows PowerShell**:

```powershell
ipconfig
# Look for "Wireless LAN adapter WLAN" → IPv4 Address
```

Or from **WSL**:

```bash
powershell.exe -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.InterfaceAlias -like '*WLAN*' } | Select-Object IPAddress"
```

---

## Step 3: Update ESP32 Config

Edit `esp32/mesh_client/config.py`:

```python
WIFI_SSID     = "NewSSID"
WIFI_PASSWORD = "NewPassword"
HUB_IP        = "192.168.x.x"    # Windows WiFi IP from Step 2
```

---

## Step 4: Deploy to ESP32

```bash
# Force-deploy including config.py
FORCE_CONFIG=1 bash esp32/tools/deploy.sh /dev/ttyUSB0
```

Then reset the ESP32 to pick up the new config:

```bash
mpremote connect /dev/ttyUSB0 reset
```

---

## Step 5: Re-create Port Forwarding (WSL only)

WSL's internal IP changes on every PC reboot. Port forwarding must be
refreshed.

**Find the new WSL IP** (in WSL):

```bash
ip addr show eth0 | grep 'inet '
# Example: inet 172.27.167.162/20
```

**Update port forwarding** (in **Windows PowerShell Admin**):

```powershell
# Remove old rule
netsh interface portproxy delete v4tov4 listenport=18800 listenaddress=0.0.0.0

# Add new rule with updated WSL IP
netsh interface portproxy add v4tov4 listenport=18800 listenaddress=0.0.0.0 connectport=18800 connectaddress=172.27.167.162

# Verify
netsh interface portproxy show v4tov4
```

> Replace `172.27.167.162` with your actual WSL IP from above.

---

## Step 6: Start the Gateway

```bash
# Activate conda environment
conda activate embed_nanobot

# Start gateway with verbose logging
nanobot gateway -v 2>&1 | tee ~/gateway.log

# Or with enrollment (for new devices)
nanobot gateway --enroll -v 2>&1 | tee ~/gateway.log
```

---

## Known WiFi Networks

See the full table in [TESTING_GUIDE.md](TESTING_GUIDE.md#known-wifi-networks).

| Name | SSID | Password |
|------|------|----------|
| ShenZhen Home | PPAY | PP&AY1023 |
| DongGuan ZhongXi | 1704 | 17041014 |

---

## Troubleshooting

### ESP32 can't connect to WiFi
- Check SSID/password in `config.py` on the ESP32:
  ```bash
  mpremote connect /dev/ttyUSB0 cat :config.py
  ```
- ESP32 only supports **2.4 GHz** WiFi

### ESP32 connects to WiFi but not to hub
- **[Radxa 5T]**: Verify `HUB_IP = "192.168.5.199"` and gateway is running
- **[WSL2]**: Verify `HUB_IP` matches your current Windows WiFi IP and port forwarding is set up (Step 5)
- Check Windows Firewall allows port 18800 inbound (WSL2 only)
- Test connectivity: `python3 -c "import socket; s=socket.create_connection(('192.168.5.199',18800),3); print('OK')"`

### `/dev/ttyUSB0` not found
- **[Radxa 5T]**: Check cable is data-capable (not charge-only). No usbipd needed.
- **[WSL2]**: Re-attach USB via usbipd (Step 1). Try a different USB port.

### Port forwarding not working (WSL2 only)
- Must run PowerShell **as Administrator**
- WSL IP may have changed — check with `wsl hostname -I` from PowerShell
- Delete and re-create the rule (Step 5)

---

*Last updated: 2026-03-29*

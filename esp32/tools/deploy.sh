#!/usr/bin/env bash
# deploy.sh — Copy the mesh_client/ module directory to ESP32 via mpremote.
#
# Usage: bash esp32/tools/deploy.sh [PORT]
#   PORT defaults to /dev/ttyUSB0
#
# Requirements: pip install mpremote
#
# What this does:
#   1. Copies all .py files from esp32/mesh_client/ to the ESP32 filesystem root
#   2. Does NOT overwrite /psk.bin (your enrolled secret) if it already exists
#   3. Does NOT copy config.py if it already exists on the device (use --force-config)

set -e

PORT="${1:-/dev/ttyUSB0}"
FORCE_CONFIG="${FORCE_CONFIG:-0}"
CLIENT_DIR="esp32/mesh_client"

echo "==> Deploying mesh_client to ESP32 on $PORT"
echo ""

# Check mpremote is available
if ! command -v mpremote &>/dev/null; then
    echo "ERROR: mpremote not found. Install with: pip install mpremote"
    exit 1
fi

MPREMOTE=(mpremote connect "$PORT" resume)

interrupt_running_app() {
    python - "$PORT" <<'PY'
import sys
import time

try:
    import serial
except ImportError:
    sys.exit(2)

port = sys.argv[1]
ser = serial.Serial(port, 115200, timeout=0.2)
try:
    # Send Ctrl-C twice to break out of boot.py / main.run().
    ser.write(b"\r\x03\x03")
    time.sleep(0.5)
    ser.write(b"\r")
    time.sleep(0.2)
finally:
    ser.close()
PY
}

echo "==> Interrupting running app to enter REPL"
if interrupt_running_app; then
    echo "  -> ESP32 interrupted"
else
    rc=$?
    if [[ "$rc" == "2" ]]; then
        echo "  -- pyserial not installed; continuing with mpremote resume only"
    else
        echo "  -- interrupt failed; continuing with mpremote resume only"
    fi
fi
echo ""

# Files to copy (always)
ALWAYS_FILES=(
    protocol.py
    security.py
    enrollment.py
    transport.py
    device.py
    main.py
    boot.py
    boot_manager.py
    sdk.py
)

# Copy always-files
for f in "${ALWAYS_FILES[@]}"; do
    echo "  -> $f"
    "${MPREMOTE[@]}" cp "$CLIENT_DIR/$f" ":$f"
done

# Config: only copy if not already present OR if forced
if [[ "$FORCE_CONFIG" == "1" ]]; then
    echo "  -> config.py (forced)"
    "${MPREMOTE[@]}" cp "$CLIENT_DIR/config.py" ":config.py"
else
    # Check if config already exists on device
    if "${MPREMOTE[@]}" ls :/ 2>&1 | grep -q "config.py"; then
        echo "  -- config.py already exists on device (skipping, use FORCE_CONFIG=1 to overwrite)"
    else
        echo "  -> config.py (first deploy)"
        "${MPREMOTE[@]}" cp "$CLIENT_DIR/config.py" ":config.py"
    fi
fi

echo ""
echo "✓ Deploy complete."
echo ""
echo "Next steps:"
echo "  1. Open REPL:  mpremote connect $PORT repl"
echo "  2. First boot: >>> import main; main.run(enrollment_pin='YOUR_PIN')"
echo "  3. After enrollment the device will auto-start on future power-on (boot.py deployed)."

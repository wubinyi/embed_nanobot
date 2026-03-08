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

# Files to copy (always)
ALWAYS_FILES=(
    protocol.py
    security.py
    enrollment.py
    transport.py
    device.py
    main.py
)

# Copy always-files
for f in "${ALWAYS_FILES[@]}"; do
    echo "  -> $f"
    mpremote connect "$PORT" cp "$CLIENT_DIR/$f" ":$f"
done

# Config: only copy if not already present OR if forced
if [[ "$FORCE_CONFIG" == "1" ]]; then
    echo "  -> config.py (forced)"
    mpremote connect "$PORT" cp "$CLIENT_DIR/config.py" ":config.py"
else
    # Check if config already exists on device
    if mpremote connect "$PORT" ls :/ 2>&1 | grep -q "config.py"; then
        echo "  -- config.py already exists on device (skipping, use FORCE_CONFIG=1 to overwrite)"
    else
        echo "  -> config.py (first deploy)"
        mpremote connect "$PORT" cp "$CLIENT_DIR/config.py" ":config.py"
    fi
fi

echo ""
echo "✓ Deploy complete."
echo ""
echo "Next steps:"
echo "  1. Open REPL:  mpremote connect $PORT repl"
echo "  2. First boot: >>> import main; main.run(enrollment_pin='YOUR_PIN')"
echo "  3. After enrollment the device will run automatically on future boots."
echo ""
echo "To set auto-start on boot, run in REPL:"
echo "  >>> f = open('/boot.py','w'); f.write('import main\\nmain.run()\\n'); f.close()"

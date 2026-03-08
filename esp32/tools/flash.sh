#!/usr/bin/env bash
# flash.sh — Erase ESP32 flash and write MicroPython firmware.
#
# Usage: bash esp32/tools/flash.sh [PORT]
#   PORT defaults to /dev/ttyUSB0
#
# Requirements: pip install esptool
#
# Download the latest MicroPython .bin for ESP32 from:
#   https://micropython.org/download/ESP32_GENERIC/
# and place it in esp32/tools/firmware/ or pass FIRMWARE env var.

set -e

PORT="${1:-/dev/ttyUSB0}"
FIRMWARE="${FIRMWARE:-$(ls esp32/tools/firmware/ESP32_GENERIC*.bin 2>/dev/null | sort -V | tail -1)}"

if [[ -z "$FIRMWARE" ]]; then
    echo "ERROR: No MicroPython firmware found."
    echo ""
    echo "Download from: https://micropython.org/download/ESP32_GENERIC/"
    echo "Place the .bin file in: esp32/tools/firmware/"
    echo "Or: FIRMWARE=/path/to/firmware.bin bash esp32/tools/flash.sh"
    exit 1
fi

echo "==> Port:     $PORT"
echo "==> Firmware: $FIRMWARE"
echo ""

echo "==> Step 1: Erasing flash..."
esptool.py --chip esp32 --port "$PORT" erase_flash

echo "==> Step 2: Flashing MicroPython..."
esptool.py --chip esp32 --port "$PORT" --baud 460800 \
    write_flash -z 0x1000 "$FIRMWARE"

echo ""
echo "✓ Done. MicroPython flashed to $PORT"
echo "  Connect with: python3 -m serial.tools.miniterm $PORT 115200"
echo "  Or:           mpremote connect $PORT"

# boot.py — Auto-start the mesh client on ESP32 power-on.
#
# This file is deployed to the ESP32 root (/) by deploy.sh.
# It runs automatically after MicroPython initializes.
#
# To disable auto-start temporarily, create a flag file on the ESP32:
#   mpremote connect /dev/ttyUSB0 exec "open('/no_autostart','w').close()"
# To re-enable:
#   mpremote connect /dev/ttyUSB0 rm :no_autostart
#
# To remove boot.py entirely:
#   mpremote connect /dev/ttyUSB0 rm :boot.py

import time
import os

# Grace period: 3 seconds to press Ctrl-C (in REPL) or allow mpremote to connect
print("[boot] Auto-start in 3s... (Ctrl-C to cancel)")
time.sleep(3)

# Check for "no_autostart" flag file
try:
    os.stat("/no_autostart")
    print("[boot] Auto-start disabled (/no_autostart exists)")
except OSError:
    try:
        import main
        main.run()
    except KeyboardInterrupt:
        print("[boot] Interrupted — entering REPL")

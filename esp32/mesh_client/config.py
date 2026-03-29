# config.py — User configuration for ESP32 mesh client
# Copy this file to the ESP32 and edit before running.
# This file is the ONLY file you need to customize.

# ------------------------------------------------------------------
# WiFi credentials
# ------------------------------------------------------------------
WIFI_SSID     = "1704"
WIFI_PASSWORD = "17041014"
WIFI_TIMEOUT  = 20   # seconds to wait for connection

# ------------------------------------------------------------------
# Hub connection
# ------------------------------------------------------------------
HUB_IP   = "192.168.1.100"  # LAN IP of the machine running nanobot gateway
HUB_PORT = 18800             # Must match channels.mesh.tcpPort in hub config.json

# ------------------------------------------------------------------
# Device identity
# ------------------------------------------------------------------
NODE_ID  = "esp32-01"        # Unique name for this device (no spaces)

# ------------------------------------------------------------------
# Device capabilities
# Declare what this board can do — the hub uses this to route commands.
# Supported types: "switch", "sensor", "dimmer", "servo"
# Supported access: "read", "write", "read_write"
# ------------------------------------------------------------------
CAPABILITIES = [
    {
        "name":          "led",
        "type":          "switch",
        "access":        "write",
        "value_type":    "bool",
        "current_value": False,
        # GPIO pin for this capability (used by device.py)
        "gpio_pin":      2,    # GPIO2 = built-in LED on most ESP32 Dev Boards
    },
    # Uncomment to enable onboard temperature sensor reading via NTC or DS18B20
    # {
    #     "name":          "temperature",
    #     "type":          "sensor",
    #     "access":        "read",
    #     "value_type":    "float",
    #     "unit":          "celsius",
    #     "gpio_pin":      4,    # DS18B20 data pin
    # },
]

# ------------------------------------------------------------------
# Protocol settings (match hub defaults, do not change unless needed)
# ------------------------------------------------------------------
PING_INTERVAL_S    = 30   # Send a ping to hub every N seconds
RECONNECT_DELAY_S  = 5    # Wait before retrying on disconnect
FIRMWARE_VERSION   = "0.1.0"

"""transport.py — TCP connection management for the ESP32 mesh client.

Handles:
  - WiFi connection (with retry)
  - TCP socket connect / reconnect
  - Non-blocking receive loop
"""

import socket
import time
import network

import config as cfg
from protocol import build_envelope, encode, decode
import security


def connect_wifi() -> str:
    """Connect to WiFi. Returns the assigned IP address."""
    wlan = network.WLAN(network.STA_IF)
    if wlan.isconnected():
        return wlan.ifconfig()[0]

    print("[wifi] Connecting to", cfg.WIFI_SSID, "...")
    wlan.active(True)
    wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)

    deadline = time.time() + cfg.WIFI_TIMEOUT
    while not wlan.isconnected():
        if time.time() > deadline:
            raise OSError("WiFi connection timed out")
        time.sleep(0.5)

    ip = wlan.ifconfig()[0]
    print("[wifi] Connected. IP:", ip)
    return ip


def connect_hub() -> socket.socket:
    """Open a TCP connection to the hub. Returns the socket."""
    print("[transport] Connecting to hub at {}:{}".format(cfg.HUB_IP, cfg.HUB_PORT))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((cfg.HUB_IP, cfg.HUB_PORT))
    print("[transport] Hub connected")
    return sock


class MeshTransport:
    """Persistent transport with automatic reconnect.

    Usage::

        t = MeshTransport()
        t.start(psk)          # blocks: receive loop
    """

    def __init__(self):
        self._sock = None
        self._psk: bytes | None = None
        self._dispatch = None    # set by main to route incoming messages

    def set_dispatch(self, fn):
        """Register a callback: fn(envelope: dict, transport: MeshTransport)."""
        self._dispatch = fn

    def send(self, msg_type: str, target: str, payload: dict) -> None:
        """Send a signed envelope to the hub."""
        env = build_envelope(msg_type, cfg.NODE_ID, target, payload, self._psk)
        self._sock.sendall(encode(env))

    def start(self, psk: bytes) -> None:
        """Enter the main receive loop.  Only returns on unrecoverable error."""
        self._psk = psk
        last_ping = 0.0

        while True:
            try:
                if self._sock is None:
                    self._sock = connect_hub()
                    self._on_connect()

                # Periodic ping
                now = time.time()
                if now - last_ping > cfg.PING_INTERVAL_S:
                    self.send("ping", "hub-01", {})
                    last_ping = now

                # Non-blocking read with short timeout
                self._sock.settimeout(1.0)
                try:
                    env = decode(self._sock)
                    if self._dispatch:
                        self._dispatch(env, self)
                except OSError:
                    pass  # timeout — no message, that's fine

            except Exception as e:
                print("[transport] Error:", e, "— reconnecting in", cfg.RECONNECT_DELAY_S, "s")
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                self._sock = None
                time.sleep(cfg.RECONNECT_DELAY_S)

    def _on_connect(self):
        """Send STATE_REPORT immediately after connecting (or reconnecting)."""
        from device import get_state_report_payload
        self.send("state_report", "*", get_state_report_payload())
        print("[transport] STATE_REPORT sent")

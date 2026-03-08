"""main.py — Entry point for the ESP32 embed_nanobot mesh client.

This is the only file you run.  All other files in mesh_client/ are modules
imported by this file.

Startup sequence:
  1.  Connect to WiFi
  2a. If PSK exists in flash → load it, skip enrollment
  2b. If PSK missing → require enrollment_pin argument, call enroll()
  3.  Enter the persistent message receive loop (reconnects automatically)

Usage
-----
  # First boot (with enrollment PIN):
  import main
  main.run(enrollment_pin="482193")

  # Subsequent boots (PSK already saved to flash):
  import main
  main.run()             # <- also called automatically at boot via boot.py

Boot integration
----------------
Copy the following two lines into /boot.py on the ESP32 to auto-start on power-on:
  import main
  main.run()
"""

import config as cfg
import security
from transport import connect_wifi, MeshTransport
from device import execute_command, get_state_report_payload


# ------------------------------------------------------------------
# Message dispatch — routes hub messages to device actions
# ------------------------------------------------------------------

def _dispatch(envelope: dict, transport: MeshTransport) -> None:
    """Handle a single incoming message from the hub."""
    msg_type = envelope.get("type", "")
    payload  = envelope.get("payload", {})
    source   = envelope.get("source", "?")

    if msg_type == "ping":
        transport.send("pong", source, {})

    elif msg_type == "command":
        cap    = payload.get("capability", "")
        action = payload.get("action", "")
        value  = payload.get("value", None)
        print("[device] Command from hub: {} → {} = {}".format(cap, action, value))
        result = execute_command(cap, action, value)
        transport.send("response", source, {
            "capability": cap,
            "action":     action,
            **result,
        })

    elif msg_type == "ota_offer":
        _handle_ota_offer(payload, transport, source)

    elif msg_type == "pong":
        pass   # Hub replied to our ping — connection confirmed

    else:
        print("[mesh] Unhandled message type:", msg_type)


# ------------------------------------------------------------------
# OTA offer handler (stub — extend in Phase 5.2)
# ------------------------------------------------------------------

def _handle_ota_offer(payload: dict, transport: MeshTransport, source: str) -> None:
    """Respond to an OTA firmware offer from the hub.

    For now we always accept.  In Phase 5.2 this will verify the
    firmware signature before writing to the app partition.
    """
    fw_id   = payload.get("firmware_id", "")
    version = payload.get("version", "?")
    size    = payload.get("size", 0)
    sha256  = payload.get("sha256", "")

    print("[ota] Hub offers firmware {} (v{}, {} bytes)".format(fw_id, version, size))

    # Accept the offer
    transport.send("ota_accept", source, {"firmware_id": fw_id})

    # Chunks will follow as ota_chunk messages — handled in _dispatch
    # TODO (Phase 5.2): write chunks to app partition, verify SHA-256, reboot


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def run(enrollment_pin: str | None = None) -> None:
    """Start the mesh client.

    Parameters
    ----------
    enrollment_pin:
        Required only on the very first boot when no PSK is stored on flash.
        Get this PIN from the hub by running ``nanobot gateway --enroll``.
        After the first successful enrollment you can reboot without a PIN.
    """
    # Step 1: WiFi
    connect_wifi()

    # Step 2: PSK
    psk = security.load_psk()
    if psk is None:
        if enrollment_pin is None:
            raise RuntimeError(
                "No PSK found in flash. "
                "Run: main.run(enrollment_pin='123456') with the PIN from the hub."
            )
        from enrollment import enroll
        from transport import connect_hub
        sock = connect_hub()
        psk = enroll(sock, cfg.NODE_ID, enrollment_pin)
        sock.close()
        print("[main] Enrollment complete. Reconnecting with PSK...")

    # Step 3: Persistent receive loop
    transport = MeshTransport()
    transport.set_dispatch(_dispatch)
    transport.start(psk)

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
# OTA session state (module-level, persists across messages)
# ------------------------------------------------------------------
_ota = None   # dict with firmware_id, total_chunks, sha256, received, tmp_path


# ------------------------------------------------------------------
# Message dispatch — routes hub messages to device actions
# ------------------------------------------------------------------

def _dispatch(envelope, transport):
    """Handle a single incoming message from the hub."""
    msg_type = envelope.get("type", "")
    payload  = envelope.get("payload", {})
    source   = envelope.get("source", "?")

    if msg_type == "ping":
        transport.send("pong", source, {})

    elif msg_type == "command":
        cap    = payload.get("capability", "")
        action = payload.get("action", "")
        params = payload.get("params", {})
        value  = params.get("value", payload.get("value", None))
        # Map hub actions (set/get/toggle) to device actions (turn_on/turn_off/read/set_value)
        if action == "set" and isinstance(value, bool):
            action = "turn_on" if value else "turn_off"
        elif action == "set":
            action = "set_value"
        elif action == "get":
            action = "read"
        elif action == "toggle":
            # Read current state and invert
            from device import _state as dev_state
            cur = dev_state.get(cap, False)
            action = "turn_off" if cur else "turn_on"
        print("[device] Command from hub: {} -> {} = {}".format(cap, action, value))
        result = execute_command(cap, action, value)
        resp = {"capability": cap, "action": action}
        resp.update(result)
        transport.send("response", source, resp)

    elif msg_type == "ota_offer":
        _handle_ota_offer(payload, transport, source)

    elif msg_type == "ota_chunk":
        _handle_ota_chunk(payload, transport, source)

    elif msg_type == "ota_complete":
        _handle_ota_complete(payload, transport, source)

    elif msg_type == "ota_abort":
        _handle_ota_abort(payload, transport, source)

    elif msg_type == "pong":
        pass   # Hub replied to our ping — connection confirmed

    else:
        print("[mesh] Unhandled message type:", msg_type)


# ------------------------------------------------------------------
# OTA handlers
# ------------------------------------------------------------------

def _handle_ota_offer(payload, transport, source):
    """Respond to an OTA firmware offer from the hub."""
    global _ota

    fw_id   = payload.get("firmware_id", "")
    version = payload.get("version", "?")
    size    = payload.get("size", 0)
    sha256  = payload.get("sha256", "")
    total   = payload.get("total_chunks", 0)

    print("[ota] Hub offers firmware {} (v{}, {} bytes, {} chunks)".format(
        fw_id, version, size, total))

    # Clean up any previous OTA session
    _ota_cleanup()

    # Initialize OTA session state
    tmp_path = "_ota_" + fw_id.replace("/", "_")
    _ota = {
        "firmware_id":  fw_id,
        "total_chunks": total,
        "sha256":       sha256,
        "received":     0,
        "tmp_path":     tmp_path,
        "source":       source,
        "version":      version,
    }

    # Create (or truncate) temp file for firmware data
    f = open(tmp_path, "wb")
    f.close()

    # Accept the offer
    transport.send("ota_accept", source, {"firmware_id": fw_id})
    print("[ota] Accepted, waiting for chunks...")


def _handle_ota_chunk(payload, transport, source):
    """Receive a single OTA data chunk, write to flash, ACK back."""
    global _ota

    if _ota is None:
        print("[ota] Chunk received but no active OTA session — ignoring")
        return

    fw_id = payload.get("firmware_id", "")
    seq   = payload.get("seq", -1)
    total = payload.get("total_chunks", 0)
    data  = payload.get("data", "")

    if fw_id != _ota["firmware_id"]:
        print("[ota] Chunk firmware_id mismatch — ignoring")
        return

    # Decode base64 data
    import ubinascii
    chunk_bytes = ubinascii.a2b_base64(data)

    # Append to temp file
    f = open(_ota["tmp_path"], "ab")
    f.write(chunk_bytes)
    f.close()

    _ota["received"] = seq + 1
    print("[ota] Chunk {}/{} ({} bytes)".format(seq + 1, total, len(chunk_bytes)))

    # ACK this chunk
    transport.send("ota_chunk_ack", source, {"firmware_id": fw_id, "seq": seq})

    # If all chunks received, compute SHA-256 and send verify
    if _ota["received"] >= _ota["total_chunks"]:
        _ota_verify(transport, source)


def _ota_verify(transport, source):
    """Compute SHA-256 of received firmware and send ota_verify to hub."""
    import hashlib

    fw_id = _ota["firmware_id"]
    tmp_path = _ota["tmp_path"]
    print("[ota] All chunks received. Verifying SHA-256...")

    h = hashlib.sha256()
    f = open(tmp_path, "rb")
    while True:
        block = f.read(1024)
        if not block:
            break
        h.update(block)
    f.close()

    import ubinascii
    digest = ubinascii.hexlify(h.digest()).decode()
    print("[ota] Computed SHA-256: {}".format(digest[:16] + "..."))

    transport.send("ota_verify", source, {"firmware_id": fw_id, "sha256": digest})


def _handle_ota_complete(payload, transport, source):
    """Hub confirmed integrity. Apply the firmware and reset."""
    global _ota
    import os
    import machine as mach

    if _ota is None:
        print("[ota] Complete received but no active OTA session")
        return

    fw_id    = payload.get("firmware_id", "")
    tmp_path = _ota["tmp_path"]
    version  = _ota["version"]

    print("[ota] Hub verified OK — applying firmware {}".format(fw_id))

    # The firmware is a Python file — write it to /app.py
    # (Future: support multi-file packages, dual-partition)
    target_path = "app.py"
    try:
        # Remove old app.py if it exists
        try:
            os.remove(target_path)
        except OSError:
            pass
        os.rename(tmp_path, target_path)
        print("[ota] Firmware installed at {}".format(target_path))
    except Exception as e:
        print("[ota] Error installing firmware:", e)
        _ota_cleanup()
        return

    _ota = None
    print("[ota] OTA complete (v{}). Resetting in 2s...".format(version))
    import time
    time.sleep(2)
    mach.reset()


def _handle_ota_abort(payload, transport, source):
    """Hub aborted the OTA session. Clean up."""
    reason = payload.get("reason", "unknown")
    print("[ota] Hub aborted OTA: {}".format(reason))
    _ota_cleanup()


def _ota_cleanup():
    """Remove temp OTA file and clear session state."""
    global _ota
    if _ota is not None:
        try:
            import os
            os.remove(_ota["tmp_path"])
        except OSError:
            pass
    _ota = None


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def run(enrollment_pin=None):
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

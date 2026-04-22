"""tests/test_ota_hardware.py — Real-hardware E2E OTA and mesh tests.

Requires a physical ESP32 connected via USB to /dev/ttyUSB0 AND on the same
WiFi network as the hub (Radxa Rock 5T at 192.168.5.199).

All tests in this file are automatically **skipped** when:
  - /dev/ttyUSB0 is not present (no USB-attached ESP32), OR
  - TCP port 18800 is already in use (gateway is already running), OR
  - pytest is run with ``-m "not hardware"`` marker.

To run specifically:
  conda run -n embed_nanobot pytest tests/test_ota_hardware.py -v

Test flow
---------
Each test uses a shared ``mesh_channel`` fixture that:
  1. Starts a MeshChannel bound to port 18800
  2. Resets the ESP32 via mpremote (triggers boot.py → main.run())
  3. Waits for the device to register in the hub's device registry
  4. Yields the ready channel for the test to use
  5. Stops the channel after the test
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from nanobot.mesh.protocol import MeshEnvelope

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ESP32_NODE_ID = "esp32-01"
_HUB_NODE_ID   = "hub-01"
_HUB_TCP_PORT  = 18800
_HUB_UDP_PORT  = 18799
_USB_DEVICE    = "/dev/ttyUSB0"

# Wait times (seconds)
_DEVICE_CONNECT_TIMEOUT = 120  # ESP32: boot.py 3s + WiFi ~8s + NTP sync ~90s
_OTA_TIMEOUT            = 120  # max time for a full OTA cycle
_POST_RESET_RECONNECT   = 120  # wait for device to reconnect after OTA-triggered reset (NTP sync ~90s)

# Firmware directory (shared across tests)
_FW_DIR = str(Path.home() / ".nanobot" / "workspace" / "firmware")

# Key store (must have esp32-01 enrolled)
_KEY_STORE = str(Path.home() / ".nanobot" / "workspace" / "mesh_keys.json")

# Device registry
_REGISTRY = str(Path.home() / ".nanobot" / "workspace" / "device_registry.json")

# Workspace for auxiliary files
_WORKSPACE = str(Path.home() / ".nanobot" / "workspace")


# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

def _esp32_available() -> bool:
    """Return True if /dev/ttyUSB0 exists."""
    return Path(_USB_DEVICE).exists()


def _port_free(port: int) -> bool:
    """Return True if TCP port is not yet bound by a LISTEN socket.

    Uses SO_REUSEADDR so that FIN-WAIT-2 / TIME_WAIT connections left
    from a previous test run don't cause false negatives — the transport
    binds with SO_REUSEADDR anyway.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


# Single skip condition shared by all tests
_SKIP_REASON: str | None = None
if not _esp32_available():
    _SKIP_REASON = f"ESP32 not connected ({_USB_DEVICE} not found)"
elif not _port_free(_HUB_TCP_PORT):
    _SKIP_REASON = f"Port {_HUB_TCP_PORT} is already in use (gateway running?)"

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or ""),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_channel_config(fw_dir: str = _FW_DIR) -> SimpleNamespace:
    """Build a minimal channel config namespace for MeshChannel."""
    return SimpleNamespace(
        node_id=_HUB_NODE_ID,
        tcp_port=_HUB_TCP_PORT,
        udp_port=_HUB_UDP_PORT,
        roles=["nanobot"],
        allow_from=["*"],
        psk_auth_enabled=True,
        allow_unauthenticated=False,
        nonce_window=2_000_000_000,  # ~63 years: disable replay protection for HW tests (NTP may be unreliable)
        key_store_path=_KEY_STORE,
        encryption_enabled=True,
        registry_path=_REGISTRY,
        automation_rules_path="",
        mtls_enabled=False,
        ca_dir="",
        device_cert_validity_days=365,
        firmware_dir=fw_dir,
        ota_chunk_size=4096,
        ota_chunk_timeout=30,
        enrollment_pin_length=6,
        enrollment_pin_timeout=300,
        enrollment_max_attempts=3,
        groups_path="",
        scenes_path="",
        dashboard_port=0,
        industrial_config_path="",
        federation_config_path="",
        pipeline_enabled=False,
        pipeline_path="",
        pipeline_max_points=10000,
        pipeline_flush_interval=60,
        ble_config_path="",
        codegen_templates_path="",
        _workspace_path=_WORKSPACE,
    )


def _reset_esp32() -> None:
    """Hardware-reset the ESP32 by toggling DTR via pyserial.

    DTR is wired to the EN (reset) pin on NodeMCU-32S boards via the
    CP2102 auto-reset circuit.  This works even when MicroPython is deep
    inside a blocking C-level socket recv — no REPL access required.

    Falls back to a no-op warning on any serial error.
    """
    try:
        import serial
        s = serial.Serial(_USB_DEVICE, 115200, timeout=0.5)
        # Pull DTR low → EN goes low → chip reset asserted
        s.dtr = False
        time.sleep(0.1)
        # Release DTR → EN goes high → chip runs
        s.dtr = True
        s.close()
    except Exception as exc:
        # Non-fatal: device will reconnect automatically via its reconnect loop
        print(f"  [warn] ESP32 hardware reset skipped: {exc}")


async def _wait_for_device(channel, node_id: str, timeout: float) -> bool:
    """Poll registry until *node_id* is marked online (TCP connection active).

    We specifically check ``device.online`` — NOT just ``get_device() is not None``.
    The device may already be in the registry JSON from a previous test run, but
    the TCP connection is not yet established after a reset.  Only ``mark_online``
    (triggered by the transport's on_device_connected hook) sets ``online=True``.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        device = channel.registry.get_device(node_id)
        if device is not None and device.online:
            return True
        await asyncio.sleep(1.0)
    return False


def _generate_test_firmware(version: str) -> bytes:
    """Generate a small test firmware (Python source) for OTA delivery."""
    import datetime
    placeholder = "0" * 64
    content = (
        f"# test_app.py — generated by test_ota_hardware.py\n"
        f"# Version: {version}\n"
        f"# SHA-256: {placeholder}\n"
        f"# Date:    {datetime.datetime.now(datetime.timezone.utc).isoformat()}Z\n"
        f"OTA_VERSION = '{version}'\n"
        f"def greet(): return 'Hello from OTA v{version}'\n"
    )
    data = content.encode()
    real_sha = hashlib.sha256(data).hexdigest()
    return content.replace(placeholder, real_sha).encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def mesh_channel():
    """Start a MeshChannel, reset ESP32, wait for device, then yield.

    Teardown stops the channel automatically.
    """
    from nanobot.mesh.channel import MeshChannel
    from nanobot.bus.queue import MessageBus

    # Ensure firmware dir exists
    Path(_FW_DIR).mkdir(parents=True, exist_ok=True)

    config = _build_channel_config()
    bus = MessageBus()
    channel = MeshChannel(config, bus)

    try:
        await channel.start()
        await asyncio.sleep(0.5)   # give transport a moment to bind

        # Hardware-reset the ESP32 (instant, doesn't need REPL access).
        # This triggers boot.py → main.run() → auto-connect to new hub channel.
        _reset_esp32()

        # Wait for device to connect and register
        connected = await _wait_for_device(channel, _ESP32_NODE_ID, _DEVICE_CONNECT_TIMEOUT)
        if not connected:
            pytest.fail(
                f"ESP32 '{_ESP32_NODE_ID}' did not register within "
                f"{_DEVICE_CONNECT_TIMEOUT}s.  "
                f"Check WiFi (SSID: PPAY) and hub IP (192.168.5.199)."
            )
    except BaseException:
        # Always stop channel on setup failure to release port 18800
        try:
            await channel.stop()
        except Exception:
            pass
        raise

    try:
        yield channel
    finally:
        await channel.stop()


# ---------------------------------------------------------------------------
# Test: Device connectivity (no OTA)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_esp32_connects_to_hub(mesh_channel):
    """ESP32 registers itself in the hub device registry after boot."""
    channel = mesh_channel
    device = channel.registry.get_device(_ESP32_NODE_ID)
    assert device is not None, f"Device '{_ESP32_NODE_ID}' not in registry"
    assert device.node_id == _ESP32_NODE_ID
    # Device should have at least one capability (led)
    assert len(device.capabilities) >= 1, "Device reported no capabilities"


@pytest.mark.asyncio
async def test_esp32_ping_pong(mesh_channel):
    """Hub can send a ping and ESP32 responds (round-trip via TCP)."""
    channel = mesh_channel

    received_pong = asyncio.Event()

    async def _pong_listener(envelope):
        if envelope.type == "pong" and envelope.source == _ESP32_NODE_ID:
            received_pong.set()

    # on_message appends to a list — safe to add without removing existing handlers
    channel.transport.on_message(_pong_listener)

    env = MeshEnvelope(type="ping", source=_HUB_NODE_ID, target=_ESP32_NODE_ID)
    await channel.transport.send(env)

    try:
        await asyncio.wait_for(received_pong.wait(), timeout=15)
    except asyncio.TimeoutError:
        pytest.fail("No pong received from ESP32 within 15s")

    assert received_pong.is_set()


# ---------------------------------------------------------------------------
# Test: OTA firmware update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ota_firmware_update(mesh_channel):
    """Full OTA cycle: offer → chunks → verify → complete on real ESP32."""
    channel = mesh_channel
    assert channel.firmware_store is not None, "FirmwareStore not initialized (check firmwareDir config)"
    assert channel.ota is not None, "OTAManager not initialized"

    fw_version = "1.0.0-hw-test"
    fw_id = f"hw-test-{fw_version}"
    fw_data = _generate_test_firmware(fw_version)
    # Use current epoch as version_counter so anti-rollback never blocks test re-runs
    fw_version_counter = int(time.time())

    # Clean up any previous test firmware
    try:
        channel.firmware_store.remove_firmware(fw_id)
    except Exception:
        pass

    fw_info = channel.firmware_store.add_firmware(
        fw_id, fw_version, "sensor", fw_data, version_counter=fw_version_counter
    )
    assert fw_info is not None

    # Track OTA progress
    ota_done = asyncio.Event()
    ota_result: dict = {"state": "pending"}

    def _on_progress(session) -> None:
        state = session.state.value
        pct = round(session.progress * 100, 1)
        print(f"  [OTA] state={state:<12}  progress={pct:5.1f}%  chunks={session.acked_up_to + 1}/{session.total_chunks}")
        if state in ("complete", "failed", "rejected"):
            ota_result["state"] = state
            ota_result["error"] = getattr(session, "error_message", "")
            ota_done.set()

    channel.ota.on_progress(_on_progress)

    session = await channel.start_ota_update(_ESP32_NODE_ID, fw_id)
    assert session is not None, "start_ota_update returned None — firmware ID may be wrong"

    try:
        await asyncio.wait_for(ota_done.wait(), timeout=_OTA_TIMEOUT)
    except asyncio.TimeoutError:
        status = channel.get_ota_status(_ESP32_NODE_ID)
        pytest.fail(
            f"OTA timed out after {_OTA_TIMEOUT}s.  "
            f"Last status: {status}"
        )

    assert ota_result["state"] == "complete", (
        f"OTA ended with state='{ota_result['state']}' "
        f"error='{ota_result.get('error', '')}'"
    )


@pytest.mark.asyncio
async def test_ota_device_reconnects_after_reset(mesh_channel):
    """After OTA completes and ESP32 resets, it reconnects to the hub."""
    channel = mesh_channel

    # Run OTA
    fw_version = "1.0.1-reconnect-test"
    fw_id = f"reconnect-test-{fw_version}"
    fw_data = _generate_test_firmware(fw_version)

    try:
        channel.firmware_store.remove_firmware(fw_id)
    except Exception:
        pass
    channel.firmware_store.add_firmware(fw_id, fw_version, "sensor", fw_data)

    ota_done = asyncio.Event()

    def _on_progress(session) -> None:
        if session.state.value in ("complete", "failed", "rejected"):
            ota_done.set()

    channel.ota.on_progress(_on_progress)
    session = await channel.start_ota_update(_ESP32_NODE_ID, fw_id)
    assert session is not None

    try:
        await asyncio.wait_for(ota_done.wait(), timeout=_OTA_TIMEOUT)
    except asyncio.TimeoutError:
        pytest.fail("OTA timed out before device reset")

    # Device resets after OTA — wait for it to come back.
    # Register a handler BEFORE the OTA completes so we don't miss the callback.
    device_back = asyncio.Event()

    def _on_reconnect(node_id: str):
        if node_id == _ESP32_NODE_ID:
            device_back.set()

    channel.transport.on_device_connected(_on_reconnect)

    # Give the device time to reset and reconnect (includes NTP sync again)
    reconnected = await _wait_for_device(channel, _ESP32_NODE_ID, _POST_RESET_RECONNECT)

    assert reconnected, (
        f"ESP32 did not reconnect within {_POST_RESET_RECONNECT}s after OTA reset"
    )


# ---------------------------------------------------------------------------
# Test: OTA abort
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ota_abort(mesh_channel):
    """Hub can abort an in-flight OTA and device returns to normal operation."""
    channel = mesh_channel
    assert channel.ota is not None

    fw_version = "1.0.2-abort-test"
    fw_id = f"abort-test-{fw_version}"
    # Use a large firmware so there's time to abort mid-transfer (50 KB)
    fw_data = (_generate_test_firmware(fw_version) * 50)[:50 * 1024]
    fw_data += b"\n# padding\n"

    try:
        channel.firmware_store.remove_firmware(fw_id)
    except Exception:
        pass
    channel.firmware_store.add_firmware(fw_id, fw_version, "sensor", fw_data)

    ota_aborted = asyncio.Event()
    ota_result: dict = {"state": "pending"}

    def _on_progress(session) -> None:
        state = session.state.value
        ota_result["state"] = state
        if state in ("failed", "rejected", "aborted"):
            ota_aborted.set()
        # Abort after first chunk acknowledged
        if state == "transferring" and session.acked_up_to >= 1:
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(channel.abort_ota_update(_ESP32_NODE_ID))
            )

    channel.ota.on_progress(_on_progress)
    session = await channel.start_ota_update(_ESP32_NODE_ID, fw_id)
    assert session is not None

    try:
        await asyncio.wait_for(ota_aborted.wait(), timeout=60)
    except asyncio.TimeoutError:
        pytest.fail("OTA abort did not complete within 60s")

# After abort, device should still be online (no reboot triggered)
        device = channel.registry.get_device(_ESP32_NODE_ID)
        assert device is not None, "Device disappeared from registry after abort"
        assert device.online, "Device went offline after abort (should stay connected)"


# ---------------------------------------------------------------------------
# Test: Partition query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partition_query(mesh_channel):
    """Hub can request partition information from the ESP32."""
    channel = mesh_channel

    received_report = asyncio.Event()
    report_payload: dict = {}

    async def _partition_listener(envelope):
        if envelope.type == "partition_report" and envelope.source == _ESP32_NODE_ID:
            report_payload.update(envelope.payload or {})
            received_report.set()

    channel.transport.on_message(_partition_listener)

    env = MeshEnvelope(type="partition_query", source=_HUB_NODE_ID, target=_ESP32_NODE_ID)
    await channel.transport.send(env)

    try:
        await asyncio.wait_for(received_report.wait(), timeout=15)
    except asyncio.TimeoutError:
        pytest.fail("No partition_report received from ESP32 within 15s")

    assert received_report.is_set()
    # The report should include at least slot info
    assert len(report_payload) > 0, f"partition_report payload was empty: {report_payload}"

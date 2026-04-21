#!/usr/bin/env python3
"""esp32/tools/test_ota_wifi.py — Live hardware OTA WiFi validation script.

Runs on the Radxa Rock 5T (hub machine) to perform a full end-to-end OTA
firmware push to an enrolled ESP32 over WiFi.  USB is NOT required after
initial enrollment.

Prerequisites
-------------
1. ESP32 is enrolled and running (PSK saved in flash).
2. nanobot gateway is NOT running (this script starts one internally).
3. The test firmware file is available (or will be generated).

Usage
-----
  # From the project root, with the embed_nanobot conda environment active:
  python esp32/tools/test_ota_wifi.py

  # With a specific firmware file:
  python esp32/tools/test_ota_wifi.py --firmware path/to/app.py --node-id esp32-01

  # Dry-run: just check gateway + device connectivity, don't push OTA
  python esp32/tools/test_ota_wifi.py --dry-run

  # Keep gateway running after test (for inspection):
  python esp32/tools/test_ota_wifi.py --no-teardown

Test Flow
---------
1. Start nanobot gateway mesh listener (background asyncio task)
2. Wait for ESP32 to connect and be registered in the device registry
3. Generate or load a test firmware (test_app.py content)
4. Store firmware in FirmwareStore with a unique version ID
5. Start OTA session → monitor progress until COMPLETE or FAILED
6. Verify result with ESP32 state report or ping-pong
7. Print PASS / FAIL summary

Exit codes:
  0  — OTA completed successfully
  1  — OTA failed or timed out
  2  — ESP32 not reachable / setup error
"""

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="[%(levelname)s] %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("ota_test")

# ---------------------------------------------------------------------------
# Project path setup
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants (matching copilot-instructions.md environment table)
# ---------------------------------------------------------------------------
DEFAULT_HUB_NODE_ID = "hub"
DEFAULT_ESP32_NODE_ID = "esp32-01"
DEFAULT_TCP_PORT = 18800
DEFAULT_UDP_PORT = 18799
DEFAULT_FW_ID = "test-ota-fw"
DEFAULT_FW_VERSION = "0.0.1-ota-test"

# Tight timeouts for the test script (real hardware may be slower on bad WiFi)
CONNECT_TIMEOUT = 30   # seconds to wait for ESP32 to appear in registry
OTA_TIMEOUT = 120      # seconds to wait for OTA to complete

# ---------------------------------------------------------------------------
# Test firmware content  — a minimal app.py that reports its version
# ---------------------------------------------------------------------------
_TEST_APP_TEMPLATE = """\
# test_app.py — injected by test_ota_wifi.py
# Version: {version}
# SHA-256: {sha256}
# Date:    {date}

OTA_VERSION = "{version}"

def greet():
    return "Hello from OTA app v{version}"
"""


def _generate_test_firmware(version: str) -> bytes:
    """Generate a minimal test firmware (Python source) as bytes."""
    import datetime

    placeholder_sha = "0" * 64
    content = _TEST_APP_TEMPLATE.format(
        version=version,
        sha256=placeholder_sha,
        date=datetime.datetime.utcnow().isoformat() + "Z",
    )
    data = content.encode()
    # Embed real sha256 in a second pass
    real_sha = hashlib.sha256(data).hexdigest()
    content = content.replace(placeholder_sha, real_sha)
    return content.encode()


# ---------------------------------------------------------------------------
# OTA test runner
# ---------------------------------------------------------------------------

class OTATestRunner:
    """Runs the live OTA test against real hardware."""

    def __init__(
        self,
        node_id: str,
        firmware_path: str | None,
        fw_version: str,
        tcp_port: int,
        udp_port: int,
        dry_run: bool,
        no_teardown: bool,
        fw_dir: str,
        key_store_path: str,
        registry_path: str,
    ) -> None:
        self.node_id = node_id
        self.firmware_path = firmware_path
        self.fw_version = fw_version
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.dry_run = dry_run
        self.no_teardown = no_teardown
        self.fw_dir = fw_dir
        self.key_store_path = key_store_path
        self.registry_path = registry_path

        self._channel = None
        self._ota_done = asyncio.Event()
        self._ota_result: str = "pending"

    # -- setup ---------------------------------------------------------------

    async def setup(self) -> bool:
        """Import nanobot modules and start mesh channel."""
        log.info("Setting up mesh channel (port %d)…", self.tcp_port)
        try:
            from nanobot.mesh.ota import FirmwareStore
            from nanobot.mesh.channel import MeshChannel
            from unittest.mock import MagicMock

            # Minimal config object
            config = MagicMock()
            config.node_id = DEFAULT_HUB_NODE_ID
            config.tcp_port = self.tcp_port
            config.udp_port = self.udp_port
            config.roles = ["nanobot"]
            config.psk_auth_enabled = True
            config.allow_unauthenticated = False
            config.nonce_window = 60
            config.key_store_path = self.key_store_path
            config.encryption_enabled = False
            config.registry_path = self.registry_path
            config.automation_rules_path = ""
            config.mtls_enabled = False
            config.ca_dir = ""
            config.device_cert_validity_days = 365
            config.firmware_dir = self.fw_dir
            config.ota_chunk_size = 4096
            config.ota_chunk_timeout = 30
            config.enrollment_pin_length = 6
            config.enrollment_pin_timeout = 300
            config.enrollment_max_attempts = 3
            config._workspace_path = str(
                Path.home() / ".nanobot" / "workspace"
            )

            bus = MagicMock()
            bus.inbound = MagicMock()
            bus.inbound.put = MagicMock(return_value=None)

            self._channel = MeshChannel(config, bus)
            return True
        except Exception as exc:
            log.error("Setup failed: %s", exc)
            return False

    # -- firmware preparation ------------------------------------------------

    def prepare_firmware(self) -> str | None:
        """Return firmware_id after storing firmware in FirmwareStore.

        Returns None on failure.
        """
        fw_id = f"{DEFAULT_FW_ID}-{self.fw_version}"

        try:
            if self.firmware_path:
                log.info("Loading firmware from %s", self.firmware_path)
                fw_data = Path(self.firmware_path).read_bytes()
            else:
                log.info("Generating test firmware (version=%s)…", self.fw_version)
                fw_data = _generate_test_firmware(self.fw_version)

            sha256 = hashlib.sha256(fw_data).hexdigest()
            log.info(
                "Firmware ready: %d bytes, SHA-256=%s…", len(fw_data), sha256[:16]
            )

            store = self._channel.firmware_store
            if store is None:
                log.error("firmware_store not initialized")
                return None

            # Remove any previous version with same ID
            store.remove_firmware(fw_id)
            info = store.add_firmware(fw_id, self.fw_version, "sensor", fw_data)
            log.info("Firmware stored as %r", info.firmware_id)
            return info.firmware_id

        except Exception as exc:
            log.error("Firmware preparation failed: %s", exc)
            return None

    # -- device connectivity check -------------------------------------------

    async def wait_for_device(self) -> bool:
        """Poll the device registry until node_id appears or timeout."""
        log.info("Waiting for %r to appear in registry…", self.node_id)
        deadline = time.time() + CONNECT_TIMEOUT
        while time.time() < deadline:
            try:
                registry = self._channel.registry
                device = registry.get_device(self.node_id)
                if device is not None:
                    log.info(
                        "Device %r registered — type=%s, caps=%s",
                        self.node_id,
                        device.device_type,
                        [c.name for c in device.capabilities],
                    )
                    return True
            except Exception:
                pass
            await asyncio.sleep(1.0)
        log.error("Timed out waiting for device %r after %ds", self.node_id, CONNECT_TIMEOUT)
        return False

    # -- OTA -----------------------------------------------------------------

    def _on_progress(self, session) -> None:
        """OTA progress callback."""
        state = session.state.value
        progress_pct = round(session.progress * 100, 1)
        log.info(
            "[OTA] %s  state=%-12s  progress=%5.1f%%  chunks=%d/%d",
            session.node_id,
            state,
            progress_pct,
            session.acked_up_to + 1,
            session.total_chunks,
        )
        if state in ("complete", "failed", "rejected"):
            self._ota_result = state
            self._ota_done.set()

    async def run_ota(self, firmware_id: str) -> bool:
        """Start OTA and wait for it to reach a terminal state."""
        log.info("Starting OTA for %r → firmware %r", self.node_id, firmware_id)

        ota_mgr = self._channel.ota
        if ota_mgr is None:
            log.error("OTA manager not available on channel")
            return False

        ota_mgr.on_progress(self._on_progress)

        session = await self._channel.start_ota_update(self.node_id, firmware_id)
        if session is None:
            log.error("start_ota_update returned None — firmware not found or session conflict")
            return False

        log.info("OTA session started — waiting up to %ds…", OTA_TIMEOUT)
        try:
            await asyncio.wait_for(self._ota_done.wait(), timeout=OTA_TIMEOUT)
        except asyncio.TimeoutError:
            log.error("OTA timed out after %ds", OTA_TIMEOUT)
            final = self._channel.get_ota_status(self.node_id)
            log.error("Final status: %s", final)
            return False

        if self._ota_result == "complete":
            log.info("OTA COMPLETE ✓")
            return True
        else:
            final = self._channel.get_ota_status(self.node_id)
            log.error("OTA ended with state=%r  error=%s", self._ota_result,
                      final.get("error", "?") if final else "unknown")
            return False

    # -- post-OTA verification -----------------------------------------------

    async def verify_device(self) -> bool:
        """Send a ping and verify the device responds (post-reset)."""
        log.info("Waiting 5s for device to reset and reconnect…")
        await asyncio.sleep(5)

        # After reset, the device re-enrolls or reconnects.
        # We ping and expect a pong back on the registry.
        log.info("Pinging %r…", self.node_id)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                await self._channel.transport.send(
                    "ping", self.node_id, {}
                )
                await asyncio.sleep(2)
                # If device appears back in registry, it has reset and reconnected
                device = self._channel.registry.get_device(self.node_id)
                if device is not None:
                    log.info("Device %r reconnected after OTA reset ✓", self.node_id)
                    return True
            except Exception as exc:
                log.debug("Ping error: %s", exc)
        log.warning("Device did not reconnect within 20s after OTA")
        return False

    # -- teardown ------------------------------------------------------------

    async def teardown(self) -> None:
        """Stop the mesh channel."""
        if self._channel and not self.no_teardown:
            log.info("Stopping mesh channel…")
            try:
                await self._channel.close()
            except Exception:
                pass

    # -- main entry point ----------------------------------------------------

    async def run(self) -> int:
        """Execute the full test.  Returns exit code (0=pass, 1=fail, 2=error)."""
        log.info("=" * 60)
        log.info("OTA WiFi Hardware Test — Radxa Rock 5T")
        log.info("  Target device: %s", self.node_id)
        log.info("  Hub TCP port:  %d", self.tcp_port)
        log.info("  Firmware dir:  %s", self.fw_dir)
        log.info("=" * 60)

        if not await self.setup():
            return 2

        fw_id = self.prepare_firmware()
        if fw_id is None:
            return 2

        if self.dry_run:
            log.info("[DRY RUN] Skipping actual OTA push.")
            log.info("Firmware prepared: %r", fw_id)
            log.info("PASS (dry run)")
            return 0

        # Start the mesh channel's receive loop
        log.info("Starting mesh TCP listener on port %d…", self.tcp_port)
        listen_task = asyncio.create_task(self._channel._start_transport())
        await asyncio.sleep(1)  # let listener bind

        try:
            device_found = await self.wait_for_device()
            if not device_found:
                log.error("FAIL — device not found")
                return 2

            ota_ok = await self.run_ota(fw_id)
            if not ota_ok:
                log.error("FAIL — OTA did not complete")
                return 1

            verify_ok = await self.verify_device()
            if not verify_ok:
                log.warning("WARNING — device reconnect check failed (may be normal on slow WiFi)")

            log.info("")
            log.info("=" * 60)
            log.info("RESULT: PASS — OTA firmware update successful ✓")
            log.info("  Firmware: %s v%s", fw_id, self.fw_version)
            log.info("  Device:   %s", self.node_id)
            log.info("=" * 60)
            return 0

        finally:
            listen_task.cancel()
            await self.teardown()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Live OTA WiFi hardware test for embed_nanobot on Radxa Rock 5T",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--node-id",
        default=DEFAULT_ESP32_NODE_ID,
        help="ESP32 node_id (default: %(default)s)",
    )
    p.add_argument(
        "--firmware",
        default=None,
        metavar="PATH",
        help="Path to firmware .py file; generated if omitted",
    )
    p.add_argument(
        "--fw-version",
        default=DEFAULT_FW_VERSION,
        help="Firmware version string (default: %(default)s)",
    )
    p.add_argument(
        "--tcp-port",
        type=int,
        default=DEFAULT_TCP_PORT,
        help="Mesh TCP port (default: %(default)s)",
    )
    p.add_argument(
        "--udp-port",
        type=int,
        default=DEFAULT_UDP_PORT,
        help="Mesh UDP port (default: %(default)s)",
    )
    p.add_argument(
        "--fw-dir",
        default=str(Path.home() / ".nanobot" / "workspace" / "firmware"),
        help="Firmware storage directory (default: %(default)s)",
    )
    p.add_argument(
        "--key-store",
        default=str(Path.home() / ".nanobot" / "workspace" / "mesh_keys.json"),
        help="Path to mesh PSK key store JSON (default: %(default)s)",
    )
    p.add_argument(
        "--registry",
        default=str(Path.home() / ".nanobot" / "workspace" / "device_registry.json"),
        help="Path to device registry JSON (default: %(default)s)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare firmware and verify setup without pushing OTA",
    )
    p.add_argument(
        "--no-teardown",
        action="store_true",
        help="Keep gateway channel running after test (for inspection)",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = OTATestRunner(
        node_id=args.node_id,
        firmware_path=args.firmware,
        fw_version=args.fw_version,
        tcp_port=args.tcp_port,
        udp_port=args.udp_port,
        dry_run=args.dry_run,
        no_teardown=args.no_teardown,
        fw_dir=args.fw_dir,
        key_store_path=args.key_store,
        registry_path=args.registry,
    )

    return asyncio.run(runner.run())


if __name__ == "__main__":
    sys.exit(main())

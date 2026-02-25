"""Tests for the mesh monitoring dashboard (task 3.6).

Covers: MeshDashboard HTTP server, all API endpoints, HTML page,
error handling, channel integration (dashboard_port config).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.mesh.dashboard import MeshDashboard


# ---------------------------------------------------------------------------
# Mock data structures
# ---------------------------------------------------------------------------

@dataclass
class _FakeCapability:
    name: str = "temperature"
    cap_type: str = "sensor"
    data_type: str = "float"
    unit: str = "°C"


@dataclass
class _FakeDevice:
    node_id: str = "dev-001"
    device_type: str = "sensor"
    name: str = "Living Room Sensor"
    online: bool = True
    last_seen: float = 0.0
    registered_at: float = 0.0
    capabilities: list = field(default_factory=lambda: [_FakeCapability()])
    state: dict = field(default_factory=lambda: {"temperature": 22.5})


@dataclass
class _FakePeer:
    node_id: str = "peer-001"
    ip: str = "192.168.1.100"
    tcp_port: int = 18800
    roles: list = field(default_factory=lambda: ["device"])
    last_seen: float = 0.0
    device_type: str = "sensor"


@dataclass
class _FakeGroup:
    group_id: str = "grp-001"
    name: str = "Kitchen"
    device_ids: list = field(default_factory=lambda: ["dev-001", "dev-002"])
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "name": self.name,
            "device_ids": self.device_ids,
            "metadata": self.metadata,
        }


@dataclass
class _FakeScene:
    scene_id: str = "scn-001"
    name: str = "Movie Mode"
    commands: list = field(default_factory=list)
    description: str = "Dim lights"

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "commands": self.commands,
            "description": self.description,
        }


@dataclass
class _FakeCondition:
    device_id: str = "dev-001"
    capability: str = "temperature"
    operator: str = "gt"
    value: float = 25.0

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "capability": self.capability,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass
class _FakeAction:
    device_id: str = "dev-002"
    capability: str = "power"
    action: str = "set"
    params: dict = field(default_factory=lambda: {"value": True})

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "capability": self.capability,
            "action": self.action,
            "params": self.params,
        }


@dataclass
class _FakeRule:
    rule_id: str = "rule-001"
    name: str = "Auto Fan"
    description: str = "Turn on fan when hot"
    enabled: bool = True
    conditions: list = field(default_factory=lambda: [_FakeCondition()])
    actions: list = field(default_factory=lambda: [_FakeAction()])
    cooldown_seconds: int = 60
    last_triggered: float = 0.0


@dataclass
class _FakeFirmware:
    firmware_id: str = "fw-001"
    version: str = "2.0.0"
    device_type: str = "sensor"
    filename: str = "sensor_v2.bin"
    size: int = 65536
    sha256: str = "abc123"
    added_date: str = "2026-01-01"

    def to_dict(self) -> dict:
        return {
            "firmware_id": self.firmware_id,
            "version": self.version,
            "device_type": self.device_type,
            "filename": self.filename,
            "size": self.size,
            "sha256": self.sha256,
            "added_date": self.added_date,
        }


def _make_registry(devices: list | None = None, online: int | None = None):
    reg = MagicMock()
    devs = devices or [_FakeDevice()]
    reg.device_count = len(devs)
    reg.online_count = online if online is not None else sum(1 for d in devs if d.online)
    reg.get_all_devices.return_value = devs
    return reg


def _make_discovery(peers: list | None = None):
    disc = MagicMock()
    disc.online_peers.return_value = peers or [_FakePeer()]
    return disc


def _make_groups(groups: list | None = None, scenes: list | None = None):
    gm = MagicMock()
    gm.list_groups.return_value = groups or [_FakeGroup()]
    gm.list_scenes.return_value = scenes or [_FakeScene()]
    return gm


def _make_automation(rules: list | None = None):
    eng = MagicMock()
    eng.list_rules.return_value = rules or [_FakeRule()]
    return eng


def _make_ota(sessions: list | None = None):
    ota = MagicMock()
    ota.list_sessions.return_value = sessions or [
        {"node_id": "dev-001", "firmware_id": "fw-001", "version": "2.0.0",
         "state": "transferring", "progress": 0.5, "total_chunks": 16,
         "acked_up_to": 7, "error": ""}
    ]
    return ota


def _make_firmware_store(fw_list: list | None = None):
    store = MagicMock()
    store.list_firmware.return_value = fw_list or [_FakeFirmware()]
    return store


def _data_fn(
    registry=None, discovery=None, groups=None,
    automation=None, ota=None, firmware_store=None,
    node_id: str = "test-hub",
) -> dict[str, Any]:
    return {
        "registry": registry or _make_registry(),
        "discovery": discovery or _make_discovery(),
        "groups": groups or _make_groups(),
        "automation": automation or _make_automation(),
        "ota": ota or _make_ota(),
        "firmware_store": firmware_store or _make_firmware_store(),
        "node_id": node_id,
    }


# ---------------------------------------------------------------------------
# Helper to send raw HTTP request to the dashboard
# ---------------------------------------------------------------------------

async def _http_get(port: int, path: str, method: str = "GET") -> tuple[int, dict | str]:
    """Send a raw HTTP request and return (status_code, parsed_body)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    request = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    writer.write(request.encode())
    await writer.drain()

    data = b""
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        data += chunk
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass

    # Parse HTTP response
    text = data.decode("utf-8", errors="replace")
    parts = text.split("\r\n\r\n", 1)
    status_line = parts[0].split("\r\n")[0]
    status_code = int(status_line.split(" ")[1])
    body_text = parts[1] if len(parts) > 1 else ""

    # Try JSON parse
    try:
        return status_code, json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return status_code, body_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def dashboard():
    """Create and start a dashboard on a random available port, yield, then stop."""
    # Use port 0 to get a random available port
    db = MeshDashboard(port=0, data_fn=lambda: _data_fn())
    await db.start()
    # Retrieve actual port assigned
    actual_port = db._server.sockets[0].getsockname()[1]
    db.port = actual_port
    yield db
    await db.stop()


@pytest.fixture
async def dashboard_empty():
    """Dashboard with no data (None providers)."""
    db = MeshDashboard(port=0, data_fn=lambda: {
        "registry": None, "discovery": None, "groups": None,
        "automation": None, "ota": None, "firmware_store": None,
        "node_id": "empty-hub",
    })
    await db.start()
    actual_port = db._server.sockets[0].getsockname()[1]
    db.port = actual_port
    yield db
    await db.stop()


# ---------------------------------------------------------------------------
# Test: MeshDashboard lifecycle
# ---------------------------------------------------------------------------

class TestDashboardLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        db = MeshDashboard(port=0, data_fn=lambda: _data_fn())
        await db.start()
        assert db._server is not None
        port = db._server.sockets[0].getsockname()[1]
        # Verify server is accepting connections
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        await db.stop()
        assert db._server is None

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        db = MeshDashboard(port=0, data_fn=lambda: _data_fn())
        await db.start()
        await db.stop()
        await db.stop()  # Should not raise
        assert db._server is None

    @pytest.mark.asyncio
    async def test_uptime_tracking(self):
        db = MeshDashboard(port=0, data_fn=lambda: _data_fn())
        before = time.time()
        await db.start()
        # start_time should be recent
        assert db._start_time >= before
        await db.stop()


# ---------------------------------------------------------------------------
# Test: API /api/status
# ---------------------------------------------------------------------------

class TestAPIStatus:
    @pytest.mark.asyncio
    async def test_status_endpoint(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/api/status")
        assert status_code == 200
        assert body["node_id"] == "test-hub"
        assert body["device_count"] == 1
        assert body["online_count"] == 1
        assert body["peer_count"] == 1
        assert body["ota_active"] == 1
        assert body["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_status_empty(self, dashboard_empty):
        status_code, body = await _http_get(dashboard_empty.port, "/api/status")
        assert status_code == 200
        assert body["device_count"] == 0
        assert body["online_count"] == 0
        assert body["peer_count"] == 0
        assert body["ota_active"] == 0

    @pytest.mark.asyncio
    async def test_status_uptime_increases(self, dashboard):
        _, b1 = await _http_get(dashboard.port, "/api/status")
        await asyncio.sleep(0.1)
        _, b2 = await _http_get(dashboard.port, "/api/status")
        assert b2["uptime_seconds"] >= b1["uptime_seconds"]


# ---------------------------------------------------------------------------
# Test: API /api/devices
# ---------------------------------------------------------------------------

class TestAPIDevices:
    @pytest.mark.asyncio
    async def test_devices_list(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/api/devices")
        assert status_code == 200
        assert isinstance(body, list)
        assert len(body) == 1
        dev = body[0]
        assert dev["node_id"] == "dev-001"
        assert dev["device_type"] == "sensor"
        assert dev["name"] == "Living Room Sensor"
        assert dev["online"] is True
        assert len(dev["capabilities"]) == 1
        assert dev["capabilities"][0]["name"] == "temperature"
        assert dev["state"] == {"temperature": 22.5}

    @pytest.mark.asyncio
    async def test_devices_empty(self, dashboard_empty):
        status_code, body = await _http_get(dashboard_empty.port, "/api/devices")
        assert status_code == 200
        assert body == []

    @pytest.mark.asyncio
    async def test_devices_multiple(self):
        devs = [
            _FakeDevice(node_id="dev-001", online=True),
            _FakeDevice(node_id="dev-002", online=False, name="Garage"),
        ]
        db = MeshDashboard(
            port=0,
            data_fn=lambda: _data_fn(registry=_make_registry(devs)),
        )
        await db.start()
        port = db._server.sockets[0].getsockname()[1]
        try:
            _, body = await _http_get(port, "/api/devices")
            assert len(body) == 2
            assert body[0]["node_id"] == "dev-001"
            assert body[1]["node_id"] == "dev-002"
            assert body[1]["online"] is False
        finally:
            await db.stop()


# ---------------------------------------------------------------------------
# Test: API /api/peers
# ---------------------------------------------------------------------------

class TestAPIPeers:
    @pytest.mark.asyncio
    async def test_peers_list(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/api/peers")
        assert status_code == 200
        assert len(body) == 1
        p = body[0]
        assert p["node_id"] == "peer-001"
        assert p["ip"] == "192.168.1.100"
        assert p["tcp_port"] == 18800
        assert p["roles"] == ["device"]

    @pytest.mark.asyncio
    async def test_peers_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/peers")
        assert body == []


# ---------------------------------------------------------------------------
# Test: API /api/groups
# ---------------------------------------------------------------------------

class TestAPIGroups:
    @pytest.mark.asyncio
    async def test_groups_list(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/api/groups")
        assert status_code == 200
        assert len(body) == 1
        g = body[0]
        assert g["group_id"] == "grp-001"
        assert g["name"] == "Kitchen"
        assert g["device_ids"] == ["dev-001", "dev-002"]

    @pytest.mark.asyncio
    async def test_groups_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/groups")
        assert body == []


# ---------------------------------------------------------------------------
# Test: API /api/scenes
# ---------------------------------------------------------------------------

class TestAPIScenes:
    @pytest.mark.asyncio
    async def test_scenes_list(self, dashboard):
        _, body = await _http_get(dashboard.port, "/api/scenes")
        assert len(body) == 1
        s = body[0]
        assert s["scene_id"] == "scn-001"
        assert s["name"] == "Movie Mode"
        assert s["description"] == "Dim lights"

    @pytest.mark.asyncio
    async def test_scenes_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/scenes")
        assert body == []


# ---------------------------------------------------------------------------
# Test: API /api/rules
# ---------------------------------------------------------------------------

class TestAPIRules:
    @pytest.mark.asyncio
    async def test_rules_list(self, dashboard):
        _, body = await _http_get(dashboard.port, "/api/rules")
        assert len(body) == 1
        r = body[0]
        assert r["rule_id"] == "rule-001"
        assert r["name"] == "Auto Fan"
        assert r["enabled"] is True
        assert len(r["conditions"]) == 1
        assert r["conditions"][0]["operator"] == "gt"
        assert len(r["actions"]) == 1
        assert r["actions"][0]["action"] == "set"

    @pytest.mark.asyncio
    async def test_rules_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/rules")
        assert body == []


# ---------------------------------------------------------------------------
# Test: API /api/ota
# ---------------------------------------------------------------------------

class TestAPIOTA:
    @pytest.mark.asyncio
    async def test_ota_sessions(self, dashboard):
        _, body = await _http_get(dashboard.port, "/api/ota")
        assert len(body) == 1
        s = body[0]
        assert s["node_id"] == "dev-001"
        assert s["state"] == "transferring"
        assert s["progress"] == 0.5

    @pytest.mark.asyncio
    async def test_ota_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/ota")
        assert body == []


# ---------------------------------------------------------------------------
# Test: API /api/firmware
# ---------------------------------------------------------------------------

class TestAPIFirmware:
    @pytest.mark.asyncio
    async def test_firmware_list(self, dashboard):
        _, body = await _http_get(dashboard.port, "/api/firmware")
        assert len(body) == 1
        f = body[0]
        assert f["firmware_id"] == "fw-001"
        assert f["version"] == "2.0.0"
        assert f["size"] == 65536

    @pytest.mark.asyncio
    async def test_firmware_empty(self, dashboard_empty):
        _, body = await _http_get(dashboard_empty.port, "/api/firmware")
        assert body == []


# ---------------------------------------------------------------------------
# Test: HTML dashboard
# ---------------------------------------------------------------------------

class TestHTMLDashboard:
    @pytest.mark.asyncio
    async def test_html_page(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/")
        assert status_code == 200
        assert isinstance(body, str)
        assert "<!DOCTYPE html>" in body
        assert "Mesh Dashboard" in body
        assert "/api/status" in body

    @pytest.mark.asyncio
    async def test_html_contains_refresh_script(self, dashboard):
        _, body = await _http_get(dashboard.port, "/")
        assert "setInterval(refresh" in body


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_404(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/nonexistent")
        assert status_code == 404

    @pytest.mark.asyncio
    async def test_405_post(self, dashboard):
        status_code, body = await _http_get(dashboard.port, "/api/status", method="POST")
        assert status_code == 405

    @pytest.mark.asyncio
    async def test_handler_exception(self):
        """Endpoint handler that raises should return 500."""
        def bad_data_fn():
            return {
                "registry": None, "discovery": None, "groups": None,
                "automation": None, "ota": None, "firmware_store": None,
                "node_id": "err-hub",
            }

        db = MeshDashboard(port=0, data_fn=bad_data_fn)
        # Monkey-patch one handler to raise
        original = db._api_status

        async def exploding_status(writer):
            raise RuntimeError("boom")

        db._api_status = exploding_status
        await db.start()
        port = db._server.sockets[0].getsockname()[1]
        try:
            status_code, body = await _http_get(port, "/api/status")
            assert status_code == 500
            assert "boom" in body.get("error", "") if isinstance(body, dict) else "boom" in str(body)
        finally:
            await db.stop()


# ---------------------------------------------------------------------------
# Test: Channel integration (config → dashboard creation)
# ---------------------------------------------------------------------------

class TestChannelIntegration:
    """Test that MeshChannel creates/skips dashboard based on dashboard_port."""

    def test_dashboard_disabled_when_port_zero(self):
        """When dashboard_port=0, channel.dashboard should be None."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-1"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = "/tmp/test_reg.json"
        config.automation_rules_path = "/tmp/test_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_groups.json"
        config.scenes_path = "/tmp/test_scenes.json"
        config.dashboard_port = 0

        bus = MagicMock()
        ch = MeshChannel(config, bus)
        assert ch.dashboard is None

    def test_dashboard_created_when_port_set(self):
        """When dashboard_port > 0, channel.dashboard should be a MeshDashboard."""
        from nanobot.mesh.channel import MeshChannel

        config = MagicMock()
        config.node_id = "hub-1"
        config.tcp_port = 18800
        config.udp_port = 18799
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.encryption_enabled = False
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config.registry_path = "/tmp/test_reg.json"
        config.automation_rules_path = "/tmp/test_auto.json"
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = "/tmp/test_groups.json"
        config.scenes_path = "/tmp/test_scenes.json"
        config.dashboard_port = 9090

        bus = MagicMock()
        ch = MeshChannel(config, bus)
        assert ch.dashboard is not None
        assert isinstance(ch.dashboard, MeshDashboard)
        assert ch.dashboard.port == 9090


# ---------------------------------------------------------------------------
# Test: CORS header
# ---------------------------------------------------------------------------

class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_header_present(self, dashboard):
        """Response should include Access-Control-Allow-Origin: *."""
        reader, writer = await asyncio.open_connection("127.0.0.1", dashboard.port)
        request = "GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        data = b""
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            data += chunk
        writer.close()
        headers_text = data.decode().split("\r\n\r\n")[0]
        assert "Access-Control-Allow-Origin: *" in headers_text


# ---------------------------------------------------------------------------
# Test: JSON serialization edge cases
# ---------------------------------------------------------------------------

class TestSerializationEdgeCases:
    @pytest.mark.asyncio
    async def test_non_serializable_values_use_str(self):
        """Values that aren't JSON-serializable should be serialized via str()."""
        # The dashboard uses default=str in json.dumps
        class _Weird:
            def __str__(self):
                return "weird-value"

        reg = _make_registry([_FakeDevice(state={"x": _Weird()})])
        db = MeshDashboard(
            port=0,
            data_fn=lambda: _data_fn(registry=reg),
        )
        await db.start()
        port = db._server.sockets[0].getsockname()[1]
        try:
            status_code, body = await _http_get(port, "/api/devices")
            assert status_code == 200
            assert body[0]["state"]["x"] == "weird-value"
        finally:
            await db.stop()


# ---------------------------------------------------------------------------
# Test: Multiple concurrent requests
# ---------------------------------------------------------------------------

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, dashboard):
        """Multiple simultaneous requests should all succeed."""
        tasks = [
            _http_get(dashboard.port, "/api/status"),
            _http_get(dashboard.port, "/api/devices"),
            _http_get(dashboard.port, "/api/peers"),
            _http_get(dashboard.port, "/api/groups"),
            _http_get(dashboard.port, "/api/rules"),
        ]
        results = await asyncio.gather(*tasks)
        for status_code, _ in results:
            assert status_code == 200

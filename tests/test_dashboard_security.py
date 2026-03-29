"""Tests for dashboard security features (task 5.3.3).

Tests TLS config, bearer token authentication, and CORS origin config
added to MeshDashboard.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.mesh.dashboard import MeshDashboard


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _data_fn() -> dict:
    """Minimal data function for dashboard."""
    reg = MagicMock()
    reg.list_devices.return_value = []
    disc = MagicMock()
    disc.peers = {}
    groups = MagicMock()
    groups.list_groups.return_value = []
    groups.list_scenes.return_value = []
    auto = MagicMock()
    auto.rules = {}
    return {
        "registry": reg,
        "discovery": disc,
        "groups": groups,
        "automation": auto,
        "ota": None,
        "firmware_store": None,
        "node_id": "test-hub",
        "pipeline": None,
    }


async def _http_get(port: int, path: str = "/api/status",
                    auth_token: str = "", use_ssl: bool = False) -> tuple[int, str]:
    """Make a raw HTTP GET request and return (status_code, body)."""
    ssl_ctx = None
    if use_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ssl_ctx)
    headers = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    if auth_token:
        headers += f"Authorization: Bearer {auth_token}\r\n"
    headers += "\r\n"
    writer.write(headers.encode())
    await writer.drain()

    response = await asyncio.wait_for(reader.read(8192), timeout=5.0)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass

    decoded = response.decode("utf-8", errors="replace")
    # Parse status line
    first_line = decoded.split("\r\n")[0]
    status = int(first_line.split(" ")[1])
    # Parse body (after double newline)
    body = decoded.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in decoded else ""
    return status, body


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


class TestDashboardConstructor:
    def test_default_no_auth(self):
        d = MeshDashboard(port=0, data_fn=_data_fn)
        assert d._auth_token == ""
        assert d._tls_cert == ""
        assert d._cors_origin == "*"

    def test_with_auth_token(self):
        d = MeshDashboard(port=0, data_fn=_data_fn, auth_token="secret123")
        assert d._auth_token == "secret123"

    def test_with_tls_config(self):
        d = MeshDashboard(port=0, data_fn=_data_fn,
                          tls_cert="/path/cert.pem", tls_key="/path/key.pem")
        assert d._tls_cert == "/path/cert.pem"
        assert d._tls_key == "/path/key.pem"

    def test_custom_cors(self):
        d = MeshDashboard(port=0, data_fn=_data_fn, cors_origin="https://example.com")
        assert d._cors_origin == "https://example.com"


# ---------------------------------------------------------------------------
# Auth tests (require a running server)
# ---------------------------------------------------------------------------


class TestBearerTokenAuth:
    @pytest.mark.asyncio
    async def test_no_auth_required(self):
        """Without auth_token configured, all requests pass."""
        d = MeshDashboard(port=0, data_fn=_data_fn)
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            status, body = await _http_get(port, "/api/status")
            assert status == 200
        finally:
            await d.stop()

    @pytest.mark.asyncio
    async def test_auth_required_no_token(self):
        """With auth_token, request without token gets 401."""
        d = MeshDashboard(port=0, data_fn=_data_fn, auth_token="my-secret")
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            status, _ = await _http_get(port, "/api/status")
            assert status == 401
        finally:
            await d.stop()

    @pytest.mark.asyncio
    async def test_auth_required_wrong_token(self):
        """With auth_token, wrong token gets 403."""
        d = MeshDashboard(port=0, data_fn=_data_fn, auth_token="my-secret")
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            status, _ = await _http_get(port, "/api/status", auth_token="wrong")
            assert status == 403
        finally:
            await d.stop()

    @pytest.mark.asyncio
    async def test_auth_required_correct_token(self):
        """With auth_token, correct token gets 200."""
        d = MeshDashboard(port=0, data_fn=_data_fn, auth_token="my-secret")
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            status, body = await _http_get(port, "/api/status", auth_token="my-secret")
            assert status == 200
            data = json.loads(body)
            assert "node_id" in data
        finally:
            await d.stop()


# ---------------------------------------------------------------------------
# CORS tests
# ---------------------------------------------------------------------------


class TestCORSConfig:
    @pytest.mark.asyncio
    async def test_default_cors_star(self):
        """Default CORS is '*'."""
        d = MeshDashboard(port=0, data_fn=_data_fn)
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /api/status HTTP/1.1\r\nHost: test\r\n\r\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            writer.close()
            headers = resp.decode().split("\r\n\r\n")[0]
            assert "Access-Control-Allow-Origin: *" in headers
        finally:
            await d.stop()

    @pytest.mark.asyncio
    async def test_custom_cors(self):
        """Custom CORS origin reflected in response."""
        d = MeshDashboard(port=0, data_fn=_data_fn,
                          cors_origin="https://dashboard.example.com")
        await d.start()
        port = d._server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /api/status HTTP/1.1\r\nHost: test\r\n\r\n")
            await writer.drain()
            resp = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            writer.close()
            headers = resp.decode().split("\r\n\r\n")[0]
            assert "Access-Control-Allow-Origin: https://dashboard.example.com" in headers
        finally:
            await d.stop()


# ---------------------------------------------------------------------------
# TLS config tests (no cert files needed — just config validation)
# ---------------------------------------------------------------------------


class TestTLSConfig:
    def test_tls_fields_stored(self):
        d = MeshDashboard(
            port=0, data_fn=_data_fn,
            tls_cert="/tmp/cert.pem", tls_key="/tmp/key.pem",
        )
        assert d._tls_cert == "/tmp/cert.pem"
        assert d._tls_key == "/tmp/key.pem"


# ---------------------------------------------------------------------------
# Config schema tests
# ---------------------------------------------------------------------------


class TestSchemaFields:
    def test_dashboard_security_defaults(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig()
        assert cfg.dashboard_tls_cert == ""
        assert cfg.dashboard_tls_key == ""
        assert cfg.dashboard_auth_token == ""
        assert cfg.dashboard_cors_origin == "*"

    def test_dashboard_security_custom(self):
        from nanobot.config.schema import MeshConfig
        cfg = MeshConfig(
            dashboard_tls_cert="/certs/cert.pem",
            dashboard_tls_key="/certs/key.pem",
            dashboard_auth_token="super-secret",
            dashboard_cors_origin="https://my.dashboard",
        )
        assert cfg.dashboard_tls_cert == "/certs/cert.pem"
        assert cfg.dashboard_auth_token == "super-secret"
        assert cfg.dashboard_cors_origin == "https://my.dashboard"

"""Lightweight monitoring dashboard for the mesh network.

Provides a zero-dependency HTTP server (stdlib asyncio only) with:
- JSON API endpoints for devices, peers, groups, rules, OTA, firmware
- Embedded single-page HTML dashboard

Start via ``MeshDashboard.start()`` inside the channel's event loop.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from loguru import logger


class MeshDashboard:
    """Async HTTP server exposing mesh status as JSON + HTML.

    Parameters
    ----------
    port:
        TCP port to listen on.
    data_fn:
        Callable that returns a dict of data providers:
        ``{"registry": ..., "discovery": ..., "groups": ...,
           "automation": ..., "ota": ..., "firmware_store": ...,
           "node_id": str}``
    """

    def __init__(self, port: int, data_fn: Callable[[], dict[str, Any]]) -> None:
        self.port = port
        self._data_fn = data_fn
        self._server: asyncio.AbstractServer | None = None
        self._start_time = time.time()

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self._start_time = time.time()
        self._server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self.port,
        )
        logger.info("[Dashboard] started on http://0.0.0.0:{}", self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("[Dashboard] stopped")

    # -- HTTP handling -------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            if not data:
                writer.close()
                return

            request_line = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
            parts = request_line.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, "text/plain", b"Bad Request")
                return

            method, raw_path = parts[0], parts[1]
            parsed = urlparse(raw_path)
            path = parsed.path

            if method != "GET":
                await self._send_response(writer, 405, "text/plain", b"Method Not Allowed")
                return

            await self._route(writer, path)

        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        except Exception as exc:
            logger.debug("[Dashboard] request error: {}", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route(self, writer: asyncio.StreamWriter, path: str) -> None:
        routes: dict[str, Callable] = {
            "/": self._html_dashboard,
            "/api/status": self._api_status,
            "/api/devices": self._api_devices,
            "/api/peers": self._api_peers,
            "/api/groups": self._api_groups,
            "/api/scenes": self._api_scenes,
            "/api/rules": self._api_rules,
            "/api/ota": self._api_ota,
            "/api/firmware": self._api_firmware,
        }

        handler = routes.get(path)
        if handler is None:
            await self._send_response(writer, 404, "text/plain", b"Not Found")
            return

        try:
            await handler(writer)
        except Exception as exc:
            logger.warning("[Dashboard] handler error for {}: {}", path, exc)
            await self._send_response(
                writer, 500, "application/json",
                json.dumps({"error": str(exc)}).encode(),
            )

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        content_type: str,
        body: bytes,
    ) -> None:
        status_text = {200: "OK", 400: "Bad Request", 404: "Not Found",
                       405: "Method Not Allowed", 500: "Internal Server Error"}
        header = (
            f"HTTP/1.1 {status} {status_text.get(status, 'Error')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        writer.write(header.encode() + body)
        await writer.drain()

    async def _send_json(self, writer: asyncio.StreamWriter, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        await self._send_response(writer, 200, "application/json", body)

    # -- Data helpers --------------------------------------------------------

    def _get_data(self) -> dict[str, Any]:
        return self._data_fn()

    # -- API endpoints -------------------------------------------------------

    async def _api_status(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        registry = d.get("registry")
        discovery = d.get("discovery")
        ota = d.get("ota")

        status = {
            "node_id": d.get("node_id", ""),
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "device_count": registry.device_count if registry else 0,
            "online_count": registry.online_count if registry else 0,
            "peer_count": len(discovery.online_peers()) if discovery else 0,
            "ota_active": len([
                s for s in (ota.list_sessions() if ota else [])
                if s.get("state") in ("offered", "transferring", "verifying")
            ]),
        }
        await self._send_json(writer, status)

    async def _api_devices(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        registry = d.get("registry")
        if registry is None:
            await self._send_json(writer, [])
            return
        devices = []
        for dev in registry.get_all_devices():
            devices.append({
                "node_id": dev.node_id,
                "device_type": dev.device_type,
                "name": dev.name,
                "online": dev.online,
                "last_seen": dev.last_seen,
                "registered_at": dev.registered_at,
                "capabilities": [
                    {
                        "name": c.name,
                        "type": c.cap_type,
                        "data_type": c.data_type,
                        "unit": c.unit,
                    }
                    for c in dev.capabilities
                ],
                "state": dev.state,
            })
        await self._send_json(writer, devices)

    async def _api_peers(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        discovery = d.get("discovery")
        if discovery is None:
            await self._send_json(writer, [])
            return
        peers = []
        for p in discovery.online_peers():
            peers.append({
                "node_id": p.node_id,
                "ip": p.ip,
                "tcp_port": p.tcp_port,
                "roles": p.roles,
                "last_seen": p.last_seen,
                "device_type": p.device_type,
            })
        await self._send_json(writer, peers)

    async def _api_groups(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        groups = d.get("groups")
        if groups is None:
            await self._send_json(writer, [])
            return
        await self._send_json(writer, [g.to_dict() for g in groups.list_groups()])

    async def _api_scenes(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        groups = d.get("groups")
        if groups is None:
            await self._send_json(writer, [])
            return
        await self._send_json(writer, [s.to_dict() for s in groups.list_scenes()])

    async def _api_rules(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        automation = d.get("automation")
        if automation is None:
            await self._send_json(writer, [])
            return
        rules = []
        for r in automation.list_rules():
            rules.append({
                "rule_id": r.rule_id,
                "name": r.name,
                "description": r.description,
                "enabled": r.enabled,
                "conditions": [c.to_dict() for c in r.conditions],
                "actions": [a.to_dict() for a in r.actions],
                "cooldown_seconds": r.cooldown_seconds,
                "last_triggered": r.last_triggered,
            })
        await self._send_json(writer, rules)

    async def _api_ota(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        ota = d.get("ota")
        if ota is None:
            await self._send_json(writer, [])
            return
        await self._send_json(writer, ota.list_sessions())

    async def _api_firmware(self, writer: asyncio.StreamWriter) -> None:
        d = self._get_data()
        store = d.get("firmware_store")
        if store is None:
            await self._send_json(writer, [])
            return
        await self._send_json(writer, [f.to_dict() for f in store.list_firmware()])

    # -- HTML dashboard ------------------------------------------------------

    async def _html_dashboard(self, writer: asyncio.StreamWriter) -> None:
        html = _DASHBOARD_HTML.encode("utf-8")
        await self._send_response(writer, 200, "text/html; charset=utf-8", html)


# ---------------------------------------------------------------------------
# Embedded HTML dashboard
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mesh Dashboard</title>
<style>
  :root { --bg: #0f1117; --card: #1a1d27; --border: #2a2d37; --text: #e0e0e0;
          --dim: #888; --accent: #4fc3f7; --green: #66bb6a; --red: #ef5350;
          --orange: #ffa726; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: var(--bg); color: var(--text); padding: 20px; }
  h1 { color: var(--accent); margin-bottom: 8px; font-size: 1.5em; }
  .subtitle { color: var(--dim); font-size: 0.85em; margin-bottom: 20px; }
  .stats { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
  .stat { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 16px 24px; min-width: 140px; }
  .stat .value { font-size: 2em; font-weight: bold; color: var(--accent); }
  .stat .label { color: var(--dim); font-size: 0.8em; text-transform: uppercase; }
  .section { margin-bottom: 24px; }
  .section h2 { color: var(--accent); font-size: 1.1em; margin-bottom: 8px;
                 border-bottom: 1px solid var(--border); padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; background: var(--card);
          border-radius: 8px; overflow: hidden; }
  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
  th { background: var(--border); color: var(--dim); font-size: 0.8em;
       text-transform: uppercase; }
  td { font-size: 0.9em; }
  .online { color: var(--green); }
  .offline { color: var(--red); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
           font-size: 0.75em; font-weight: bold; }
  .badge-green { background: rgba(102,187,106,0.2); color: var(--green); }
  .badge-red { background: rgba(239,83,80,0.2); color: var(--red); }
  .badge-orange { background: rgba(255,167,38,0.2); color: var(--orange); }
  .badge-blue { background: rgba(79,195,247,0.2); color: var(--accent); }
  .empty { color: var(--dim); font-style: italic; padding: 12px; }
  #error { color: var(--red); display: none; padding: 8px; margin-bottom: 12px;
           background: rgba(239,83,80,0.1); border-radius: 4px; }
</style>
</head>
<body>
<h1>&#x1f310; Mesh Dashboard</h1>
<div class="subtitle" id="info">Loading...</div>
<div id="error"></div>

<div class="stats" id="stats"></div>

<div class="section" id="devices-section">
  <h2>Devices</h2>
  <div id="devices">Loading...</div>
</div>

<div class="section" id="peers-section">
  <h2>Network Peers</h2>
  <div id="peers">Loading...</div>
</div>

<div class="section" id="groups-section">
  <h2>Groups</h2>
  <div id="groups">Loading...</div>
</div>

<div class="section" id="rules-section">
  <h2>Automation Rules</h2>
  <div id="rules">Loading...</div>
</div>

<div class="section" id="ota-section">
  <h2>OTA Updates</h2>
  <div id="ota">Loading...</div>
</div>

<script>
const API = '';
let refreshInterval = 5000;

async function fetchJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

function timeAgo(ts) {
  if (!ts) return 'never';
  const d = Date.now() / 1000 - ts;
  if (d < 60) return Math.round(d) + 's ago';
  if (d < 3600) return Math.round(d / 60) + 'm ago';
  if (d < 86400) return Math.round(d / 3600) + 'h ago';
  return Math.round(d / 86400) + 'd ago';
}

function badge(text, cls) {
  return `<span class="badge badge-${cls}">${text}</span>`;
}

function statusBadge(online) {
  return online ? badge('Online', 'green') : badge('Offline', 'red');
}

async function refresh() {
  try {
    const [status, devices, peers, groups, rules, ota] = await Promise.all([
      fetchJSON('/api/status'),
      fetchJSON('/api/devices'),
      fetchJSON('/api/peers'),
      fetchJSON('/api/groups'),
      fetchJSON('/api/rules'),
      fetchJSON('/api/ota'),
    ]);
    document.getElementById('error').style.display = 'none';
    renderStatus(status);
    renderDevices(devices);
    renderPeers(peers);
    renderGroups(groups);
    renderRules(rules);
    renderOTA(ota);
  } catch (e) {
    const el = document.getElementById('error');
    el.textContent = 'Failed to fetch: ' + e.message;
    el.style.display = 'block';
  }
}

function renderStatus(s) {
  document.getElementById('info').textContent =
    `Hub: ${s.node_id} | Uptime: ${Math.round(s.uptime_seconds / 60)}m | Refreshing every ${refreshInterval/1000}s`;
  document.getElementById('stats').innerHTML = [
    {v: s.device_count, l: 'Devices'},
    {v: s.online_count, l: 'Online'},
    {v: s.peer_count, l: 'Peers'},
    {v: s.ota_active, l: 'OTA Active'},
  ].map(x => `<div class="stat"><div class="value">${x.v}</div><div class="label">${x.l}</div></div>`).join('');
}

function renderDevices(devs) {
  if (!devs.length) { document.getElementById('devices').innerHTML = '<div class="empty">No devices registered</div>'; return; }
  let h = '<table><tr><th>Name</th><th>Node ID</th><th>Type</th><th>Status</th><th>Capabilities</th><th>Last Seen</th></tr>';
  for (const d of devs) {
    const caps = d.capabilities.map(c => c.name).join(', ') || '-';
    h += `<tr><td>${d.name||d.node_id}</td><td>${d.node_id}</td><td>${d.device_type}</td>
          <td>${statusBadge(d.online)}</td><td>${caps}</td><td>${timeAgo(d.last_seen)}</td></tr>`;
  }
  document.getElementById('devices').innerHTML = h + '</table>';
}

function renderPeers(peers) {
  if (!peers.length) { document.getElementById('peers').innerHTML = '<div class="empty">No peers discovered</div>'; return; }
  let h = '<table><tr><th>Node ID</th><th>IP</th><th>Port</th><th>Roles</th><th>Last Seen</th></tr>';
  for (const p of peers) {
    h += `<tr><td>${p.node_id}</td><td>${p.ip}</td><td>${p.tcp_port}</td>
          <td>${p.roles.join(', ')}</td><td>${timeAgo(p.last_seen)}</td></tr>`;
  }
  document.getElementById('peers').innerHTML = h + '</table>';
}

function renderGroups(groups) {
  if (!groups.length) { document.getElementById('groups').innerHTML = '<div class="empty">No groups defined</div>'; return; }
  let h = '<table><tr><th>Name</th><th>ID</th><th>Devices</th></tr>';
  for (const g of groups) {
    h += `<tr><td>${g.name}</td><td>${g.group_id}</td><td>${(g.device_ids||[]).join(', ')||'-'}</td></tr>`;
  }
  document.getElementById('groups').innerHTML = h + '</table>';
}

function renderRules(rules) {
  if (!rules.length) { document.getElementById('rules').innerHTML = '<div class="empty">No automation rules</div>'; return; }
  let h = '<table><tr><th>Name</th><th>Status</th><th>Conditions</th><th>Actions</th><th>Last Triggered</th></tr>';
  for (const r of rules) {
    const st = r.enabled ? badge('Active', 'green') : badge('Disabled', 'red');
    const conds = r.conditions.length + ' condition' + (r.conditions.length !== 1 ? 's' : '');
    const acts = r.actions.length + ' action' + (r.actions.length !== 1 ? 's' : '');
    h += `<tr><td>${r.name}</td><td>${st}</td><td>${conds}</td><td>${acts}</td><td>${timeAgo(r.last_triggered)}</td></tr>`;
  }
  document.getElementById('rules').innerHTML = h + '</table>';
}

function renderOTA(sessions) {
  if (!sessions.length) { document.getElementById('ota').innerHTML = '<div class="empty">No OTA sessions</div>'; return; }
  let h = '<table><tr><th>Device</th><th>Firmware</th><th>State</th><th>Progress</th><th>Error</th></tr>';
  for (const s of sessions) {
    const cls = {complete:'green', failed:'red', rejected:'red', offered:'blue', transferring:'orange', verifying:'orange'}[s.state]||'blue';
    const pct = Math.round(s.progress * 100) + '%';
    h += `<tr><td>${s.node_id}</td><td>${s.firmware_id} v${s.version||''}</td>
          <td>${badge(s.state, cls)}</td><td>${pct}</td><td>${s.error||'-'}</td></tr>`;
  }
  document.getElementById('ota').innerHTML = h + '</table>';
}

refresh();
setInterval(refresh, refreshInterval);
</script>
</body>
</html>"""

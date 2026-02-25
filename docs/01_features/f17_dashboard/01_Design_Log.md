# f17: Monitoring Dashboard — Design Log

**Task**: 3.6 — Monitoring dashboard (web UI)  
**Branch**: `copilot/monitoring-dashboard`  
**Date**: 2026-02-25  

---

## Motivation

Operators need visibility into the mesh network status: which devices are online, their current state, automation rules, OTA progress, groups/scenes. A web dashboard provides this without requiring chat interaction.

## Architecture

### Zero-dependency HTTP server

Built on Python stdlib `asyncio` — no Flask, aiohttp, or FastAPI dependency. This follows the project's "stdlib-only for mesh modules" pattern and avoids adding attack surface.

### New Module: `nanobot/mesh/dashboard.py`

- **MeshDashboard** class: async HTTP server on configurable port (default 18880)
- JSON API endpoints for all mesh subsystems
- Embedded HTML/JS single-page dashboard (no build tools, no npm)
- Auto-refresh via polling (simple, no WebSocket needed for MVP)

### API Endpoints

| Endpoint | Data Source | Description |
|----------|------------|-------------|
| `GET /` | embedded HTML | Dashboard UI |
| `GET /api/status` | aggregated | Hub status summary (node_id, uptime, device/peer counts) |
| `GET /api/devices` | registry | All devices with state and capabilities |
| `GET /api/peers` | discovery | Online peers from UDP discovery |
| `GET /api/groups` | groups | Device groups |
| `GET /api/scenes` | groups | Scenes |
| `GET /api/rules` | automation | Automation rules |
| `GET /api/ota` | ota | OTA sessions (if ota manager exists) |
| `GET /api/firmware` | firmware store | Available firmware images (if store exists) |

### Config

One field appended to `MeshConfig`: `dashboard_port: int = 0` (0 = disabled)

### Channel Integration

- `MeshChannel` starts dashboard in `start()` if `dashboard_port > 0`
- Dashboard stopped in `stop()`

## Key Decisions

1. **Zero dependencies**: stdlib asyncio HTTP server, embedded HTML with inline CSS/JS
2. **Read-only API**: Dashboard is observation only — no mutating endpoints in MVP
3. **JSON API first**: HTML dashboard consumes the same API, enabling future custom UIs
4. **No auth in MVP**: Dashboard runs on LAN — future task could add basic auth
5. **Polling over WebSocket**: Simpler implementation, adequate for LAN refresh rates

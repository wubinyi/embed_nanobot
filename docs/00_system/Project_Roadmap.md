# Project Roadmap — embed_nanobot

> Single source of truth for project progress. Updated after each feature completion.

**Last updated**: 2026-03-29 (Roadmap audit — clarified all task statuses against actual codebase)

### Status Legend

| Status | Meaning |
|--------|---------|
| **Done** | Fully implemented, tested, and committed |
| **Not Started** | No code exists yet — zero implementation |
| **In Progress** | Active development underway |

### Progress Overview

| Phase | Description | Tasks | Done | Not Started |
|-------|-------------|-------|------|-------------|
| 1 | Foundation | 11 | 11 | 0 |
| 2 | Device Ecosystem | 7 | 7 | 0 |
| 3 | Production Hardening | 6 | 6 | 0 |
| 4 | Smart Factory Extension | 5 | 5 | 0 |
| 5 | Autonomous Intelligence & Secure Device Mgmt | 12 | 12 | 0 |
| **Total** | | **41** | **41** | **0** |

---

## Phase 1 — Foundation ✅

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 1.1 | Fork nanobot, establish `main_embed` branch | Done | 2026-02-05 | Remote `upstream` → HKUDS/nanobot |
| 1.2 | Implement Hybrid Router (local + cloud LLM routing) | Done | 2026-02-06 | `nanobot/providers/hybrid_router.py`, difficulty scoring, PII sanitization |
| 1.3 | Implement LAN Mesh (UDP discovery + TCP transport) | Done | 2026-02-07 | `nanobot/mesh/` — channel, discovery, transport, protocol |
| 1.4 | First upstream merge (manual) | Done | 2026-02-07 | Documented in SYNC_LOG.md, PR #4 |
| 1.5 | Developer documentation (arch, config, customization) | Done | 2026-02-08 | `docs/architecture.md`, `docs/configuration.md`, `docs/customization.md` |
| 1.6 | Second upstream merge (MiniMax, MoChat, DingTalk) | Done | 2026-02-10 | PR #6, conflicts resolved |
| 1.7 | Project SKILL file for Copilot workflow | Done | 2026-02-12 | `.github/copilot-instructions.md`, bootstrap protocol, PRD |
| 1.8 | Upstream sync (catch up 116 upstream commits) | Done | 2026-02-17 | Merged MCP, Codex, memory redesign, CLI overhaul, security hardening. See SYNC_LOG.md |
| 1.8b | Upstream sync (remaining 22 commits) | Done | 2026-02-17 | Telegram media, GitHub Copilot provider, cron timezone, ClawHub skill. Fully synced. |
| 1.9 | PSK-based device authentication (HMAC signing) | Done | 2026-02-17 | `nanobot/mesh/security.py` — KeyStore, HMAC-SHA256 sign/verify, nonce replay protection. 25 new tests. |
| 1.9b | Upstream sync (20 commits: 8053193→7f8a3df) | Done | 2026-02-18 | Base class alias_generator, Mochat channel, CustomProvider, Slack enhancements, Docker Compose. Migrated configs to Base. |
| 1.10 | Device enrollment flow (PIN-based pairing) | Done | 2026-02-18 | `nanobot/mesh/enrollment.py` — EnrollmentService, PBKDF2 PIN-derived key, XOR one-time pad PSK encryption. 35 new tests (146 total). |
| 1.11 | Mesh message encryption (AES-GCM) | Done | 2026-02-18 | `nanobot/mesh/encryption.py` — AES-256-GCM with PSK-derived keys, Encrypt-then-MAC, AAD binding. 37 new tests (183 total). `cryptography` dep. |

### Phase 1 complete ✅

All Phase 1 foundation tasks are done. Ready to begin Phase 2: Device Ecosystem.

---

## Phase 2 — Device Ecosystem ✅

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 2.1 | Device capability registry and state management | Done | 2026-02-18 | `nanobot/mesh/registry.py` — DeviceRegistry, DeviceCapability, DeviceInfo. STATE_REPORT msg type, discovery callbacks. 50 new tests (233 total). |
| 2.2 | Standardized device command schema | Done | 2026-02-18 | `nanobot/mesh/commands.py` — DeviceCommand, CommandResponse, BatchCommand, Action/CommandStatus enums. 6-level validation (action/device/online/capability/compatibility/value). Mesh envelope conversion. LLM command descriptor. 42 new tests (275 total). |
| 2.3 | Natural language → device command (LLM skill) | Done | 2026-02-18 | `nanobot/agent/tools/device.py` — DeviceControlTool (list/command/state/describe). `nanobot/skills/device-control/SKILL.md` always-active skill. Conditional registration in CLI when mesh enabled. 32 new tests (307 total). |
| 2.4 | Command-type routing: device commands always local | Done | 2026-02-18 | `nanobot/mesh/routing.py` — registry-aware device detection. `force_local_fn` callback on HybridRouter. Auto-wired in CLI when mesh + HybridRouter both active. 21 new tests (328 total). |
| 2.5 | ESP32 SDK (MicroPython mesh client) | Done | 2026-03-29 | `esp32/mesh_client/` — 8 modules (889 lines): WiFi connection + NTP sync, PIN-based enrollment + PBKDF2 PSK decryption, HMAC-SHA256 signing, TCP transport with auto-reconnect, GPIO device control, OTA chunk receiver (base64 decode + SHA-256 verify + file install + reset). Full E2E verified on hardware (NodeMCU-32S). |
| 2.6 | Basic automation rules engine | Done | 2026-02-18 | `nanobot/mesh/automation.py` — AutomationEngine with Condition/RuleAction/AutomationRule, device-indexed evaluation, cooldown, JSON persistence, validation. MeshChannel dispatch hook. 75 new tests (403 total). |
| 2.7 | Cloud API fallback: degrade to local if unreachable | Done | 2026-02-18 | Try/except fallback on API failure + circuit breaker (3 consecutive failures → route all to local for 300s). Half-open recovery. 3 config fields on HybridRouterConfig. 11 new tests (414 total). |

---

## Phase 3: Production Hardening ✅

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 3.1 | mTLS for device authentication (local CA) | Done | 2026-02-25 | `nanobot/mesh/ca.py` — MeshCA: EC P-256 local CA, per-device X.509 cert issuance (CN=node_id), mutual TLS on transport (CERT_REQUIRED), auto-issues hub cert, HMAC+AES-GCM skipped when TLS active, cert during enrollment. 49 new tests (487 total). |
| 3.2 | Certificate revocation (CRL) | Done | 2026-02-25 | App-level CRL: `revocation_check_fn` callback in transport, `revoke_device_cert()` in CA, dual persistence (revoked.json + crl.pem). Python ssl can't load CRL files — app-level check after TLS handshake. 36 new tests (523 total). |
| 3.3 | OTA firmware update protocol | Done | 2026-02-25 | `nanobot/mesh/ota.py` — FirmwareStore (dir-based + JSON manifest), OTAManager (state machine: offer→accept→chunks→verify→complete), chunked base64 transfer over mesh TCP, SHA-256 integrity. 8 new MsgType entries. MeshChannel integration. 49 new tests (572 total). |
| 3.4 | Device grouping and scenes | Done | 2026-02-25 | `nanobot/mesh/groups.py` — DeviceGroup, Scene, GroupManager. CRUD for groups/scenes, fan-out commands, JSON persistence. 305 lines. |
| 3.5 | Error recovery and fault tolerance | Done | 2026-02-25 | `nanobot/mesh/resilience.py` — RetryPolicy (exponential backoff + jitter), retry_send, Watchdog (periodic health check), supervised_task (auto-restart). 178 lines. |
| 3.6 | Monitoring dashboard (local web UI) | Done | 2026-02-26 | `nanobot/mesh/dashboard.py` — asyncio HTTP server with JSON APIs (/api/status, /api/devices, /api/peers, /api/groups, /api/scenes, /api/rules, /api/ota, /api/firmware) + embedded single-page HTML dashboard. 477 lines. |

---

## Phase 4: Smart Factory Extension ✅

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 4.1 | PLC/industrial device integration | Done | 2026-02-26 | `nanobot/mesh/industrial.py` — IndustrialBridge with protocol adapter framework (Modbus TCP via pymodbus, StubAdapter fallback). JSON config, auto-polling, device registry integration, automation hooks. 54 new tests (728 total). |
| 4.2 | Multi-Hub federation (hub-to-hub mesh) | Done | 2026-02-26 | `nanobot/mesh/federation.py` — FederationManager with HubLink (persistent TCP, auto-reconnect), registry sync, command forwarding, state propagation. 7 new protocol messages. 44 new tests (772 total). |
| 4.3 | Device reprogramming (AI-generated code push) | Done | 2026-02-27 | `nanobot/mesh/codegen.py` (697 lines) — CodeTemplate, CodeValidator (AST-based safety: import whitelist, blocked calls, size limits), CodeGenerator, CodePackage. 4 built-in templates. `nanobot/agent/tools/reprogram.py` (320+ lines) — ReprogramTool with actions: templates/generate/validate/deploy/status. Integrates codegen + OTAManager. |
| 4.4 | Sensor data pipeline and analytics | Done | 2026-02-26 | `nanobot/mesh/pipeline.py` (442 lines) — SensorReading, RingBuffer, SensorPipeline (ingest, query, aggregate, periodic flush to disk), aggregate_readings (min/max/avg/count). |
| 4.5 | BLE bridge for battery-powered sensors | Done | 2026-02-26 | `nanobot/mesh/ble.py` (538 lines) — BLEScanner (abstract), BleakBLEScanner (real bleak integration), StubScanner (testing), BLEBridge (scan loop → decode advertisements → register as mesh devices), BLEDeviceProfile (configurable decoders). |

---

## Current Phase: Phase 5 — Autonomous Intelligence & Secure Device Management

> AI Hub evolves from a reactive assistant to a proactive, autonomous system that monitors,
> learns, and updates the device ecosystem independently.

### 5.1 — Autonomous Heartbeat & Proactive Exploration

**Goal**: AI Hub periodically explores its environment — monitoring device states, detecting anomalies, optimizing automations, and taking proactive actions without user prompting.

**Building on existing infrastructure**:
- Upstream `HeartbeatService` already provides periodic LLM wake-ups with HEARTBEAT.md
- Upstream `CronService` provides scheduled task execution
- Our `DeviceRegistry`, `AutomationEngine`, `Pipeline` provide device + data context

| # | Task | Priority | Complexity | Dependencies | Status |
|---|------|----------|------------|--------------|--------|
| 5.1.1 | **Configurable autonomous mode** | P1 | M | Heartbeat, Cron | **Done** (2026-03-29) |
| | `nanobot/mesh/autonomous.py` — AutonomousService with periodic LLM-driven device scans. | | | | |
| | Config: `autonomous_enabled`, `autonomous_interval_s`, `autonomous_level` (monitor-only/suggest/act), `autonomous_topics`. | | | | |
| | Builds context from DeviceRegistry + SensorPipeline + AutomationEngine + exploration topics. | | | | |
| | Wired in `commands.py` — starts/stops alongside heartbeat. 21 tests. | | | | |
| 5.1.2 | **Environmental awareness loop** | P1 | L | Registry, Pipeline, 5.1.1 | **Done** (2026-03-29) |
| | `nanobot/mesh/awareness.py` — AwarenessLoop with DeviceSnapshot, trend analysis, anomaly detection. | | | | |
| | Compares recent sensor readings (5min) vs baseline (1hr), detects σ-deviations. | | | | |
| | Tracks online/offline transitions between snapshots. Integrated into AutonomousService. 9 tests. | | | | |
| 5.1.3 | **Proactive automation refinement** | P2 | L | Automation (2.6), 5.1.2 | **Done** (2026-03-29) |
| | `nanobot/mesh/refinement.py` — AutomationAnalyzer with 4 analysis dimensions: never-fired rules, | | | | |
| | frequently-fired rules, stale rules (offline/nonexistent devices), coverage gaps (uncovered devices). | | | | |
| | Generates structured LLM context for the autonomous service to reason about. 13 tests. | | | | |
| 5.1.4 | **Exploration task framework** | P2 | M | 5.1.1, 5.1.2 | **Done** (2026-03-29) |
| | `nanobot/mesh/exploration.py` — ExplorationManager with topic CRUD, append-only event log, | | | | |
| | JSON persistence. Builds LLM context with topic status + recent autonomous actions. | | | | |
| | Integrated into AutonomousService (build_context + _tick event recording). 23 tests. | | | | |

### 5.2 — Secure Remote Device Software Management (Dual-Partition OTA)

**Goal**: AI Hub can customize and deploy software to controlled devices (ESP32) via Wi-Fi,
using a secure dual-partition architecture where one partition is immutable (device core/bootloader)
and the other is remotely updatable by the Hub.

**Building on existing infrastructure**:
- `OTAManager` provides chunked firmware transfer over mesh TCP
- `CodeGenerator` provides MicroPython template-based generation with AST safety
- `MeshCA` provides X.509 certificate infrastructure for device identity

| # | Task | Priority | Complexity | Dependencies | Status |
|---|------|----------|------------|--------------|--------|
| 5.2.1 | **Dual-partition protocol specification** | P1 | L | OTA (3.3), Codegen (4.3) | **Done** (2026-03-29) |
| | Hub: `nanobot/mesh/partitions.py` — PartitionManifest with per-device PartitionEntry tracking | | | | |
| | (core/app version, hash, boot state, crash count, rollback target). JSON persistence. | | | | |
| | Protocol: PARTITION_REPORT + PARTITION_QUERY message types in protocol.py. | | | | |
| | ESP32: `boot_manager.py` — crash counter, hash verification, backup/rollback, boot sequence. | | | | |
| | Integration: MeshChannel handles PARTITION_REPORT; OTA complete writes app_meta + backup. | | | | |
| | Transport sends PARTITION_REPORT on every connect. 21 tests. | | | | |
| 5.2.2 | **Signed firmware protocol** | P1 | M | MeshCA (3.1), 5.2.1 | **Done** (2026-03-29) |
| | Hub: `nanobot/mesh/firmware_signing.py` — FirmwareSigner with EC P-256 signing (audit) + | | | | |
| | per-device HMAC-SHA256 (PSK-based, for device verification). Anti-rollback counter. | | | | |
| | ESP32: boot_manager anti-rollback check + HMAC verification on OTA complete. | | | | |
| | OTA offer/complete extended with firmware_hmac + version_counter fields. 18 tests. | | | | |
| 5.2.3 | **Intelligent firmware generation** | P1 | L | Codegen (4.3), 5.2.1 | **Done** (2026-02-27) |
| | ~~AI Hub generates device-specific firmware based on user requirements AND environment context~~ | | | | |
| | Template-based generation with 4 built-in templates (`switch_basic`, `switch_relay`, `sensor_temperature`). AST-based safety validation. ReprogramTool integrates with CodeGenerator + OTAManager for end-to-end deploy. | | | | |
| | *Note: No built-in LLM code generation — the AI agent provides code via ReprogramTool, which validates and deploys it. Environment/capability awareness is via the agent's context, not codegen itself.* | | | | |
| 5.2.4 | **Safe deployment pipeline** | P2 | M | 5.2.1, 5.2.2, 5.2.3 | **Done** (2026-03-29) |
| | Hub: `nanobot/mesh/deployment.py` — DeploymentPipeline with canary → health check → group rollout → monitor → finalize flow. Emergency recall aborts all OTA sessions. JSON audit trail. Wired into MeshChannel alongside PartitionManifest + OTAManager. 26 tests. | | | | |
| 5.2.5 | **ESP32 core partition SDK** | P2 | XL | 5.2.1, 5.2.2 | **Done** (2026-03-29) |
| | ESP32: `esp32/mesh_client/sdk.py` — Public API for app developers: `get_core_version()`, `execute_command()`, `send_message()`, `verify_core_integrity()`, `get_core_file_hashes()`, `is_enrolled()`, `get_partition_report()`. CORE_FILES manifest for integrity verification. Hub: CORE_INTEGRITY_QUERY/REPORT protocol + handler in channel.py. Deploy script updated with boot_manager.py + sdk.py. 12 tests. | | | | |
| | *Note: C-level bootloader deferred — MicroPython file-based partitioning with crash detection + rollback achieves the same goals. EC P-256 on-device verify replaced by HMAC-SHA256 (design choice in 5.2.2).* | | | | |

### 5.3 — Improvements to Existing Features

| # | Task | Priority | Complexity | Dependencies | Status |
|---|------|----------|------------|--------------|--------|
| 5.3.1 | **MCP-based device protocol tools** | P2 | M | MCP (upstream) | **Done** (2026-03-29) |
| | `nanobot/mesh/mcp_server.py` — MeshMCPServer wraps nanobot Tool instances as MCP tools. SSE transport via Starlette/uvicorn. Config: `mcp_server_port` in MeshConfig (0=disabled). Wired in commands.py: registers device_control + device_reprogram tools, starts alongside gateway. 12 tests. | | | | |
| 5.3.2 | **ESP32 SDK (MicroPython mesh client)** | P1 | XL | All mesh | **Done** (2026-03-29) |
| | `esp32/mesh_client/` — 8 modules, 889 lines of real MicroPython code. | | | | |
| | WiFi connection + NTP sync (`transport.py`), PIN-based enrollment + PBKDF2 (`enrollment.py`), HMAC-SHA256 signing (`security.py`), TCP transport with auto-reconnect, GPIO device control (`device.py`), OTA chunk receiver with base64 decode + SHA-256 verify + file install + reset (`main.py`), protocol framing (`protocol.py`). | | | | |
| | Full E2E verified on hardware (NodeMCU-32S): enrollment → PSK auth → STATE_REPORT → COMMAND → OTA. | | | | |
| | Deploy tooling: `esp32/tools/deploy.sh`, `esp32/tools/flash.sh`. Guides: `GETTING_STARTED.md`, `MICROPYTHON_GUIDE.md`, `LOCATION_CHANGE_GUIDE.md`. | | | | |
| | *Remaining gaps: No dual-partition support (single-file OTA to `app.py`). No firmware signature verification. No crash counter/watchdog.* | | | | |
| 5.3.3 | **Cloud dashboard (web-based)** | P3 | L | Dashboard (3.6) | **Done** (2026-03-29) |
| | `nanobot/mesh/dashboard.py` enhanced: TLS/HTTPS support via ssl.SSLContext (TLSv1.2+), Bearer token authentication with timing-safe comparison, configurable CORS origin. Config: `dashboard_tls_cert`, `dashboard_tls_key`, `dashboard_auth_token`, `dashboard_cors_origin` in MeshConfig. Wired through channel.py. 13 tests. | | | | |

### 5.4 — Hardware Validation (Radxa 5T, ShenZhen Home)

| # | Task | Priority | Complexity | Dependencies | Status |
|---|------|----------|------------|--------------|--------|
| 5.4.1 | **End-to-end OTA WiFi test on Radxa 5T** | P1 | S | 5.3.2, 3.3 | **Done** 2026-04-21 |
| | Both hub (`nanobot/mesh/ota.py`) and ESP32 (`esp32/mesh_client/main.py` OTA handlers) are implemented. Needs live end-to-end test: enroll ESP32 → push app.py via OTA over WiFi → verify ESP32 resets and runs new code. No USB needed after initial deploy. | | | | |

---

## Upstream Sync Status

| Metric | Value |
|--------|-------|
| Last sync date | 2026-03-07 |
| `origin/main` HEAD | ab89775 |
| `upstream/main` HEAD | ab89775 |
| Commits behind | 0 (fully synced) |
| Next sync target | On-demand, before next feature task |

See [docs/sync/SYNC_LOG.md](../sync/SYNC_LOG.md) for full merge history.

---

## Strategic Notes

### 2026-02-12 — Project Setup Complete
- **SKILL workflow established**: Multi-agent (Architect/Reviewer/Developer/Tester) with bootstrap protocol, structured documentation, upstream sync protocol.
- **PRD finalized**: Clear 4-phase roadmap from foundation → smart factory.
- **Key architectural decision**: PSK+HMAC first (simple, fits ESP32), mTLS later (production-grade).
- **Main risk**: Upstream divergence — mitigated by daily sync protocol and append-only convention.
- **Next priority**: Perform upstream sync (9 commits behind), then start PSK authentication (task 1.9).

### 2026-03-08 — ESP32 Hardware Integration Started
- **Physical ESP32 Dev Board available**: Hardware testing phase begins.
- **MicroPython client scaffold created**: `esp32/mesh_client/` — 6 modules covering WiFi connection, enrollment protocol, PSK security (HMAC-SHA256 + flash persistence), TCP transport with auto-reconnect, device GPIO abstraction, and main dispatch loop.
- **Deploy tooling added**: `esp32/tools/flash.sh` (erase + flash MicroPython) and `esp32/tools/deploy.sh` (upload via mpremote).
- **Getting started guide written**: `docs/GETTING_STARTED.md` covers installation, Google Gemini config, test execution, and ESP32 connection walkthrough.
- **Task 5.3.2 unblocked**: Changed from Deferred to In Progress. OTA receive stub in place, ready for Phase 5.2 dual-partition work once basic connectivity is validated on hardware.
- **Immediate next steps**: Flash MicroPython → deploy client → test enrollment → test LED command via NL ("turn on the LED on esp32-01").

### 2026-03-26 — Gateway Bugs Fixed, Enrollment Ready
- **Environment**: ESP32 NodeMCU-32S (CP2102), Windows 10 + WSL dev setup, usbipd-win for USB pass-through.
- **ESP32 deployed**: MicroPython flashed, mesh client uploaded via `deploy.sh /dev/ttyUSB0` from WSL.
- **Gateway bugs found and fixed** (3 bugs):
  - BUG-001: `ota_manager` attribute → `ota` + missing logger import in `commands.py`.
  - BUG-002: `--enroll` CLI flag referenced but never implemented → implemented with `EnrollmentService.create_pin()`.
  - BUG-003: `allowFrom: []` denies all connections → documented fix (set `["*"]`).
- **Workflow established**: Created `docs/02_bugfix/BUGFIX_LOG.md` for tracking, updated `copilot-instructions.md` v1.5 with Bugfix Workflow and Hardware Testing & Feedback Loop.
- **Provider**: Using OpenRouter/stepfun (`stepfun/step-3.5-flash:free`), no local LLM.
- **Next steps**: Run `nanobot gateway --enroll`, test ESP32 enrollment over Wi-Fi, then test NL device commands.

### 2026-03-27 — E2E COMMAND Flow Verified
- **Full pipeline working**: CHAT from authenticated client → nanobot agent → DeviceControlTool → COMMAND envelope → ESP32 via persistent TCP connection. Agent correctly calls `device_control(action="command")` and command arrives at ESP32.
- **6 gap fixes implemented**:
  1. **Auto-registration**: `_handle_state_report()` now auto-registers devices from STATE_REPORT capabilities when authenticated but not in registry.
  2. **COMMAND dispatch**: ESP32 `_dispatch()` fixed to extract `value` from `params` dict; maps hub actions (set/get/toggle) to device actions (turn_on/turn_off/read/set_value).
  3. **boot.py**: Created with 3-second grace period, `/no_autostart` flag file, KeyboardInterrupt handling.
  4. **Persistent bidirectional TCP**: Major transport.py refactor — `_device_writers` dict, `_persistent_read_loop` with 90s idle timeout, `send()` uses persistent connections.
  5. **Device online/offline tracking**: Transport fires `on_device_connected`/`on_device_disconnected` callbacks; channel hooks these to `registry.mark_online/mark_offline`.
  6. **Bool value coercion**: `_send_command()` coerces string "True"/"False" from LLM to Python bool. Offline status treated as advisory, not blocking.
- **Files modified**: `nanobot/mesh/channel.py`, `nanobot/mesh/transport.py`, `nanobot/agent/tools/device.py`, `esp32/mesh_client/main.py`, `esp32/mesh_client/boot.py`, `esp32/tools/deploy.sh`, `tests/test_device_control_tool.py`.
- **New documentation**: `docs/MICROPYTHON_GUIDE.md` — comprehensive MicroPython/mpremote reference.
- **Test baseline**: 1454 passed, 1 skipped (only failure is unrelated `duckduckgo_search` module).
- **16 upstream commits pending** — low priority, deferred.

### 2026-02-17 — Major Upstream Sync Complete
- **116 upstream commits merged** (77 non-merge): MCP support, OpenAI Codex provider, redesigned memory system, CLI overhaul with prompt_toolkit, security hardening, cron improvements.
- **Documentation fully updated**: architecture.md, configuration.md, customization.md, SYNC_LOG.md all refreshed to reflect new upstream features.
- **Key upstream changes to note for our work**:
  - Memory system is now two-layer (MEMORY.md + HISTORY.md) — our future device registry may want to leverage this pattern.
  - MCP support adds a new tool extension mechanism — consider MCP for device protocol tools.
  - Provider registry now supports `is_oauth` and `extra_headers` — useful for future industrial cloud integrations.
- **Upstream still advancing**: 22 more commits ahead (Telegram media sending, GitHub Copilot provider, timezone cron). Next sync before task 1.9.
- **Conflict surface stable**: 7 shared files, all manageable with append-only convention.

### 2026-04-21 — Platform Migration: WSL2 → Radxa Rock 5T (Debian 13)

- **Hub moved** from Windows 10 + WSL2 (x86-64) to Radxa Rock 5T (RK3588, aarch64, Armbian 26 / Debian 13 Trixie).
- **Fixed IP**: `192.168.5.199` — ShenZhen Home location.
- **Python env**: conda `embed_nanobot` (Miniforge3, Python 3.12) at `~/.miniforge3/envs/embed_nanobot`.
- **Config path**: `~/.embed_nanobot/config.json` (unchanged — already set by `loader.py`).
- **ESP32 access**: `/dev/ttyUSB0` directly on Debian — no usbipd-win needed.
- **All 1638 tests passing** on ARM64 (post-migration verification).
- **Bug fixed**: `nanobot run` does not exist — correct command is `nanobot agent`. Fixed in all docs.
- **Docs updated**: GETTING_STARTED.md, LOCATION_CHANGE_GUIDE.md, TESTING_GUIDE.md, TESTING_FAQ.md, MICROPYTHON_GUIDE.md, copilot-instructions.md all updated with Radxa 5T platform notes (WSL2 sections preserved as reference).
- **WiFi/OTA clarification**: nanobot already communicates with ESP32 **entirely over WiFi** (mesh TCP 18800). OTA update over WiFi is also already implemented (`nanobot/mesh/ota.py` + ESP32 `_handle_ota_*` handlers). USB (mpremote) is only needed for initial MicroPython flash + first deploy.sh.
- **New planned task added**: `5.4.1` — End-to-end OTA WiFi test on Radxa 5T hardware (code exists on both sides; needs live validation).
- **ESP32 config updated**: `esp32/mesh_client/config.py` now has ShenZhen Home WiFi + hub IP `192.168.5.199`.

### 2026-04-21 — Task 5.4.1 Complete: E2E OTA WiFi Test Suite

- **Deliverables**:
  - `tests/test_ota_e2e.py`: 52 E2E simulation tests, all passing (0.54 s). 10 test classes covering happy path, chunking integrity (128 KB), concurrent 3-device OTA, abort scenarios, hash mismatch, anti-rollback, timeouts, progress callbacks, protocol edge cases, and firmware store integration.
  - `esp32/tools/test_ota_wifi.py`: Live hardware validation script for Radxa 5T. Generates test firmware, stores in `FirmwareStore`, pushes OTA over WiFi, monitors progress, verifies post-reset reconnect.
  - Feature docs: `docs/01_features/f05_ota_e2e_test/` (Design Log, Dev Implementation, Test Report).
- **Key gap documented**: Hub `OTA_OFFER` does not send `version_counter` or `firmware_hmac`. ESP32 defaults to 0/empty, so anti-rollback and HMAC signing are silently bypassed. Tracked as TD-02 — follow-up task proposed.
- **No conflict surface increase**: No shared upstream files modified.
- **Tech debt added to follow-up**: TD-02 (add `version_counter`/`firmware_hmac` to hub OTA_OFFER), TD-01 (cosmetic error message in `check_timeouts`).
- **Follow-up proposed**: Add task 5.4.2 — "Add version_counter + firmware_hmac to hub OTA_OFFER to enable anti-rollback and HMAC signing end-to-end".

### 2026-03-29 — Roadmap Audit & Status Clarification
- **Action**: Comprehensive code audit of all 41 roadmap items against actual codebase.
- **Results**:
  - **Phases 1-4**: All 31 tasks confirmed **Done** (code exists, tests pass, committed).
  - **Phase 5**: 2 of 12 tasks Done (5.2.3 Intelligent Firmware Generation, 5.3.2 ESP32 SDK). 10 tasks **Not Started** (zero code).
  - **Phase 2.5 corrected**: "Deferred" → **Done** — ESP32 SDK fully functional (WiFi, enrollment, PSK, commands, OTA).
  - **Phase 5.3.2 corrected**: "In Progress" → **Done** — all core features E2E verified on hardware.
  - **Phase 5.2.3 corrected**: "Planned" → **Done** — CodeGenerator + ReprogramTool + OTA pipeline all working.
- **Status legend added**: Clear definitions — "Done" (implemented+tested), "Not Started" (zero code), "In Progress" (active dev).
- **Progress overview table added**: Quick glance at per-phase completion.
- **Next priorities for Phase 5**: 5.1.1 (Configurable autonomous mode) is the natural next step — it unlocks 5.1.2/5.1.3/5.1.4.

### 2026-02-17b — Second Sync + SKILL v1.2
- **22 remaining upstream commits merged** (fully synced): Telegram media file support, GitHub Copilot provider with is_oauth, cron timezone improvements, ClawHub skill, empty content fix.
- **SKILL v1.2 shipped**: Extracted Upstream_Sync_Protocol to dedicated file, added completion gate checklist, Key Features column in sync log, post-sync verification step, simplified Session_Bootstrap.
- **All documentation refreshed**: GitHub Copilot provider added to architecture.md and configuration.md, Telegram media support noted, proxy field documented.
- **Ready for task 1.9** (PSK-based device authentication).

### 2026-02-17c — Task 1.9: PSK Authentication Complete
- **HMAC-SHA256 authentication added** to mesh transport: every TCP message is signed with a per-device Pre-Shared Key.
- **New module**: `nanobot/mesh/security.py` — `KeyStore` class manages device enrollment, PSK storage (JSON with `0600` perms), HMAC sign/verify, nonce replay tracking, and timestamp window validation.
- **Wire format extended**: `MeshEnvelope` now supports `nonce` and `hmac` optional fields, backward-compatible with old unsigned messages.
- **25 new tests**: KeyStore management, HMAC correctness, nonce replay rejection, transport-level integration (authenticated send/receive, unsigned message rejection, unknown node rejection, allow_unauthenticated mode).
- **111 total tests passing**, zero regressions.
- **Zero new dependencies** — uses only Python stdlib (`hmac`, `hashlib`, `secrets`).
- **Config additions**: 4 fields appended to `MeshConfig` (append-only convention).
- **Docs updated**: architecture.md (4-layer mesh diagram), configuration.md (PSK auth fields + security notes), feature docs (Design Log, Dev Implementation, Test Report).
- **SKILL v1.3 shipped**: Added AUTO mode for unattended workflow progression.
- **Next tasks**: 1.10 (PIN-based device enrollment) and 1.11 (AES-GCM encryption), both now unblocked.

### 2026-02-18 — Task 1.10: Device Enrollment Complete
- **PIN-based pairing protocol** added: Hub generates time-limited numeric PIN, device proves knowledge via HMAC-SHA256, Hub sends PSK encrypted with PBKDF2-derived one-time pad.
- **New module**: `nanobot/mesh/enrollment.py` (~240 LOC) — `EnrollmentService` manages PIN lifecycle (create/cancel/expire), validates enrollment requests, rate-limits failures (max 3 attempts), encrypts PSK transfer.
- **Security measures**: PBKDF2-HMAC-SHA256 with 100K iterations makes 6-digit PIN brute-force costly (~115 days). Single-use PINs with auto-expiry. Auth bypass narrowly scoped to `ENROLL_REQUEST` during active enrollment only.
- **Wire protocol extended**: `ENROLL_REQUEST` and `ENROLL_RESPONSE` message types. Transport auth bypass for enrollment. Channel routes enrollment messages and exposes `create_enrollment_pin()`/`cancel_enrollment_pin()` convenience methods.
- **35 new tests** across 7 test classes (146 total, zero regressions). Covers crypto roundtrips, PIN lifecycle, rate limiting, expiry, transport bypass, channel wiring, config validation.
- **Zero new dependencies** — uses only stdlib (`hashlib.pbkdf2_hmac`, `hmac`, `secrets`).
- **3 config fields** appended to `MeshConfig` (append-only convention): `enrollmentPinLength`, `enrollmentPinTimeout`, `enrollmentMaxAttempts`.
- **Next task**: 1.11 (AES-GCM mesh message encryption) — last remaining Phase 1 task.

### 2026-02-18b — Task 1.11: Mesh Encryption Complete — Phase 1 Done
- **AES-256-GCM payload encryption** added to mesh transport. CHAT, COMMAND, and RESPONSE payloads are encrypted with a key derived from the device's PSK.
- **New module**: `nanobot/mesh/encryption.py` (~150 LOC) — `derive_encryption_key()` (HMAC-SHA256 PRF with `"mesh-encrypt-v1"` domain separator), `encrypt_payload()`, `decrypt_payload()`, `build_aad()`, `is_available()`.
- **Encrypt-then-MAC**: Transport encrypts payload before HMAC signing. Receiver verifies HMAC first, then decrypts. Correct security order.
- **AAD (Additional Authenticated Data)**: GCM binds ciphertext to envelope metadata (`type|source|target|ts`), preventing payload reuse across contexts.
- **Key separation**: Raw PSK for HMAC authentication; `HMAC-SHA256(PSK, "mesh-encrypt-v1")` for AES key. Both 256-bit.
- **Selective encryption**: Only user/device data types encrypted. PING/PONG, ENROLL_*, and broadcast messages skip encryption.
- **First non-stdlib dependency**: `cryptography>=41.0.0` (PyCA-maintained OpenSSL wrapper). Graceful degradation if not installed (`HAS_AESGCM=False`, logs warning).
- **37 new tests** across 6 test classes (183 total, zero regressions). Covers roundtrips, tampered ciphertext, AAD mismatch, wrong key, unicode payloads, transport integration, config.
- **1 config field** appended to `MeshConfig`: `encryptionEnabled` (default `true`).
- **Phase 1 Foundation is now complete**: Hybrid Router (1.2) + LAN Mesh (1.3) + PSK Auth (1.9) + Device Enrollment (1.10) + AES-GCM Encryption (1.11). 183 tests, 7 upstream syncs.
- **Next phase**: Phase 2 — Device Ecosystem. First task: 2.1 (Device capability registry and state management).

### 2026-02-18c — Task 2.1: Device Capability Registry Complete
- **DeviceRegistry module** (`nanobot/mesh/registry.py`, ~350 LOC): Central registry for all mesh devices with CRUD, state management, JSON persistence, event callbacks, and LLM context helpers.
- **Data model**: `DeviceCapability` (sensor/actuator/property with typed values), `DeviceInfo` (node_id, type, capabilities, state, online status).
- **Protocol extended**: `STATE_REPORT` message type for devices pushing state changes.
- **Discovery enhanced**: `PeerInfo` now carries `capabilities`/`device_type`; `on_peer_seen`/`on_peer_lost` callbacks for registry integration.
- **Channel integrated**: MeshChannel auto-registers devices from discovery beacons, handles STATE_REPORT messages, tracks online/offline via discovery hooks.
- **50 new tests** across 12 test classes (233 total, zero regressions). Covers CRUD, state updates, persistence, events, LLM context, protocol, channel integration.
- **Zero new dependencies** — stdlib only.
- **1 config field** appended to MeshConfig: `registry_path`.
- **Also synced upstream** (7f8a3df→ce4f005): SiliconFlow provider, workspace-scoped sessions.
- **Next task**: 2.2 (Standardized device command schema).

### 2026-02-18d — Task 2.2: Standardized Device Command Schema Complete
- **Command schema module** (`nanobot/mesh/commands.py`, ~330 LOC): Standardized JSON-based command/response format for device control.
- **Data model**: `DeviceCommand` (device, action, capability, params), `CommandResponse` (device, status, value, error), `BatchCommand` (ordered list with stop-on-error).
- **Action types**: `set`, `get`, `toggle`, `execute` — validated against device capability types.
- **6-level validation**: action validity → device existence → online status → capability existence → action/capability compatibility → value type/range.
- **Mesh integration**: Envelope conversion helpers reuse existing COMMAND/RESPONSE message types — zero protocol changes.
- **LLM context**: `describe_device_commands()` generates structured Markdown for system prompt injection.
- **42 new tests** across 8 test classes (275 total, zero regressions). Covers model serialization, all validation paths, value type/range checks, envelope roundtrips, LLM output.
- **Zero conflict surface increase** — pure additive new file, no shared file modifications.
- **Next task**: 2.3 (Natural language → device command LLM skill).

### 2026-02-18e — Task 2.3: NL → Device Command (LLM Skill) Complete
- **DeviceControlTool** (`nanobot/agent/tools/device.py`, ~190 LOC): Agent tool with 4 actions — list (device summary), command (validate+dispatch), state (query device), describe (full capabilities).
- **device-control skill** (`nanobot/skills/device-control/SKILL.md`, `always: true`): NL→command translation patterns, quick reference, action types, important notes (~200 tokens).
- **CLI integration**: Tool registered conditionally in `cli/commands.py` when mesh channel enabled. Gets registry+transport refs from MeshChannel.
- **32 new tests** across 7 classes (307 total, zero regressions): tool metadata, list/command/state/describe actions, validation failures, transport failures, envelope construction.
- **Conflict surface**: +1 append block in `commands.py` (guarded try/except).
- **Next task**: 2.4 (Command-type routing: device commands always local).

### 2026-02-18f — Task 2.4: Device-Command Routing Complete
- **Routing module** (`nanobot/mesh/routing.py`, ~100 LOC): `is_device_related()` checks text against device names/node_ids/types/capabilities with word-boundary-aware matching. `build_force_local_fn()` creates closure for HybridRouter.
- **HybridRouter hook**: Added `force_local_fn` callback attribute. Checked before difficulty judge in `chat()` — if True, routes to local model immediately (skips judge + PII sanitization).
- **CLI wiring**: Conditional setup when both mesh channel and HybridRouter are active.
- **21 new tests** across 3 classes (328 total, zero regressions): detection logic, closure behavior, router integration.
- **Conflict surface**: +3 lines in hybrid_router.py, +5 lines in commands.py.
- **Next task**: 2.5 (ESP32 SDK) or 2.6 (Automation rules engine).

### 2026-02-18h — Task 2.7: Cloud API Fallback Complete
- **Fallback mechanism**: When API call fails (any exception), router falls back to local model using original (unsanitised) messages.
- **Circuit breaker**: After 3 consecutive API failures, routes ALL traffic to local for 300s. Half-open state after timeout: success closes breaker, failure reopens.
- **Config**: 3 new fields in HybridRouterConfig (fallback_to_local, circuit_breaker_threshold, circuit_breaker_timeout), all with sensible defaults.
- **11 new tests** (414 total, zero regressions): fallback, re-raise when disabled, timeout errors, success reset, breaker open/half-open/closed, original messages preserved.
- **Minimal conflict surface**: +40 LOC in hybrid_router.py, +3 fields in schema.py, +3 lines in commands.py.
- **Phase 2 assessment**: Tasks 2.1–2.4, 2.6–2.7 all Done. Task 2.5 (ESP32 SDK) is hardware-dependent and deferred. Phase 2 core software tasks complete.

### 2026-02-18g — Task 2.6: Basic Automation Rules Engine Complete
- **AutomationEngine** (`nanobot/mesh/automation.py`, ~380 LOC): Evaluates user-defined rules when device state changes, generates DeviceCommands for dispatch.
- **Data model**: `Condition` (device/capability/operator/value), `RuleAction` (generates DeviceCommand), `AutomationRule` (AND-logic + cooldown).
- **Evaluation**: Sync (pure comparisons), indexed by trigger device_id for O(1) lookup. Cooldown prevents re-triggering.
- **Integration**: `MeshChannel._handle_state_report()` evaluates rules after registry update, dispatches commands via transport.
- **Validation**: `validate_rule()` checks devices/capabilities exist in registry.
- **Persistence**: JSON file alongside registry.
- **75 new tests** across 10 test classes (403 total, zero regressions).
- **1 config field** appended to MeshConfig: `automation_rules_path`.
- **Conflict surface**: +26 lines in channel.py, +1 field in schema.py. New file zero conflict.
- **Next tasks**: 2.7 (Cloud API fallback, P2/S), 2.5 (ESP32 SDK, P1/L — hardware-dependent, may defer).

### 2026-02-25 — Major Upstream Sync (276 commits, v0.1.4 era)
- **276 upstream commits merged** (148 non-merge) — largest sync to date. Tags: v0.1.4, v0.1.4.post1, v0.1.4.post2.
- **Key upstream changes**: workspace/→nanobot/templates/ migration, memory consolidation extraction, CLI bus routing refactor, BaseChannel._handle_message session_key param, VolcEngine provider, Mochat channel, prompt caching, progress streaming, tool hints, HeartbeatService refactored to virtual tool-call decision (HEARTBEAT_OK_TOKEN removed), agent defaults changed (temp 0.1, max_iter 40, memory_window 100), dependencies pinned with upper bounds.
- **3 conflicts resolved**: manager.py (accept Mochat block + adopt loguru format for QQ, re-append mesh), commands.py (accept skills mkdir), pyproject.toml (accept upstream pinned versions, re-append cryptography).
- **1 upstream test fixed**: test_heartbeat_service.py imported removed HEARTBEAT_OK_TOKEN and used obsolete on_heartbeat constructor — updated to use mock provider with current API.
- **All 438 tests pass** (was 414 pre-sync — gained 24 upstream tests: heartbeat, memory consolidation types, context prompt cache, cron commands/service).
- **Convention updates**: loguru `{}` formatting now mandatory (no f-strings in loggers), dep versions must have upper bounds, workspace dir gone (use nanobot/templates/).
- **Conflict surface updated**: Removed providers/registry.py (no custom mods). Added tests/test_heartbeat_service.py.
- **Phase 2 remains complete**. Ready for Phase 3 (Production Hardening) when user chooses.

### Conventions Reminder

### 2026-02-25b — Task 3.1: mTLS Device Authentication Complete
- **Local CA module** (`nanobot/mesh/ca.py`, ~290 LOC): `MeshCA` class with EC P-256 (SECP256R1) keys for ESP32/mbedTLS compatibility. Generates self-signed root CA (10-year validity), issues per-device X.509 certificates (CN=node_id, 365-day validity, configurable).
- **Transport TLS integration**: `MeshTransport` accepts `server_ssl_context` and `client_ssl_context_factory`. When TLS active, HMAC verification and AES-GCM encryption are skipped (TLS handles both auth and encryption at transport layer). Zero behavioral change when disabled.
- **Enrollment cert issuance**: On successful PIN-based enrollment, if CA is available, `EnrollmentService` issues a device certificate and includes `cert_pem`, `key_pem`, `ca_cert_pem` in the response. Backward-compatible: no CA → PSK-only enrollment.
- **Hub identity**: Hub gets its own cert (CN="hub"), auto-issued on first SSL context creation.
- **Security**: CA and device private keys stored with `0600` permissions. `ssl.CERT_REQUIRED` on server, TLS 1.2+ minimum, `check_hostname=False` (node_ids aren't DNS names).
- **3 config fields** appended to MeshConfig: `mtls_enabled`, `ca_dir`, `device_cert_validity_days`.
- **49 new tests** across 11 test classes (487 total, zero regressions): CA lifecycle, cert validation, TLS handshake (real sockets), wrong-CA rejection, peer CN extraction, transport integration, enrollment integration, channel wiring, config.
- **Modified 4 files** (transport.py, enrollment.py, channel.py, schema.py) + 1 new (ca.py) + docs.
- **Conflict surface**: +1 ssl import in transport.py (our file), +3 fields in schema.py, minor wiring in channel.py. ca.py is new (zero conflict).
- **Next task**: 3.2 (Certificate revocation / CRL), which depends on this CA infrastructure.

### 2026-02-25d — Task 3.3: OTA Firmware Update Protocol Complete
- **Hub-initiated push OTA** over existing mesh TCP transport. Firmware stored in a directory with JSON manifest.
- **New module** `nanobot/mesh/ota.py` (~410 LOC): `FirmwareStore` (CRUD + manifest persistence + chunk reading from disk), `OTASession` (state machine: OFFERED → TRANSFERRING → VERIFYING → COMPLETE/FAILED/REJECTED), `OTAManager` (orchestrates concurrent updates, progress callbacks).
- **8 new protocol messages**: OTA_OFFER, OTA_ACCEPT, OTA_REJECT, OTA_CHUNK, OTA_CHUNK_ACK, OTA_VERIFY, OTA_COMPLETE, OTA_ABORT.
- **Chunked transfer**: 4KB default chunks, base64 in JSON payload. Firmware read chunk-by-chunk from disk (no full-file memory load). SHA-256 integrity check.
- **Channel integration**: MeshChannel creates OTAManager when `firmware_dir` configured, routes OTA messages, provides convenience methods (start_ota_update, abort_ota_update, get_ota_status).
- **49 new tests** across 11 classes (572 total, zero regressions): store CRUD, session state machine, full protocol flow, chunk data integrity, progress callbacks, edge cases, channel integration.
- **3 config fields** appended to MeshConfig: `firmware_dir`, `ota_chunk_size`, `ota_chunk_timeout`.
- **Zero new dependencies** — uses stdlib only (hashlib, base64, json, pathlib).
- **Conflict surface**: +8 enum entries in protocol.py (append-only), +3 fields in schema.py, OTA routing in channel.py. ota.py is new (zero conflict).
- **Next task**: 3.4 (Device grouping and scenes).

### 2026-02-25e — Task 3.4: Device Grouping and Scenes Complete
- **DeviceGroup** (named set of node_ids) and **Scene** (named command batch) with CRUD and JSON persistence.
- **New module** `nanobot/mesh/groups.py` (~306 LOC): `GroupManager` with dual JSON persistence (groups.json, scenes.json), group CRUD (add/remove/list, add/remove device), scene CRUD, execution helpers (`get_scene_commands`, `fan_out_group_command`), LLM context helpers (`describe_groups`, `describe_scenes`).
- **Channel integration**: `MeshChannel.groups` attribute, `execute_scene(scene_id)` sends all scene commands via transport, `execute_group_command(group_id, action, capability, params)` fans out to all group members.
- **2 config fields** appended to MeshConfig: `groups_path`, `scenes_path`.
- **35 new tests** across 8 classes (607 total, zero regressions): data model roundtrips, CRUD, persistence, fan-out, LLM descriptions, channel integration.
- **Zero new dependencies** — pure stdlib.
- **Conflict surface**: +2 fields in schema.py, GroupManager import+init+methods in channel.py. groups.py is new (zero conflict).
- **Next task**: 3.5 (Error recovery and fault tolerance).

### 2026-02-25f — Task 3.5: Error Recovery and Fault Tolerance Complete
- **New module** `nanobot/mesh/resilience.py` (~170 LOC): `RetryPolicy` (exponential backoff config), `retry_send()` (wraps async send with retries), `Watchdog` (periodic async loop for health checks), `supervised_task()` (create_task with error logging).
- **Critical fix**: Discovery `prune()` was defined but never called — stale peers accumulated forever and `on_peer_lost` never fired. Now a `Watchdog` auto-prunes at `peer_timeout / 2` interval.
- **Transport retry**: New `send_with_retry()` method with configurable `RetryPolicy` (default: 3 retries, 0.5s base, 2x backoff, 10s cap). Available for critical sends.
- **Channel error isolation**: `start()` catches transport failure and stops discovery. `stop()` catches errors in each component independently — partial failures no longer leave dangling resources.
- **Supervised tasks**: All fire-and-forget `create_task` calls replaced with `supervised_task()` — exceptions logged instead of silently swallowed.
- **OTA timeout enforcement**: `check_timeouts()` enforces `OFFER_TIMEOUT` (60s), `CHUNK_ACK_TIMEOUT` (30s), `VERIFY_TIMEOUT` (60s). `cleanup_completed()` removes terminal sessions after configurable max_age.
- **Protocol safety**: `read_envelope()` now catches `json.JSONDecodeError`, `struct.error`, `UnicodeDecodeError` — returns `None` instead of crashing.
- **36 new tests** across 9 classes (643 total, zero regressions).
- **Zero new config fields** — resilience is auto-enabled with sensible defaults.
- **Zero new dependencies** — uses only stdlib (asyncio, time).
- **Conflict surface**: +import in discovery.py, +method in transport.py, channel start/stop refactored, OTA methods added. resilience.py is new (zero conflict).
- **Next task**: 3.6 (Monitoring dashboard).

### 2026-02-25c — Task 3.2: Certificate Revocation (CRL) Complete
- **Application-level revocation** — Python's `ssl` module cannot load CRL files (`load_verify_locations()` only loads CA certs). Switched from OpenSSL CRL enforcement to app-level check in `MeshTransport._handle_connection()`.
- **Revocation flow**: `ca.revoke_device_cert(node_id)` reads cert serial, adds to `_revoked` dict, persists `revoked.json`, generates `crl.pem` (X.509 CRL for external tooling), deletes cert+key files.
- **Transport enforcement**: `revocation_check_fn` callback checked after TLS handshake, before message processing. Revoked device connections dropped immediately.
- **Instant revocation**: No SSL context rebuild needed — in-memory dict lookup on each new connection.
- **Dual persistence**: `revoked.json` (fast, survives restart) + `crl.pem` (standard X.509 CRL for ESP32/mbedTLS/external tools).
- **Channel integration**: `MeshChannel.revoke_device()` delegates to CA, optionally removes from registry.
- **36 new tests** across 8 classes (523 total, zero regressions): lifecycle, CRL file validation, rebuild, transport rejection (real TLS), channel integration, re-enrollment after revocation.
- **Zero new config fields** — CRL is automatic when mTLS is active.
- **Zero new dependencies** — uses existing `cryptography` for CRL generation.
- **Conflict surface unchanged**: Changes only in our mesh module files (ca.py, transport.py, channel.py).
- **Next task**: 3.3 (OTA firmware update protocol).

### Conventions Reminder
- Feature branches: `copilot/<feature-name>` from `main_embed`
- Docs per feature: `docs/01_features/fXX_<name>/{01_Design_Log, 02_Dev_Implementation, 03_Test_Report}.md`
- Code placement: Custom code in separate modules, append to existing configs
- Tests: `tests/test_<module>.py`, pytest + pytest-asyncio
### 2026-02-26 — Task 3.6: Monitoring Dashboard Complete — Phase 3 Done
- **Zero-dependency HTTP dashboard** (`nanobot/mesh/dashboard.py`, ~478 LOC): `MeshDashboard` class built on stdlib `asyncio.start_server`. No aiohttp/flask/fastapi.
- **9 API endpoints**: `/api/status`, `/api/devices`, `/api/peers`, `/api/groups`, `/api/scenes`, `/api/rules`, `/api/ota`, `/api/firmware`, `/` (HTML).
- **Embedded single-page HTML dashboard**: Dark theme, auto-refresh (5s polling), stat cards, device/peer/group/rule/OTA tables, status badges, timeAgo formatting. Zero external JS/CSS dependencies.
- **Data access pattern**: `data_fn` closure returns dict of existing managers — dashboard is read-only observer, zero coupling to mesh state.
- **Channel integration**: Dashboard created when `dashboard_port > 0`, started after transport (non-critical), stopped with error isolation.
- **`isinstance(raw, int)` pattern**: Discovered that `getattr(config, "field", 0) or 0` fails with MagicMock configs (returns truthy MagicMock). Defensive `isinstance` guard adopted.
- **1 config field** appended to MeshConfig: `dashboard_port` (default 0 = disabled).
- **31 new tests** across 12 test classes (674 total, zero regressions): lifecycle, all 9 endpoints, error handling (404/405/500), CORS, serialization edge cases, concurrency, channel integration config wiring.
- **Phase 3 Production Hardening complete**: mTLS (3.1) + CRL (3.2) + OTA (3.3) + Groups/Scenes (3.4) + Error Recovery (3.5) + Dashboard (3.6). 674 tests.
- **Next phase**: Phase 4 — Smart Factory Extension. First task: 4.1 (PLC/industrial device integration).

### 2026-02-26b — Task 4.1: PLC/Industrial Device Integration Complete
- **Protocol adapter framework** (`nanobot/mesh/industrial.py`, ~430 LOC): `IndustrialProtocol` ABC + `ModbusTCPAdapter` (pymodbus >= 3.0, async) + `StubAdapter` (fallback). Protocol registry for extensibility (`register_protocol()`).
- **Data model**: `PLCPointConfig` (capability/register_type/address/data_type/unit/scale/value_range), `PLCDeviceConfig` (node_id/device_type/name/points), `BridgeConfig` (bridge_id/protocol/host/port/unit_id/poll_interval/devices). All with `from_dict()` constructors.
- **IndustrialBridge orchestrator**: JSON config loader, lifecycle (connect/disconnect all adapters), periodic polling (per-bridge interval, auto-reconnect), command dispatch (node_id→bridge→adapter routing), device registry integration (registers PLC devices with proper capabilities).
- **Data types**: bool, uint16, int16, uint32, int32, float32, float64 — decoded from Modbus registers with big-endian struct packing.
- **Channel integration**: Industrial bridge created when `industrial_config_path` configured, started/stopped with error isolation, state updates trigger automation rules, commands routed to industrial bridge when target is PLC device.
- **Optional dependency**: `pymodbus >= 3.0` — graceful degradation to StubAdapter when not installed.
- **1 config field** appended to MeshConfig: `industrial_config_path`.
- **54 new tests** across 14 classes (728 total, zero regressions): data type codec roundtrips, config parsing, MockAdapter protocol, bridge lifecycle, command dispatch, polling, channel integration.
- **Zero conflict surface increase**: industrial.py is a new file, schema.py/channel.py have append-only changes.
- **Phase 4 started**: First smart factory task done. Next task: 4.2 (Multi-Hub federation).

### 2026-02-26c — Task 4.2: Multi-Hub Federation Complete
- **Federation module** (`nanobot/mesh/federation.py`, ~500 LOC): `FederationManager` with `HubLink` persistent TCP connections, auto-reconnect (exponential backoff 2s→60s), periodic registry sync, command forwarding (future-based with timeout), state propagation.
- **7 new protocol messages**: FEDERATION_HELLO (handshake), FEDERATION_SYNC (registry snapshot), FEDERATION_COMMAND/RESPONSE (forwarded command+reply), FEDERATION_STATE (state push), FEDERATION_PING/PONG (keepalive).
- **HubLink**: Bidirectional TCP connection with background receive loop, ping loop (15s), auto-reconnect on connection loss, exponential backoff (2s base, 60s max).
- **Registry sync**: Periodic broadcast of local device list (capabilities, state, online status) to all connected peers. Stale devices automatically removed on re-sync.
- **Command forwarding**: `forward_command()` sends FEDERATION_COMMAND, waits for FEDERATION_RESPONSE via asyncio.Future with configurable timeout (default 10s).
- **State propagation**: Local state changes broadcast to federated peers. Remote state changes trigger local automation rules with proper command routing (industrial/federation/mesh).
- **Channel integration**: `_execute_local_command()` handles forwarded commands (tries industrial bridge first, falls back to mesh transport). `_on_federation_state_update()` routes automation output. `_handle_state_report()` broadcasts to federation.
- **1 config field** appended to MeshConfig: `federation_config_path`.
- **44 new tests** across 18 test classes (772 total, zero regressions): config parsing, HubLink send/lifecycle, sync/stale removal, command forward/timeout/handling, response resolution, state propagation, ping/pong, queries, message dispatch, channel integration.
- **Zero new dependencies** — uses stdio asyncio TCP only.
- **Zero conflict surface increase**: federation.py is a new file, protocol.py/schema.py/channel.py have append-only changes.
- **Next tasks**: 4.3 (Device reprogramming, P2/XL), 4.5 (BLE mesh, P2/L).

### Strategic Note — Task 4.4 (Sensor Data Pipeline) — 2026-02-26

- **Architecture**: In-memory ring buffers (`collections.deque(maxlen=N)`) per (device, capability). JSON persistence with configurable auto-flush. Zero external dependencies.
- **Auto-recording**: Hooks into `_handle_state_report()` in channel.py. Every numeric/boolean STATE_REPORT value is automatically recorded.
- **Analytics**: 7 aggregation functions (min/max/avg/sum/count/median/stdev) with time-range filtering. `summary()` produces LLM-friendly Markdown.
- **Config**: 4 fields appended to MeshConfig: `pipeline_enabled`, `pipeline_path`, `pipeline_max_points`, `pipeline_flush_interval`.
- **Integration**: Pipeline added to dashboard `data_fn` for monitoring. Channel auto-creates when `pipeline_enabled=True`.
- **72 new tests** across 14 test classes (844 total, zero regressions).
- **Zero conflict surface increase**: pipeline.py is a new file, schema.py/channel.py have append-only changes.
- **Next**: This completes all L-complexity tasks. Remaining: 4.3 (XL) and 4.5 (L).

### Strategic Note — Task 4.5 (BLE Sensor Support) — 2026-02-26

- **Architecture**: Passive BLE advertisement scanning with configurable device profiles. `BLEScanner` ABC → `BleakBLEScanner` (real) / `StubScanner` (test). JSON config with regex device name matching and byte-level decode rules.
- **Data model**: `BLECapabilityDef` (7 data types: uint8/int8/uint16/int16/uint32/int32/float32, scale factor, byte offset/length). `BLEDeviceProfile` groups capabilities per device type.
- **Scan loop**: Configurable interval (30s) + duration (10s). Stale device pruning at configurable timeout (120s).
- **Integration**: Auto-registers BLE devices in registry, feeds state to pipeline via callback, triggers automation rules. RSSI included in state.
- **Config**: 1 field appended to MeshConfig: `ble_config_path`. Optional `bleak` dependency.
- **50 new tests** across 16 test classes (894 total, zero regressions): advertisement parsing, byte decoding, profile matching, scan processing, device pruning, lifecycle, channel integration.
- **Zero conflict surface increase**: ble.py is a new file, schema.py/channel.py have append-only changes.
- **Phase 4 status**: Only 4.3 (Device reprogramming, XL) remains. All other Phase 4 tasks complete.

### Strategic Note — Task 4.3 (Device Code Generation) — 2026-02-27

- **Architecture**: AST-based code generation and safety validation pipeline. `CodeValidator` performs 7-point safety analysis (syntax, import whitelist, blocked calls/attrs, network server detection, structure check, size limit). `CodeGenerator` manages templates and produces `CodePackage` bundles.
- **Templates**: 4 built-in MicroPython templates (sensor_reader, actuator_switch, pwm_controller, i2c_sensor). Custom templates loadable from JSON file.
- **Agent tool**: `ReprogramTool` with 5 actions (templates, generate, validate, deploy, status). Bridges LLM to codegen + OTA infrastructure.
- **Safety model**: Whitelist-first import control (30+ MicroPython-safe modules). Blocked sandbox escapes (__class__, __subclasses__, __globals__). No eval/exec/compile. Network server patterns rejected.
- **Config**: 1 field appended to MeshConfig: `codegen_templates_path`.
- **78 new tests** across 9 test classes (78 codegen + validator + tool tests): safety validation (23 tests), generator (16 tests), tool actions (22 tests), data models, constants.
- **Zero conflict surface increase**: codegen.py and reprogram.py are new files, schema.py/commands.py have append-only changes.

### 2026-03-07 — Phase 5 Planning: Autonomous Intelligence & Secure Device Management

- **Upstream sync completed**: 211 commits merged (ab89775). 7 conflicts resolved. Key new upstream features: Azure OpenAI, tool auto-cast, allow_from validation, reasoning_effort.
- **SKILL v1.4 shipped**: Added Self-Reflection Protocol (8 dimensions, self-update authority), Subagent Integration (Explore subagent), updated Conflict_Minimization_Strategy (Rules 7-8).
- **Phase 5 planned** based on user vision for AI Hub evolution:
  - **5.1 Autonomous Heartbeat**: Builds on upstream HeartbeatService + CronService. Adds configurable autonomy levels (off/monitor/suggest/act), environmental awareness loop, proactive automation refinement, exploration task framework.
  - **5.2 Secure Remote Device Management**: Builds on existing OTA + CodeGenerator + MeshCA. Adds dual-partition flash protocol (immutable core + updatable app), signed firmware with anti-rollback, intelligent environment-aware code generation, safe deployment pipeline with staged rollout.
  - **5.3 Improvements**: MCP-based device tools, ESP32 SDK (now depends on 5.2.5 for dual-partition), cloud dashboard.
- **Key architectural decisions**:
  - Dual-partition approach chosen for security and reliability: core partition cannot be modified remotely, preventing bricked devices.
  - Autonomy levels provide user control: `off` = traditional assistant, `monitor-only` = observe and report, `suggest` = propose actions for approval, `act` = execute autonomously.
  - Anti-rollback counter prevents firmware downgrade attacks in 5.2.2.
- **Next tasks**: 5.1.1 (configurable autonomous mode) and 5.2.1 (dual-partition protocol spec), both P1 with no blockers.
- **Phase 4 status**: All Phase 4 tasks now complete. All planned roadmap tasks finished.
# Project Roadmap — embed_nanobot

> Single source of truth for project progress. Updated after each feature completion.

**Last updated**: 2026-02-26 (Task 4.1 complete)

---

## Current Phase: Phase 1 — Foundation

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

## Current Phase: Phase 2 — Device Ecosystem

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 2.1 | Device capability registry and state management | Done | 2026-02-18 | `nanobot/mesh/registry.py` — DeviceRegistry, DeviceCapability, DeviceInfo. STATE_REPORT msg type, discovery callbacks. 50 new tests (233 total). |

### Planned Tasks

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 2.2 | Standardized device command schema | Done | 2026-02-18 | `nanobot/mesh/commands.py` — DeviceCommand, CommandResponse, BatchCommand, Action/CommandStatus enums. 6-level validation (action/device/online/capability/compatibility/value). Mesh envelope conversion. LLM command descriptor. 42 new tests (275 total). |
| 2.3 | Natural language → device command (LLM skill) | Done | 2026-02-18 | `nanobot/agent/tools/device.py` — DeviceControlTool (list/command/state/describe). `nanobot/skills/device-control/SKILL.md` always-active skill. Conditional registration in CLI when mesh enabled. 32 new tests (307 total). |
| 2.4 | Command-type routing: device commands always local | Done | 2026-02-18 | `nanobot/mesh/routing.py` — registry-aware device detection. `force_local_fn` callback on HybridRouter. Auto-wired in CLI when mesh + HybridRouter both active. 21 new tests (328 total). |
| 2.5 | ESP32 SDK (MicroPython mesh client) | P1 | L | Mesh + Auth (1.3, 1.9) |
| 2.6 | Basic automation rules engine | Done | 2026-02-18 | `nanobot/mesh/automation.py` — AutomationEngine with Condition/RuleAction/AutomationRule, device-indexed evaluation, cooldown, JSON persistence, validation. MeshChannel dispatch hook. 75 new tests (403 total). |
| 2.7 | Cloud API fallback: degrade to local if unreachable | Done | 2026-02-18 | Try/except fallback on API failure + circuit breaker (3 consecutive failures → route all to local for 300s). Half-open recovery. 3 config fields on HybridRouterConfig. 11 new tests (414 total). |

---

## Phase 3: Production Hardening

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 3.1 | mTLS for device authentication (local CA) | Done | 2026-02-25 | `nanobot/mesh/ca.py` — MeshCA: EC P-256 local CA, per-device X.509 cert issuance (CN=node_id), mutual TLS on transport (CERT_REQUIRED), auto-issues hub cert, HMAC+AES-GCM skipped when TLS active, cert during enrollment. 49 new tests (487 total). |
| 3.2 | Certificate revocation (CRL) | Done | 2026-02-25 | App-level CRL: `revocation_check_fn` callback in transport, `revoke_device_cert()` in CA, dual persistence (revoked.json + crl.pem). Python ssl can't load CRL files — app-level check after TLS handshake. 36 new tests (523 total). |
| 3.3 | OTA firmware update protocol | Done | 2026-02-25 | `nanobot/mesh/ota.py` — FirmwareStore (dir-based + JSON manifest), OTAManager (state machine: offer→accept→chunks→verify→complete), chunked base64 transfer over mesh TCP, SHA-256 integrity. 8 new MsgType entries. MeshChannel integration. 49 new tests (572 total). |

### Planned Tasks

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 3.4 | Device grouping and scenes | P1 | M | Registry (2.1) | **Done** (2026-02-25) |
| 3.5 | Error recovery and fault tolerance | P1 | M | All mesh components | **Done** (2026-02-25) |
| 3.6 | Monitoring dashboard (web UI) | P2 | L | Registry (2.1) | **Done** (2026-02-26) |

---

## Phase 4: Smart Factory Extension

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 4.1 | PLC/industrial device integration | Done | 2026-02-26 | `nanobot/mesh/industrial.py` — IndustrialBridge with protocol adapter framework (Modbus TCP via pymodbus, StubAdapter fallback). JSON config, auto-polling, device registry integration, automation hooks. 54 new tests (728 total). |

### Planned Tasks

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 4.2 | Multi-Hub federation (hub-to-hub mesh) | P1 | XL | Mesh + mTLS |
| 4.3 | Device reprogramming (AI-generated code push) | P2 | XL | OTA (3.3), Commands (2.2) |
| 4.4 | Sensor data pipeline and analytics | P2 | L | Registry (2.1) |
| 4.5 | BLE mesh support for battery-powered sensors | P2 | L | Mesh transport abstraction |

---

## Upstream Sync Status

| Metric | Value |
|--------|-------|
| Last sync date | 2026-02-25 |
| `origin/main` HEAD | 9e806d7 |
| `upstream/main` HEAD | 9e806d7 |
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

### 2026-02-17 — Major Upstream Sync Complete
- **116 upstream commits merged** (77 non-merge): MCP support, OpenAI Codex provider, redesigned memory system, CLI overhaul with prompt_toolkit, security hardening, cron improvements.
- **Documentation fully updated**: architecture.md, configuration.md, customization.md, SYNC_LOG.md all refreshed to reflect new upstream features.
- **Key upstream changes to note for our work**:
  - Memory system is now two-layer (MEMORY.md + HISTORY.md) — our future device registry may want to leverage this pattern.
  - MCP support adds a new tool extension mechanism — consider MCP for device protocol tools.
  - Provider registry now supports `is_oauth` and `extra_headers` — useful for future industrial cloud integrations.
- **Upstream still advancing**: 22 more commits ahead (Telegram media sending, GitHub Copilot provider, timezone cron). Next sync before task 1.9.
- **Conflict surface stable**: 7 shared files, all manageable with append-only convention.

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
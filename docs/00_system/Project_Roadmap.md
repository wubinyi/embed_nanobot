# Project Roadmap — embed_nanobot

> Single source of truth for project progress. Updated after each feature completion.

**Last updated**: 2026-02-18 (Task 2.1 complete)

---

## Current Phase: Phase 1 — Foundation

### Completed Tasks

| # | Task | Status | Completed | Notes |
|---|------|--------|-----------|-------|
| 1.1 | Fork nanobot, establish `main_embed` branch | Done | 2026-02-05 | Remote `upstream` → HKUDS/nanobot |
| 1.2 | Implement Hybrid Router (local + cloud LLM routing) | Done | 2026-02-06 | `nanobot/providers/hybrid_router.py`, difficulty scoring, PII sanitization |
| 1.3 | Implement LAN Mesh (UDP discovery + TCP transport) | Done | 2026-02-07 | `nanobot/mesh/` — channel, discovery, transport, protocol |
| 1.4 | First upstream merge (manual) | Done | 2026-02-07 | Documented in MERGE_ANALYSIS.md, PR #4 |
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
| 2.4 | Command-type routing: device commands always local | P1 | S | Hybrid Router (1.2) |
| 2.5 | ESP32 SDK (MicroPython mesh client) | P1 | L | Mesh + Auth (1.3, 1.9) |
| 2.6 | Basic automation rules engine | P1 | M | Registry (2.1), Commands (2.2) |
| 2.7 | Cloud API fallback: degrade to local if unreachable | P2 | S | Hybrid Router (1.2) |

---

## Phase 3: Production Hardening

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 3.1 | mTLS for device authentication (local CA) | P0 | L | PSK auth (1.9) |
| 3.2 | Certificate revocation (CRL) | P1 | M | mTLS (3.1) |
| 3.3 | OTA firmware update protocol | P1 | L | Mesh + Auth |
| 3.4 | Device grouping and scenes | P1 | M | Registry (2.1) |
| 3.5 | Error recovery and fault tolerance | P1 | M | All mesh components |
| 3.6 | Monitoring dashboard (web UI) | P2 | L | Registry (2.1) |

---

## Phase 4: Smart Factory Extension

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 4.1 | PLC/industrial device integration | P1 | L | Registry (2.1), Commands (2.2) |
| 4.2 | Multi-Hub federation (hub-to-hub mesh) | P1 | XL | Mesh + mTLS |
| 4.3 | Device reprogramming (AI-generated code push) | P2 | XL | OTA (3.3), Commands (2.2) |
| 4.4 | Sensor data pipeline and analytics | P2 | L | Registry (2.1) |
| 4.5 | BLE mesh support for battery-powered sensors | P2 | L | Mesh transport abstraction |

---

## Upstream Sync Status

| Metric | Value |
|--------|-------|
| Last sync date | 2026-02-18b |
| `origin/main` HEAD | ce4f005 |
| `upstream/main` HEAD | ce4f005 |
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
- **Documentation fully updated**: architecture.md, configuration.md, customization.md, SYNC_LOG.md, MERGE_ANALYSIS.md all refreshed to reflect new upstream features.
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

### Conventions Reminder
- Feature branches: `copilot/<feature-name>` from `main_embed`
- Docs per feature: `docs/01_features/fXX_<name>/{01_Design_Log, 02_Dev_Implementation, 03_Test_Report}.md`
- Code placement: Custom code in separate modules, append to existing configs
- Tests: `tests/test_<module>.py`, pytest + pytest-asyncio

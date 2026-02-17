# Project Roadmap — embed_nanobot

> Single source of truth for project progress. Updated after each feature completion.

**Last updated**: 2026-02-12

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

### In Progress

| # | Task | Status | Assignee | Notes |
|---|------|--------|----------|-------|
| 1.8 | Upstream sync (catch up 9 new commits) | Pending | Next session | `origin/main` is 9 commits behind `upstream/main` |

### Planned (Phase 1 Remaining)

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 1.9 | PSK-based device authentication (HMAC signing) | P0 | L | Mesh transport layer |
| 1.10 | Device enrollment flow (PIN-based pairing) | P0 | M | PSK auth (1.9) |
| 1.11 | Mesh message encryption (AES-GCM) | P0 | M | PSK auth (1.9) |

---

## Phase 2: Device Ecosystem

| # | Task | Priority | Complexity | Dependencies |
|---|------|----------|------------|--------------|
| 2.1 | Device capability registry and state management | P0 | L | Mesh (1.3) |
| 2.2 | Standardized device command schema | P0 | M | Registry (2.1) |
| 2.3 | Natural language → device command (LLM skill) | P0 | L | Command schema (2.2), Hybrid Router (1.2) |
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
| Last sync date | 2026-02-12 |
| `origin/main` HEAD | ea1d2d7 |
| `upstream/main` HEAD | b429bf9 |
| Commits behind | 9 |
| Next sync target | Before task 1.9 |

See [docs/sync/SYNC_LOG.md](../sync/SYNC_LOG.md) for full merge history.

---

## Strategic Notes

### 2026-02-12 — Project Setup Complete
- **SKILL workflow established**: Multi-agent (Architect/Reviewer/Developer/Tester) with bootstrap protocol, structured documentation, upstream sync protocol.
- **PRD finalized**: Clear 4-phase roadmap from foundation → smart factory.
- **Key architectural decision**: PSK+HMAC first (simple, fits ESP32), mTLS later (production-grade).
- **Main risk**: Upstream divergence — mitigated by daily sync protocol and append-only convention.
- **Next priority**: Perform upstream sync (9 commits behind), then start PSK authentication (task 1.9).

### Conventions Reminder
- Feature branches: `copilot/<feature-name>` from `main_embed`
- Docs per feature: `docs/01_features/fXX_<name>/{01_Design_Log, 02_Dev_Implementation, 03_Test_Report}.md`
- Code placement: Custom code in separate modules, append to existing configs
- Tests: `tests/test_<module>.py`, pytest + pytest-asyncio

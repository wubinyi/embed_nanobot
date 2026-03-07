# Product Requirements Document (PRD)

## Embed Nanobot — AI Hub for Smart Home & Smart Factory

| Field | Value |
|-------|-------|
| **Project** | embed_nanobot |
| **Repository** | wubinyi/embed_nanobot (fork of HKUDS/nanobot) |
| **Primary Branch** | `main_embed` |
| **Upstream Branch** | `main` (tracks HKUDS/nanobot main) |
| **Author** | wubinyi |
| **Created** | 2026-02-12 |
| **Status** | Active |

---

## 1. Vision

Build an **AI Hub** — a central intelligence node for smart homes and smart factories. The Hub runs on a local device (Raspberry Pi, mini-PC, or edge server) within the same WiFi/LAN as all connected devices. It combines a **local LLM** for fast, private processing with access to **cloud LLMs** for complex reasoning, creating a tiered intelligence system that controls, monitors, and reprograms embedded devices.

### Core Principles

1. **Privacy-first**: Sensitive data (device state, personal routines, sensor readings) stays on the local network. Only anonymized or non-sensitive queries reach the cloud.
2. **Low latency**: Routine device commands ("turn on light", "set thermostat to 22°C") are processed by the local LLM in milliseconds, not round-tripped to the internet.
3. **Security**: Only certified/enrolled devices can join the network. Uncertified devices are rejected at the protocol level.
4. **Extensibility**: New device types, skills, and capabilities can be added without modifying the core system.
5. **Upstream alignment**: The project inherits and stays synchronized with HKUDS/nanobot, gaining upstream improvements while maintaining custom embedded features.

---

## 2. System Architecture

### 2.1 High-Level Topology

```
                         ┌─────────────────────────┐
                         │    Cloud LLM APIs        │
                         │  (OpenAI, Anthropic, etc)│
                         └────────────┬─────────────┘
                                      │ (complex tasks only)
                                      │ PII sanitized
                         ┌────────────┴─────────────┐
                         │       AI Hub              │
                         │  ┌─────────────────────┐  │
                         │  │  embed_nanobot       │  │
                         │  │  ├─ Local LLM        │  │
                         │  │  ├─ Hybrid Router    │  │
                         │  │  ├─ Device Registry  │  │
                         │  │  ├─ Mesh Transport   │  │
                         │  │  └─ Security Layer   │  │
                         │  └─────────────────────┘  │
                         └──┬────┬────┬────┬────┬───┘
                WiFi/LAN    │    │    │    │    │
              ┌─────────────┘    │    │    │    └──────────────┐
              ▼                  ▼    ▼    ▼                   ▼
        ┌──────────┐    ┌──────┐ ┌──────┐ ┌──────┐    ┌──────────────┐
        │Smart Lock│    │Light │ │HVAC  │ │Sensor│    │Factory Robot │
        │(ESP32)   │    │(Wiz) │ │(Zone)│ │(Temp)│    │(PLC + Agent) │
        └──────────┘    └──────┘ └──────┘ └──────┘    └──────────────┘
```

### 2.2 Component Breakdown

| Component | Description | Status |
|-----------|-------------|--------|
| **nanobot core** | Agentic loop, tools, skills, memory, sessions | Inherited from upstream |
| **Hybrid Router** | Routes tasks between local LLM and cloud API, with circuit breaker fallback | ✅ Implemented |
| **LAN Mesh** | UDP discovery + TCP transport for device communication | ✅ Implemented |
| **Device Security** | PSK+HMAC auth, AES-256-GCM encryption, mTLS, device enrollment, CRL | ✅ Implemented |
| **Device Registry** | Capability discovery, device state management | ✅ Implemented |
| **Device Command Schema** | Standardized command format, NL→command translation | ✅ Implemented |
| **Automation Engine** | Rule-based device control (condition → action, cooldown, validation) | ✅ Implemented |
| **OTA Update** | Hub-initiated chunked firmware push via mesh TCP | ✅ Implemented |
| **Code Generation** | AST-validated MicroPython code generation + OTA deploy | ✅ Implemented |
| **Device Grouping** | Named groups and scenes with batch command execution | ✅ Implemented |
| **Error Recovery** | Retry policies, watchdog, supervised tasks, OTA timeout enforcement | ✅ Implemented |
| **Monitoring Dashboard** | Web UI for mesh status, device state, pipeline data | ✅ Implemented |
| **Industrial/PLC** | Protocol adapter framework (Modbus TCP), auto-polling | ✅ Implemented |
| **Hub Federation** | Hub-to-hub TCP mesh, registry sync, command forwarding | ✅ Implemented |
| **Sensor Pipeline** | Time-series ring buffers, aggregation, auto-recording | ✅ Implemented |
| **BLE Sensors** | Passive BLE advertisement scanning, auto-registration | ✅ Implemented |
| **Autonomous Mode** | Configurable proactive monitoring, exploration, and self-tuning | 🔲 Planned (5.1) |
| **Dual-Partition OTA** | Secure dual-partition firmware management with signed updates | 🔲 Planned (5.2) |
| **Local LLM Serving** | vLLM/Ollama integration for on-device inference | ✅ Supported via config |
| **Upstream Sync** | Merge from HKUDS/nanobot main into main_embed | ✅ Active (11 syncs) |

---

## 3. Functional Requirements

### 3.1 Device Communication (LAN Mesh)

**Status: ✅ Implemented** — see `nanobot/mesh/`

| ID | Requirement | Priority |
|----|-------------|----------|
| DC-01 | Devices discover each other via UDP broadcast on configurable port | ✅ Done |
| DC-02 | Reliable message delivery via TCP with length-prefixed JSON envelopes | ✅ Done |
| DC-03 | Support message types: CHAT, COMMAND, RESPONSE, PING, PONG + 10 more (STATE_REPORT, ENROLL_*, OTA_*, FEDERATION_*) | ✅ Done |
| DC-04 | Mesh integrates with nanobot message bus as a channel | ✅ Done |
| DC-05 | Support device capability advertisement in discovery beacons | ✅ Done (task 2.1: PeerInfo carries capabilities/device_type) |
| DC-06 | Support message acknowledgement and delivery guarantees | ✅ Done (task 3.5: retry_send with exponential backoff) |
| DC-07 | Support broadcast and unicast messaging | ✅ Done (target="*") |

### 3.2 Device Security & Authentication

**Status: ✅ Fully implemented** — PSK+HMAC (1.9), Enrollment (1.10), AES-GCM (1.11), mTLS (3.1), CRL (3.2)

| ID | Requirement | Priority |
|----|-------------|----------|
| DS-01 | All mesh communication encrypted (TLS or AES-GCM) | ✅ Done (AES-256-GCM in task 1.11, mTLS in task 3.1) |
| DS-02 | Device enrollment flow: Hub generates pairing token → device presents it → Hub issues certificate/PSK | ✅ Done (PIN-based enrollment in task 1.10, cert issuance in 3.1) |
| DS-03 | Mutual authentication: Hub verifies device, device verifies Hub | ✅ Done (mTLS with CERT_REQUIRED in task 3.1) |
| DS-04 | Reject unenrolled/uncertified devices at transport layer | ✅ Done (HMAC verification in 1.9, TLS handshake rejection in 3.1, CRL in 3.2) |
| DS-05 | Certificate/key revocation for compromised devices | ✅ Done (app-level CRL + revoked.json + crl.pem in task 3.2) |
| DS-06 | Secure key storage on Hub (encrypted keystore) | ✅ Done (KeyStore with 0600 perms in task 1.9) |
| DS-07 | Rate limiting to prevent brute-force enrollment attempts | ✅ Done (max 3 attempts + lockout in task 1.10) |

**Recommended solution — PSK + HMAC (Phase 1) → mTLS (Phase 2):**

**Phase 1 — PSK + HMAC (simpler, suitable for prototyping):**
- Each enrolled device shares a Pre-Shared Key (PSK) with the Hub.
- Every mesh envelope includes an HMAC-SHA256 signature computed over the payload using the PSK.
- The Hub verifies the HMAC before processing any message.
- Enrollment: Hub displays a 6-digit PIN on its interface. User enters PIN on the device. Hub sends the PSK over the (temporary, PIN-authenticated) channel.
- Pros: Simple to implement, low overhead for constrained devices (ESP32).
- Cons: Shared key — if one device is compromised, its PSK must be rotated.

**Phase 2 — mTLS (production-grade):**
- Hub runs a local Certificate Authority (CA) using a self-signed root cert.
- During enrollment, Hub issues a per-device X.509 certificate signed by the CA.
- All TCP connections require mutual TLS: both sides present certificates.
- Devices without valid CA-signed certificates cannot establish a connection.
- Revocation: Hub maintains a Certificate Revocation List (CRL) checked on every connection.
- Pros: Industry standard (used in Matter/Thread), per-device identity, easy revocation.
- Cons: Higher resource use, requires TLS stack on embedded devices.

**Network-level isolation (complementary):**
- Dedicated IoT WiFi SSID / VLAN with no internet access.
- Only the Hub bridges between IoT network and internet.
- Prevents compromised IoT devices from exfiltrating data directly.

### 3.3 Hybrid Intelligence (Dual-Model Routing)

**Status: Implemented** — see `nanobot/providers/hybrid_router.py`

| ID | Requirement | Priority |
|----|-------------|----------|
| HI-01 | Local LLM judges task difficulty (score 0.0–1.0) | ✅ Done |
| HI-02 | Easy tasks processed entirely by local LLM | ✅ Done |
| HI-03 | Hard tasks forwarded to cloud API after PII sanitization | ✅ Done |
| HI-04 | Configurable difficulty threshold | ✅ Done |
| HI-05 | All device commands forced to local-only processing | ✅ Done (task 2.4: force_local_fn on HybridRouter) |
| HI-06 | Command-type routing: device commands always local, knowledge queries can be remote | ✅ Done (task 2.4: registry-aware routing) |
| HI-07 | Fallback: if cloud API is unreachable, degrade to local model | ✅ Done (task 2.7: circuit breaker + fallback) |

### 3.4 Device Control & Management

**Status: ✅ Fully implemented**

| ID | Requirement | Priority |
|----|-------------|----------|
| DM-01 | Device registry: track all enrolled devices, their capabilities, and state | ✅ Done (task 2.1: DeviceRegistry with CRUD, state, persistence) |
| DM-02 | Standardized command schema: `{"device": "light-1", "action": "set", "params": {"brightness": 80}}` | ✅ Done (task 2.2: DeviceCommand, 6-level validation) |
| DM-03 | LLM generates device commands from natural language | ✅ Done (task 2.3: DeviceControlTool + SKILL.md) |
| DM-04 | Device state query: "Is the front door locked?" → query device → respond | ✅ Done (task 2.3: DeviceControlTool 'state' action) |
| DM-05 | Device grouping and scenes: "Good night" → lock doors + dim lights + arm alarm | ✅ Done (task 3.4: GroupManager, scenes, fan-out) |
| DM-06 | OTA firmware update: push new firmware to devices via mesh | ✅ Done (task 3.3: OTAManager, chunked transfer, SHA-256) |
| DM-07 | Device reprogramming: AI generates and pushes new code to ESP32/Arduino devices | ✅ Done (task 4.3: CodeGenerator, AST validator, ReprogramTool) |
| DM-08 | Automation rules: "If temperature > 28°C, turn on AC" | ✅ Done (task 2.6: AutomationEngine, condition/action, cooldown) |

### 3.5 Upstream Synchronization

**Status: Active** — 10 manual syncs completed (500+ upstream commits merged). Automation deferred.

| ID | Requirement | Priority |
|----|-------------|----------|
| US-01 | `main` branch tracks HKUDS/nanobot `main` branch | ✅ Done |
| US-02 | Daily automated fetch of upstream changes | 🔲 Deferred (manual sync sufficient at current cadence) |
| US-03 | Automated merge attempt from `main` into `main_embed` | 🔲 Deferred (conflict resolution requires human judgment) |
| US-04 | Conflict detection and documentation | ✅ Done (manual, see SYNC_LOG.md conflict surface) |
| US-05 | Merge results logged to `docs/sync/` for traceability | ✅ Done (SYNC_LOG.md maintained) |
| US-06 | Custom code follows "append-only" convention to minimize conflicts | ✅ Done (agent.md) |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NF-01 | Local command latency | < 500ms (local LLM response for simple commands) |
| NF-02 | Device discovery time | < 5 seconds on local WiFi |
| NF-03 | Hub memory footprint | < 4GB RAM for core + local LLM (quantized) |
| NF-04 | Supported device count | 50+ devices on single Hub |
| NF-05 | Uptime | 99.9% (with automatic recovery) |
| NF-06 | Code size | Stay lightweight — inherit nanobot's ~4000 LOC philosophy |

---

## 5. Technical Decisions

### 5.1 Communication Protocol: WiFi + Custom Mesh

**Why WiFi over Zigbee/Z-Wave/BLE?**
- Universal: every device with a WiFi chip can participate (ESP32, Raspberry Pi, etc.)
- Higher bandwidth: supports firmware updates, log streaming, and rich message payloads
- Simpler stack: standard TCP/IP, no dedicated coordinator hardware
- Trade-off: higher power consumption (not suitable for battery-powered sensors in Phase 1)

**BLE support**: BLE advertisement scanning implemented in Phase 4 (task 4.5) for battery-powered sensors. Uses `bleak` library with passive scanning and configurable device profiles.

### 5.2 Local LLM: vLLM / Ollama

- **vLLM** for GPU-equipped hubs (NVIDIA Jetson, mini-PCs with GPU)
- **Ollama** for CPU-only hubs (Raspberry Pi 5, fanless PCs)
- Model recommendations:
  - Qwen2.5-3B or Phi-3-mini for basic command processing
  - LLaMA 3.1-8B-Instruct for more capable local reasoning
  - Quantized (GGUF Q4) for memory-constrained devices

### 5.3 Embedded Device SDK

Target platforms for device-side mesh client:
- **ESP32** (MicroPython or Arduino C++)
- **Raspberry Pi** (Python)
- **Arduino** (C++ with WiFi shield)

The SDK should implement:
- UDP beacon broadcast/listen
- TCP connection to Hub
- Mesh envelope serialization/deserialization
- HMAC signing (Phase 1) or TLS (Phase 2)
- Capability advertisement
- Command execution callback

---

## 6. Phased Roadmap

### Phase 1: Foundation ✅
- [x] Fork nanobot, establish main_embed branch
- [x] Implement LAN Mesh communication (UDP discovery + TCP transport)
- [x] Implement Hybrid Router (local + cloud LLM routing)
- [x] Developer documentation (architecture, configuration, customization)
- [x] Upstream merge workflow (manual) — 10 syncs completed (500+ upstream commits merged)
- [x] Project SKILL file for Copilot-assisted development
- [x] PSK-based device authentication (HMAC signing)
- [x] Device enrollment flow (PIN-based pairing)
- [x] Mesh message encryption (AES-256-GCM)

### Phase 2: Device Ecosystem ✅
- [x] Device capability registry and state management
- [x] Standardized command schema
- [x] Natural language → device command translation (LLM skill)
- [x] Command-type routing (device commands always local)
- [x] Basic automation rules engine
- [x] Cloud API fallback (circuit breaker + degrade to local)
- [ ] ESP32 SDK (MicroPython mesh client) — deferred, hardware-dependent

### Phase 3: Production Hardening ✅
- [x] mTLS for device authentication
- [x] Certificate revocation (CRL)
- [x] OTA firmware update protocol
- [x] Device grouping and scenes
- [x] Error recovery and fault tolerance
- [x] Monitoring dashboard (web UI)

### Phase 4: Smart Factory Extension ✅
- [x] PLC/industrial device integration
- [x] Multi-Hub federation (hub-to-hub mesh)
- [x] Device reprogramming (AI-generated code push)
- [x] Sensor data pipeline and analytics
- [x] BLE mesh support for battery-powered sensors

### Phase 5: Autonomous Intelligence & Secure Device Management
- [ ] Configurable autonomous mode (autonomy levels: off/monitor/suggest/act)
- [ ] Environmental awareness loop (state snapshots, trend analysis, anomaly detection)
- [ ] Proactive automation refinement (rule effectiveness analysis, self-tuning)
- [ ] Exploration task framework (user-defined topics, sandboxed actions, event log)
- [ ] Dual-partition OTA protocol (immutable core + updatable app partition)
- [ ] Signed firmware with anti-rollback protection
- [ ] Intelligent environment-aware firmware generation
- [ ] Safe deployment pipeline (staged rollout, health monitoring, emergency recall)
- [ ] ESP32 core partition SDK (dual-partition bootloader, mesh client, signature verification)

---

## 7. Success Metrics

| Metric | Phase 1 Target | Phase 2 Target |
|--------|----------------|----------------|
| Devices controllable | 3+ (LED, relay, sensor) | 10+ variety |
| Command response time | < 2s (local) | < 500ms (local) |
| Upstream sync cadence | Manual | Daily automated |
| Security | None (dev only) | PSK + HMAC |
| Test coverage | Unit tests for mesh/router | Integration tests with real devices |

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Upstream divergence causes merge conflicts | Medium | Append-only convention (agent.md), daily sync, proper conflict documentation |
| WiFi not suitable for all IoT sensors | Low (Phase 1) | Plan BLE mesh support for Phase 4 |
| Local LLM too slow on RPi | Medium | Use quantized models, command caching, pre-compiled responses for common commands |
| Security vulnerabilities in mesh protocol | High | Prioritize PSK auth in Phase 1, mTLS in Phase 3 |
| Single-person project bandwidth | High | Copilot-assisted workflow (SKILL), clear phased roadmap, automated tooling |

---

## Appendix A: Existing Codebase Map

| Module | Purpose | Embed-specific? |
|--------|---------|-----------------|
| `nanobot/agent/` | Agentic loop, context, memory, skills, tools | No (upstream) |
| `nanobot/bus/` | Async message bus (inbound/outbound queues) | No (upstream) |
| `nanobot/channels/` | Chat channels (Telegram, Discord, WhatsApp, etc.) | No (upstream) |
| `nanobot/cli/` | CLI interface (typer-based) | No (upstream) |
| `nanobot/config/` | Pydantic configuration schema | Extended (MeshConfig, HybridRouterConfig) |
| `nanobot/cron/` | Scheduled tasks | No (upstream) |
| `nanobot/heartbeat/` | Periodic task execution | No (upstream) |
| `nanobot/mesh/` | LAN device mesh (discovery, transport, protocol, security, registry, commands, automation, OTA, groups, resilience, codegen, industrial, federation, pipeline, BLE) | **Yes** |
| `nanobot/providers/` | LLM providers (LiteLLM wrapper) | Extended (hybrid_router, openai_codex_provider) |
| `nanobot/session/` | Conversation session management | No (upstream) |
| `nanobot/skills/` | Modular skill packages | Extended (embed-specific skills) |
| `nanobot/utils/` | Utility helpers | No (upstream) |
| `bridge/` | Node.js WhatsApp bridge | No (upstream) |
| `docs/` | Developer documentation | **Yes** |
| `workspace/` | Agent workspace (memory, heartbeat, etc.) | No (upstream) |

# Task 3.1: mTLS for Device Authentication — Design Log

## Date: 2026-02-25

---

## [Architect] Design Proposal

### Motivation

Current security layers (PSK+HMAC auth, AES-GCM encryption) use shared symmetric keys. mTLS provides:
- **Per-device identity** via X.509 certificates (vs shared PSK)
- **Standard infrastructure** (TLS 1.2/1.3 supported by ESP32/mbedTLS)
- **Revocation capability** (revoke one device without rotating others — task 3.2)
- **Transport-level security** (auth + encryption in one layer)

### Architecture

A local Certificate Authority (CA) runs on the Hub. During device enrollment, the CA issues a per-device certificate. All mesh TCP connections are TLS-wrapped with mutual authentication.

```
                    Hub
            ┌───────────────────┐
            │   Local CA        │
            │   ├── ca.key      │
            │   ├── ca.crt      │
            │   └── devices/    │
            │       ├── hub.crt │
            │       └── dev1.crt│
            │                   │
            │   MeshTransport   │
            │   (TLS server)    │
            └───────┬───────────┘
                    │ mTLS handshake
         ┌──────────┼──────────┐
         │          │          │
     ┌───┴───┐ ┌───┴───┐ ┌───┴───┐
     │ Dev A │ │ Dev B │ │ Dev C │
     │ (TLS  │ │ (TLS  │ │ (TLS  │
     │client)│ │client)│ │client)│
     └───────┘ └───────┘ └───────┘
```

### Key Decisions

1. **EC P-256 keys** (SECP256R1) — widely supported including ESP32/mbedTLS, good performance on constrained devices.
2. **mTLS coexists with PSK** — when mTLS is enabled, TLS handles auth+encryption at transport layer. PSK/HMAC/AES-GCM layers are skipped (redundant). When mTLS is disabled, falls back to existing PSK stack.
3. **Hub gets a cert too** — Hub is issued a cert by its own CA (CN="hub"), so devices can verify the Hub identity.
4. **Node ID in certificate CN** — `get_peer_node_id()` extracts CN from TLS peer cert to identify the connecting device.
5. **Certificate issued during enrollment** — After PIN-based enrollment succeeds, if CA is available, cert+key are sent to device alongside the PSK (backward compatible).

### Data Flow

**Enrollment with mTLS (enhanced flow):**
1. PIN enrollment succeeds → PSK issued (existing)
2. If CA available: issue device cert, send `cert_pem + key_pem + ca_cert_pem` in ENROLL_RESPONSE
3. Device stores cert and switches to TLS for subsequent connections

**Runtime with mTLS:**
1. Hub's TCP server starts with `ssl=server_ssl_context` (requires client cert)
2. Device opens TLS connection with its cert → mutual auth at TLS handshake
3. Length-prefixed JSON framing works identically over TLS stream
4. HMAC signing / AES-GCM encryption skipped (TLS provides both)

---

## [Reviewer] Challenge

1. **Key management complexity**: CA key is the crown jewel. If compromised, all device certs are untrusted.
   - **Mitigation**: CA key stored with `0o600` permissions. Future: HSM support.

2. **Certificate expiry handling**: Device certs expire. What happens?
   - **Decision**: 1-year device certs. Channel logs warning when cert is near expiry. Full rotation via re-enrollment. CRL handling deferred to task 3.2.

3. **Backward compatibility**: Devices enrolled before mTLS still have PSK only.
   - **Decision**: When mTLS is enabled, non-TLS connections are rejected. Devices must re-enroll to get certs. This is acceptable for a production transition.

4. **ESP32 TLS overhead**: TLS handshake on ESP32 takes ~2s with mbedTLS.
   - **Acceptable**: Mesh uses short-lived connections. 2s handshake once per message is fine for IoT command latency.

5. **Testing without real TLS devices**: How to test mTLS in unit tests?
   - **Solution**: Create test CA + certs in tmp_path, use SSL-wrapped local sockets.

**Consensus**: Design approved. Proceed with implementation.

---

## [Architect] Implementation Plan

### New Files

| File | Purpose | LOC (est) |
|------|---------|-----------|
| `nanobot/mesh/ca.py` | Local CA: key gen, cert issuance, SSL context creation | ~280 |
| `tests/test_mtls.py` | CA, cert issuance, SSL context, transport+enrollment integration | ~350 |
| `docs/01_features/f12_mtls_auth/` | Design log, dev implementation, test report | — |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/transport.py` | Add optional `ssl_context` param to constructor; pass to `asyncio.start_server` and `asyncio.open_connection`; skip HMAC/AES-GCM when TLS active |
| `nanobot/mesh/enrollment.py` | After successful enrollment, issue cert via CA (if available); include cert data in ENROLL_RESPONSE |
| `nanobot/mesh/channel.py` | Initialize MeshCA from config; create SSL context; pass to transport |
| `nanobot/config/schema.py` | Append mTLS config fields to MeshConfig |
| `nanobot/mesh/protocol.py` | Add `CERT_ISSUE` message type (optional, may not be needed) |

### Dependencies
- `cryptography` (already in pyproject.toml) — `x509`, `ec`, `hashes`, `serialization`

### Upstream Impact
- Zero. All changes are in `nanobot/mesh/` (our module) and append-only on `schema.py`.

### Test Plan
- CA initialization + idempotent reload
- Device cert issuance + validation
- SSL context creation (server + client)
- Peer node_id extraction from cert CN
- Transport with TLS: send/receive over mTLS
- Enrollment integration: cert issued during enrollment
- Error cases: expired cert, wrong CA, missing cert, uninitialized CA
- Config integration

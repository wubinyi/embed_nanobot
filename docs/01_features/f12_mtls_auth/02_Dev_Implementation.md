# f12: mTLS Device Authentication — Development Implementation

**Task**: 3.1 — mTLS for device authentication (local CA)  
**Branch**: `copilot/mtls-device-auth`  
**Date**: 2025-02-25  

---

## Summary

Implemented a local Certificate Authority (CA) integrated into the mesh transport layer, enabling mutual TLS authentication for device-to-hub communication. Devices receive X.509 certificates during enrollment and use them for all subsequent TLS handshakes.

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/ca.py` | ~290 | `MeshCA` class — Local CA lifecycle, cert issuance, SSL context creation |
| `tests/test_mtls.py` | ~470 | 49 tests covering CA, certs, TLS handshake, enrollment, transport, channel integration |
| `docs/01_features/f12_mtls_auth/01_Design_Log.md` | — | Architect/Reviewer design debate and implementation plan |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/transport.py` | Added `ssl` import, `server_ssl_context`/`client_ssl_context_factory` params, `tls_enabled` flag, `_get_client_ssl()` method, conditional HMAC/AES-GCM skip when TLS active |
| `nanobot/mesh/enrollment.py` | Added `MeshCA` type import, `ca` constructor param, cert issuance in enrollment success path |
| `nanobot/mesh/channel.py` | Added `ssl`/`MeshCA` imports, CA initialization from config, SSL context creation, `_make_client_ssl()`, pass `ca` to EnrollmentService |
| `nanobot/config/schema.py` | Appended 3 mTLS fields to `MeshConfig`: `mtls_enabled`, `ca_dir`, `device_cert_validity_days` |

## Key Design Decisions

### 1. EC P-256 (SECP256R1) for all keys
- ESP32/mbedTLS compatible
- Good performance on constrained devices (~10ms sign vs ~300ms for RSA-2048)
- 128-bit security level sufficient for IoT

### 2. TLS coexists with PSK stack (doesn't replace)
- When `tls_enabled=True`: transport skips HMAC verification and AES-GCM encrypt/decrypt (TLS handles both)
- When `tls_enabled=False`: existing PSK+HMAC+AES-GCM layers operate as before
- Zero behavioral change for existing deployments

### 3. Hub gets its own cert (CN="hub")
- Auto-issued on first `create_server_ssl_context()` call
- Enables the Hub to also be a TLS client for device-to-device relay

### 4. node_id embedded as certificate CN
- `get_peer_node_id(transport)` extracts CN from peer cert
- Enables identity verification at TLS layer without additional protocol fields
- SAN extension also includes node_id as DNS name

### 5. Certificate issuance during enrollment
- After successful PIN-based enrollment, if CA is available, `EnrollmentService` calls `ca.issue_device_cert(device_id)`
- Response includes `cert_pem`, `key_pem`, and `ca_cert_pem`
- Backward-compatible: if CA is `None`, enrollment works as before (PSK-only)

## Architecture

```
MeshChannel.__init__()
│
├── if mtls_enabled:
│   ├── MeshCA(ca_dir, validity_days)
│   ├── ca.initialize()
│   ├── ca.create_server_ssl_context() → server_ssl
│   └── _make_client_ssl() → client_ssl_factory
│
├── MeshTransport(
│   │   server_ssl_context=server_ssl,
│   │   client_ssl_context_factory=client_ssl_factory
│   │)
│   ├── tls_enabled = (server_ssl is not None)
│   ├── start() → asyncio.start_server(ssl=server_ssl)
│   ├── _send_to() → asyncio.open_connection(ssl=client_ssl)
│   └── When tls_enabled: skip HMAC verify + AES-GCM
│
└── EnrollmentService(ca=ca)
    └── On success: ca.issue_device_cert(device_id)
        └── Response includes cert_pem, key_pem, ca_cert_pem
```

## Deviations from Design

### MagicMock truthiness guard
During testing, `getattr(mock_config, "mtls_enabled", False)` returns a truthy `MagicMock` instead of `False`. Fixed with strict `is True` comparison in `channel.py`:

```python
mtls_enabled = getattr(config, "mtls_enabled", False) is True
```

Also added `isinstance(..., int)` guard for `device_cert_validity_days` to prevent MagicMock leaking into `MeshCA`.

### No deviation from file plan
All files in the implementation plan were created/modified as specified. No unplanned changes.

## Documentation Freshness Check
- architecture.md: OK — `nanobot/mesh/` already documented; ca.py is a sub-module of mesh
- configuration.md: **Needs update** — 3 new MeshConfig fields to document (deferred to post-merge)
- customization.md: OK — no new extension patterns
- PRD.md: OK — mTLS is Phase 2 requirement, status unchanged until roadmap update
- agent.md: OK — no upstream convention changes

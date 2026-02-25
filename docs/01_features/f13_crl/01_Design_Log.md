# f13: Certificate Revocation (CRL) — Design Log

**Task**: 3.2 — Certificate revocation list  
**Branch**: `copilot/crl-revocation`  
**Date**: 2026-02-25  

---

## Motivation

Task 3.1 established mTLS with a local CA. However, there's no way to revoke a compromised or decommissioned device's certificate. Once issued, a cert remains valid until expiry. This is unacceptable for production IoT — a stolen device should be immediately untrusted.

## Architecture

### CRL (Certificate Revocation List) Approach

We use X.509 CRL rather than OCSP because:
- **Offline-first**: CRL is a signed file, no online responder needed
- **Local CA**: CRL is generated and consumed on the same Hub — no distribution delay
- **Simplicity**: Single file, signed by CA, loaded into `ssl.SSLContext`
- **ESP32-compatible**: mbedTLS supports CRL verification natively

### Data Flow

```
revoke_device_cert("sensor-42")
│
├── Load cert from devices/sensor-42.crt → extract serial number
├── Add serial + revocation date to CRL builder
├── Sign CRL with CA key
├── Write to ca_dir/crl.pem
├── Delete device cert+key from devices/
└── Caller should rebuild SSL contexts to pick up new CRL
```

### Application-Level Revocation Check

> **Design revision**: Python's `ssl` module **cannot load CRL files**. `load_verify_locations()` only loads CA certificates — there is no public API to feed a CRL into an `SSLContext`. The `ssl.VERIFY_CRL_CHECK_LEAF` flag exists but is unusable without CRL loading. We therefore enforce revocation at the **application level** in the transport connection handler.

```python
# In MeshTransport._handle_connection():
if self._server_ssl_ctx and self.revocation_check_fn:
    peer_id = MeshCA.get_peer_node_id(writer.transport)
    if peer_id and self.revocation_check_fn(peer_id):
        writer.close()  # reject revoked device
        return
```

The CRL PEM file is still generated for **external tooling interoperability** (e.g., mbedTLS on ESP32 devices, external audit tools) but is not consumed by the Hub's Python SSL stack.

### Channel Integration

```
MeshChannel.revoke_device(node_id)
│
├── ca.revoke_device_cert(node_id)
│   ├── Read cert → extract serial
│   ├── Add to in-memory _revoked dict
│   ├── Persist revoked.json
│   ├── Generate crl.pem (for external tooling)
│   └── Delete device cert+key files
└── Optionally remove device from registry

# Revocation takes effect INSTANTLY — no SSL context rebuild needed
# Transport checks ca.is_revoked() on every new connection
```

## Key Decisions

### 1. CRL stored as PEM file in ca_dir
- `ca_dir/crl.pem` — single file, re-signed on each revocation
- Created lazily on first revocation (or on initialization if stale revocations exist)

### 2. Device cert+key deleted on revocation
- Prevents accidental re-use
- Device node_id can be re-enrolled (new cert issued)
- CRL entry persists to block old cert even if device files are gone

### 3. Application-level revocation (not OpenSSL CRL)
- Python's `ssl` module lacks CRL loading API
- Revocation enforced in `MeshTransport._handle_connection()` via `revocation_check_fn` callback
- `MeshChannel` wires `ca.is_revoked` as the callback
- Instant enforcement: no SSL context rebuild needed for revocation

### 4. CRL PEM still generated for external consumers
- `ca_dir/crl.pem` — standard X.509 CRL, signed by CA
- Used by ESP32 (mbedTLS), external audit tools, not by Hub's Python SSL
- Re-generated on each revocation call

### 5. Hot-reload of SSL contexts (for cert rotation, not CRL)
- `transport.update_server_ssl_context()` still exists for certificate rotation
- Not needed for revocation (app-level check is immediate)
- Existing connections from revoked devices continue until they complete
- New connections from revoked devices are dropped at the transport layer

## Reviewer Challenge

**Q: What if someone manually deletes crl.pem?**  
A: All previously revoked devices regain access. Mitigated by: (1) JSON backup enables CRL rebuild, (2) device cert+key files are deleted so at least the Hub can't re-create SSL contexts for them, (3) we add a `rebuild_crl()` method that regenerates CRL from revoked.json.

**Q: What about CRL expiry?**  
A: CRL has a `next_update` field. We set it to 30 days. If the CRL expires and isn't refreshed, strict TLS stacks may reject ALL connections. Mitigated by: re-generating CRL on every Hub startup and on every revocation.

**Q: Performance with many revocations?**  
A: Revocation check is O(1) dict lookup per new connection. CRL PEM generation is O(n) where n = revoked certs. For typical IoT deployments (<1000 devices), both are negligible.

**Q: Why not use OpenSSL-level CRL?**  
A: Python's `ssl` module has `VERIFY_CRL_CHECK_LEAF` flag but no API to load CRL files into `SSLContext`. The `load_verify_locations()` method only loads CA certificates. Application-level checking is more portable and gives us instant revocation without SSL context rebuilds.

## Implementation Plan

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/ca.py` | Add `revoke_device_cert()`, `is_revoked()`, `list_revoked()`, `rebuild_crl()`, `_load_revoked()`, `_save_revoked()`, `_generate_crl()`. Update `list_device_certs()` to show revoked status. |
| `nanobot/mesh/channel.py` | Add `revoke_device()` method. Wire `ca.is_revoked` as `transport.revocation_check_fn`. |
| `nanobot/mesh/transport.py` | Add `revocation_check_fn` attribute + check in `_handle_connection()`. Add `update_server_ssl_context()` for hot-reload. |

### New Files

| File | Purpose |
|------|---------|
| `tests/test_crl.py` | Tests for CRL generation, revocation, SSL rejection, hot-reload |
| `docs/01_features/f13_crl/01_Design_Log.md` | This file |

### No New Config Fields
CRL is automatic when mTLS is enabled. No additional user configuration needed.

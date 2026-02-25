# f13: Certificate Revocation (CRL) — Dev Implementation

**Task**: 3.2 — Certificate revocation list  
**Branch**: `copilot/crl-revocation`  
**Date**: 2026-02-25  

---

## Summary

Implemented certificate revocation for the mesh CA, enabling immediate revocation of compromised or decommissioned device certificates. Revocation is enforced at the **application level** in the transport connection handler, not at the OpenSSL level (Python's `ssl` module cannot load CRL files).

## Architecture Decision: App-Level vs OpenSSL CRL

**Initial approach**: Load CRL into `ssl.SSLContext` via `load_verify_locations()` + `VERIFY_CRL_CHECK_LEAF`.  
**Discovery**: Python's `ssl.SSLContext.load_verify_locations()` only loads CA certificates — there is no public API to feed a CRL into the context. The `VERIFY_CRL_CHECK_LEAF` flag exists but is unusable.  
**Final approach**: Application-level revocation check in `MeshTransport._handle_connection()` via a `revocation_check_fn` callback, wired to `MeshCA.is_revoked()`.

Benefits of app-level approach:
- **Instant revocation**: No SSL context rebuild needed — revocation takes effect on the next connection attempt
- **Python-compatible**: Works with standard `ssl` module, no ctypes/cffi hacks
- **Dual persistence**: In-memory dict (fast) + JSON file (survives restart) + CRL PEM (for external tooling)

## Changed Files

### `nanobot/mesh/ca.py`

New constants:
- `CRL_VALIDITY_DAYS = 30` — CRL `next_update` window

New instance state:
- `_revoked: dict[str, dict]` — in-memory revocation index (`{node_id: {serial: int, date: str}}`)

New properties:
- `crl_path` → `ca_dir/crl.pem`
- `revoked_json_path` → `ca_dir/revoked.json`

New methods:
- `_load_revoked()` — Loads `revoked.json` into `_revoked` dict. Called during `initialize()` and `_load_ca()`.
- `_save_revoked()` — Persists `_revoked` dict to `revoked.json`.
- `_generate_crl()` — Builds X.509 CRL from `_revoked` entries, signs with CA key, writes PEM. Uses `cryptography`'s `CertificateRevocationListBuilder`, `RevokedCertificateBuilder`.
- `revoke_device_cert(node_id: str) -> bool` — Main revocation method. Reads cert to extract serial, adds to `_revoked`, saves JSON, generates CRL PEM, deletes cert+key files. Returns `True` on success, `False` if node_id not found or already revoked.
- `is_revoked(node_id: str) -> bool` — O(1) dict lookup.
- `list_revoked() -> list[dict]` — Returns list of `{node_id, serial, date}` dicts.
- `rebuild_crl()` — Regenerates CRL PEM from `revoked.json` (recovery method).

Modified methods:
- `initialize()` — Calls `_load_revoked()` after CA creation.
- `_load_ca()` — Calls `_load_revoked()` after CA loading.
- `list_device_certs()` — Includes `"revoked": bool` field for each entry. Lists revoked entries even though their cert files are deleted (metadata from `_revoked` dict).

### `nanobot/mesh/transport.py`

New attribute:
- `revocation_check_fn: Callable[[str], bool] | None` — Set by channel to `ca.is_revoked`.

Modified method `_handle_connection()`:
```python
# After TLS handshake, before reading message:
if self._server_ssl_ctx and self.revocation_check_fn:
    peer_id = MeshCA.get_peer_node_id(writer.transport)
    if peer_id and self.revocation_check_fn(peer_id):
        writer.close()
        await writer.wait_closed()
        return
```

New method:
- `update_server_ssl_context(ctx)` — Hot-reload server SSL context (useful for cert rotation, not needed for revocation).

### `nanobot/mesh/channel.py`

Modified `__init__` / transport setup:
- After creating `MeshTransport`, wires `self.ca.is_revoked` as `transport.revocation_check_fn`.

New method:
- `async revoke_device(node_id: str, *, remove_from_registry: bool = False) -> bool` — Revokes cert via CA, optionally removes device from registry.

## Deviations from Design

1. **No SSL context rebuild on revocation** — Original design called for rebuilding SSL context after each revocation. App-level approach eliminates this entirely.
2. **CRL PEM is write-only from Hub's perspective** — Generated for external consumers (ESP32, audit tools) but not loaded into Python's SSL context.
3. **`update_server_ssl_context()`** — Kept for future cert rotation use, but not called during revocation.

## Key Code Patterns

### Dual Persistence
```
revoke_device_cert()
├── _revoked dict (in-memory, instant access)
├── revoked.json (file, survives restart)
└── crl.pem (X.509 CRL, for external tooling)
```

### Connection Rejection Flow
```
New TLS connection → TLS handshake succeeds → Extract peer CN
→ Check revocation_check_fn(CN) → If revoked: close immediately
→ If not revoked: proceed to read_envelope() and process message
```

### Documentation Freshness Check
- architecture.md: OK — mesh module already documented
- configuration.md: OK — no new config fields (CRL is automatic)
- customization.md: OK — no new extension points
- PRD.md: OK — will update status in roadmap
- agent.md: OK — no upstream convention changes

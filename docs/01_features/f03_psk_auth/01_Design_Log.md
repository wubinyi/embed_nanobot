# f03 — PSK-Based Device Authentication (HMAC Signing)

## Design Log

**Task**: 1.9 — PSK-based device authentication  
**Date**: 2026-02-17  
**Status**: Approved  

---

## 1. Overview

Add HMAC-SHA256 authentication to the LAN mesh transport layer. Every TCP mesh
message carries a signature computed with a per-device Pre-Shared Key (PSK).
The Hub maintains a key store mapping `node_id → PSK`. Unauthenticated messages
are rejected at the transport layer.

Discovery beacons (UDP) remain unsigned — they carry no sensitive data and
imply no trust. Authentication is enforced at the TCP transport layer.

---

## 2. Data Flow

```
Device sends message:
  1. Serialize envelope body (JSON, all fields except "hmac")
  2. Generate random 16-hex-char nonce
  3. Compute HMAC-SHA256(canonical_body + nonce, device_psk) → signature
  4. Attach "hmac" and "nonce" to the envelope dict
  5. Serialize full envelope → length-prefixed frame → TCP send

Hub receives message:
  1. Read length-prefixed frame → parse JSON
  2. Extract "hmac" and "nonce" fields; reconstruct body without them
  3. Look up PSK for source node_id in key store
  4. If node unknown → reject
  5. Compute HMAC-SHA256(canonical_body + nonce, stored_psk) → expected
  6. If hmac != expected → reject (log warning, close connection)
  7. Check timestamp window (reject if |now - ts| > nonce_window seconds)
  8. Check nonce not recently seen (reject replays)
  9. If all pass → deserialize to MeshEnvelope → dispatch to handlers
```

---

## 3. Wire Format

### Current (unauthenticated)
```
[4-byte big-endian length][JSON body]

JSON body:
{
  "type": "chat",
  "source": "device-01",
  "target": "hub-01",
  "payload": {"text": "hello"},
  "ts": 1700000000.0
}
```

### New (authenticated)
```
[4-byte big-endian length][JSON body with hmac + nonce]

JSON body:
{
  "type": "chat",
  "source": "device-01",
  "target": "hub-01",
  "payload": {"text": "hello"},
  "ts": 1700000000.0,
  "nonce": "a1b2c3d4e5f6a7b8",
  "hmac": "hex-encoded-hmac-sha256"
}
```

HMAC is computed over the canonical JSON of all fields **except** `hmac` and `nonce`,
concatenated with the nonce bytes. This prevents circular dependency and binds
the nonce to the signature.

Canonical body = `json.dumps(fields_without_hmac_nonce, sort_keys=True, ensure_ascii=False)`
HMAC input = `canonical_body_bytes + nonce_bytes`

---

## 4. Key Store Design

**Module**: `nanobot/mesh/security.py`  
**Storage**: JSON file at configurable path (default: `<workspace>/mesh_keys.json`)  
**Permissions**: `0600` on creation  

```json
{
  "device-01": {
    "psk": "hex-encoded-32-byte-key",
    "enrolled_at": "2026-02-17T12:00:00Z",
    "name": "Living Room Light"
  },
  "device-02": {
    "psk": "...",
    "enrolled_at": "...",
    "name": "Front Door Lock"
  }
}
```

### KeyStore API
- `load()` / `save()` — file I/O
- `add_device(node_id, name) → psk` — generate PSK, store, return
- `remove_device(node_id)` — revoke
- `get_psk(node_id) → str | None` — lookup
- `has_device(node_id) → bool`
- `sign(body_bytes, nonce, psk) → hex_hmac` — static
- `verify(body_bytes, nonce, psk, hmac_hex) → bool` — static

### Nonce Tracking
- In-memory set of recently seen nonces (bounded, last N minutes)
- `check_nonce(nonce) → bool` — returns True if nonce is fresh (not seen)
- `record_nonce(nonce)` — add to seen set
- Auto-prune nonces older than `nonce_window` seconds

---

## 5. Config Schema Additions

Appended to `MeshConfig` (append-only convention):

```python
# --- embed_nanobot extensions (append below this line) ---
psk_auth_enabled: bool = True           # Enable HMAC-PSK authentication
key_store_path: str = ""                # Path to mesh_keys.json (default: <workspace>/mesh_keys.json)
allow_unauthenticated: bool = False     # If True, log warning but still process unsigned messages
nonce_window: int = 60                  # Seconds; reject messages with ts outside this window
```

---

## 6. File Change Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/security.py` | KeyStore, HMAC sign/verify, nonce tracking, PSK generation |
| `docs/01_features/f03_psk_auth/01_Design_Log.md` | This document |
| `docs/01_features/f03_psk_auth/02_Dev_Implementation.md` | Implementation log |
| `docs/01_features/f03_psk_auth/03_Test_Report.md` | Test report |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Add `hmac` and `nonce` optional fields to `MeshEnvelope`; add `canonical_bytes()` method |
| `nanobot/mesh/transport.py` | Inject `KeyStore`; verify HMAC on receive; auto-sign on send |
| `nanobot/mesh/channel.py` | Create `KeyStore` from config; pass to `MeshTransport` |
| `nanobot/config/schema.py` | Append auth fields to `MeshConfig` |
| `tests/test_mesh.py` | Add security tests |

### Dependencies / Upstream Impact

- **No new dependencies** — uses only stdlib (`hmac`, `hashlib`, `secrets`, `json`, `os`, `time`)
- All new logic in `nanobot/mesh/security.py` — **zero upstream conflict risk**
- Config changes are append-only — **minimal conflict surface**
- `protocol.py` changes are additive (new optional fields + 1 method)
- `transport.py` changes are surgical (verification in `_handle_connection`, signing in `_send_to`)

---

## 7. Architect / Reviewer Debate

### Reviewer Challenge 1: Replay Attacks
> The `ts` field exists but isn't verified. Signed messages could be replayed.

**Resolution**: Added `nonce` field (16-hex-char random) included in HMAC computation.
Receiver tracks recent nonces to reject replays. Timestamp window check (configurable,
default 60s) as secondary defense.

### Reviewer Challenge 2: Discovery Beacons
> UDP beacons are unsigned. Rogue devices can advertise and attract connections.

**Resolution**: Acceptable for Phase 1. TCP authentication gates all message
processing. Discovery is a "phone book" only — no trust implied. Phase 2 mTLS
will secure the full stack.

### Reviewer Challenge 3: Key Storage Security
> Plain JSON on disk. Compromised Hub exposes all keys.

**Resolution**: Acceptable for Phase 1 (edge prototype). File permissions set
to `0600`. Phase 2 can add encrypted storage or OS keyring integration.

### Reviewer Challenge 4: `allow_unauthenticated` Flag
> Development convenience but security risk.

**Resolution**: Default `False`. Loud log warnings when enabled. Clear
documentation that this is for development only.

### Reviewer Challenge 5: HMAC Computation
> Including `hmac` in JSON creates circular dependency.

**Resolution**: Compute over canonical JSON of all fields **except** `hmac`/`nonce`,
then concatenate nonce. Inject `hmac` and `nonce` into dict before final serialization.

### Reviewer Challenge 6: ESP32 Compatibility
> Can constrained devices handle this?

**Resolution**: HMAC-SHA256 is hardware-accelerated on ESP32 (mbedtls). 32-byte PSK
is standard. Nonce + timestamp add negligible overhead (~50 bytes per message).

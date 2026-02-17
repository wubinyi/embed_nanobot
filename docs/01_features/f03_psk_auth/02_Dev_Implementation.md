# f03 — PSK Authentication: Dev Implementation Log

**Task**: 1.9 — PSK-based device authentication (HMAC signing)  
**Date**: 2026-02-17  
**Branch**: `copilot/psk-auth`  
**Status**: Complete  

---

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/security.py` | ~190 | `KeyStore` class, HMAC sign/verify, nonce tracking, PSK generation |
| `docs/01_features/f03_psk_auth/01_Design_Log.md` | — | Design document |
| `docs/01_features/f03_psk_auth/02_Dev_Implementation.md` | — | This file |
| `docs/01_features/f03_psk_auth/03_Test_Report.md` | — | Test Report |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Added `hmac` and `nonce` optional fields to `MeshEnvelope`; added `to_dict()`, `canonical_bytes()` methods; updated `from_bytes()` to handle auth fields gracefully |
| `nanobot/mesh/transport.py` | Added `key_store`, `psk_auth_enabled`, `allow_unauthenticated` params; added `_verify_inbound()` and `_sign_outbound()` methods |
| `nanobot/mesh/channel.py` | Added `KeyStore` initialization from config; passes auth params to `MeshTransport` |
| `nanobot/config/schema.py` | Appended 4 PSK auth fields to `MeshConfig` |
| `tests/test_mesh.py` | Added 25 new tests for security; updated existing tests with `psk_auth_enabled=False` |
| `.github/copilot-instructions.md` | v1.3 — added AUTO mode |

---

## Key Implementation Decisions

### 1. Canonical Serialization
HMAC is computed over `json.dumps(fields_excluding_hmac_nonce, sort_keys=True)` + nonce.
`sort_keys=True` ensures deterministic output regardless of dict ordering. The nonce
is appended (not included in JSON) to bind it to the signature without affecting
the canonical body.

### 2. Backward Compatibility
- `MeshEnvelope.to_dict()` omits `hmac`/`nonce` fields when they're empty strings.
- `from_bytes()` uses `.get()` with defaults, so old-format messages parse cleanly.
- When `psk_auth_enabled=False`, all auth checks are skipped — zero overhead.

### 3. Key Store Persistence
- JSON file at `<workspace>/mesh_keys.json` by default.
- `0600` permissions on creation (best-effort on Windows).
- Auto-creates parent directories.
- `add_device()` auto-saves; no need to call `save()` separately.

### 4. Nonce Tracking
- `OrderedDict` insertion-ordered for efficient front-pruning.
- Pruning happens lazily on every `check_and_record_nonce()` call.
- Bounded by `nonce_window` (default 60s) — memory usage grows linearly with
  message rate but is bounded by window size.

### 5. No New Dependencies
Uses only Python stdlib: `hmac`, `hashlib`, `secrets`, `json`, `os`, `time`,
`collections.OrderedDict`. This keeps the project lightweight and avoids adding
to `pyproject.toml`.

---

## Deviations from Design

None. Implementation follows the design log exactly.

---

### Documentation Freshness Check
- architecture.md: Updated — added security.py to mesh module description
- configuration.md: Updated — added PSK auth config fields
- customization.md: OK — no new extension patterns
- PRD.md: OK — DS-01/DS-03/DS-04 will be marked Done in roadmap update
- agent.md: OK — no upstream convention changes

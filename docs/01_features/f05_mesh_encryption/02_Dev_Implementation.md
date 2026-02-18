# f05 — Mesh Encryption: Dev Implementation

**Task**: 1.11 — Mesh message encryption (AES-256-GCM)
**Branch**: `copilot/mesh-encryption`
**Date**: 2026-02-18

---

## Files Changed

### New Files

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/encryption.py` | ~150 | AES-256-GCM encrypt/decrypt helpers, key derivation, availability check |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Added `encrypted_payload`, `iv` fields to `MeshEnvelope`; updated `to_dict()`, `from_bytes()` |
| `nanobot/mesh/transport.py` | Added `encryption_enabled` param, `_encrypt_outbound()`, `_decrypt_inbound()` methods; wired into send/receive pipeline |
| `nanobot/mesh/channel.py` | Passes `encryption_enabled` from config to transport |
| `nanobot/config/schema.py` | Added `encryption_enabled: bool = True` to `MeshConfig` |
| `pyproject.toml` | Added `cryptography>=41.0.0` dependency |
| `tests/test_mesh.py` | Added 37 new tests across 6 test classes; updated auth test for encryption compat |

---

## Key Design Decisions

1. **Key separation**: Encryption key derived as `HMAC-SHA256(PSK, b"mesh-encrypt-v1")`, separate from raw PSK used for HMAC auth. The domain separator `"mesh-encrypt-v1"` can be versioned for key rotation.

2. **Encrypt-then-MAC**: `_encrypt_outbound()` runs before `_sign_outbound()`. HMAC covers the ciphertext, following the Encrypt-then-MAC paradigm. On receive, HMAC verified first, then decrypted.

3. **AAD binding**: AES-GCM's additional authenticated data is `"type|source|target|ts"`, preventing an attacker from moving encrypted payloads between different message contexts.

4. **Selective encryption**: Only `CHAT`, `COMMAND`, `RESPONSE` types are encrypted. `PING`/`PONG` (heartbeat), `ENROLL_*` (no PSK yet), and broadcast (`*`) are left plaintext.

5. **PSK direction**: Outbound uses `target`'s PSK; inbound uses `source`'s PSK. In hub-spoke topology, both map to the same shared per-device key.

6. **Graceful degradation**: If `cryptography` is not installed, `HAS_AESGCM=False` disables encryption silently with a logged warning. Messages are sent/received unencrypted as before.

7. **Backward compatibility**: Unencrypted inbound messages (no `encrypted_payload` field) pass through `_decrypt_inbound()` untouched.

---

## Deviations from Plan

- None. Implementation matches design exactly.

---

### Documentation Freshness Check
- architecture.md: Updated — added encryption layer (3c) to mesh diagram
- configuration.md: Updated — added `encryptionEnabled` config field
- customization.md: OK — no changes needed
- PRD.md: OK — no status changes yet (will update roadmap separately)
- agent.md: OK — no upstream convention changes

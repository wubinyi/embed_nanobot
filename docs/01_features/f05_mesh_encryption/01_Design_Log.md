# f05 — Mesh Message Encryption (AES-256-GCM)

**Task**: 1.11 — Mesh message encryption
**Status**: In Progress
**Created**: 2026-02-18

---

## Architect/Reviewer Debate

### Architect — Design Proposal

**Problem**: Mesh messages are authenticated (HMAC, Task 1.9) but travel as plaintext JSON on the LAN. Anyone on the same network can sniff message content.

**Solution**: Encrypt message payloads with AES-256-GCM using per-device PSK-derived keys.

**Protocol flow** (Encrypt-then-MAC):

```
Sender (outbound):
  1. Build MeshEnvelope with plaintext payload
  2. _encrypt_outbound() → encrypt payload with AES-256-GCM
     - Only CHAT, COMMAND, RESPONSE message types
     - Key: HMAC-SHA256(PSK, "mesh-encrypt-v1") → 32-byte AES key
     - IV: random 12 bytes
     - AAD: "type|source|target|ts" (binds ciphertext to context)
     - Result: ciphertext (includes GCM tag) stored in encrypted_payload
     - Original payload cleared to {}
  3. _sign_outbound() → HMAC signs the encrypted envelope

Receiver (inbound):
  1. Read envelope (encrypted_payload + iv present)
  2. _verify_inbound() → verify HMAC over ciphertext (Encrypt-then-MAC)
  3. _decrypt_inbound() → decrypt payload back to plaintext
  4. Dispatch to handlers
```

**Key design decisions**:

1. **AES-256-GCM chosen over AES-CBC**: Provides AEAD (authenticated encryption), modern standard, single-pass.

2. **Key derivation**: `enc_key = HMAC-SHA256(key=PSK, msg=b"mesh-encrypt-v1")` — separates encryption key from HMAC key (which uses raw PSK). Correct, ESP32-friendly, stdlib-only derivation.

3. **Payload-only encryption**: Envelope metadata (type, source, target, ts) remains plaintext for routing. Payload is the sensitive content.

4. **AAD (Additional Authenticated Data)**: GCM binds ciphertext to envelope metadata, preventing payload reuse across different message contexts.

5. **`cryptography` library**: No stdlib AES available. `cryptography` is the standard Python crypto package (PyCA-maintained, uses OpenSSL). Handled gracefully if missing (logs warning, disables encryption).

6. **Which PSK**: Uses remote peer's PSK — `target` for outbound, `source` for inbound. In hub-spoke topology, both sides share the same per-device PSK.

7. **Excluded from encryption**: PING, PONG, ENROLL_REQUEST, ENROLL_RESPONSE, broadcast ("*").

### Reviewer — Challenges

1. **New dependency** (`cryptography`): Breaks "stdlib-only" pattern.
   - *Resolution*: Justified — there's no stdlib AES. Made optional with ImportError fallback. Standard package, well-maintained.

2. **Double authentication** (GCM tag + HMAC): Redundant?
   - *Resolution*: HMAC needed for backward compat with unencrypted messages. GCM AAD provides inner authentication. Defense in depth is acceptable.

3. **Key separation**: Same PSK for HMAC and AES derivation.
   - *Resolution*: HMAC-SHA256 derivation provides cryptographic key separation. Different domain separator ("mesh-encrypt-v1") ensures keys are independent.

4. **Enrollment messages**: Must not be encrypted (no PSK yet).
   - *Resolution*: Explicit type whitelist — only CHAT, COMMAND, RESPONSE are encrypted.

5. **ESP32 compatibility**: `cryptography` not available on MicroPython.
   - *Resolution*: ESP32 SDK (Task 2.5) will use `ucryptolib` or hardware AES. Protocol is the same; only the crypto library differs.

### Consensus

Design approved. AES-256-GCM with PSK-derived keys; `cryptography` as a (gracefully optional) dependency; Encrypt-then-MAC layered with existing HMAC.

---

## Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/encryption.py` | AES-256-GCM helpers: key derivation, encrypt/decrypt payload, availability check |

### Modified Files

| File | Changes |
|------|---------|
| `nanobot/mesh/protocol.py` | Add `encrypted_payload`, `iv` fields to MeshEnvelope; update `to_dict()`, `from_bytes()` |
| `nanobot/mesh/transport.py` | Add `encryption_enabled` param; `_encrypt_outbound()`, `_decrypt_inbound()` methods |
| `nanobot/mesh/channel.py` | Pass `encryption_enabled` from config to transport |
| `nanobot/config/schema.py` | Add `encryption_enabled: bool = True` to MeshConfig |
| `pyproject.toml` | Add `cryptography>=41.0.0` to dependencies |
| `tests/test_mesh.py` | Encryption tests (~25-30 tests) |

### Dependencies

- `cryptography>=41.0.0` (new; handles gracefully if missing)
- Uses existing: `KeyStore` (PSK lookup), `MeshTransport` (encrypt/decrypt hooks)

### Upstream Impact

- `pyproject.toml`: append `cryptography` at end of dependencies list
- All other changes in embed_nanobot-only files/sections (zero upstream conflict)

### Test Plan

- Key derivation determinism
- Encrypt/decrypt roundtrip (various payload sizes)
- AAD mismatch detection (tampered metadata)
- Wrong key detection
- Empty payload handling
- Availability check (is_available)
- Transport integration: encrypted send/receive, unencrypted fallback
- Config: encryption_enabled toggle
- Backward compat: unencrypted inbound still works
- Excluded types: PING/PONG/ENROLL not encrypted

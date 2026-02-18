# f09: Device-Command Routing — Design Log

**Task**: 2.4 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Requirements

> **Task 2.4**: Command-type routing — device commands always local.  
> When a user message references a registered device, bypass the difficulty judge and route directly to the local LLM for privacy and low latency.

## 2. Architect Proposal

### 2.1 Architecture

Three-layer approach:

1. **Detection** (`nanobot/mesh/routing.py`): Pure function `is_device_related(text, registry)` checks if text mentions device names, node IDs, types, or capabilities using case-insensitive, word-boundary-aware matching.

2. **Routing hook** (`nanobot/providers/hybrid_router.py`): `force_local_fn` callback on HybridRouterProvider, checked before the difficulty judge. If it returns `True`, route directly to local model.

3. **Wiring** (`nanobot/cli/commands.py`): After both provider and channels are created, set `provider.force_local_fn = build_force_local_fn(mesh_ch.registry)`.

### 2.2 Detection Strategy

| Match type | Example | Method |
|-----------|---------|--------|
| Device name | "Living Room Light" | Substring match (case-insensitive) |
| Node ID | "light-01" | Substring match |
| Device type | "smart_light" / "smart light" | Substring + underscore→space |
| Capability | "brightness", "temperature" | Word-boundary regex (`\b...\b`) |

**Anti-false-positive measures**:
- Capability names < 3 chars are skipped (avoid matching "on" in "online")
- Word-boundary matching for capabilities (avoid "power" matching "PowerPoint")

### 2.3 Data Flow

```
User: "Turn on the living room light"
  → HybridRouter.chat()
    → force_local_fn("Turn on the living room light")
      → is_device_related() → matches "Living Room Light" → True
    → Skip difficulty judge
    → Route to LOCAL model
    → Agent uses device_control tool to send command
```

## 3. Reviewer Assessment

**[Reviewer]**:
- **Positive**: Detection is registry-driven — adapts automatically as devices are added/removed.
- **Positive**: Word-boundary matching prevents false positives on capability names.
- **Positive**: Exception handling in force_local_fn — if detection fails, normal routing continues.
- **Concern**: Device type "temp_sensor" might match "temp" in unrelated text. Mitigated by full-string match (won't match "temp" alone).
- **Conflict surface**: 2 shared files modified minimally (hybrid_router.py + 3 lines, commands.py + 5 lines).

**[Architect]**: Approved. False positive risk is low given full-string matching for names/types.

## 4. Implementation Plan

### New Files

| File | Purpose |
|------|---------|
| `nanobot/mesh/routing.py` | `is_device_related()`, `build_force_local_fn()` |
| `tests/test_device_routing.py` | 21 tests across 3 classes |

### Modified Files

| File | Change |
|------|--------|
| `nanobot/providers/hybrid_router.py` | Added `force_local_fn` attribute, pre-routing check in `chat()` |
| `nanobot/cli/commands.py` | Wire up force_local_fn when mesh + HybridRouter both active |

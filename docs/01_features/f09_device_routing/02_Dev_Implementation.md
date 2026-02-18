# f09: Device-Command Routing — Dev Implementation

**Task**: 2.4 from Project Roadmap  
**Date**: 2026-02-18  
**Status**: Done

---

## 1. Implementation Summary

Three changes: one new module, two shared-file modifications (minimal).

## 2. New Module: `nanobot/mesh/routing.py` (~100 LOC)

### `is_device_related(text, registry) -> bool`

Scans text against all registered devices:
1. **Device node_id**: Substring match (`"light-01" in text_lower`)
2. **Device name**: Substring match (`"living room light" in text_lower`)
3. **Device type**: Substring + underscore-to-space variant
4. **Capability names**: Word-boundary regex (`\bbrightness\b`), skip names < 3 chars

Returns `True` on first match (short-circuit).

### `build_force_local_fn(registry) -> Callable[[str], bool]`

Closure factory that captures the registry reference. Returns a callback suitable for `HybridRouterProvider.force_local_fn`.

## 3. Modified: `nanobot/providers/hybrid_router.py`

**Import change**: Added `Callable` to typing imports.

**Constructor**: Appended `self.force_local_fn: Callable[[str], bool] | None = None`

**`chat()` method**: Added pre-routing block (before difficulty judge):
```python
if self.force_local_fn is not None:
    try:
        if self.force_local_fn(user_text):
            logger.info("[HybridRouter] forced LOCAL (device command detected)")
            return await self.local.chat(...)
    except Exception:
        # Fall through to normal routing
```

## 4. Modified: `nanobot/cli/commands.py`

Inside the existing mesh block (task 2.3), appended:
```python
from nanobot.providers.hybrid_router import HybridRouterProvider
if isinstance(provider, HybridRouterProvider):
    from nanobot.mesh.routing import build_force_local_fn
    provider.force_local_fn = build_force_local_fn(mesh_ch.registry)
```

## 5. Documentation Freshness Check

- architecture.md: Updated — added routing.py to mesh components
- configuration.md: OK — no new config fields
- customization.md: OK — no new patterns
- PRD.md: OK — will update via roadmap
- agent.md: OK — no convention changes

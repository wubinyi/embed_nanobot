# f20 Sensor Data Pipeline — Dev Implementation

**Task**: 4.4 Sensor Data Pipeline  
**Branch**: `copilot/sensor-pipeline`  
**Date**: 2026-02-26  

---

## Summary

Implemented an in-memory time-series sensor data pipeline with JSON persistence,
enabling historical queries, aggregations, and LLM-friendly summaries of device
sensor data.

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `nanobot/mesh/pipeline.py` | ~310 | Core pipeline module: SensorReading, RingBuffer, SensorPipeline, aggregation helpers |
| `tests/test_pipeline.py` | ~420 | 72 tests across 14 test classes |

## Files Modified

| File | Change |
|------|--------|
| `nanobot/config/schema.py` | Added 4 fields: `pipeline_enabled`, `pipeline_path`, `pipeline_max_points`, `pipeline_flush_interval` |
| `nanobot/mesh/channel.py` | Import SensorPipeline; init when enabled; start/stop lifecycle; auto-record in `_handle_state_report`; add to dashboard `data_fn` |

## Architecture Decisions

### In-Memory Ring Buffers
- Used `collections.deque(maxlen=N)` for O(1) append with automatic eviction
- One buffer per `(node_id, capability)` pair
- Default 10,000 readings per buffer; clamped minimum 100

### Persistence Model
- JSON file with `total_recorded` counter and serialised buffers
- Key format: `"node_id|capability"` for flat dict structure
- Auto-flush via configurable interval (default 60s)
- Final flush on stop to avoid data loss

### Auto-Recording Hook
- Pipeline records in `_handle_state_report()` after `registry.update_state()`
- Only numeric/boolean values are recorded; strings silently skipped
- Records before automation evaluation (so rules can reference fresh data)

### Aggregation Functions
Supported: `min`, `max`, `avg`, `sum`, `count`, `median`, `stdev`

### LLM Context
- `summary()` generates human-readable Markdown with per-device stats
- Includes: latest value, avg/min/max, count, time since last update
- Can filter to a single device

### Config Extraction Pattern
- Int fields use `isinstance(_raw, int)` guard (MagicMock safe)
- Bool field uses `is True` guard
- String field uses `or ""` pattern

## Deviations from Design

None. Implementation matches design log exactly.

---

### Documentation Freshness Check
- architecture.md: Updated — added pipeline.py to mesh components
- configuration.md: Updated — added pipeline config fields + setup guide
- customization.md: OK — no new extension points
- PRD.md: OK — no status changes needed yet
- agent.md: OK — no upstream convention changes

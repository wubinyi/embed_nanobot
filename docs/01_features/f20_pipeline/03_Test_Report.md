# f20 Sensor Data Pipeline — Test Report

**Task**: 4.4 Sensor Data Pipeline  
**Date**: 2026-02-26  
**Result**: 72 passed, 0 failed  
**Full regression**: 844 passed (772 baseline + 72 new), 0 failures  

---

## Test File

`tests/test_pipeline.py` — 72 tests across 14 classes

## Test Classes

| Class | Tests | Covers |
|-------|-------|--------|
| TestSensorReading | 5 | Dataclass creation (float, bool), to_dict, from_dict, roundtrip |
| TestRingBuffer | 9 | Empty, append, len, latest, max_size eviction, query (all/range/start/end), empty range |
| TestRingBufferSerialization | 4 | to_list, from_list, replace on load, skip bad entries |
| TestAggregation | 8 | min, max, avg, sum, count, median, stdev, empty, unknown raises, bool coercion, single-value stdev |
| TestPipelineRecording | 9 | record float/int/bool, ignore string/None, auto-timestamp, record_state (multi + empty), total_recorded |
| TestPipelineQuery | 4 | Nonexistent device, None latest, time range, most recent |
| TestPipelineAggregation | 4 | avg, range-filtered avg, empty, unknown raises |
| TestPipelinePersistence | 6 | save+load roundtrip, nonexistent file, corrupt file, no-path noop, total_recorded persistence |
| TestPipelineLifecycle | 3 | start/stop, flush loop auto-save, stop saves dirty data |
| TestPipelineSummary | 5 | Empty summary, with data, device filter, stats dict, buffer detail |
| TestPipelineListing | 4 | list_devices, empty list, list_capabilities, unknown device |
| TestPipelineConfig | 2 | max_points minimum clamp, large value |
| TestChannelPipelineIntegration | 5 | Disabled by default, enabled, custom settings, state report recording, dashboard data_fn |

## Edge Cases Covered

- **String/None values**: Silently ignored during recording
- **Empty state dict**: Returns 0 recorded
- **Corrupt JSON file**: Gracefully returns 0 on load
- **Missing file**: Returns 0 on load
- **No path configured**: Save/load are no-ops
- **Buffer eviction**: Ring buffer auto-evicts oldest when full
- **Time range queries**: Start-only, end-only, both, empty range
- **Min clamp**: max_points below 100 clamped to 100
- **Single-value stdev**: Returns 0.0 (no division error)
- **Bool coercion**: True → 1.0, False → 0.0 in aggregations
- **MagicMock safety**: int config fields use isinstance guard

## Test Execution

```
$ python -m pytest tests/test_pipeline.py -v
72 passed in 0.72s

$ python -m pytest tests/ -v
844 passed in 14.65s
```

# f20 — Sensor Data Pipeline: Design Log

**Task**: 4.4 — Sensor data pipeline and analytics  
**Priority**: P2 | **Complexity**: L  
**Dependencies**: Registry (2.1)

---

## Problem Statement

The device registry tracks only the **latest** state of each device. For sensor-heavy deployments (temperature, humidity, pressure, motor RPM, power usage), we need **time-series history** to support:

1. Trend analysis ("What was the temperature over the last 24 hours?")
2. Aggregations ("Average power consumption this week")
3. Anomaly detection ("Alert when vibration exceeds 2x the rolling average")
4. LLM context ("The sensor has been reading 45°C steadily for 2 hours")

## Design Goals

1. **Zero new dependencies** — stdlib only, file-based storage (JSON-lines)
2. **Resource-efficient** — bounded retention, configurable max points per device
3. **Auto-recording** — hooks into registry state_changed events
4. **Query API** — time-range queries, aggregation functions
5. **Dashboard integration** — pipeline stats available via existing dashboard API
6. **LLM context** — summarize sensor trends for agent context

## Architecture

### Architect/Reviewer Debate

**[Architect]**: Two storage options:

**Option A — JSON-lines file**: One `.jsonl` file, append-only, periodic compaction. Simple, no dependencies.
- Pro: Simplest possible, universal format
- Con: Querying requires scanning; compaction overhead

**Option B — SQLite**: Use stdlib `sqlite3` for proper time-series queries.
- Pro: Real indexing, efficient range queries, aggregation built-in
- Con: File locking in async context needs careful handling; heavier

**[Reviewer]**: For a resource-constrained hub (RPi 4, 4GB RAM), SQLite is actually lighter than loading a big JSONL file into memory. But for L complexity, keeping things in-memory with periodic JSON dump is fine. We're not storing millions of points — bounded at N points per device.

**[Architect]**: Agreed. In-memory ring buffer per (device, capability) pair, periodic JSON dump for persistence. Keep it simple. If we ever need real time-series at scale, we can add InfluxDB/TimescaleDB as a future extension.

### Design

```
┌───────────────────────────────────────────────────┐
│  SensorPipeline                                    │
│                                                    │
│  _buffers: dict[(node_id, capability) → RingBuffer]│
│                                                    │
│  record(node_id, capability, value, ts)            │
│  query(node_id, capability, start, end) → [points] │
│  aggregate(node_id, cap, start, end, fn) → float   │
│  summary(node_id) → str (LLM context)             │
│  stats() → dict (for dashboard)                    │
│                                                    │
│  _save() / load() — JSON persistence               │
│  _compact() — trim to max_points per buffer         │
└───────────────────────────────────────────────────┘
```

### Data Model

```python
@dataclass
class SensorReading:
    value: float | int | bool
    ts: float  # Unix timestamp

class RingBuffer:
    max_size: int
    readings: deque[SensorReading]
    # O(1) append, O(1) len, automatic eviction of oldest
```

### Config

```json
"mesh": {
  "pipelineEnabled": true,
  "pipelinePath": "",           // Path to pipeline data file. Empty = <workspace>/sensor_data.json
  "pipelineMaxPoints": 10000,   // Max readings per (device, capability) pair
  "pipelineFlushInterval": 60   // Seconds between auto-save to disk
}
```

### Channel Integration

- **Init**: Create SensorPipeline if `pipeline_enabled`
- **State hook**: On `state_changed` event, record numeric/boolean readings
- **Dashboard**: Add pipeline stats to dashboard data_fn

## File Plan

### New Files
| File | Purpose |
|------|---------|
| `nanobot/mesh/pipeline.py` | SensorPipeline, RingBuffer, SensorReading |
| `tests/test_pipeline.py` | Unit tests |
| `docs/01_features/f20_pipeline/` | Design, implementation, test docs |

### Modified Files
| File | Change |
|------|--------|
| `nanobot/config/schema.py` | +4 fields: pipeline_enabled, pipeline_path, pipeline_max_points, pipeline_flush_interval |
| `nanobot/mesh/channel.py` | Pipeline init, state hook, dashboard integration |
| `docs/configuration.md` | +pipeline fields + example |
| `docs/architecture.md` | +pipeline component description |

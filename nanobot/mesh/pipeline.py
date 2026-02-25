"""Sensor data pipeline — time-series recording and analytics.

Records device readings over time, enabling historical queries, aggregations,
and LLM-friendly summaries.

Storage model
-------------
In-memory ring buffers (``collections.deque``) per ``(node_id, capability)``
pair.  Each buffer retains up to ``max_points`` readings (default 10 000).
Periodic JSON dump for persistence across restarts.

Usage in MeshChannel
--------------------
The channel hooks into the registry's ``state_changed`` event and calls
``record()`` for every numeric/boolean value change.  The pipeline's
``summary()`` method can be injected into the LLM system prompt for
data-aware reasoning.

Configuration
-------------
See ``MeshConfig.pipeline_enabled``, ``pipeline_path``,
``pipeline_max_points``, ``pipeline_flush_interval``.
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SensorReading:
    """A single timestamped sensor measurement."""

    value: float | int | bool
    ts: float  # Unix timestamp

    def to_dict(self) -> dict:
        return {"value": self.value, "ts": self.ts}

    @classmethod
    def from_dict(cls, d: dict) -> "SensorReading":
        return cls(value=d["value"], ts=d["ts"])


class RingBuffer:
    """Fixed-capacity FIFO buffer for sensor readings.

    Uses ``collections.deque`` with ``maxlen`` for O(1) append and
    automatic eviction of the oldest reading when full.
    """

    __slots__ = ("_buf",)

    def __init__(self, max_size: int = 10_000):
        self._buf: deque[SensorReading] = deque(maxlen=max_size)

    def append(self, reading: SensorReading) -> None:
        self._buf.append(reading)

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def max_size(self) -> int:
        return self._buf.maxlen  # type: ignore[return-value]

    def query(
        self,
        start: float | None = None,
        end: float | None = None,
    ) -> list[SensorReading]:
        """Return readings in the [start, end] time range."""
        result: list[SensorReading] = []
        for r in self._buf:
            if start is not None and r.ts < start:
                continue
            if end is not None and r.ts > end:
                continue
            result.append(r)
        return result

    def latest(self) -> SensorReading | None:
        """Return the most recent reading, or None if empty."""
        return self._buf[-1] if self._buf else None

    def to_list(self) -> list[dict]:
        """Serialise all readings to a list of dicts."""
        return [r.to_dict() for r in self._buf]

    def from_list(self, data: list[dict]) -> None:
        """Load readings from a list of dicts (replaces current contents)."""
        self._buf.clear()
        for d in data:
            try:
                self._buf.append(SensorReading.from_dict(d))
            except (KeyError, TypeError):
                pass


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

_AGG_FUNCTIONS: dict[str, Callable[[list[float]], float]] = {
    "min": min,
    "max": max,
    "avg": lambda vals: statistics.mean(vals) if vals else 0.0,
    "sum": sum,
    "count": lambda vals: float(len(vals)),
    "median": lambda vals: statistics.median(vals) if vals else 0.0,
    "stdev": lambda vals: statistics.stdev(vals) if len(vals) >= 2 else 0.0,
}


def aggregate_readings(
    readings: list[SensorReading],
    fn_name: str,
) -> float:
    """Apply a named aggregation function to a list of readings.

    Supported functions: min, max, avg, sum, count, median, stdev.
    Non-numeric readings (bool) are coerced to 0/1.
    """
    fn = _AGG_FUNCTIONS.get(fn_name)
    if fn is None:
        raise ValueError(f"Unknown aggregation: {fn_name!r}. "
                         f"Supported: {list(_AGG_FUNCTIONS.keys())}")
    values = [float(r.value) for r in readings]
    if not values:
        return 0.0
    return fn(values)


# ---------------------------------------------------------------------------
# SensorPipeline
# ---------------------------------------------------------------------------

class SensorPipeline:
    """Time-series sensor data pipeline with recording, querying, and analytics.

    Parameters
    ----------
    path:
        File path for JSON persistence. Empty string disables persistence.
    max_points:
        Maximum readings per (device, capability) buffer.
    flush_interval:
        Seconds between auto-save to disk. 0 = manual save only.
    """

    def __init__(
        self,
        path: str = "",
        max_points: int = 10_000,
        flush_interval: float = 60.0,
    ) -> None:
        self.path = path
        self.max_points = max(100, max_points)
        self.flush_interval = flush_interval
        self._buffers: dict[tuple[str, str], RingBuffer] = {}
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._dirty = False
        self._total_recorded: int = 0

    # -- lifecycle ---

    def load(self) -> int:
        """Load persisted data from disk.

        Returns the total number of readings loaded.
        """
        if not self.path:
            return 0
        p = Path(self.path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            total = 0
            for key_str, readings_list in data.get("buffers", {}).items():
                parts = key_str.split("|", 1)
                if len(parts) != 2:
                    continue
                node_id, capability = parts
                buf = self._get_or_create_buffer(node_id, capability)
                buf.from_list(readings_list)
                total += len(buf)
            self._total_recorded = data.get("total_recorded", total)
            logger.info(
                "[Pipeline] loaded {} readings across {} buffers from {}",
                total, len(self._buffers), self.path,
            )
            return total
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("[Pipeline] failed to load data: {}", exc)
            return 0

    async def start(self) -> None:
        """Start the auto-flush loop."""
        self._running = True
        if self.flush_interval > 0 and self.path:
            self._flush_task = asyncio.ensure_future(self._flush_loop())
        logger.info(
            "[Pipeline] started (max_points={}, flush={}s, path={})",
            self.max_points, self.flush_interval, self.path or "disabled",
        )

    async def stop(self) -> None:
        """Stop the flush loop and save final state."""
        self._running = False
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._dirty:
            self._save()
        logger.info("[Pipeline] stopped")

    async def _flush_loop(self) -> None:
        """Periodically save to disk."""
        try:
            while self._running:
                await asyncio.sleep(self.flush_interval)
                if not self._running:
                    break
                if self._dirty:
                    self._save()
        except asyncio.CancelledError:
            pass

    def _save(self) -> None:
        """Persist all buffers to disk."""
        if not self.path:
            return
        data: dict[str, Any] = {
            "total_recorded": self._total_recorded,
            "buffers": {},
        }
        for (node_id, cap), buf in self._buffers.items():
            key_str = f"{node_id}|{cap}"
            data["buffers"][key_str] = buf.to_list()
        try:
            Path(self.path).write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            self._dirty = False
        except OSError as exc:
            logger.error("[Pipeline] save failed: {}", exc)

    # -- buffer management ---

    def _get_or_create_buffer(
        self,
        node_id: str,
        capability: str,
    ) -> RingBuffer:
        """Get or create a ring buffer for a (device, capability) pair."""
        key = (node_id, capability)
        buf = self._buffers.get(key)
        if buf is None:
            buf = RingBuffer(max_size=self.max_points)
            self._buffers[key] = buf
        return buf

    # -- recording ---

    def record(
        self,
        node_id: str,
        capability: str,
        value: float | int | bool,
        ts: float | None = None,
    ) -> None:
        """Record a sensor reading.

        Non-numeric values are silently ignored.
        """
        if not isinstance(value, (int, float, bool)):
            return
        reading = SensorReading(value=value, ts=ts or time.time())
        buf = self._get_or_create_buffer(node_id, capability)
        buf.append(reading)
        self._total_recorded += 1
        self._dirty = True

    def record_state(self, node_id: str, state: dict[str, Any]) -> int:
        """Record all numeric/boolean values from a state dict.

        Returns the number of readings recorded.
        """
        count = 0
        ts = time.time()
        for cap, value in state.items():
            if isinstance(value, (int, float, bool)):
                self.record(node_id, cap, value, ts)
                count += 1
        return count

    # -- querying ---

    def query(
        self,
        node_id: str,
        capability: str,
        start: float | None = None,
        end: float | None = None,
    ) -> list[SensorReading]:
        """Query readings for a (device, capability) in a time range.

        Returns an empty list if no data exists.
        """
        key = (node_id, capability)
        buf = self._buffers.get(key)
        if buf is None:
            return []
        return buf.query(start=start, end=end)

    def latest(
        self,
        node_id: str,
        capability: str,
    ) -> SensorReading | None:
        """Get the most recent reading for a (device, capability)."""
        key = (node_id, capability)
        buf = self._buffers.get(key)
        return buf.latest() if buf else None

    def aggregate(
        self,
        node_id: str,
        capability: str,
        fn_name: str,
        start: float | None = None,
        end: float | None = None,
    ) -> float:
        """Run an aggregation over readings in a time range.

        Supported: min, max, avg, sum, count, median, stdev.
        Returns 0.0 if no data.
        """
        readings = self.query(node_id, capability, start=start, end=end)
        return aggregate_readings(readings, fn_name)

    # -- LLM context ---

    def summary(self, node_id: str | None = None) -> str:
        """Generate a human-readable summary of sensor data.

        If ``node_id`` is given, summarise only that device.
        Otherwise, summarise all devices.
        """
        lines: list[str] = ["## Sensor Data Summary\n"]
        # Group by node_id
        device_caps: dict[str, list[str]] = {}
        for (nid, cap) in self._buffers:
            if node_id and nid != node_id:
                continue
            device_caps.setdefault(nid, []).append(cap)

        if not device_caps:
            return "No sensor data recorded."

        for nid in sorted(device_caps):
            lines.append(f"### {nid}")
            for cap in sorted(device_caps[nid]):
                buf = self._buffers[(nid, cap)]
                count = len(buf)
                latest_r = buf.latest()
                if count == 0 or latest_r is None:
                    continue
                readings = buf.query()
                values = [float(r.value) for r in readings]
                avg_val = statistics.mean(values) if values else 0
                min_val = min(values) if values else 0
                max_val = max(values) if values else 0
                age_s = time.time() - latest_r.ts
                if age_s < 60:
                    age_str = f"{age_s:.0f}s ago"
                elif age_s < 3600:
                    age_str = f"{age_s / 60:.0f}m ago"
                else:
                    age_str = f"{age_s / 3600:.1f}h ago"
                lines.append(
                    f"- **{cap}**: latest={latest_r.value}, "
                    f"avg={avg_val:.2f}, min={min_val}, max={max_val}, "
                    f"count={count}, last update {age_str}"
                )
            lines.append("")
        return "\n".join(lines)

    # -- monitoring ---

    def stats(self) -> dict[str, Any]:
        """Return pipeline statistics for the dashboard."""
        buffer_stats: list[dict] = []
        for (node_id, cap), buf in self._buffers.items():
            latest = buf.latest()
            buffer_stats.append({
                "node_id": node_id,
                "capability": cap,
                "count": len(buf),
                "max_size": buf.max_size,
                "latest_value": latest.value if latest else None,
                "latest_ts": latest.ts if latest else None,
            })
        return {
            "total_recorded": self._total_recorded,
            "active_buffers": len(self._buffers),
            "buffers": buffer_stats,
            "path": self.path,
            "max_points_per_buffer": self.max_points,
            "flush_interval": self.flush_interval,
        }

    def list_capabilities(self, node_id: str) -> list[str]:
        """List all tracked capabilities for a device."""
        return [
            cap for (nid, cap) in self._buffers
            if nid == node_id
        ]

    def list_devices(self) -> list[str]:
        """List all devices with sensor data."""
        return list({nid for (nid, _) in self._buffers})

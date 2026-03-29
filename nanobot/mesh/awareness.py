"""Environmental awareness loop (task 5.1.2).

Periodically builds a snapshot of the device ecosystem and detects anomalies
by comparing recent sensor readings against historical baselines.  Generates
actionable summaries that feed into the autonomous mode LLM prompt.

This module integrates with:
- ``DeviceRegistry`` — online/offline tracking, state snapshots
- ``SensorPipeline`` — historical data, trend analysis
- ``AutomationEngine`` — rule activity analysis
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from nanobot.mesh.automation import AutomationEngine
    from nanobot.mesh.pipeline import SensorPipeline
    from nanobot.mesh.registry import DeviceRegistry


class DeviceSnapshot:
    """Immutable snapshot of the device ecosystem at a point in time."""

    __slots__ = ("ts", "online_ids", "offline_ids", "device_states", "anomalies")

    def __init__(
        self,
        ts: float,
        online_ids: list[str],
        offline_ids: list[str],
        device_states: dict[str, dict[str, Any]],
        anomalies: list[str],
    ):
        self.ts = ts
        self.online_ids = online_ids
        self.offline_ids = offline_ids
        self.device_states = device_states
        self.anomalies = anomalies


class AwarenessLoop:
    """Builds device ecosystem snapshots and detects anomalies.

    Not an asyncio loop itself — called by ``AutonomousService`` each tick
    to produce an enriched context string.
    """

    def __init__(
        self,
        registry: DeviceRegistry | None = None,
        pipeline: SensorPipeline | None = None,
        automation: AutomationEngine | None = None,
        anomaly_threshold: float = 2.0,
    ):
        self.registry = registry
        self.pipeline = pipeline
        self.automation = automation
        self.anomaly_threshold = anomaly_threshold
        self._previous_snapshot: DeviceSnapshot | None = None

    def take_snapshot(self) -> DeviceSnapshot:
        """Capture current device ecosystem state and detect anomalies."""
        now = time.time()
        online_ids: list[str] = []
        offline_ids: list[str] = []
        device_states: dict[str, dict[str, Any]] = {}
        anomalies: list[str] = []

        if self.registry:
            for dev in self.registry.get_all_devices():
                if dev.online:
                    online_ids.append(dev.node_id)
                else:
                    offline_ids.append(dev.node_id)
                if dev.state:
                    device_states[dev.node_id] = dict(dev.state)

        # Detect status changes from previous snapshot
        if self._previous_snapshot:
            prev_online = set(self._previous_snapshot.online_ids)
            curr_online = set(online_ids)
            went_offline = prev_online - curr_online
            came_online = curr_online - prev_online
            for nid in went_offline:
                anomalies.append(f"Device {nid} went OFFLINE since last scan")
            for nid in came_online:
                anomalies.append(f"Device {nid} came ONLINE since last scan")

        # Detect sensor anomalies (values outside historical baseline)
        if self.pipeline:
            anomalies.extend(self._detect_sensor_anomalies(now))

        snap = DeviceSnapshot(
            ts=now,
            online_ids=online_ids,
            offline_ids=offline_ids,
            device_states=device_states,
            anomalies=anomalies,
        )
        self._previous_snapshot = snap
        return snap

    def _detect_sensor_anomalies(self, now: float) -> list[str]:
        """Compare recent sensor readings against historical averages."""
        anomalies: list[str] = []
        if not self.pipeline:
            return anomalies

        # Look at last 5 minutes of data vs last 1 hour
        recent_window = 5 * 60
        baseline_window = 60 * 60

        for node_id in self.pipeline.list_devices():
            for cap in self.pipeline.list_capabilities(node_id):
                try:
                    recent = self.pipeline.query(
                        node_id, cap,
                        start=now - recent_window,
                        end=now,
                    )
                    baseline = self.pipeline.query(
                        node_id, cap,
                        start=now - baseline_window,
                        end=now - recent_window,
                    )

                    if len(recent) < 2 or len(baseline) < 5:
                        continue

                    recent_vals = [float(r.value) for r in recent]
                    baseline_vals = [float(r.value) for r in baseline]
                    recent_avg = sum(recent_vals) / len(recent_vals)
                    baseline_avg = sum(baseline_vals) / len(baseline_vals)

                    if baseline_avg == 0:
                        continue

                    # compute standard deviation of baseline
                    variance = sum((v - baseline_avg) ** 2 for v in baseline_vals) / len(baseline_vals)
                    stdev = variance ** 0.5
                    if stdev == 0:
                        continue

                    deviation = abs(recent_avg - baseline_avg) / stdev
                    if deviation >= self.anomaly_threshold:
                        direction = "above" if recent_avg > baseline_avg else "below"
                        anomalies.append(
                            f"{node_id}/{cap}: recent avg ({recent_avg:.1f}) is "
                            f"{deviation:.1f}σ {direction} baseline ({baseline_avg:.1f})"
                        )
                except (ValueError, TypeError):
                    continue

        return anomalies

    def format_snapshot(self, snap: DeviceSnapshot) -> str:
        """Format a snapshot into a human-readable report section."""
        lines: list[str] = []

        lines.append("## Device Ecosystem Snapshot")
        lines.append(f"Online: {len(snap.online_ids)} | Offline: {len(snap.offline_ids)}")

        if snap.anomalies:
            lines.append("\n### ⚠ Anomalies Detected")
            for a in snap.anomalies:
                lines.append(f"- {a}")

        if snap.device_states:
            lines.append("\n### Device States")
            for nid in sorted(snap.device_states):
                state = snap.device_states[nid]
                state_str = ", ".join(f"{k}={v}" for k, v in state.items())
                lines.append(f"- **{nid}**: {state_str}")

        return "\n".join(lines)

    def build_awareness_context(self) -> str:
        """Take a snapshot and return a formatted context string.

        This is the primary method called by AutonomousService.
        """
        snap = self.take_snapshot()
        return self.format_snapshot(snap)

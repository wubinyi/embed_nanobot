"""Tests for the environmental awareness loop (task 5.1.2)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from nanobot.mesh.awareness import AwarenessLoop, DeviceSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(node_id: str, online: bool = True, state: dict | None = None,
                 device_type: str = "esp32"):
    d = MagicMock()
    d.node_id = node_id
    d.online = online
    d.device_type = device_type
    d.state = state or {}
    d.capabilities = []
    return d


def _make_registry(devices: list | None = None):
    reg = MagicMock()
    reg.get_all_devices.return_value = devices or []
    return reg


def _make_reading(value: float, ts: float):
    r = MagicMock()
    r.value = value
    r.ts = ts
    return r


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_empty_snapshot(self):
        loop = AwarenessLoop()
        snap = loop.take_snapshot()
        assert snap.online_ids == []
        assert snap.offline_ids == []
        assert snap.anomalies == []

    def test_snapshot_captures_devices(self):
        devices = [
            _make_device("d1", True, {"temp": 24}),
            _make_device("d2", False),
        ]
        loop = AwarenessLoop(registry=_make_registry(devices))
        snap = loop.take_snapshot()
        assert snap.online_ids == ["d1"]
        assert snap.offline_ids == ["d2"]
        assert snap.device_states == {"d1": {"temp": 24}}

    def test_detects_offline_change(self):
        """Second snapshot should detect device going offline."""
        reg = _make_registry([_make_device("d1", True)])
        loop = AwarenessLoop(registry=reg)

        # First snapshot: d1 online
        loop.take_snapshot()

        # Second snapshot: d1 offline
        reg.get_all_devices.return_value = [_make_device("d1", False)]
        snap2 = loop.take_snapshot()
        assert any("d1" in a and "OFFLINE" in a for a in snap2.anomalies)

    def test_detects_online_change(self):
        """Second snapshot should detect device coming online."""
        reg = _make_registry([_make_device("d1", False)])
        loop = AwarenessLoop(registry=reg)
        loop.take_snapshot()

        reg.get_all_devices.return_value = [_make_device("d1", True)]
        snap2 = loop.take_snapshot()
        assert any("d1" in a and "ONLINE" in a for a in snap2.anomalies)


# ---------------------------------------------------------------------------
# Anomaly detection tests
# ---------------------------------------------------------------------------

class TestAnomalyDetection:
    def test_no_anomaly_within_threshold(self):
        """Values within normal range should not trigger anomaly."""
        now = time.time()
        pipeline = MagicMock()
        pipeline.list_devices.return_value = ["d1"]
        pipeline.list_capabilities.return_value = ["temp"]
        # Baseline: 20-24 (avg 22), Recent: 22-23 (avg 22.5) — well within 1σ
        pipeline.query.side_effect = [
            [_make_reading(22, now - 60), _make_reading(23, now - 30)],  # recent
            [_make_reading(20, now - 3000), _make_reading(22, now - 2000),
             _make_reading(24, now - 1000), _make_reading(22, now - 800),
             _make_reading(22, now - 600)],  # baseline
        ]
        loop = AwarenessLoop(pipeline=pipeline, anomaly_threshold=2.0)
        snap = loop.take_snapshot()
        assert len(snap.anomalies) == 0

    def test_anomaly_above_threshold(self):
        """Values significantly above baseline should trigger anomaly."""
        now = time.time()
        pipeline = MagicMock()
        pipeline.list_devices.return_value = ["d1"]
        pipeline.list_capabilities.return_value = ["temp"]
        # Baseline: consistent 22 (stdev ~0), Recent: 35 — huge deviation
        pipeline.query.side_effect = [
            [_make_reading(35, now - 60), _make_reading(35, now - 30)],  # recent
            [_make_reading(22, now - 3000), _make_reading(22.1, now - 2000),
             _make_reading(21.9, now - 1000), _make_reading(22, now - 800),
             _make_reading(22, now - 600)],  # baseline
        ]
        loop = AwarenessLoop(pipeline=pipeline, anomaly_threshold=2.0)
        snap = loop.take_snapshot()
        assert len(snap.anomalies) == 1
        assert "above" in snap.anomalies[0]

    def test_not_enough_data_skipped(self):
        """Insufficient data points should be silently skipped."""
        now = time.time()
        pipeline = MagicMock()
        pipeline.list_devices.return_value = ["d1"]
        pipeline.list_capabilities.return_value = ["temp"]
        # Only 1 recent reading, 2 baseline — below thresholds
        pipeline.query.side_effect = [
            [_make_reading(35, now - 60)],  # recent (< 2)
            [_make_reading(22, now - 3000), _make_reading(22, now - 2000)],  # baseline (< 5)
        ]
        loop = AwarenessLoop(pipeline=pipeline)
        snap = loop.take_snapshot()
        assert len(snap.anomalies) == 0


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------

class TestFormat:
    def test_format_snapshot(self):
        loop = AwarenessLoop()
        snap = DeviceSnapshot(
            ts=time.time(),
            online_ids=["d1", "d2"],
            offline_ids=["d3"],
            device_states={"d1": {"led": True}, "d2": {"temp": 24}},
            anomalies=["d3 went OFFLINE since last scan"],
        )
        text = loop.format_snapshot(snap)
        assert "Online: 2" in text
        assert "Offline: 1" in text
        assert "d3 went OFFLINE" in text
        assert "led=True" in text

    def test_build_awareness_context(self):
        devices = [_make_device("d1", True, {"led": False})]
        loop = AwarenessLoop(registry=_make_registry(devices))
        ctx = loop.build_awareness_context()
        assert "Device Ecosystem Snapshot" in ctx
        assert "d1" in ctx

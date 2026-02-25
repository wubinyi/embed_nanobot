"""Tests for nanobot.mesh.pipeline — sensor data pipeline."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.mesh.pipeline import (
    RingBuffer,
    SensorPipeline,
    SensorReading,
    aggregate_readings,
)


# ---------------------------------------------------------------------------
# SensorReading
# ---------------------------------------------------------------------------


class TestSensorReading:
    """Test SensorReading dataclass."""

    def test_create_float(self):
        r = SensorReading(value=23.5, ts=1000.0)
        assert r.value == 23.5
        assert r.ts == 1000.0

    def test_create_bool(self):
        r = SensorReading(value=True, ts=2000.0)
        assert r.value is True

    def test_to_dict(self):
        r = SensorReading(value=42, ts=3000.0)
        d = r.to_dict()
        assert d == {"value": 42, "ts": 3000.0}

    def test_from_dict(self):
        r = SensorReading.from_dict({"value": 99.9, "ts": 4000.0})
        assert r.value == 99.9
        assert r.ts == 4000.0

    def test_roundtrip(self):
        original = SensorReading(value=-5.5, ts=5000.0)
        restored = SensorReading.from_dict(original.to_dict())
        assert restored.value == original.value
        assert restored.ts == original.ts


# ---------------------------------------------------------------------------
# RingBuffer
# ---------------------------------------------------------------------------


class TestRingBuffer:
    """Test RingBuffer with deque."""

    def test_empty(self):
        buf = RingBuffer(max_size=100)
        assert len(buf) == 0
        assert buf.latest() is None

    def test_append_and_len(self):
        buf = RingBuffer(max_size=100)
        buf.append(SensorReading(value=1.0, ts=100.0))
        buf.append(SensorReading(value=2.0, ts=200.0))
        assert len(buf) == 2

    def test_latest(self):
        buf = RingBuffer(max_size=100)
        buf.append(SensorReading(value=1.0, ts=100.0))
        buf.append(SensorReading(value=2.0, ts=200.0))
        latest = buf.latest()
        assert latest is not None
        assert latest.value == 2.0

    def test_max_size_eviction(self):
        buf = RingBuffer(max_size=3)
        for i in range(5):
            buf.append(SensorReading(value=float(i), ts=float(i)))
        assert len(buf) == 3
        # Oldest 2 should be evicted
        assert buf.latest().value == 4.0
        readings = buf.query()
        assert [r.value for r in readings] == [2.0, 3.0, 4.0]

    def test_max_size_property(self):
        buf = RingBuffer(max_size=500)
        assert buf.max_size == 500

    def test_query_all(self):
        buf = RingBuffer(max_size=100)
        for i in range(5):
            buf.append(SensorReading(value=float(i), ts=float(i * 10)))
        result = buf.query()
        assert len(result) == 5

    def test_query_time_range(self):
        buf = RingBuffer(max_size=100)
        for i in range(10):
            buf.append(SensorReading(value=float(i), ts=float(i * 10)))
        # [30, 60] should give timestamps 30, 40, 50, 60
        result = buf.query(start=30.0, end=60.0)
        assert len(result) == 4
        assert result[0].ts == 30.0
        assert result[-1].ts == 60.0

    def test_query_start_only(self):
        buf = RingBuffer(max_size=100)
        for i in range(5):
            buf.append(SensorReading(value=float(i), ts=float(i * 10)))
        result = buf.query(start=20.0)
        assert len(result) == 3
        assert result[0].ts == 20.0

    def test_query_end_only(self):
        buf = RingBuffer(max_size=100)
        for i in range(5):
            buf.append(SensorReading(value=float(i), ts=float(i * 10)))
        result = buf.query(end=20.0)
        assert len(result) == 3  # 0, 10, 20

    def test_query_empty_range(self):
        buf = RingBuffer(max_size=100)
        buf.append(SensorReading(value=1.0, ts=100.0))
        result = buf.query(start=200.0, end=300.0)
        assert result == []


class TestRingBufferSerialization:
    """Test to_list / from_list."""

    def test_to_list(self):
        buf = RingBuffer(max_size=100)
        buf.append(SensorReading(value=1.0, ts=100.0))
        buf.append(SensorReading(value=2.0, ts=200.0))
        data = buf.to_list()
        assert len(data) == 2
        assert data[0] == {"value": 1.0, "ts": 100.0}

    def test_from_list(self):
        buf = RingBuffer(max_size=100)
        buf.from_list([
            {"value": 10.0, "ts": 1000.0},
            {"value": 20.0, "ts": 2000.0},
        ])
        assert len(buf) == 2
        assert buf.latest().value == 20.0

    def test_from_list_replaces_existing(self):
        buf = RingBuffer(max_size=100)
        buf.append(SensorReading(value=99.0, ts=99.0))
        buf.from_list([{"value": 1.0, "ts": 1.0}])
        assert len(buf) == 1
        assert buf.latest().value == 1.0

    def test_from_list_skips_bad_entries(self):
        buf = RingBuffer(max_size=100)
        buf.from_list([
            {"value": 1.0, "ts": 1.0},
            {"bad": "entry"},
            {"value": 3.0, "ts": 3.0},
        ])
        assert len(buf) == 2


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    """Test aggregate_readings()."""

    @pytest.fixture()
    def readings(self):
        return [
            SensorReading(value=10.0, ts=1.0),
            SensorReading(value=20.0, ts=2.0),
            SensorReading(value=30.0, ts=3.0),
            SensorReading(value=40.0, ts=4.0),
        ]

    def test_min(self, readings):
        assert aggregate_readings(readings, "min") == 10.0

    def test_max(self, readings):
        assert aggregate_readings(readings, "max") == 40.0

    def test_avg(self, readings):
        assert aggregate_readings(readings, "avg") == 25.0

    def test_sum(self, readings):
        assert aggregate_readings(readings, "sum") == 100.0

    def test_count(self, readings):
        assert aggregate_readings(readings, "count") == 4.0

    def test_median(self, readings):
        assert aggregate_readings(readings, "median") == 25.0

    def test_stdev(self, readings):
        result = aggregate_readings(readings, "stdev")
        assert result > 0

    def test_empty_returns_zero(self):
        assert aggregate_readings([], "avg") == 0.0
        assert aggregate_readings([], "min") == 0.0

    def test_unknown_function_raises(self, readings):
        with pytest.raises(ValueError, match="Unknown aggregation"):
            aggregate_readings(readings, "nonexistent")

    def test_bool_coercion(self):
        readings = [
            SensorReading(value=True, ts=1.0),
            SensorReading(value=False, ts=2.0),
            SensorReading(value=True, ts=3.0),
        ]
        assert aggregate_readings(readings, "sum") == 2.0

    def test_stdev_single_value(self):
        readings = [SensorReading(value=5.0, ts=1.0)]
        assert aggregate_readings(readings, "stdev") == 0.0


# ---------------------------------------------------------------------------
# SensorPipeline — recording
# ---------------------------------------------------------------------------


class TestPipelineRecording:
    """Test SensorPipeline.record() and record_state()."""

    def test_record_float(self):
        p = SensorPipeline()
        p.record("sensor-1", "temperature", 23.5, ts=1000.0)
        readings = p.query("sensor-1", "temperature")
        assert len(readings) == 1
        assert readings[0].value == 23.5

    def test_record_int(self):
        p = SensorPipeline()
        p.record("sensor-1", "brightness", 200, ts=1000.0)
        assert len(p.query("sensor-1", "brightness")) == 1

    def test_record_bool(self):
        p = SensorPipeline()
        p.record("switch-1", "on", True, ts=1000.0)
        assert len(p.query("switch-1", "on")) == 1

    def test_record_ignores_string(self):
        p = SensorPipeline()
        p.record("d1", "name", "hello", ts=1000.0)  # type: ignore
        assert len(p.query("d1", "name")) == 0

    def test_record_ignores_none(self):
        p = SensorPipeline()
        p.record("d1", "val", None, ts=1000.0)  # type: ignore
        assert len(p.query("d1", "val")) == 0

    def test_record_auto_timestamp(self):
        p = SensorPipeline()
        before = time.time()
        p.record("d1", "temp", 20.0)
        after = time.time()
        r = p.latest("d1", "temp")
        assert r is not None
        assert before <= r.ts <= after

    def test_record_state_multiple(self):
        p = SensorPipeline()
        count = p.record_state("sensor-1", {
            "temperature": 23.5,
            "humidity": 60,
            "online": True,
            "name": "Sensor 1",  # string — should be skipped
        })
        assert count == 3
        assert len(p.query("sensor-1", "temperature")) == 1
        assert len(p.query("sensor-1", "humidity")) == 1
        assert len(p.query("sensor-1", "online")) == 1
        assert len(p.query("sensor-1", "name")) == 0

    def test_record_state_empty(self):
        p = SensorPipeline()
        assert p.record_state("d1", {}) == 0

    def test_total_recorded(self):
        p = SensorPipeline()
        p.record("d1", "temp", 20.0, ts=1.0)
        p.record("d1", "temp", 21.0, ts=2.0)
        p.record("d2", "hum", 50, ts=3.0)
        stats = p.stats()
        assert stats["total_recorded"] == 3


# ---------------------------------------------------------------------------
# SensorPipeline — querying
# ---------------------------------------------------------------------------


class TestPipelineQuery:
    """Test query and latest."""

    def test_query_nonexistent(self):
        p = SensorPipeline()
        assert p.query("no-device", "no-cap") == []

    def test_latest_nonexistent(self):
        p = SensorPipeline()
        assert p.latest("no-device", "no-cap") is None

    def test_query_time_range(self):
        p = SensorPipeline()
        for i in range(10):
            p.record("d1", "temp", float(i), ts=float(i * 10))
        result = p.query("d1", "temp", start=30.0, end=60.0)
        assert len(result) == 4

    def test_latest_returns_most_recent(self):
        p = SensorPipeline()
        p.record("d1", "temp", 20.0, ts=100.0)
        p.record("d1", "temp", 25.0, ts=200.0)
        r = p.latest("d1", "temp")
        assert r is not None
        assert r.value == 25.0


# ---------------------------------------------------------------------------
# SensorPipeline — aggregation
# ---------------------------------------------------------------------------


class TestPipelineAggregation:
    """Test aggregate() method."""

    def test_aggregate_avg(self):
        p = SensorPipeline()
        p.record("d1", "temp", 10.0, ts=1.0)
        p.record("d1", "temp", 20.0, ts=2.0)
        p.record("d1", "temp", 30.0, ts=3.0)
        assert p.aggregate("d1", "temp", "avg") == 20.0

    def test_aggregate_with_range(self):
        p = SensorPipeline()
        for i in range(10):
            p.record("d1", "temp", float(i), ts=float(i))
        # avg of 3, 4, 5 = 4.0
        assert p.aggregate("d1", "temp", "avg", start=3.0, end=5.0) == 4.0

    def test_aggregate_empty(self):
        p = SensorPipeline()
        assert p.aggregate("d1", "temp", "avg") == 0.0

    def test_aggregate_unknown_raises(self):
        p = SensorPipeline()
        p.record("d1", "temp", 10.0, ts=1.0)
        with pytest.raises(ValueError):
            p.aggregate("d1", "temp", "bad_fn")


# ---------------------------------------------------------------------------
# SensorPipeline — persistence
# ---------------------------------------------------------------------------


class TestPipelinePersistence:
    """Test save/load with JSON files."""

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "sensor_data.json")
        p1 = SensorPipeline(path=path)
        p1.record("d1", "temp", 23.5, ts=1000.0)
        p1.record("d1", "humidity", 60, ts=1000.0)
        p1.record("d2", "brightness", 200, ts=1000.0)
        p1._save()

        p2 = SensorPipeline(path=path)
        loaded = p2.load()
        assert loaded == 3
        assert len(p2.query("d1", "temp")) == 1
        assert p2.latest("d1", "temp").value == 23.5

    def test_load_nonexistent_file(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        p = SensorPipeline(path=path)
        assert p.load() == 0

    def test_load_corrupt_file(self, tmp_path):
        path = str(tmp_path / "bad.json")
        Path(path).write_text("not json at all")
        p = SensorPipeline(path=path)
        assert p.load() == 0

    def test_load_no_path(self):
        p = SensorPipeline(path="")
        assert p.load() == 0

    def test_save_no_path(self):
        p = SensorPipeline(path="")
        p.record("d1", "temp", 20.0, ts=1.0)
        p._save()  # should not raise

    def test_persists_total_recorded(self, tmp_path):
        path = str(tmp_path / "data.json")
        p1 = SensorPipeline(path=path)
        p1.record("d1", "t", 1.0, ts=1.0)
        p1.record("d1", "t", 2.0, ts=2.0)
        p1._save()

        p2 = SensorPipeline(path=path)
        p2.load()
        assert p2.stats()["total_recorded"] == 2


# ---------------------------------------------------------------------------
# SensorPipeline — lifecycle (async)
# ---------------------------------------------------------------------------


class TestPipelineLifecycle:
    """Test start/stop and flush loop."""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        p = SensorPipeline(path="", flush_interval=0)
        await p.start()
        assert p._running is True
        await p.stop()
        assert p._running is False

    @pytest.mark.asyncio
    async def test_flush_loop_saves(self, tmp_path):
        path = str(tmp_path / "data.json")
        p = SensorPipeline(path=path, flush_interval=0.05)
        p.record("d1", "temp", 20.0, ts=1.0)
        await p.start()
        # Wait a bit for flush to fire
        await asyncio.sleep(0.15)
        await p.stop()
        # File should exist now
        assert Path(path).exists()
        data = json.loads(Path(path).read_text())
        assert "d1|temp" in data["buffers"]

    @pytest.mark.asyncio
    async def test_stop_saves_dirty(self, tmp_path):
        path = str(tmp_path / "data.json")
        p = SensorPipeline(path=path, flush_interval=0)  # no auto-flush
        await p.start()
        p.record("d1", "temp", 25.0, ts=1.0)
        await p.stop()
        assert Path(path).exists()


# ---------------------------------------------------------------------------
# SensorPipeline — summary and stats
# ---------------------------------------------------------------------------


class TestPipelineSummary:
    """Test summary() and stats()."""

    def test_summary_empty(self):
        p = SensorPipeline()
        assert p.summary() == "No sensor data recorded."

    def test_summary_with_data(self):
        p = SensorPipeline()
        ts = time.time()
        p.record("sensor-1", "temperature", 23.5, ts=ts)
        p.record("sensor-1", "temperature", 24.0, ts=ts)
        p.record("sensor-1", "humidity", 60, ts=ts)
        text = p.summary()
        assert "sensor-1" in text
        assert "temperature" in text
        assert "humidity" in text

    def test_summary_device_filter(self):
        p = SensorPipeline()
        ts = time.time()
        p.record("d1", "temp", 20.0, ts=ts)
        p.record("d2", "temp", 30.0, ts=ts)
        text = p.summary(node_id="d1")
        assert "d1" in text
        assert "d2" not in text

    def test_stats(self):
        p = SensorPipeline(path="/tmp/test.json", max_points=5000, flush_interval=30)
        p.record("d1", "temp", 20.0, ts=1.0)
        p.record("d1", "humidity", 60, ts=1.0)
        stats = p.stats()
        assert stats["total_recorded"] == 2
        assert stats["active_buffers"] == 2
        assert stats["path"] == "/tmp/test.json"
        assert stats["max_points_per_buffer"] == 5000
        assert stats["flush_interval"] == 30
        assert len(stats["buffers"]) == 2

    def test_stats_buffer_detail(self):
        p = SensorPipeline()
        p.record("d1", "temp", 20.0, ts=100.0)
        stats = p.stats()
        buf = stats["buffers"][0]
        assert buf["node_id"] == "d1"
        assert buf["capability"] == "temp"
        assert buf["count"] == 1
        assert buf["latest_value"] == 20.0
        assert buf["latest_ts"] == 100.0


# ---------------------------------------------------------------------------
# SensorPipeline — list helpers
# ---------------------------------------------------------------------------


class TestPipelineListing:
    """Test list_devices() and list_capabilities()."""

    def test_list_devices(self):
        p = SensorPipeline()
        p.record("d1", "temp", 20.0, ts=1.0)
        p.record("d2", "temp", 30.0, ts=1.0)
        devices = p.list_devices()
        assert set(devices) == {"d1", "d2"}

    def test_list_devices_empty(self):
        p = SensorPipeline()
        assert p.list_devices() == []

    def test_list_capabilities(self):
        p = SensorPipeline()
        p.record("d1", "temp", 20.0, ts=1.0)
        p.record("d1", "humidity", 60, ts=1.0)
        p.record("d2", "brightness", 200, ts=1.0)
        caps = p.list_capabilities("d1")
        assert set(caps) == {"temp", "humidity"}

    def test_list_capabilities_unknown_device(self):
        p = SensorPipeline()
        assert p.list_capabilities("nonexistent") == []


# ---------------------------------------------------------------------------
# SensorPipeline — max_points clamping
# ---------------------------------------------------------------------------


class TestPipelineConfig:
    """Test configuration edge cases."""

    def test_max_points_minimum(self):
        p = SensorPipeline(max_points=10)
        assert p.max_points == 100  # Minimum clamped to 100

    def test_max_points_large(self):
        p = SensorPipeline(max_points=50000)
        assert p.max_points == 50000


# ---------------------------------------------------------------------------
# Channel integration
# ---------------------------------------------------------------------------


class TestChannelPipelineIntegration:
    """Test MeshChannel integration with SensorPipeline."""

    def _make_config(self, **overrides):
        """Create a minimal mock config."""
        cfg = MagicMock()
        cfg.node_id = "test-hub"
        cfg.tcp_port = 18800
        cfg.udp_port = 18799
        cfg.roles = ["nanobot"]
        cfg.psk_auth_enabled = False
        cfg.allow_unauthenticated = True
        cfg.nonce_window = 60
        cfg.key_store_path = ""
        cfg.mtls_enabled = False
        cfg.ca_dir = ""
        cfg.device_cert_validity_days = 365
        cfg.encryption_enabled = False
        cfg.enrollment_pin_length = 6
        cfg.enrollment_pin_timeout = 300
        cfg.enrollment_max_attempts = 3
        cfg.registry_path = "/tmp/test_reg.json"
        cfg.automation_rules_path = "/tmp/test_auto.json"
        cfg.firmware_dir = ""
        cfg.ota_chunk_size = 4096
        cfg.ota_chunk_timeout = 30
        cfg.groups_path = "/tmp/groups.json"
        cfg.scenes_path = "/tmp/scenes.json"
        cfg.dashboard_port = 0
        cfg.industrial_config_path = ""
        cfg.federation_config_path = ""
        cfg.pipeline_enabled = False
        cfg.pipeline_path = ""
        cfg.pipeline_max_points = 10000
        cfg.pipeline_flush_interval = 60
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_pipeline_disabled_by_default(self):
        cfg = self._make_config()
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.pipeline is None

    def test_pipeline_enabled(self, tmp_path):
        path = str(tmp_path / "sensor_data.json")
        cfg = self._make_config(pipeline_enabled=True, pipeline_path=path)
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.pipeline is not None
        assert ch.pipeline.path == path
        assert ch.pipeline.max_points == 10000

    def test_pipeline_custom_settings(self, tmp_path):
        path = str(tmp_path / "sensor_data.json")
        cfg = self._make_config(
            pipeline_enabled=True,
            pipeline_path=path,
            pipeline_max_points=5000,
            pipeline_flush_interval=120,
        )
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)
        assert ch.pipeline is not None
        assert ch.pipeline.max_points == 5000
        assert ch.pipeline.flush_interval == 120.0

    @pytest.mark.asyncio
    async def test_state_report_records_to_pipeline(self, tmp_path):
        """STATE_REPORT should auto-record numeric values to pipeline."""
        path = str(tmp_path / "sensor_data.json")
        cfg = self._make_config(pipeline_enabled=True, pipeline_path=path)
        bus = MagicMock()
        ch = MeshChannel(cfg, bus)

        # Register a device first
        from nanobot.mesh.registry import DeviceCapability
        await ch.registry.register_device(
            "sensor-1", "temp_sensor",
            capabilities=[DeviceCapability(name="temperature", cap_type="sensor", data_type="float")],
        )

        # Simulate a state report
        from nanobot.mesh.protocol import MeshEnvelope, MsgType
        env = MeshEnvelope(
            type=MsgType.STATE_REPORT,
            source="sensor-1",
            target=ch.node_id,
            payload={"state": {"temperature": 23.5, "status": "ok"}},
        )
        await ch._handle_state_report(env)

        # Pipeline should have recorded the numeric value
        readings = ch.pipeline.query("sensor-1", "temperature")
        assert len(readings) == 1
        assert readings[0].value == 23.5

        # String value should NOT have been recorded
        assert len(ch.pipeline.query("sensor-1", "status")) == 0

    def test_pipeline_in_dashboard_data(self, tmp_path):
        """Pipeline should be included in dashboard data_fn when enabled."""
        path = str(tmp_path / "sensor_data.json")
        cfg = self._make_config(
            pipeline_enabled=True,
            pipeline_path=path,
            dashboard_port=9999,
        )
        bus = MagicMock()

        # We need to patch MeshDashboard to avoid actually starting a server
        with patch("nanobot.mesh.channel.MeshDashboard") as MockDash:
            ch = MeshChannel(cfg, bus)
            # The dashboard was created — check data_fn includes pipeline
            call_kwargs = MockDash.call_args[1]
            data = call_kwargs["data_fn"]()
            assert "pipeline" in data
            assert data["pipeline"] is ch.pipeline


# Import at bottom to avoid circular issues during collection
from nanobot.mesh.channel import MeshChannel

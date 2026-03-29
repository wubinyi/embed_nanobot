"""Tests for nanobot.mesh.deployment – Safe deployment pipeline (task 5.2.4)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest

from nanobot.mesh.deployment import (
    DeploymentPipeline,
    DeploymentRecord,
    DeploymentState,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ota_manager(
    start_returns: object = "session",
    abort_returns: bool = True,
) -> MagicMock:
    """Create a mock OTAManager with async methods."""
    mgr = MagicMock()
    mgr.start_update = AsyncMock(return_value=start_returns)
    mgr.abort_update = AsyncMock(return_value=abort_returns)
    return mgr


def _make_manifest() -> MagicMock:
    """Create a mock PartitionManifest."""
    m = MagicMock()
    m.get = MagicMock(return_value=None)
    return m


def _make_registry(devices: dict | None = None) -> MagicMock:
    """Create a mock DeviceRegistry."""
    r = MagicMock()
    if devices is None:
        devices = {}

    def _get(nid: str):
        return devices.get(nid)

    r.get_device = MagicMock(side_effect=_get)
    return r


# ---------------------------------------------------------------------------
# DeploymentRecord
# ---------------------------------------------------------------------------

class TestDeploymentRecord:
    def test_round_trip(self):
        rec = DeploymentRecord(
            deployment_id="d1",
            firmware_id="fw1",
            firmware_version="1.0.0",
            target_devices=["nodeA", "nodeB"],
        )
        d = rec.to_dict()
        restored = DeploymentRecord.from_dict(d)
        assert restored.deployment_id == "d1"
        assert restored.target_devices == ["nodeA", "nodeB"]
        assert restored.state == DeploymentState.PENDING

    def test_from_dict_defaults(self):
        rec = DeploymentRecord.from_dict({})
        assert rec.deployment_id == ""
        assert rec.target_devices == []
        assert rec.devices_succeeded == []


# ---------------------------------------------------------------------------
# DeploymentPipeline — create
# ---------------------------------------------------------------------------

class TestCreateDeployment:
    def test_creates_record(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "log.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        assert dep.deployment_id.startswith("deploy-")
        assert dep.firmware_id == "fw1"
        assert dep.canary_device == "n1"
        assert dep.state == DeploymentState.PENDING

    def test_persists_to_disk(self, tmp_path: Path):
        log = tmp_path / "log.json"
        pipe = DeploymentPipeline(log_path=str(log))
        pipe.create_deployment("fw1", "1.0", ["n1"])
        data = json.loads(log.read_text())
        assert len(data["deployments"]) == 1

    def test_loads_existing(self, tmp_path: Path):
        log = tmp_path / "log.json"
        log.write_text(json.dumps({"deployments": [
            DeploymentRecord(
                deployment_id="old",
                firmware_id="fw0",
                firmware_version="0.1",
                target_devices=["x"],
            ).to_dict()
        ]}))
        pipe = DeploymentPipeline(log_path=str(log))
        assert len(pipe.deployment_history()) == 1
        assert pipe.get_deployment("old") is not None


# ---------------------------------------------------------------------------
# Start deployment / canary
# ---------------------------------------------------------------------------

class TestStartDeployment:
    @pytest.mark.asyncio
    async def test_start_sends_ota(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        result = await pipe.start_deployment(dep.deployment_id)
        assert result.state == DeploymentState.CANARY
        ota.start_update.assert_awaited_once_with("n1", "fw1")

    @pytest.mark.asyncio
    async def test_start_fails_without_ota(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        result = await pipe.start_deployment(dep.deployment_id)
        assert result.state == DeploymentState.FAILED
        assert "OTA manager" in result.error

    @pytest.mark.asyncio
    async def test_start_fails_empty_targets(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", [])
        result = await pipe.start_deployment(dep.deployment_id)
        assert result.state == DeploymentState.FAILED

    @pytest.mark.asyncio
    async def test_start_unknown_deployment(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        result = await pipe.start_deployment("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_canary_ota_failure(self, tmp_path: Path):
        ota = _make_ota_manager(start_returns=None)
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        result = await pipe.start_deployment(dep.deployment_id)
        assert result.state == DeploymentState.FAILED
        assert "canary" in result.error


# ---------------------------------------------------------------------------
# Canary health check
# ---------------------------------------------------------------------------

class TestCanaryHealth:
    def test_healthy_canary(self, tmp_path: Path):
        manifest = _make_manifest()
        registry = _make_registry()
        pipe = DeploymentPipeline(
            partition_manifest=manifest,
            registry=registry,
            log_path=str(tmp_path / "l.json"),
        )
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        dep.state = DeploymentState.CANARY
        ok = pipe.check_canary_health(dep.deployment_id)
        assert ok
        assert dep.state == DeploymentState.CANARY_HEALTHY
        assert "n1" in dep.devices_succeeded

    def test_canary_crash_loop(self, tmp_path: Path):
        @dataclass
        class FakeEntry:
            boot_state: str = "crash_loop"
        manifest = _make_manifest()
        manifest.get.return_value = FakeEntry()
        pipe = DeploymentPipeline(
            partition_manifest=manifest,
            log_path=str(tmp_path / "l.json"),
        )
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        dep.state = DeploymentState.CANARY
        ok = pipe.check_canary_health(dep.deployment_id)
        assert not ok
        assert dep.state == DeploymentState.FAILED

    def test_canary_offline(self, tmp_path: Path):
        device = MagicMock()
        device.online = False
        registry = _make_registry({"n1": device})
        pipe = DeploymentPipeline(
            registry=registry,
            log_path=str(tmp_path / "l.json"),
        )
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        dep.state = DeploymentState.CANARY
        ok = pipe.check_canary_health(dep.deployment_id)
        assert not ok
        assert dep.state == DeploymentState.FAILED

    def test_wrong_state_returns_false(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        # still PENDING
        assert not pipe.check_canary_health(dep.deployment_id)


# ---------------------------------------------------------------------------
# Continue rollout
# ---------------------------------------------------------------------------

class TestContinueRollout:
    @pytest.mark.asyncio
    async def test_rolls_out_to_remaining(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2", "n3"])
        dep.state = DeploymentState.CANARY_HEALTHY
        dep.devices_succeeded.append("n1")
        result = await pipe.continue_rollout(dep.deployment_id)
        assert result.state == DeploymentState.MONITORING
        assert ota.start_update.await_count == 2  # n2 and n3

    @pytest.mark.asyncio
    async def test_single_device_completes_immediately(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        dep.state = DeploymentState.CANARY_HEALTHY
        result = await pipe.continue_rollout(dep.deployment_id)
        assert result.state == DeploymentState.COMPLETE
        ota.start_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_state_noop(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        result = await pipe.continue_rollout(dep.deployment_id)
        assert result.state == DeploymentState.PENDING  # unchanged

    @pytest.mark.asyncio
    async def test_rollout_ota_failures_tracked(self, tmp_path: Path):
        ota = _make_ota_manager(start_returns=None)
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        dep.state = DeploymentState.CANARY_HEALTHY
        result = await pipe.continue_rollout(dep.deployment_id)
        assert "n2" in result.devices_failed


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_all_healthy(self, tmp_path: Path):
        manifest = _make_manifest()
        pipe = DeploymentPipeline(
            partition_manifest=manifest,
            log_path=str(tmp_path / "l.json"),
        )
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        dep.state = DeploymentState.MONITORING
        result = pipe.finalize_deployment(dep.deployment_id)
        assert result.state == DeploymentState.COMPLETE
        assert result.completed_at > 0

    def test_device_unhealthy(self, tmp_path: Path):
        @dataclass
        class FakeEntry:
            boot_state: str = "crash_loop"
        manifest = _make_manifest()
        manifest.get.side_effect = lambda nid: FakeEntry() if nid == "n2" else None
        pipe = DeploymentPipeline(
            partition_manifest=manifest,
            log_path=str(tmp_path / "l.json"),
        )
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2"])
        dep.state = DeploymentState.MONITORING
        result = pipe.finalize_deployment(dep.deployment_id)
        assert result.state == DeploymentState.FAILED
        assert "n2" in result.devices_failed


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------

class TestRecall:
    @pytest.mark.asyncio
    async def test_recall_aborts_all(self, tmp_path: Path):
        ota = _make_ota_manager()
        pipe = DeploymentPipeline(ota_manager=ota, log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1", "n2", "n3"])
        dep.state = DeploymentState.ROLLING_OUT
        result = await pipe.recall_deployment(dep.deployment_id)
        assert result.state == DeploymentState.RECALLED
        assert ota.abort_update.await_count == 3

    @pytest.mark.asyncio
    async def test_recall_unknown(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        result = await pipe.recall_deployment("nope")
        assert result is None


# ---------------------------------------------------------------------------
# Query / summary
# ---------------------------------------------------------------------------

class TestQuery:
    def test_summary_empty(self):
        pipe = DeploymentPipeline()
        assert "No deployment" in pipe.summary()

    def test_summary_with_records(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        pipe.create_deployment("fw1", "1.0", ["n1"])
        s = pipe.summary()
        assert "fw1" in s
        assert "v1.0" in s

    def test_active_deployment_tracking(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        dep = pipe.create_deployment("fw1", "1.0", ["n1"])
        assert pipe.active_deployment() is None
        pipe._active = dep
        assert pipe.active_deployment() is dep

    def test_deployment_history_limit(self, tmp_path: Path):
        pipe = DeploymentPipeline(log_path=str(tmp_path / "l.json"))
        for i in range(10):
            pipe.create_deployment(f"fw{i}", "1.0", ["n1"])
        assert len(pipe.deployment_history(limit=3)) == 3
        assert len(pipe.deployment_history()) == 10

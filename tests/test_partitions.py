"""Tests for nanobot.mesh.partitions (task 5.2.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.mesh.partitions import BootState, PartitionEntry, PartitionManifest


# ---------------------------------------------------------------------------
# PartitionEntry
# ---------------------------------------------------------------------------


class TestPartitionEntry:
    def test_default_state(self):
        e = PartitionEntry(node_id="esp-01")
        assert e.boot_state == BootState.BARE
        assert e.crash_count == 0
        assert e.app_version == ""
        assert e.core_version == "unknown"

    def test_to_dict_round_trip(self):
        e = PartitionEntry(
            node_id="esp-01",
            core_version="1.0.0",
            app_version="2.0.0",
            app_hash="abc123",
            boot_state=BootState.NORMAL,
        )
        d = e.to_dict()
        e2 = PartitionEntry.from_dict(d)
        assert e2.node_id == "esp-01"
        assert e2.core_version == "1.0.0"
        assert e2.app_version == "2.0.0"
        assert e2.app_hash == "abc123"
        assert e2.boot_state == BootState.NORMAL

    def test_from_dict_defaults(self):
        e = PartitionEntry.from_dict({})
        assert e.node_id == ""
        assert e.boot_state == BootState.BARE


# ---------------------------------------------------------------------------
# PartitionManifest — CRUD
# ---------------------------------------------------------------------------


class TestManifestCRUD:
    def test_get_nonexistent(self):
        m = PartitionManifest()
        assert m.get("nope") is None

    def test_get_or_create(self):
        m = PartitionManifest()
        e = m.get_or_create("esp-01")
        assert e.node_id == "esp-01"
        # Second call returns same entry
        assert m.get_or_create("esp-01") is e

    def test_remove(self):
        m = PartitionManifest()
        m.get_or_create("esp-01")
        assert m.remove("esp-01") is True
        assert m.get("esp-01") is None

    def test_remove_nonexistent(self):
        m = PartitionManifest()
        assert m.remove("nope") is False

    def test_all_entries(self):
        m = PartitionManifest()
        m.get_or_create("esp-01")
        m.get_or_create("esp-02")
        assert len(m.all_entries()) == 2


# ---------------------------------------------------------------------------
# State updates
# ---------------------------------------------------------------------------


class TestStateUpdates:
    def test_record_deployment(self):
        m = PartitionManifest()
        e = m.record_deployment("esp-01", "1.0.0", "abc123")
        assert e.app_version == "1.0.0"
        assert e.app_hash == "abc123"
        assert e.boot_state == BootState.NORMAL
        assert e.crash_count == 0

    def test_deployment_preserves_rollback(self):
        m = PartitionManifest()
        # First deployment
        m.record_deployment("esp-01", "1.0.0", "hash1")
        e = m.get("esp-01")
        # Set state to normal (simulating successful boot)
        e.boot_state = BootState.NORMAL
        # Second deployment — old version becomes rollback target
        e2 = m.record_deployment("esp-01", "2.0.0", "hash2")
        assert e2.last_good_app_hash == "hash1"
        assert e2.last_good_app_version == "1.0.0"

    def test_record_partition_report(self):
        m = PartitionManifest()
        report = {
            "core_version": "1.0.0",
            "app_version": "2.0.0",
            "boot_state": BootState.NORMAL,
            "crash_count": 0,
        }
        e = m.record_partition_report("esp-01", report)
        assert e.core_version == "1.0.0"
        assert e.app_version == "2.0.0"
        assert e.boot_state == BootState.NORMAL

    def test_record_crash(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "hash")
        # Crash 3 times — should enter crash loop
        m.record_crash("esp-01")
        m.record_crash("esp-01")
        e = m.record_crash("esp-01")
        assert e.crash_count == 3
        assert e.boot_state == BootState.CRASH_LOOP

    def test_record_rollback(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "hash1")
        e = m.get("esp-01")
        e.boot_state = BootState.NORMAL
        m.record_deployment("esp-01", "2.0.0", "hash2")
        e = m.record_rollback("esp-01")
        assert e.boot_state == BootState.ROLLBACK
        assert e.app_hash == "hash1"
        assert e.crash_count == 0


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_devices_in_state(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "h1")
        m.get_or_create("esp-02")  # BARE
        assert len(m.devices_in_state(BootState.NORMAL)) == 1
        assert len(m.devices_in_state(BootState.BARE)) == 1

    def test_devices_needing_attention(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "h1")  # NORMAL — fine
        m.get_or_create("esp-02")  # BARE — needs attention
        e3 = m.get_or_create("esp-03")
        e3.boot_state = BootState.CRASH_LOOP  # needs attention
        attention = m.devices_needing_attention()
        assert len(attention) == 2

    def test_summary(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "h1")
        m.get_or_create("esp-02")
        s = m.summary()
        assert "esp-01" in s
        assert "esp-02" in s
        assert "NO APP" in s

    def test_summary_empty(self):
        m = PartitionManifest()
        assert "No device" in m.summary()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path):
        path = str(tmp_path / "manifest.json")
        m = PartitionManifest(path=path)
        m.record_deployment("esp-01", "1.0.0", "hash1")

        m2 = PartitionManifest(path=path)
        e = m2.get("esp-01")
        assert e is not None
        assert e.app_version == "1.0.0"
        assert e.app_hash == "hash1"

    def test_corrupt_file(self, tmp_path: Path):
        path = tmp_path / "manifest.json"
        path.write_text("invalid")
        m = PartitionManifest(path=str(path))
        assert len(m.all_entries()) == 0

    def test_no_path(self):
        m = PartitionManifest()
        m.record_deployment("esp-01", "1.0.0", "hash")
        # No crash — save is a no-op without path
        assert m.get("esp-01") is not None


# ---------------------------------------------------------------------------
# Protocol integration
# ---------------------------------------------------------------------------


class TestProtocolIntegration:
    def test_partition_report_msg_type_exists(self):
        """PARTITION_REPORT and PARTITION_QUERY exist as protocol message types."""
        from nanobot.mesh.protocol import MsgType
        assert MsgType.PARTITION_REPORT == "partition_report"
        assert MsgType.PARTITION_QUERY == "partition_query"

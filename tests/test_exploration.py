"""Tests for nanobot.mesh.exploration (task 5.1.4)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.mesh.exploration import ExplorationEvent, ExplorationManager


# ---------------------------------------------------------------------------
# ExplorationEvent
# ---------------------------------------------------------------------------


class TestExplorationEvent:
    def test_to_dict(self):
        ev = ExplorationEvent(ts=1000.0, level="act", topic="energy", action="scan", detail="ok")
        d = ev.to_dict()
        assert d["ts"] == 1000.0
        assert d["level"] == "act"
        assert d["topic"] == "energy"
        assert d["action"] == "scan"
        assert d["detail"] == "ok"

    def test_from_dict(self):
        d = {"ts": 2000.0, "level": "suggest", "topic": "motion", "action": "check", "detail": "done"}
        ev = ExplorationEvent.from_dict(d)
        assert ev.ts == 2000.0
        assert ev.level == "suggest"
        assert ev.topic == "motion"

    def test_from_dict_defaults(self):
        ev = ExplorationEvent.from_dict({})
        assert ev.ts == 0.0
        assert ev.level == "monitor-only"
        assert ev.topic == ""


# ---------------------------------------------------------------------------
# Topic management
# ---------------------------------------------------------------------------


class TestTopicManagement:
    def test_add_topic(self):
        mgr = ExplorationManager()
        assert mgr.add_topic("energy") is True
        assert "energy" in mgr.list_topics()

    def test_add_duplicate_topic(self):
        mgr = ExplorationManager(topics=["energy"])
        assert mgr.add_topic("energy") is False

    def test_remove_topic(self):
        mgr = ExplorationManager(topics=["energy", "motion"])
        assert mgr.remove_topic("energy") is True
        assert "energy" not in mgr.list_topics()

    def test_remove_nonexistent_topic(self):
        mgr = ExplorationManager()
        assert mgr.remove_topic("nope") is False

    def test_list_topics_returns_copy(self):
        mgr = ExplorationManager(topics=["a", "b"])
        topics = mgr.list_topics()
        topics.append("c")
        assert len(mgr.list_topics()) == 2


# ---------------------------------------------------------------------------
# Event recording
# ---------------------------------------------------------------------------


class TestEventRecording:
    def test_record_event(self):
        mgr = ExplorationManager()
        ev = mgr.record_event(level="act", topic="energy", action="scan", detail="ok")
        assert ev.topic == "energy"
        assert mgr.event_count() == 1

    def test_recent_events(self):
        mgr = ExplorationManager()
        for i in range(20):
            mgr.record_event(level="monitor-only", topic="t", action=f"a{i}", detail="")
        recent = mgr.recent_events(5)
        assert len(recent) == 5
        assert recent[-1].action == "a19"

    def test_events_for_topic(self):
        mgr = ExplorationManager()
        mgr.record_event(level="act", topic="energy", action="a1", detail="")
        mgr.record_event(level="act", topic="motion", action="a2", detail="")
        mgr.record_event(level="act", topic="energy", action="a3", detail="")
        assert len(mgr.events_for_topic("energy")) == 2
        assert len(mgr.events_for_topic("motion")) == 1

    def test_max_log_entries(self):
        mgr = ExplorationManager(max_log_entries=5)
        for i in range(10):
            mgr.record_event(level="act", topic="t", action=f"a{i}", detail="")
        assert mgr.event_count() == 5
        assert mgr.recent_events(5)[0].action == "a5"


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


class TestContextBuilding:
    def test_empty_context(self):
        mgr = ExplorationManager()
        assert mgr.build_exploration_context() == ""

    def test_topics_only(self):
        mgr = ExplorationManager(topics=["energy", "motion"])
        ctx = mgr.build_exploration_context()
        assert "## Exploration Topics" in ctx
        assert "energy (never explored)" in ctx
        assert "motion (never explored)" in ctx

    def test_topics_with_events(self):
        mgr = ExplorationManager(topics=["energy"])
        with patch("time.time", return_value=1000.0):
            mgr.record_event(level="act", topic="energy", action="scan", detail="ok")
        with patch("time.time", return_value=1060.0):
            ctx = mgr.build_exploration_context()
        assert "energy (last explored" in ctx
        assert "## Recent Autonomous Actions" in ctx

    def test_recent_actions_section(self):
        mgr = ExplorationManager()
        mgr.record_event(level="act", topic="general", action="check-sensors", detail="all normal")
        ctx = mgr.build_exploration_context()
        assert "## Recent Autonomous Actions" in ctx
        assert "check-sensors" in ctx


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_and_load(self, tmp_path: Path):
        log_path = str(tmp_path / "exploration_log.json")

        mgr = ExplorationManager(topics=["energy"], log_path=log_path)
        mgr.record_event(level="act", topic="energy", action="scan", detail="ok")
        mgr.record_event(level="suggest", topic="motion", action="watch", detail="detected")

        # Load into new manager
        mgr2 = ExplorationManager(log_path=log_path)
        assert mgr2.event_count() == 2
        assert "energy" in mgr2.list_topics()

    def test_merge_persisted_topics(self, tmp_path: Path):
        log_path = str(tmp_path / "exploration_log.json")

        mgr = ExplorationManager(topics=["energy"], log_path=log_path)
        mgr.record_event(level="act", topic="energy", action="scan", detail="ok")

        # Load with different constructor topics — should merge
        mgr2 = ExplorationManager(topics=["motion"], log_path=log_path)
        topics = mgr2.list_topics()
        assert "motion" in topics
        assert "energy" in topics

    def test_corrupt_log_file(self, tmp_path: Path):
        log_path = tmp_path / "exploration_log.json"
        log_path.write_text("not valid json")

        # Should not raise — just log warning
        mgr = ExplorationManager(log_path=str(log_path))
        assert mgr.event_count() == 0

    def test_no_log_path_no_persistence(self):
        mgr = ExplorationManager()
        mgr.record_event(level="act", topic="t", action="a", detail="")
        # No crash — _save is a no-op when no log_path
        assert mgr.event_count() == 1


# ---------------------------------------------------------------------------
# Integration with AutonomousService
# ---------------------------------------------------------------------------


class TestAutonomousIntegration:
    def test_build_context_uses_exploration(self):
        """AutonomousService.build_context() uses exploration when available."""
        from nanobot.mesh.autonomous import AutonomousService

        mgr = ExplorationManager(topics=["energy-monitor"])
        svc = AutonomousService(exploration=mgr, enabled=False)
        ctx = svc.build_context()
        assert "energy-monitor" in ctx

    def test_build_context_fallback_to_topics_list(self):
        """When no ExplorationManager, falls back to simple topics list."""
        from nanobot.mesh.autonomous import AutonomousService

        svc = AutonomousService(exploration_topics=["test-topic"], enabled=False)
        ctx = svc.build_context()
        assert "test-topic" in ctx

    @pytest.mark.asyncio
    async def test_tick_records_event(self):
        """After _tick() executes, an event is recorded in ExplorationManager."""
        from nanobot.mesh.autonomous import AutonomousService

        mgr = ExplorationManager(topics=["energy"])

        async def fake_execute(ctx: str) -> str:
            return "Everything normal"

        svc = AutonomousService(
            exploration=mgr,
            on_execute=fake_execute,
            enabled=False,
            autonomy_level="monitor-only",
        )

        await svc._tick()
        assert mgr.event_count() == 1
        ev = mgr.recent_events(1)[0]
        assert ev.topic == "autonomous-scan"
        assert ev.action == "tick"
        assert "Everything normal" in ev.detail

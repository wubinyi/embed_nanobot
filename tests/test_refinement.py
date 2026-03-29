"""Tests for proactive automation refinement (task 5.1.3)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from nanobot.mesh.refinement import AutomationAnalyzer


# ---------------------------------------------------------------------------
# Helpers — lightweight rule/device mocks
# ---------------------------------------------------------------------------

@dataclass
class MockCondition:
    device_id: str
    capability: str = "temp"
    operator: str = "gt"
    value: float = 30.0


@dataclass
class MockAction:
    device_id: str
    capability: str = "power"
    action: str = "set"
    params: dict | None = None


@dataclass
class MockRule:
    rule_id: str
    name: str
    enabled: bool = True
    last_triggered: float = 0.0
    cooldown_seconds: int = 60
    conditions: list = field(default_factory=list)
    actions: list = field(default_factory=list)

    def trigger_device_ids(self) -> set[str]:
        return {c.device_id for c in self.conditions}


def _make_device(node_id: str, online: bool = True, caps: list[str] | None = None):
    d = MagicMock()
    d.node_id = node_id
    d.online = online
    cap_objs = []
    for c in (caps or []):
        cap = MagicMock()
        cap.name = c
        cap_objs.append(cap)
    d.capabilities = cap_objs
    return d


def _make_automation(rules: list[MockRule]) -> MagicMock:
    engine = MagicMock()
    engine.list_rules.return_value = rules
    return engine


def _make_registry(devices: list) -> MagicMock:
    reg = MagicMock()
    reg.get_all_devices.return_value = devices
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNeverFired:
    def test_finds_never_fired_rules(self):
        rules = [
            MockRule("r1", "Test Rule", enabled=True, last_triggered=0.0,
                     conditions=[MockCondition("d1")]),
            MockRule("r2", "Fired Rule", enabled=True, last_triggered=time.time() - 3600,
                     conditions=[MockCondition("d1")]),
        ]
        analyzer = AutomationAnalyzer(automation=_make_automation(rules))
        result = analyzer.analyze()
        assert len(result.never_fired) == 1
        assert result.never_fired[0]["rule_id"] == "r1"

    def test_disabled_rules_excluded(self):
        rules = [
            MockRule("r1", "Disabled", enabled=False, last_triggered=0.0),
        ]
        analyzer = AutomationAnalyzer(automation=_make_automation(rules))
        result = analyzer.analyze()
        assert len(result.never_fired) == 0


class TestFrequentlyFired:
    def test_finds_recent_fires(self):
        rules = [
            MockRule("r1", "Recent", enabled=True,
                     last_triggered=time.time() - 60,  # 60s ago
                     conditions=[MockCondition("d1")]),
        ]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            frequent_threshold_s=300,
        )
        result = analyzer.analyze()
        assert len(result.frequently_fired) == 1

    def test_old_fires_excluded(self):
        rules = [
            MockRule("r1", "Old", enabled=True,
                     last_triggered=time.time() - 3600,
                     conditions=[MockCondition("d1")]),
        ]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            frequent_threshold_s=300,
        )
        result = analyzer.analyze()
        assert len(result.frequently_fired) == 0


class TestStaleRules:
    def test_finds_nonexistent_device(self):
        rules = [
            MockRule("r1", "Stale", enabled=True,
                     conditions=[MockCondition("nonexistent")],
                     actions=[MockAction("d1")]),
        ]
        devices = [_make_device("d1", True)]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert len(result.stale_rules) == 1
        assert "nonexistent" in result.stale_rules[0]["reason"]

    def test_finds_offline_device(self):
        rules = [
            MockRule("r1", "Offline ref", enabled=True,
                     conditions=[MockCondition("d1")],
                     actions=[MockAction("d2")]),
        ]
        devices = [_make_device("d1", True), _make_device("d2", False)]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert len(result.stale_rules) == 1
        assert "offline" in result.stale_rules[0]["reason"]


class TestCoverageGaps:
    def test_finds_uncovered_devices(self):
        rules = [
            MockRule("r1", "Covers d1", enabled=True,
                     conditions=[MockCondition("d1")]),
        ]
        devices = [
            _make_device("d1", True, ["temp"]),
            _make_device("d2", True, ["led", "temp"]),
        ]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert len(result.coverage_gaps) == 1
        assert result.coverage_gaps[0]["device_id"] == "d2"

    def test_no_gap_when_all_covered(self):
        rules = [
            MockRule("r1", "All", enabled=True,
                     conditions=[MockCondition("d1"), MockCondition("d2")]),
        ]
        devices = [
            _make_device("d1", True, ["temp"]),
            _make_device("d2", True, ["led"]),
        ]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert len(result.coverage_gaps) == 0


class TestSummary:
    def test_healthy_summary(self):
        rules = [
            MockRule("r1", "Good", enabled=True,
                     last_triggered=time.time() - 3600,
                     conditions=[MockCondition("d1")]),
        ]
        devices = [_make_device("d1", True, ["temp"])]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert "healthy" in result.summary.lower() or "No issues" in result.summary

    def test_summary_includes_sections(self):
        rules = [
            MockRule("r1", "Never Fired", enabled=True, last_triggered=0.0,
                     conditions=[MockCondition("d1")]),
        ]
        devices = [
            _make_device("d1", True, ["temp"]),
            _make_device("d2", True, ["led"]),
        ]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        result = analyzer.analyze()
        assert "Never-Fired" in result.summary
        assert "Uncovered" in result.summary

    def test_build_refinement_context(self):
        """The main entry point should return the summary string."""
        rules = [MockRule("r1", "Test", enabled=True, conditions=[MockCondition("d1")])]
        devices = [_make_device("d1", True, ["temp"])]
        analyzer = AutomationAnalyzer(
            automation=_make_automation(rules),
            registry=_make_registry(devices),
        )
        ctx = analyzer.build_refinement_context()
        assert "Automation Rule Analysis" in ctx


class TestEmpty:
    def test_no_automation(self):
        analyzer = AutomationAnalyzer()
        result = analyzer.analyze()
        assert len(result.never_fired) == 0
        assert len(result.stale_rules) == 0

    def test_no_registry(self):
        rules = [MockRule("r1", "Test", conditions=[MockCondition("d1")])]
        analyzer = AutomationAnalyzer(automation=_make_automation(rules))
        result = analyzer.analyze()
        assert len(result.stale_rules) == 0
        assert len(result.coverage_gaps) == 0

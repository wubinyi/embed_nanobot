"""Proactive automation refinement (task 5.1.3).

Analyzes automation rule effectiveness and generates insights for the LLM
to suggest improvements.  Not a self-modifying optimizer — the LLM reasons
about the analysis and can use DeviceControlTool or direct API calls to
adjust rules.

Analysis dimensions:
- **Never-fired rules**: rules that have never triggered (stale or misconfigured)
- **Frequent-fire rules**: rules that fire repeatedly (possible threshold issue)
- **Stale rules**: conditions referencing offline or non-existent devices
- **Coverage gaps**: devices with capabilities but no automation rules
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.mesh.automation import AutomationEngine
    from nanobot.mesh.registry import DeviceRegistry


class RuleAnalysis:
    """Result of analyzing automation rules."""

    __slots__ = ("never_fired", "frequently_fired", "stale_rules", "coverage_gaps", "summary")

    def __init__(
        self,
        never_fired: list[dict[str, Any]],
        frequently_fired: list[dict[str, Any]],
        stale_rules: list[dict[str, Any]],
        coverage_gaps: list[dict[str, Any]],
        summary: str,
    ):
        self.never_fired = never_fired
        self.frequently_fired = frequently_fired
        self.stale_rules = stale_rules
        self.coverage_gaps = coverage_gaps
        self.summary = summary


class AutomationAnalyzer:
    """Analyzes automation rule effectiveness for LLM-driven refinement."""

    def __init__(
        self,
        automation: AutomationEngine | None = None,
        registry: DeviceRegistry | None = None,
        frequent_threshold_s: int = 300,
    ):
        self.automation = automation
        self.registry = registry
        self.frequent_threshold_s = frequent_threshold_s

    def analyze(self) -> RuleAnalysis:
        """Run full analysis and return structured results."""
        never_fired = self._find_never_fired()
        frequently_fired = self._find_frequently_fired()
        stale_rules = self._find_stale_rules()
        coverage_gaps = self._find_coverage_gaps()
        summary = self._build_summary(never_fired, frequently_fired, stale_rules, coverage_gaps)
        return RuleAnalysis(
            never_fired=never_fired,
            frequently_fired=frequently_fired,
            stale_rules=stale_rules,
            coverage_gaps=coverage_gaps,
            summary=summary,
        )

    def _find_never_fired(self) -> list[dict[str, Any]]:
        """Find enabled rules that have never triggered."""
        if not self.automation:
            return []
        results = []
        for rule in self.automation.list_rules():
            if rule.enabled and rule.last_triggered == 0.0:
                results.append({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "reason": "enabled but never triggered",
                })
        return results

    def _find_frequently_fired(self) -> list[dict[str, Any]]:
        """Find rules that fired very recently (possible threshold issue)."""
        if not self.automation:
            return []
        now = time.time()
        results = []
        for rule in self.automation.list_rules():
            if not rule.enabled or rule.last_triggered == 0.0:
                continue
            elapsed = now - rule.last_triggered
            if elapsed < self.frequent_threshold_s:
                results.append({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "last_fired_s_ago": int(elapsed),
                    "cooldown_s": rule.cooldown_seconds,
                })
        return results

    def _find_stale_rules(self) -> list[dict[str, Any]]:
        """Find rules referencing offline or nonexistent devices."""
        if not self.automation or not self.registry:
            return []
        results = []
        all_device_ids = {d.node_id for d in self.registry.get_all_devices()}
        offline_ids = {d.node_id for d in self.registry.get_all_devices() if not d.online}

        for rule in self.automation.list_rules():
            if not rule.enabled:
                continue
            trigger_ids = rule.trigger_device_ids()
            action_ids = {a.device_id for a in rule.actions}
            all_referenced = trigger_ids | action_ids

            missing = all_referenced - all_device_ids
            offline = all_referenced & offline_ids

            if missing:
                results.append({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "reason": f"references nonexistent devices: {', '.join(sorted(missing))}",
                })
            elif offline:
                results.append({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "reason": f"references offline devices: {', '.join(sorted(offline))}",
                })
        return results

    def _find_coverage_gaps(self) -> list[dict[str, Any]]:
        """Find devices with capabilities but no automation rules covering them."""
        if not self.automation or not self.registry:
            return []

        # Collect all device IDs referenced in any rule condition
        covered_devices: set[str] = set()
        for rule in self.automation.list_rules():
            if rule.enabled:
                covered_devices.update(rule.trigger_device_ids())

        results = []
        for dev in self.registry.get_all_devices():
            if dev.node_id not in covered_devices and dev.capabilities:
                cap_names = [c.name for c in dev.capabilities]
                results.append({
                    "device_id": dev.node_id,
                    "capabilities": cap_names,
                    "reason": "has capabilities but no automation rules",
                })
        return results

    def _build_summary(
        self,
        never_fired: list[dict[str, Any]],
        frequently_fired: list[dict[str, Any]],
        stale_rules: list[dict[str, Any]],
        coverage_gaps: list[dict[str, Any]],
    ) -> str:
        """Build a human-readable summary for LLM context."""
        lines: list[str] = ["## Automation Rule Analysis"]

        total_rules = len(self.automation.list_rules()) if self.automation else 0
        enabled_rules = len([r for r in (self.automation.list_rules() if self.automation else []) if r.enabled])
        lines.append(f"Total rules: {total_rules} | Enabled: {enabled_rules}")

        if not any([never_fired, frequently_fired, stale_rules, coverage_gaps]):
            lines.append("\nAll rules look healthy. No issues detected.")
            return "\n".join(lines)

        if never_fired:
            lines.append(f"\n### Never-Fired Rules ({len(never_fired)})")
            lines.append("These rules are enabled but have never triggered — they may be "
                         "misconfigured or have conditions that never match.")
            for item in never_fired:
                lines.append(f"- **{item['name']}** ({item['rule_id']})")

        if frequently_fired:
            lines.append(f"\n### Frequently-Fired Rules ({len(frequently_fired)})")
            lines.append("These rules fired very recently — consider if thresholds are too sensitive.")
            for item in frequently_fired:
                lines.append(
                    f"- **{item['name']}** ({item['rule_id']}): "
                    f"fired {item['last_fired_s_ago']}s ago, cooldown={item['cooldown_s']}s"
                )

        if stale_rules:
            lines.append(f"\n### Stale Rules ({len(stale_rules)})")
            lines.append("These rules reference devices that are offline or don't exist.")
            for item in stale_rules:
                lines.append(f"- **{item['name']}** ({item['rule_id']}): {item['reason']}")

        if coverage_gaps:
            lines.append(f"\n### Uncovered Devices ({len(coverage_gaps)})")
            lines.append("These devices have capabilities but no automation rules. "
                         "Consider whether rules would be useful.")
            for item in coverage_gaps:
                caps = ", ".join(item["capabilities"])
                lines.append(f"- **{item['device_id']}**: [{caps}]")

        return "\n".join(lines)

    def build_refinement_context(self) -> str:
        """Analyze rules and return the summary for LLM consumption.

        This is the primary method called by AutonomousService.
        """
        analysis = self.analyze()
        return analysis.summary

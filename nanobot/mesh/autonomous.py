"""Autonomous device monitoring service (task 5.1.1).

Periodically scans the device ecosystem — online/offline status, sensor
readings, automation rule activity — and runs an LLM agent turn with that
context.  The ``autonomy_level`` controls what the agent is allowed to do:

* ``monitor-only`` — observe and log, never notify the user.
* ``suggest``      — observe and suggest actions to the user.
* ``act``          — observe and execute device commands autonomously.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.mesh.automation import AutomationEngine
    from nanobot.mesh.awareness import AwarenessLoop
    from nanobot.mesh.exploration import ExplorationManager
    from nanobot.mesh.pipeline import SensorPipeline
    from nanobot.mesh.refinement import AutomationAnalyzer
    from nanobot.mesh.registry import DeviceRegistry

_LEVEL_INSTRUCTIONS = {
    "monitor-only": (
        "OBSERVE ONLY. Summarise the device ecosystem status. "
        "Do NOT take any device actions or send commands. "
        "Your report will be logged but NOT delivered to the user."
    ),
    "suggest": (
        "Review the device ecosystem and SUGGEST actions if useful. "
        "Do NOT execute commands yourself — describe what you recommend "
        "and the user will decide."
    ),
    "act": (
        "Review the device ecosystem. You MAY take actions using the "
        "available tools (device_control, reprogram, etc.) if you judge "
        "them beneficial. Explain your reasoning."
    ),
}


class AutonomousService:
    """Periodic autonomous device monitoring with configurable autonomy level."""

    def __init__(
        self,
        *,
        registry: DeviceRegistry | None = None,
        pipeline: SensorPipeline | None = None,
        automation: AutomationEngine | None = None,
        awareness: AwarenessLoop | None = None,
        analyzer: AutomationAnalyzer | None = None,
        exploration: ExplorationManager | None = None,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        provider: Any = None,
        model: str = "",
        interval_s: int = 1800,
        autonomy_level: str = "monitor-only",
        exploration_topics: list[str] | None = None,
        enabled: bool = False,
    ):
        self.registry = registry
        self.pipeline = pipeline
        self.automation = automation
        self.awareness = awareness
        self.analyzer = analyzer
        self.exploration = exploration
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.provider = provider
        self.model = model
        self.interval_s = max(60, interval_s)  # floor at 1 minute
        self.autonomy_level = autonomy_level if autonomy_level in _LEVEL_INSTRUCTIONS else "monitor-only"
        self.exploration_topics: list[str] = exploration_topics or []
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def build_context(self) -> str:
        """Build a prompt describing the current device ecosystem state."""
        sections: list[str] = []

        # Header
        from nanobot.utils.helpers import current_time_str
        sections.append(f"# Autonomous Device Scan — {current_time_str()}\n")
        sections.append(_LEVEL_INSTRUCTIONS.get(self.autonomy_level, _LEVEL_INSTRUCTIONS["monitor-only"]))
        sections.append("")

        # Use AwarenessLoop for enriched snapshot (trend analysis, anomaly detection)
        if self.awareness:
            awareness_ctx = self.awareness.build_awareness_context()
            if awareness_ctx:
                sections.append(awareness_ctx)
                sections.append("")
        elif self.registry:
            # Fallback: basic device overview without trend analysis
            sections.append("## Devices")
            all_devs = self.registry.get_all_devices()
            online = [d for d in all_devs if d.online]
            offline = [d for d in all_devs if not d.online]
            sections.append(f"Total: {len(all_devs)} | Online: {len(online)} | Offline: {len(offline)}")
            if online:
                sections.append("\n### Online")
                for d in online:
                    caps = ", ".join(c.name for c in d.capabilities)
                    state_str = ", ".join(f"{k}={v}" for k, v in (d.state or {}).items()) if d.state else "no state"
                    sections.append(f"- **{d.node_id}** ({d.device_type or 'unknown'}): caps=[{caps}] state=[{state_str}]")
            if offline:
                sections.append("\n### Offline")
                for d in offline:
                    sections.append(f"- **{d.node_id}** ({d.device_type or 'unknown'})")
            sections.append("")

        # Sensor summary
        if self.pipeline:
            try:
                summary = self.pipeline.summary()
                if summary:
                    sections.append("## Sensor Data Summary")
                    sections.append(summary)
                    sections.append("")
            except Exception:
                pass

        # Automation rules summary
        if self.automation:
            try:
                desc = self.automation.describe_rules()
                if desc:
                    sections.append("## Active Automation Rules")
                    sections.append(desc)
                    sections.append("")
            except Exception:
                pass

        # Automation rule analysis (task 5.1.3)
        if self.analyzer:
            try:
                refinement_ctx = self.analyzer.build_refinement_context()
                if refinement_ctx:
                    sections.append(refinement_ctx)
                    sections.append("")
            except Exception:
                pass

        # Exploration topics and event history (task 5.1.4)
        if self.exploration:
            try:
                exploration_ctx = self.exploration.build_exploration_context()
                if exploration_ctx:
                    sections.append(exploration_ctx)
                    sections.append("")
            except Exception:
                pass
        elif self.exploration_topics:
            sections.append("## Exploration Topics")
            for topic in self.exploration_topics:
                sections.append(f"- {topic}")
            sections.append("")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Autonomous mode disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Autonomous mode started (level={}, every {}s)",
            self.autonomy_level,
            self.interval_s,
        )

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Autonomous tick error: {}", e)

    async def _tick(self) -> None:
        """Execute a single autonomous scan."""
        from nanobot.utils.evaluator import evaluate_response

        context = self.build_context()
        if not context.strip():
            logger.debug("Autonomous: empty context, skipping")
            return

        logger.info("Autonomous: scanning device ecosystem (level={})", self.autonomy_level)

        try:
            if not self.on_execute:
                logger.debug("Autonomous: no on_execute callback")
                return

            response = await self.on_execute(context)

            if not response:
                logger.info("Autonomous: agent returned empty response")
                return

            # Record the event in exploration log if available.
            if self.exploration:
                try:
                    self.exploration.record_event(
                        level=self.autonomy_level,
                        topic="autonomous-scan",
                        action="tick",
                        detail=response[:200] if response else "",
                    )
                except Exception:
                    pass

            # For "monitor-only" just log — never notify the user.
            if self.autonomy_level == "monitor-only":
                logger.info("Autonomous (monitor-only): {}", response[:200])
                return

            # For "suggest" and "act", evaluate whether to notify.
            if self.on_notify:
                should_notify = True
                if self.provider and self.model:
                    try:
                        should_notify = await evaluate_response(
                            response, context, self.provider, self.model,
                        )
                    except Exception:
                        should_notify = True

                if should_notify:
                    logger.info("Autonomous: delivering response to user")
                    await self.on_notify(response)
                else:
                    logger.info("Autonomous: response silenced by evaluator")
        except Exception:
            logger.exception("Autonomous execution failed")

    async def trigger_now(self) -> str | None:
        """Manually trigger an autonomous scan (for testing or CLI)."""
        if not self.on_execute:
            return None
        context = self.build_context()
        if not context.strip():
            return None
        return await self.on_execute(context)

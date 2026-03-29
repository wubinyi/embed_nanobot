"""Exploration task framework (task 5.1.4).

Manages user-defined exploration topics and maintains a transparent event log
of all autonomous actions.  Exploration topics are injected into the LLM
context during autonomous scans; the event log records what the AI did and
why — providing accountability and auditability.

The ``autonomy_level`` controls sandboxing:
- ``monitor-only`` / ``suggest``: LLM can only observe and report.
- ``act``: LLM may execute device commands via available tools.

Event log is append-only and persisted to JSON for cross-session transparency.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger


class ExplorationEvent:
    """Single recorded autonomous action or observation."""

    __slots__ = ("ts", "level", "topic", "action", "detail")

    def __init__(
        self,
        ts: float,
        level: str,
        topic: str,
        action: str,
        detail: str,
    ):
        self.ts = ts
        self.level = level
        self.topic = topic
        self.action = action
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "level": self.level,
            "topic": self.topic,
            "action": self.action,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExplorationEvent:
        return cls(
            ts=d.get("ts", 0.0),
            level=d.get("level", "monitor-only"),
            topic=d.get("topic", ""),
            action=d.get("action", ""),
            detail=d.get("detail", ""),
        )


class ExplorationManager:
    """Manages exploration topics and the autonomous event log."""

    def __init__(
        self,
        topics: list[str] | None = None,
        log_path: str = "",
        max_log_entries: int = 500,
    ):
        self._topics: list[str] = list(topics) if topics else []
        self._log_path = Path(log_path) if log_path else None
        self._max_log_entries = max_log_entries
        self._events: list[ExplorationEvent] = []
        if self._log_path:
            self._load()

    # -- Topic management --

    def add_topic(self, topic: str) -> bool:
        """Add a new exploration topic. Returns False if already exists."""
        if topic in self._topics:
            return False
        self._topics.append(topic)
        return True

    def remove_topic(self, topic: str) -> bool:
        """Remove an exploration topic. Returns False if not found."""
        if topic not in self._topics:
            return False
        self._topics.remove(topic)
        return True

    def list_topics(self) -> list[str]:
        return list(self._topics)

    # -- Event log --

    def record_event(
        self,
        level: str,
        topic: str,
        action: str,
        detail: str,
    ) -> ExplorationEvent:
        """Append an event to the log."""
        event = ExplorationEvent(
            ts=time.time(),
            level=level,
            topic=topic,
            action=action,
            detail=detail,
        )
        self._events.append(event)

        # Trim if over limit
        if len(self._events) > self._max_log_entries:
            self._events = self._events[-self._max_log_entries:]

        self._save()
        return event

    def recent_events(self, n: int = 10) -> list[ExplorationEvent]:
        """Return the N most recent events."""
        return self._events[-n:]

    def events_for_topic(self, topic: str) -> list[ExplorationEvent]:
        """Return all events related to a specific topic."""
        return [e for e in self._events if e.topic == topic]

    def event_count(self) -> int:
        return len(self._events)

    # -- Context for LLM --

    def build_exploration_context(self) -> str:
        """Build context describing topics and recent activity."""
        lines: list[str] = []

        if self._topics:
            lines.append("## Exploration Topics")
            for topic in self._topics:
                topic_events = self.events_for_topic(topic)
                if topic_events:
                    last = topic_events[-1]
                    ago = int(time.time() - last.ts)
                    if ago < 3600:
                        ago_str = f"{ago // 60}min ago"
                    else:
                        ago_str = f"{ago // 3600}h ago"
                    lines.append(f"- {topic} (last explored {ago_str}: {last.action})")
                else:
                    lines.append(f"- {topic} (never explored)")

        recent = self.recent_events(5)
        if recent:
            lines.append("\n## Recent Autonomous Actions")
            for e in reversed(recent):
                import datetime
                ts_str = datetime.datetime.fromtimestamp(e.ts).strftime("%H:%M")
                lines.append(f"- [{ts_str}] [{e.level}] {e.action}: {e.detail[:100]}")

        return "\n".join(lines) if lines else ""

    # -- Persistence --

    def _load(self) -> None:
        if not self._log_path or not self._log_path.exists():
            return
        try:
            data = json.loads(self._log_path.read_text(encoding="utf-8"))
            self._events = [ExplorationEvent.from_dict(e) for e in data.get("events", [])]
            if data.get("topics"):
                # Merge persisted topics with constructor topics (union)
                for t in data["topics"]:
                    if t not in self._topics:
                        self._topics.append(t)
            logger.debug("Loaded {} exploration events from {}", len(self._events), self._log_path)
        except Exception as e:
            logger.warning("Failed to load exploration log: {}", e)

    def _save(self) -> None:
        if not self._log_path:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "topics": self._topics,
                "events": [e.to_dict() for e in self._events],
            }
            self._log_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save exploration log: {}", e)

"""Device grouping and scenes for mesh-connected devices.

Groups are named collections of device node_ids (e.g. "living_room").
Scenes are named batches of device commands (e.g. "good_night").

Architecture
------------
- ``DeviceGroup`` — named set of device node_ids
- ``Scene``       — named list of device commands
- ``GroupManager`` — CRUD, persistence, execution helpers
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.mesh.commands import Action, DeviceCommand


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DeviceGroup:
    """Named collection of device node_ids."""

    group_id: str               # Unique identifier (e.g. "living_room")
    name: str                   # Human-friendly name
    device_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeviceGroup:
        return cls(
            group_id=d["group_id"],
            name=d.get("name", d["group_id"]),
            device_ids=d.get("device_ids", []),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Scene:
    """Named batch of device commands to execute together."""

    scene_id: str              # Unique identifier (e.g. "good_night")
    name: str                  # Human-friendly name
    commands: list[dict[str, Any]] = field(default_factory=list)  # DeviceCommand dicts
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "commands": self.commands,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scene:
        return cls(
            scene_id=d["scene_id"],
            name=d.get("name", d["scene_id"]),
            commands=d.get("commands", []),
            description=d.get("description", ""),
        )

    def to_device_commands(self) -> list[DeviceCommand]:
        """Convert stored command dicts to DeviceCommand objects."""
        result: list[DeviceCommand] = []
        for c in self.commands:
            try:
                result.append(DeviceCommand.from_dict(c))
            except (KeyError, TypeError) as exc:
                logger.warning("[Groups/Scene] skipping malformed command: {}", exc)
        return result


# ---------------------------------------------------------------------------
# Group manager
# ---------------------------------------------------------------------------

class GroupManager:
    """Manages device groups and scenes with JSON persistence.

    Parameters
    ----------
    groups_path:
        Path to groups JSON file.
    scenes_path:
        Path to scenes JSON file.
    """

    def __init__(self, groups_path: str, scenes_path: str) -> None:
        self._groups_path = Path(groups_path)
        self._scenes_path = Path(scenes_path)
        self._groups: dict[str, DeviceGroup] = {}
        self._scenes: dict[str, Scene] = {}

    # -- persistence ---------------------------------------------------------

    def load(self) -> None:
        """Load groups and scenes from disk."""
        self._load_groups()
        self._load_scenes()

    def _load_groups(self) -> None:
        if self._groups_path.exists():
            try:
                data = json.loads(self._groups_path.read_text())
                self._groups = {
                    g["group_id"]: DeviceGroup.from_dict(g) for g in data.get("groups", [])
                }
                logger.info(
                    "[Groups] loaded {} groups from {}", len(self._groups), self._groups_path,
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("[Groups] failed to load groups: {}", exc)
                self._groups = {}
        else:
            self._groups = {}

    def _load_scenes(self) -> None:
        if self._scenes_path.exists():
            try:
                data = json.loads(self._scenes_path.read_text())
                self._scenes = {
                    s["scene_id"]: Scene.from_dict(s) for s in data.get("scenes", [])
                }
                logger.info(
                    "[Groups] loaded {} scenes from {}", len(self._scenes), self._scenes_path,
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("[Groups] failed to load scenes: {}", exc)
                self._scenes = {}
        else:
            self._scenes = {}

    def _save_groups(self) -> None:
        self._groups_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"groups": [g.to_dict() for g in self._groups.values()]}
        self._groups_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _save_scenes(self) -> None:
        self._scenes_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"scenes": [s.to_dict() for s in self._scenes.values()]}
        self._scenes_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # -- group CRUD ----------------------------------------------------------

    def add_group(
        self,
        group_id: str,
        name: str,
        device_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DeviceGroup:
        """Create or overwrite a device group."""
        group = DeviceGroup(
            group_id=group_id,
            name=name,
            device_ids=device_ids or [],
            metadata=metadata or {},
        )
        self._groups[group_id] = group
        self._save_groups()
        logger.info("[Groups] added group {!r} with {} devices", group_id, len(group.device_ids))
        return group

    def remove_group(self, group_id: str) -> bool:
        """Remove a group. Returns True if it existed."""
        if group_id not in self._groups:
            return False
        del self._groups[group_id]
        self._save_groups()
        logger.info("[Groups] removed group {!r}", group_id)
        return True

    def get_group(self, group_id: str) -> DeviceGroup | None:
        return self._groups.get(group_id)

    def list_groups(self) -> list[DeviceGroup]:
        return list(self._groups.values())

    def add_device_to_group(self, group_id: str, device_id: str) -> bool:
        """Add a device to an existing group. Returns True if group exists."""
        group = self._groups.get(group_id)
        if group is None:
            return False
        if device_id not in group.device_ids:
            group.device_ids.append(device_id)
            self._save_groups()
        return True

    def remove_device_from_group(self, group_id: str, device_id: str) -> bool:
        """Remove a device from a group. Returns True if both group and device existed."""
        group = self._groups.get(group_id)
        if group is None:
            return False
        if device_id not in group.device_ids:
            return False
        group.device_ids.remove(device_id)
        self._save_groups()
        return True

    # -- scene CRUD ----------------------------------------------------------

    def add_scene(
        self,
        scene_id: str,
        name: str,
        commands: list[dict[str, Any]] | None = None,
        description: str = "",
    ) -> Scene:
        """Create or overwrite a scene."""
        scene = Scene(
            scene_id=scene_id,
            name=name,
            commands=commands or [],
            description=description,
        )
        self._scenes[scene_id] = scene
        self._save_scenes()
        logger.info("[Groups] added scene {!r} with {} commands", scene_id, len(scene.commands))
        return scene

    def remove_scene(self, scene_id: str) -> bool:
        """Remove a scene. Returns True if it existed."""
        if scene_id not in self._scenes:
            return False
        del self._scenes[scene_id]
        self._save_scenes()
        logger.info("[Groups] removed scene {!r}", scene_id)
        return True

    def get_scene(self, scene_id: str) -> Scene | None:
        return self._scenes.get(scene_id)

    def list_scenes(self) -> list[Scene]:
        return list(self._scenes.values())

    # -- execution helpers ---------------------------------------------------

    def get_scene_commands(self, scene_id: str) -> list[DeviceCommand]:
        """Expand a scene into its DeviceCommands. Empty list if scene not found."""
        scene = self._scenes.get(scene_id)
        if scene is None:
            return []
        return scene.to_device_commands()

    def fan_out_group_command(
        self,
        group_id: str,
        action: str,
        capability: str = "",
        params: dict[str, Any] | None = None,
    ) -> list[DeviceCommand]:
        """Create one DeviceCommand per device in the group.

        Useful for "turn off the living room" → one SET power=off per device.
        """
        group = self._groups.get(group_id)
        if group is None:
            return []
        return [
            DeviceCommand(
                device=dev_id,
                action=action,
                capability=capability,
                params=params or {},
            )
            for dev_id in group.device_ids
        ]

    # -- LLM context ---------------------------------------------------------

    def describe_groups(self) -> str:
        """Return Markdown description of groups for LLM system prompt."""
        if not self._groups:
            return ""
        lines = ["## Device Groups\n"]
        for g in self._groups.values():
            members = ", ".join(g.device_ids) or "(empty)"
            lines.append(f"- **{g.name}** (`{g.group_id}`): {members}")
        return "\n".join(lines)

    def describe_scenes(self) -> str:
        """Return Markdown description of scenes for LLM system prompt."""
        if not self._scenes:
            return ""
        lines = ["## Scenes\n"]
        for s in self._scenes.values():
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"- **{s.name}** (`{s.scene_id}`){desc}: {len(s.commands)} commands")
        return "\n".join(lines)

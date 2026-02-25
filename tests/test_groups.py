"""Tests for device grouping and scenes (task 3.4).

Covers: DeviceGroup, Scene, GroupManager CRUD, persistence, fan-out,
scene execution, LLM descriptions, and MeshChannel integration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.mesh.commands import DeviceCommand
from nanobot.mesh.groups import DeviceGroup, GroupManager, Scene


# ---------------------------------------------------------------------------
# DeviceGroup
# ---------------------------------------------------------------------------

class TestDeviceGroup:
    def test_to_dict_roundtrip(self):
        g = DeviceGroup(
            group_id="living_room", name="Living Room",
            device_ids=["light-01", "light-02"],
            metadata={"floor": 1},
        )
        d = g.to_dict()
        restored = DeviceGroup.from_dict(d)
        assert restored.group_id == "living_room"
        assert restored.device_ids == ["light-01", "light-02"]
        assert restored.metadata == {"floor": 1}

    def test_from_dict_minimal(self):
        g = DeviceGroup.from_dict({"group_id": "g1"})
        assert g.group_id == "g1"
        assert g.name == "g1"
        assert g.device_ids == []


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class TestScene:
    def test_to_dict_roundtrip(self):
        s = Scene(
            scene_id="good_night", name="Good Night",
            commands=[
                {"device": "light-01", "action": "set", "capability": "power", "params": {"value": False}},
                {"device": "lock-01", "action": "set", "capability": "locked", "params": {"value": True}},
            ],
            description="Bedtime routine",
        )
        d = s.to_dict()
        restored = Scene.from_dict(d)
        assert restored.scene_id == "good_night"
        assert len(restored.commands) == 2
        assert restored.description == "Bedtime routine"

    def test_to_device_commands(self):
        s = Scene(
            scene_id="test", name="Test",
            commands=[
                {"device": "light-01", "action": "set", "capability": "brightness", "params": {"value": 50}},
                {"device": "thermostat", "action": "set", "capability": "temperature", "params": {"value": 22}},
            ],
        )
        cmds = s.to_device_commands()
        assert len(cmds) == 2
        assert isinstance(cmds[0], DeviceCommand)
        assert cmds[0].device == "light-01"
        assert cmds[1].params == {"value": 22}

    def test_to_device_commands_malformed(self):
        s = Scene(
            scene_id="bad", name="Bad",
            commands=[{"not_a_command": True}],
        )
        cmds = s.to_device_commands()
        # Malformed commands are skipped
        assert len(cmds) == 1  # from_dict still creates with defaults
        assert cmds[0].device == ""

    def test_from_dict_minimal(self):
        s = Scene.from_dict({"scene_id": "s1"})
        assert s.scene_id == "s1"
        assert s.commands == []


# ---------------------------------------------------------------------------
# GroupManager — Groups
# ---------------------------------------------------------------------------

class TestGroupManagerGroups:
    def test_add_and_get(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        g = mgr.add_group("lr", "Living Room", ["light-01", "tv-01"])
        assert g.group_id == "lr"
        assert mgr.get_group("lr") is not None
        assert mgr.get_group("missing") is None

    def test_list_groups(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("a", "A")
        mgr.add_group("b", "B")
        assert len(mgr.list_groups()) == 2

    def test_remove_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "Living Room")
        assert mgr.remove_group("lr") is True
        assert mgr.get_group("lr") is None
        assert mgr.remove_group("lr") is False

    def test_add_device_to_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "Living Room", ["light-01"])
        assert mgr.add_device_to_group("lr", "light-02") is True
        g = mgr.get_group("lr")
        assert "light-02" in g.device_ids

    def test_add_device_idempotent(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "LR", ["light-01"])
        mgr.add_device_to_group("lr", "light-01")  # Already there
        assert mgr.get_group("lr").device_ids == ["light-01"]

    def test_add_device_no_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.add_device_to_group("missing", "d1") is False

    def test_remove_device_from_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "LR", ["light-01", "light-02"])
        assert mgr.remove_device_from_group("lr", "light-01") is True
        assert mgr.get_group("lr").device_ids == ["light-02"]

    def test_remove_device_not_in_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "LR", ["light-01"])
        assert mgr.remove_device_from_group("lr", "missing-dev") is False

    def test_remove_device_no_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.remove_device_from_group("missing", "d1") is False

    def test_group_persistence(self, tmp_path):
        gpath = str(tmp_path / "g.json")
        spath = str(tmp_path / "s.json")
        mgr = GroupManager(gpath, spath)
        mgr.load()
        mgr.add_group("lr", "Living Room", ["light-01"])

        mgr2 = GroupManager(gpath, spath)
        mgr2.load()
        assert mgr2.get_group("lr") is not None
        assert mgr2.get_group("lr").device_ids == ["light-01"]

    def test_overwrite_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "v1", ["a"])
        mgr.add_group("lr", "v2", ["b", "c"])
        assert mgr.get_group("lr").name == "v2"
        assert mgr.get_group("lr").device_ids == ["b", "c"]


# ---------------------------------------------------------------------------
# GroupManager — Scenes
# ---------------------------------------------------------------------------

class TestGroupManagerScenes:
    def test_add_and_get(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        s = mgr.add_scene("gn", "Good Night", [
            {"device": "light-01", "action": "set", "capability": "power", "params": {"value": False}},
        ], description="Bedtime")
        assert s.scene_id == "gn"
        assert mgr.get_scene("gn") is not None
        assert mgr.get_scene("missing") is None

    def test_list_scenes(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_scene("a", "A")
        mgr.add_scene("b", "B")
        assert len(mgr.list_scenes()) == 2

    def test_remove_scene(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_scene("gn", "Good Night")
        assert mgr.remove_scene("gn") is True
        assert mgr.get_scene("gn") is None
        assert mgr.remove_scene("gn") is False

    def test_scene_persistence(self, tmp_path):
        gpath = str(tmp_path / "g.json")
        spath = str(tmp_path / "s.json")
        mgr = GroupManager(gpath, spath)
        mgr.load()
        mgr.add_scene("gn", "Good Night", [
            {"device": "light-01", "action": "set"},
        ])

        mgr2 = GroupManager(gpath, spath)
        mgr2.load()
        assert mgr2.get_scene("gn") is not None
        assert len(mgr2.get_scene("gn").commands) == 1

    def test_get_scene_commands(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_scene("gn", "Good Night", [
            {"device": "light-01", "action": "set", "capability": "power", "params": {"value": False}},
            {"device": "lock-01", "action": "set", "capability": "locked", "params": {"value": True}},
        ])
        cmds = mgr.get_scene_commands("gn")
        assert len(cmds) == 2
        assert cmds[0].device == "light-01"
        assert cmds[1].device == "lock-01"

    def test_get_scene_commands_missing(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.get_scene_commands("missing") == []


# ---------------------------------------------------------------------------
# GroupManager — Fan-out
# ---------------------------------------------------------------------------

class TestFanOut:
    def test_fan_out_group_command(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "Living Room", ["light-01", "light-02", "light-03"])
        cmds = mgr.fan_out_group_command("lr", "set", "power", {"value": False})
        assert len(cmds) == 3
        for cmd in cmds:
            assert cmd.action == "set"
            assert cmd.capability == "power"
            assert cmd.params == {"value": False}
        devices = {cmd.device for cmd in cmds}
        assert devices == {"light-01", "light-02", "light-03"}

    def test_fan_out_missing_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.fan_out_group_command("missing", "set") == []

    def test_fan_out_empty_group(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("empty", "Empty")
        assert mgr.fan_out_group_command("empty", "set", "power") == []


# ---------------------------------------------------------------------------
# GroupManager — LLM descriptions
# ---------------------------------------------------------------------------

class TestDescriptions:
    def test_describe_groups(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_group("lr", "Living Room", ["light-01", "tv-01"])
        desc = mgr.describe_groups()
        assert "Living Room" in desc
        assert "light-01" in desc
        assert "lr" in desc

    def test_describe_groups_empty(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.describe_groups() == ""

    def test_describe_scenes(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        mgr.add_scene("gn", "Good Night", [
            {"device": "light-01", "action": "set"},
        ], description="Turn everything off")
        desc = mgr.describe_scenes()
        assert "Good Night" in desc
        assert "gn" in desc
        assert "Turn everything off" in desc

    def test_describe_scenes_empty(self, tmp_path):
        mgr = GroupManager(str(tmp_path / "g.json"), str(tmp_path / "s.json"))
        mgr.load()
        assert mgr.describe_scenes() == ""


# ---------------------------------------------------------------------------
# Channel integration
# ---------------------------------------------------------------------------

class TestChannelGroupsIntegration:
    def _make_channel(self, tmp_path):
        config = MagicMock()
        config.node_id = "hub-test"
        config.tcp_port = 0
        config.udp_port = 0
        config.roles = ["nanobot"]
        config.psk_auth_enabled = False
        config.allow_unauthenticated = True
        config.nonce_window = 60
        config.key_store_path = ""
        config.encryption_enabled = False
        config.registry_path = str(tmp_path / "registry.json")
        config.automation_rules_path = str(tmp_path / "automation.json")
        config.mtls_enabled = False
        config.ca_dir = ""
        config.device_cert_validity_days = 365
        config.firmware_dir = ""
        config.ota_chunk_size = 4096
        config.ota_chunk_timeout = 30
        config.groups_path = str(tmp_path / "groups.json")
        config.scenes_path = str(tmp_path / "scenes.json")
        config.enrollment_pin_length = 6
        config.enrollment_pin_timeout = 300
        config.enrollment_max_attempts = 3
        config._workspace_path = str(tmp_path)
        return config

    def test_groups_manager_created(self, tmp_path):
        config = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        assert ch.groups is not None
        assert isinstance(ch.groups, GroupManager)

    @pytest.mark.asyncio
    async def test_execute_scene(self, tmp_path):
        config = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        ch.transport.send = AsyncMock(return_value=True)

        ch.groups.add_scene("gn", "Good Night", [
            {"device": "light-01", "action": "set", "capability": "power", "params": {"value": False}},
            {"device": "lock-01", "action": "set", "capability": "locked", "params": {"value": True}},
        ])

        results = await ch.execute_scene("gn")
        assert results == [True, True]
        assert ch.transport.send.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_scene_empty(self, tmp_path):
        config = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        results = await ch.execute_scene("missing")
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_group_command(self, tmp_path):
        config = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)
        ch.transport.send = AsyncMock(return_value=True)

        ch.groups.add_group("lr", "Living Room", ["light-01", "light-02"])

        results = await ch.execute_group_command(
            "lr", "set", "power", {"value": False},
        )
        assert results == [True, True]
        assert ch.transport.send.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_group_command_empty(self, tmp_path):
        config = self._make_channel(tmp_path)
        bus = MagicMock()
        bus.inbound = MagicMock()

        from nanobot.mesh.channel import MeshChannel
        ch = MeshChannel(config, bus)

        results = await ch.execute_group_command("missing", "set")
        assert results == []

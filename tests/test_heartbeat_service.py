import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.heartbeat.service import HeartbeatService


def _make_provider_stub(action: str = "skip", tasks: str = "") -> MagicMock:
    """Create a stub provider whose chat() returns a heartbeat tool call."""
    response = MagicMock()
    if action == "skip":
        response.has_tool_calls = False
        response.tool_calls = []
    else:
        tc = MagicMock()
        tc.arguments = {"action": action, "tasks": tasks}
        response.has_tool_calls = True
        response.tool_calls = [tc]
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)
    return provider


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = _make_provider_stub()

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)

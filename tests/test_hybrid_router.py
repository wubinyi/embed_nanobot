"""Tests for the hybrid router provider."""

import json
from typing import Any

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.hybrid_router import (
    HybridRouterProvider,
    _extract_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeProvider(LLMProvider):
    """Minimal LLM provider stub whose responses are controlled by tests."""

    def __init__(self, responses: list[LLMResponse] | None = None):
        super().__init__()
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append({
            "messages": messages,
            "tools": tools,
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="default response")

    def get_default_model(self) -> str:
        return "fake-model"


def _easy_judge_response(score: float = 0.2) -> LLMResponse:
    return LLMResponse(content=json.dumps({"difficulty": "easy", "score": score}))


def _hard_judge_response(score: float = 0.8) -> LLMResponse:
    return LLMResponse(content=json.dumps({"difficulty": "hard", "score": score}))


def _sanitised_response(text: str = "sanitised text") -> LLMResponse:
    return LLMResponse(content=text)


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

def test_extract_json_plain():
    assert _extract_json('{"difficulty": "easy", "score": 0.3}') == {
        "difficulty": "easy",
        "score": 0.3,
    }


def test_extract_json_fenced():
    text = '```json\n{"difficulty": "hard", "score": 0.9}\n```'
    assert _extract_json(text) == {"difficulty": "hard", "score": 0.9}


def test_extract_json_embedded():
    text = 'Sure, here is the result: {"difficulty": "easy", "score": 0.1} Hope it helps!'
    assert _extract_json(text) == {"difficulty": "easy", "score": 0.1}


def test_extract_json_invalid():
    assert _extract_json("no json here") == {}


# ---------------------------------------------------------------------------
# Difficulty judgement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_easy_task_to_local():
    local = FakeProvider([_easy_judge_response(0.2), LLMResponse(content="local answer")])
    api = FakeProvider()

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "Hello!"}],
    )

    assert resp.content == "local answer"
    # Local was called twice (judge + answer), API was never called
    assert len(local.calls) == 2
    assert len(api.calls) == 0


@pytest.mark.asyncio
async def test_routes_hard_task_to_api():
    # judge returns hard, then sanitise returns sanitised text
    local = FakeProvider([_hard_judge_response(0.9), _sanitised_response("sanitised msg")])
    api = FakeProvider([LLMResponse(content="api answer")])

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "Write a complex program"}],
    )

    assert resp.content == "api answer"
    # Local: judge + 1 sanitise call; API: 1 call
    assert len(local.calls) == 2
    assert len(api.calls) == 1


@pytest.mark.asyncio
async def test_threshold_boundary():
    """Score exactly at threshold → routes to local (≤ threshold is local)."""
    local = FakeProvider([_easy_judge_response(0.5), LLMResponse(content="local")])
    api = FakeProvider()

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "What is 2+2?"}],
    )

    assert resp.content == "local"
    assert len(api.calls) == 0


# ---------------------------------------------------------------------------
# PII sanitisation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pii_sanitisation_applied_before_api_call():
    """When routing to API, user messages should be sanitised."""
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("[NAME] wants to know about quantum physics"),
    ])
    api = FakeProvider([LLMResponse(content="quantum answer")])

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    resp = await router.chat(
        messages=[
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Alice wants to know about quantum physics"},
        ],
    )

    assert resp.content == "quantum answer"
    # The API should have received the sanitised user message
    api_messages = api.calls[0]["messages"]
    user_msgs = [m for m in api_messages if m["role"] == "user"]
    assert user_msgs[0]["content"] == "[NAME] wants to know about quantum physics"
    # System messages are left untouched
    sys_msgs = [m for m in api_messages if m["role"] == "system"]
    assert sys_msgs[0]["content"] == "You are helpful."


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_judge_failure_defaults_to_local_at_threshold():
    """If the judge returns unparseable JSON, score defaults to 0.5.

    With threshold=0.5, score 0.5 <= threshold -> routes to local.
    """
    local = FakeProvider([
        LLMResponse(content="not json at all"),  # judge -> unparseable -> score 0.5
        LLMResponse(content="local fallback"),    # local answer
    ])
    api = FakeProvider()

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "something"}],
    )

    # _extract_json({}) -> score defaults to 0.5 -> 0.5 <= 0.5 -> local
    assert resp.content == "local fallback"
    assert len(api.calls) == 0


@pytest.mark.asyncio
async def test_tools_forwarded_to_chosen_provider():
    """Tool definitions are passed to whichever provider handles the request."""
    local = FakeProvider([_easy_judge_response(0.1), LLMResponse(content="done")])
    api = FakeProvider()
    tools = [{"type": "function", "function": {"name": "test_tool"}}]

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        difficulty_threshold=0.5,
    )

    await router.chat(
        messages=[{"role": "user", "content": "hi"}],
        tools=tools,
    )

    # Second local call (the answer) should receive tools
    assert local.calls[1]["tools"] == tools


@pytest.mark.asyncio
async def test_get_default_model():
    local = FakeProvider()
    api = FakeProvider()
    router = HybridRouterProvider(
        local_provider=local, api_provider=api,
        local_model="llama3", api_model="claude-sonnet",
    )
    assert router.get_default_model() == "llama3"

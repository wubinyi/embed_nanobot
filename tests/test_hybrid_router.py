"""Tests for the hybrid router provider."""

import json
import time
from typing import Any
from unittest.mock import patch

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


class FailingProvider(LLMProvider):
    """Provider that always raises an exception."""

    def __init__(self, error: Exception | None = None):
        super().__init__()
        self.error = error or ConnectionError("API unreachable")
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
        })
        raise self.error

    def get_default_model(self) -> str:
        return "failing-model"


class SometimesFailingProvider(LLMProvider):
    """Provider that fails N times then succeeds."""

    def __init__(self, fail_count: int, success_response: LLMResponse | None = None):
        super().__init__()
        self._fail_count = fail_count
        self._call_count = 0
        self._success_response = success_response or LLMResponse(content="api recovered")
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
        })
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise ConnectionError(f"API failure #{self._call_count}")
        return self._success_response

    def get_default_model(self) -> str:
        return "sometimes-model"


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


# ---------------------------------------------------------------------------
# Cloud fallback (task 2.7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_failure_falls_back_to_local():
    """When the API provider raises, the router falls back to local."""
    local = FakeProvider([
        _hard_judge_response(0.9),          # judge
        _sanitised_response("sanitised"),   # sanitise
        LLMResponse(content="local fallback answer"),  # fallback answer
    ])
    api = FailingProvider(ConnectionError("network down"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "complex question"}],
    )

    assert resp.content == "local fallback answer"
    assert len(api.calls) == 1  # API was attempted
    assert len(local.calls) == 3  # judge + sanitise + fallback answer


@pytest.mark.asyncio
async def test_api_failure_no_fallback_re_raises():
    """When fallback is disabled, API failures propagate."""
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
    ])
    api = FailingProvider(ConnectionError("network down"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=False,
    )

    with pytest.raises(ConnectionError, match="network down"):
        await router.chat(
            messages=[{"role": "user", "content": "complex question"}],
        )


@pytest.mark.asyncio
async def test_api_failure_timeout_error():
    """TimeoutError also triggers fallback."""
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
        LLMResponse(content="fallback"),
    ])
    api = FailingProvider(TimeoutError("request timed out"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
    )

    resp = await router.chat(
        messages=[{"role": "user", "content": "complex question"}],
    )
    assert resp.content == "fallback"


@pytest.mark.asyncio
async def test_api_success_resets_failure_count():
    """After a successful API call, the failure counter resets."""
    local = FakeProvider([
        # First call: hard judge + sanitise (API fails)
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
        LLMResponse(content="fallback 1"),
        # Second call: hard judge + sanitise (API succeeds)
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
    ])
    api = SometimesFailingProvider(
        fail_count=1,
        success_response=LLMResponse(content="api success"),
    )

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
        circuit_breaker_threshold=5,  # High so it doesn't trip
    )

    # First call: API fails, falls back
    resp1 = await router.chat(
        messages=[{"role": "user", "content": "q1"}],
    )
    assert resp1.content == "fallback 1"
    assert router._cb_consecutive_failures == 1

    # Second call: API succeeds
    resp2 = await router.chat(
        messages=[{"role": "user", "content": "q2"}],
    )
    assert resp2.content == "api success"
    assert router._cb_consecutive_failures == 0  # Reset


# ---------------------------------------------------------------------------
# Circuit breaker (task 2.7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold():
    """After N consecutive API failures, the circuit breaker opens."""
    # We need enough local responses for 3 calls:
    # Each call: judge + sanitise + fallback = 3 local calls
    local_responses = []
    for _ in range(3):
        local_responses.extend([
            _hard_judge_response(0.9),
            _sanitised_response("sanitised"),
            LLMResponse(content="fallback"),
        ])
    local = FakeProvider(local_responses)
    api = FailingProvider(ConnectionError("down"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
        circuit_breaker_threshold=3,
        circuit_breaker_timeout=300,
    )

    # 3 consecutive failures
    for _ in range(3):
        await router.chat(messages=[{"role": "user", "content": "q"}])

    assert router._cb_consecutive_failures == 3
    assert router._cb_open_until > 0  # Breaker is open


@pytest.mark.asyncio
async def test_circuit_breaker_routes_to_local():
    """When circuit breaker is open, requests bypass difficulty judge."""
    local = FakeProvider([LLMResponse(content="breaker local")])
    api = FailingProvider()

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        circuit_breaker_threshold=3,
    )

    # Force circuit breaker open
    router._cb_consecutive_failures = 3
    router._cb_open_until = time.time() + 300

    resp = await router.chat(
        messages=[{"role": "user", "content": "q"}],
    )

    assert resp.content == "breaker local"
    # Only 1 local call (direct answer), no judge/sanitise
    assert len(local.calls) == 1
    # API was never attempted
    assert len(api.calls) == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_success():
    """After timeout, breaker is half-open: success closes it."""
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
    ])
    api = FakeProvider([LLMResponse(content="api back")])

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        circuit_breaker_threshold=3,
    )

    # Simulate breaker that was open but timeout expired
    router._cb_consecutive_failures = 3
    router._cb_open_until = time.time() - 1  # Expired

    resp = await router.chat(
        messages=[{"role": "user", "content": "q"}],
    )

    assert resp.content == "api back"
    assert router._cb_consecutive_failures == 0
    assert router._cb_open_until == 0.0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure():
    """After timeout, breaker is half-open: failure reopens it."""
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("sanitised"),
        LLMResponse(content="fallback again"),
    ])
    api = FailingProvider(ConnectionError("still down"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
        circuit_breaker_threshold=3,
        circuit_breaker_timeout=300,
    )

    # Simulate breaker that was open but timeout expired (half-open)
    router._cb_consecutive_failures = 3
    router._cb_open_until = time.time() - 1  # Expired

    resp = await router.chat(
        messages=[{"role": "user", "content": "q"}],
    )

    assert resp.content == "fallback again"
    # Failure count incremented, breaker re-opened
    assert router._cb_consecutive_failures == 4
    assert router._cb_open_until > time.time()


@pytest.mark.asyncio
async def test_circuit_breaker_closed_by_default():
    """Circuit breaker starts closed."""
    local = FakeProvider()
    api = FakeProvider()
    router = HybridRouterProvider(
        local_provider=local, api_provider=api,
        local_model="llama3", api_model="claude-sonnet",
    )
    assert router._cb_consecutive_failures == 0
    assert router._cb_open_until == 0.0
    assert not router._circuit_is_open()


def test_circuit_is_open_logic():
    """Test _circuit_is_open edge cases."""
    local = FakeProvider()
    api = FakeProvider()
    router = HybridRouterProvider(
        local_provider=local, api_provider=api,
        local_model="llama3", api_model="claude-sonnet",
    )

    # Closed
    assert not router._circuit_is_open()

    # Open (future timestamp)
    router._cb_open_until = time.time() + 100
    assert router._circuit_is_open()

    # Expired (past timestamp) → half-open → returns False
    router._cb_open_until = time.time() - 1
    assert not router._circuit_is_open()


@pytest.mark.asyncio
async def test_fallback_uses_original_messages_not_sanitised():
    """When falling back to local after API failure, use original messages
    (not sanitised), since local model is trusted."""
    original_msg = "Alice at alice@example.com wants to know about physics"
    local = FakeProvider([
        _hard_judge_response(0.9),
        _sanitised_response("[NAME] at [EMAIL] wants to know about physics"),
        LLMResponse(content="local answer"),
    ])
    api = FailingProvider(ConnectionError("down"))

    router = HybridRouterProvider(
        local_provider=local,
        api_provider=api,
        local_model="llama3",
        api_model="claude-sonnet",
        fallback_to_local=True,
    )

    await router.chat(
        messages=[{"role": "user", "content": original_msg}],
    )

    # The fallback call (3rd local call) should use ORIGINAL messages
    fallback_call = local.calls[2]
    user_msgs = [m for m in fallback_call["messages"] if m["role"] == "user"]
    assert user_msgs[0]["content"] == original_msg

"""Hybrid router: local model for easy tasks, API model for hard tasks.

The local model (vLLM / Ollama) acts as a difficulty judge.  Easy tasks are
processed locally.  Difficult tasks are forwarded to the remote API model
after private information has been stripped by the local model.
"""

import json
import re
from typing import Any, Callable

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# Prompts sent to the *local* model for judging / sanitising
# ---------------------------------------------------------------------------

DIFFICULTY_JUDGE_PROMPT = """\
You are a task difficulty classifier.  Given the user's message below,
decide whether it is EASY or HARD.

EASY tasks: simple factual questions, greetings, small talk, basic
calculations, short text formatting, simple translations, or anything a
small model can handle well.

HARD tasks: complex reasoning, multi-step analysis, long-form writing,
code generation for non-trivial programs, advanced math, tasks that need
deep domain expertise, or tasks requiring very high quality output.

Respond with EXACTLY one JSON object and nothing else:
{{"difficulty": "easy", "score": 0.2}}
or
{{"difficulty": "hard", "score": 0.8}}

"score" is a float between 0.0 (trivial) and 1.0 (very hard).

User message:
{message}"""

PII_SANITIZE_PROMPT = """\
You are a privacy filter.  Rewrite the following text so that all private
or personally identifiable information (PII) is replaced with generic
placeholders.  Replace names with [NAME], emails with [EMAIL], phone
numbers with [PHONE], addresses with [ADDRESS], ID / passport / SSN
numbers with [ID_NUMBER], and any other sensitive data with an appropriate
[PLACEHOLDER].  Keep the meaning and intent of the text intact so that an
AI assistant can still fulfil the request.  Return ONLY the sanitised text,
nothing else.

Original text:
{text}"""


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of the first JSON object in *text*."""
    # Try the whole string first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Look for a JSON block inside ```json ... ```
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Look for the first { ... }
    m = re.search(r"\{[^}]+\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return {}


class HybridRouterProvider(LLMProvider):
    """Routes requests between a *local* and a *remote* (API) LLM provider.

    Workflow
    --------
    1. The local model classifies the task difficulty.
    2. If the score ≤ threshold → the local model handles the request.
    3. Otherwise → the local model first sanitises PII, then the API model
       handles the request.
    """

    def __init__(
        self,
        local_provider: LLMProvider,
        api_provider: LLMProvider,
        local_model: str,
        api_model: str,
        difficulty_threshold: float = 0.5,
    ):
        super().__init__()
        self.local = local_provider
        self.api = api_provider
        self.local_model = local_model
        self.api_model = api_model
        self.difficulty_threshold = difficulty_threshold
        # --- embed_nanobot extensions: device-command routing (task 2.4) ---
        # Optional callback: (user_text) -> bool. If True, bypass difficulty
        # judge and route directly to the local model (e.g., device commands).
        self.force_local_fn: Callable[[str], bool] | None = None

    # -- public interface ----------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Route the request to local or API model based on difficulty."""
        user_text = self._last_user_text(messages)

        # --- embed_nanobot extensions: device-command routing (task 2.4) ---
        # If the caller has set a force_local_fn and it returns True
        # (e.g., the message references a registered device), skip the
        # difficulty judge and route straight to the local model.
        if self.force_local_fn is not None:
            try:
                if self.force_local_fn(user_text):
                    logger.info("[HybridRouter] forced LOCAL (device command detected)")
                    return await self.local.chat(
                        messages, tools=tools, model=self.local_model,
                        max_tokens=max_tokens, temperature=temperature,
                    )
            except Exception as e:
                logger.warning(f"[HybridRouter] force_local_fn failed: {e}; "
                               "falling through to normal routing")

        # 1. Judge difficulty via the local model
        score = await self._judge_difficulty(user_text)
        logger.info(f"[HybridRouter] difficulty score={score:.2f} "
                     f"threshold={self.difficulty_threshold}")

        if score <= self.difficulty_threshold:
            # Easy → local model
            logger.info("[HybridRouter] routing to LOCAL model")
            return await self.local.chat(
                messages, tools=tools, model=self.local_model,
                max_tokens=max_tokens, temperature=temperature,
            )

        # 2. Hard → sanitise PII, then use the API model
        logger.info("[HybridRouter] routing to API model (with PII sanitisation)")
        sanitised_messages = await self._sanitise_messages(messages)
        return await self.api.chat(
            sanitised_messages, tools=tools, model=self.api_model,
            max_tokens=max_tokens, temperature=temperature,
        )

    def get_default_model(self) -> str:
        return self.local_model

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _last_user_text(messages: list[dict[str, Any]]) -> str:
        """Extract the text of the last user message."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                # Vision messages: list of dicts
                if isinstance(content, list):
                    parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                    return " ".join(parts)
        return ""

    async def _judge_difficulty(self, text: str) -> float:
        """Ask the local model to classify difficulty.  Returns 0.0–1.0."""
        prompt = DIFFICULTY_JUDGE_PROMPT.format(message=text)
        try:
            resp = await self.local.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.local_model,
                max_tokens=128,
                temperature=0.0,
            )
            data = _extract_json(resp.content or "")
            score = float(data.get("score", 0.5))
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.warning(f"[HybridRouter] difficulty judge failed: {e}; "
                           "defaulting to API model")
            return 1.0  # ensures score > threshold, routing to API model

    async def _sanitise_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Strip PII from user messages using the local model."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                sanitised = await self._sanitise_text(
                    content if isinstance(content, str) else str(content)
                )
                out.append({**msg, "content": sanitised})
            else:
                out.append(msg)
        return out

    async def _sanitise_text(self, text: str) -> str:
        """Ask the local model to remove PII from *text*."""
        prompt = PII_SANITIZE_PROMPT.format(text=text)
        try:
            resp = await self.local.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.local_model,
                max_tokens=2048,
                temperature=0.0,
            )
            return resp.content or text
        except Exception as e:
            logger.warning(f"[HybridRouter] PII sanitisation failed: {e}; "
                           "sending original text")
            return text

"""Cross-cutting resilience utilities for the mesh network.

Provides:
- ``RetryPolicy`` — configurable retry parameters
- ``retry_send``  — exponential-backoff wrapper for async send callables
- ``Watchdog``    — periodic async loop for health checks / cleanup
- ``supervised_task`` — create_task wrapper with error logging
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from loguru import logger


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Configuration for exponential-backoff retries.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (0 = no retries, just the initial try).
    base_delay:
        Initial delay in seconds before the first retry.
    max_delay:
        Cap on delay between retries.
    backoff_factor:
        Multiplier applied to delay after each retry.
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    backoff_factor: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Return the delay (seconds) before retry *attempt* (0-based)."""
        d = self.base_delay * (self.backoff_factor ** attempt)
        return min(d, self.max_delay)


DEFAULT_RETRY = RetryPolicy()


async def retry_send(
    send_fn: Callable[..., Awaitable[bool]],
    *args: Any,
    policy: RetryPolicy = DEFAULT_RETRY,
    label: str = "send",
    **kwargs: Any,
) -> bool:
    """Call *send_fn* with exponential-backoff retries.

    Returns ``True`` on first success, ``False`` if all attempts fail.
    """
    for attempt in range(1 + policy.max_retries):
        try:
            ok = await send_fn(*args, **kwargs)
            if ok:
                if attempt > 0:
                    logger.info(
                        "[Resilience] {} succeeded on attempt {}/{}",
                        label, attempt + 1, 1 + policy.max_retries,
                    )
                return True
        except Exception as exc:
            logger.warning(
                "[Resilience] {} attempt {}/{} raised: {}",
                label, attempt + 1, 1 + policy.max_retries, exc,
            )

        if attempt < policy.max_retries:
            delay = policy.delay_for(attempt)
            logger.debug(
                "[Resilience] {} failed, retrying in {:.1f}s (attempt {}/{})",
                label, delay, attempt + 1, 1 + policy.max_retries,
            )
            await asyncio.sleep(delay)

    logger.warning(
        "[Resilience] {} failed after {} attempts", label, 1 + policy.max_retries,
    )
    return False


# ---------------------------------------------------------------------------
# Watchdog — periodic async health-check loop
# ---------------------------------------------------------------------------

class Watchdog:
    """Runs a callback at a fixed interval in an async task.

    Parameters
    ----------
    name:
        Human-readable label for logging.
    callback:
        Callable (sync or async) invoked each tick. Exceptions are logged,
        not propagated.
    interval:
        Seconds between ticks.
    """

    def __init__(
        self,
        name: str,
        callback: Callable[[], Any],
        interval: float = 15.0,
    ) -> None:
        self.name = name
        self._callback = callback
        self._interval = interval
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        logger.debug("[Watchdog/{}] started (interval={:.0f}s)", self.name, self._interval)
        while True:
            await asyncio.sleep(self._interval)
            try:
                result = self._callback()
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[Watchdog/{}] callback error: {}", self.name, exc)

    def start(self) -> None:
        """Start the watchdog loop as a background task."""
        if self._task is None or self._task.done():
            self._task = supervised_task(self._loop(), name=f"watchdog-{self.name}")
            logger.debug("[Watchdog/{}] task created", self.name)

    def stop(self) -> None:
        """Cancel the watchdog task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            logger.debug("[Watchdog/{}] stopped", self.name)
            self._task = None


# ---------------------------------------------------------------------------
# Supervised task — create_task with error logging
# ---------------------------------------------------------------------------

def supervised_task(
    coro: Awaitable[Any],
    *,
    name: str = "",
) -> asyncio.Task:
    """Wrap ``asyncio.create_task`` with an error-logging callback.

    If the task raises an exception (other than ``CancelledError``),
    it is logged as an error instead of becoming an unhandled exception.
    """
    task = asyncio.create_task(coro, name=name or None)

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error(
                "[Resilience] supervised task {!r} failed: {!r}",
                t.get_name(), exc,
            )

    task.add_done_callback(_on_done)
    return task

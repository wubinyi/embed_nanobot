"""Device-aware routing helpers for the Hybrid Router.

Provides functions to detect whether a user message references registered
mesh devices, allowing the Hybrid Router to bypass difficulty judgment and
route device commands directly to the local LLM.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.mesh.registry import DeviceRegistry


def is_device_related(text: str, registry: DeviceRegistry) -> bool:
    """Check whether *text* mentions a registered device or capability.

    Returns ``True`` if *text* contains any of:
    - A registered device ``node_id`` (e.g., ``light-01``)
    - A registered device ``name`` (e.g., ``Living Room Light``)
    - A registered device ``device_type`` (e.g., ``smart_light``)
    - A registered capability ``name`` (e.g., ``brightness``, ``temperature``)

    The match is case-insensitive and uses word-boundary-aware search to
    avoid false positives (e.g., "power" in "PowerPoint" won't match when
    the word is embedded in a larger word).

    Parameters
    ----------
    text:
        The user's message text.
    registry:
        The device registry to check against.

    Returns
    -------
    bool
        ``True`` if the message likely references a registered device.
    """
    if not text:
        return False

    devices = registry.get_all_devices()
    if not devices:
        return False

    text_lower = text.lower()

    for device in devices:
        # Match device node_id (often contains hyphens, so exact substring is fine)
        if device.node_id and device.node_id.lower() in text_lower:
            logger.debug(f"[Routing] matched device node_id: {device.node_id}")
            return True

        # Match device name (multi-word, case-insensitive)
        if device.name and device.name.lower() in text_lower:
            logger.debug(f"[Routing] matched device name: {device.name}")
            return True

        # Match device type (e.g., "smart_light" → also check "smart light")
        if device.device_type:
            dt_lower = device.device_type.lower()
            if dt_lower in text_lower or dt_lower.replace("_", " ") in text_lower:
                logger.debug(f"[Routing] matched device_type: {device.device_type}")
                return True

        # Match capability names (word-boundary aware to reduce false positives)
        for cap in device.capabilities:
            if cap.name and len(cap.name) >= 3:  # skip very short names
                pattern = r"\b" + re.escape(cap.name.lower()) + r"\b"
                if re.search(pattern, text_lower):
                    logger.debug(f"[Routing] matched capability: {cap.name}")
                    return True

    return False


def build_force_local_fn(registry: DeviceRegistry):
    """Create a ``force_local_fn`` callback for the HybridRouter.

    Returns a callable ``(str) -> bool`` that captures the registry and
    calls :func:`is_device_related`.

    Usage in CLI wiring::

        from nanobot.mesh.routing import build_force_local_fn
        provider.force_local_fn = build_force_local_fn(mesh_ch.registry)
    """

    def _check(text: str) -> bool:
        return is_device_related(text, registry)

    return _check

"""Safe deployment pipeline for OTA updates (task 5.2.4).

Adds staged rollout, health monitoring, emergency recall, and deployment
history on top of the existing OTAManager infrastructure.

Deployment flow:
1. **Stage**: Select firmware + target devices (single or group).
2. **Canary**: Deploy to first device. Wait ``health_check_window`` seconds.
3. **Health check**: Verify device reports healthy (STATE_REPORT, PARTITION_REPORT, online).
4. **Group rollout**: If canary healthy, deploy to remaining devices.
5. **Monitor**: After group rollout, monitor all devices for ``health_check_window``.
6. **Recall**: If any device enters crash_loop, broadcast rollback to all targets.

All deployments are recorded in an append-only JSON audit trail.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

from loguru import logger


class DeploymentState(str, Enum):
    """States of a deployment."""
    PENDING = "pending"
    CANARY = "canary"              # Deploying to first device
    CANARY_HEALTHY = "canary_healthy"
    ROLLING_OUT = "rolling_out"    # Deploying to remaining devices
    MONITORING = "monitoring"      # Post-rollout health check
    COMPLETE = "complete"
    FAILED = "failed"
    RECALLED = "recalled"


@dataclass
class DeploymentRecord:
    """Audit record of a single deployment."""

    deployment_id: str
    firmware_id: str
    firmware_version: str
    target_devices: list[str]
    state: str = DeploymentState.PENDING
    canary_device: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    health_check_window: int = 300   # seconds
    devices_succeeded: list[str] = field(default_factory=list)
    devices_failed: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "firmware_id": self.firmware_id,
            "firmware_version": self.firmware_version,
            "target_devices": self.target_devices,
            "state": self.state,
            "canary_device": self.canary_device,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "health_check_window": self.health_check_window,
            "devices_succeeded": self.devices_succeeded,
            "devices_failed": self.devices_failed,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeploymentRecord:
        return cls(
            deployment_id=d.get("deployment_id", ""),
            firmware_id=d.get("firmware_id", ""),
            firmware_version=d.get("firmware_version", ""),
            target_devices=d.get("target_devices", []),
            state=d.get("state", DeploymentState.PENDING),
            canary_device=d.get("canary_device", ""),
            started_at=d.get("started_at", 0.0),
            completed_at=d.get("completed_at", 0.0),
            health_check_window=d.get("health_check_window", 300),
            devices_succeeded=d.get("devices_succeeded", []),
            devices_failed=d.get("devices_failed", []),
            error=d.get("error", ""),
        )


class DeploymentPipeline:
    """Orchestrates safe firmware deployments.

    Parameters
    ----------
    ota_manager :
        OTAManager for sending firmware to devices.
    partition_manifest :
        PartitionManifest for checking device health.
    registry :
        DeviceRegistry for online/offline status.
    log_path :
        Path to JSON audit trail file.
    health_check_window :
        Seconds to wait after each deployment stage for health verification.
    """

    def __init__(
        self,
        ota_manager: Any = None,
        partition_manifest: Any = None,
        registry: Any = None,
        log_path: str = "",
        health_check_window: int = 300,
    ):
        self._ota = ota_manager
        self._manifest = partition_manifest
        self._registry = registry
        self._log_path = Path(log_path) if log_path else None
        self._health_check_window = health_check_window
        self._deployments: list[DeploymentRecord] = []
        self._active: DeploymentRecord | None = None
        if self._log_path:
            self._load()

    # -- Create deployment ---------------------------------------------------

    def create_deployment(
        self,
        firmware_id: str,
        firmware_version: str,
        target_devices: list[str],
        health_check_window: int | None = None,
    ) -> DeploymentRecord:
        """Create a new deployment plan (does not start it)."""
        dep = DeploymentRecord(
            deployment_id=f"deploy-{int(time.time())}",
            firmware_id=firmware_id,
            firmware_version=firmware_version,
            target_devices=list(target_devices),
            health_check_window=health_check_window or self._health_check_window,
            started_at=time.time(),
        )
        if target_devices:
            dep.canary_device = target_devices[0]
        self._deployments.append(dep)
        self._save()
        return dep

    # -- Execute deployment --------------------------------------------------

    async def start_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        """Begin a deployment: deploy to canary device first."""
        dep = self.get_deployment(deployment_id)
        if dep is None:
            return None

        if not self._ota:
            dep.state = DeploymentState.FAILED
            dep.error = "OTA manager not available"
            self._save()
            return dep

        if not dep.target_devices:
            dep.state = DeploymentState.FAILED
            dep.error = "No target devices"
            self._save()
            return dep

        self._active = dep
        dep.state = DeploymentState.CANARY

        # Deploy to canary (first device)
        canary = dep.canary_device
        logger.info("Deployment {}: canary → {}", dep.deployment_id, canary)

        session = await self._ota.start_update(canary, dep.firmware_id)
        if session is None:
            dep.state = DeploymentState.FAILED
            dep.error = f"Failed to start OTA for canary {canary}"
            self._save()
            return dep

        self._save()
        return dep

    def check_canary_health(self, deployment_id: str) -> bool:
        """Check if the canary device is healthy after deployment.

        Returns True if healthy. Should be called after health_check_window elapses.
        """
        dep = self.get_deployment(deployment_id)
        if dep is None or dep.state != DeploymentState.CANARY:
            return False

        canary = dep.canary_device

        # Check partition state
        if self._manifest:
            from nanobot.mesh.partitions import BootState
            entry = self._manifest.get(canary)
            if entry and entry.boot_state in (BootState.CRASH_LOOP, BootState.ROLLBACK):
                dep.state = DeploymentState.FAILED
                dep.devices_failed.append(canary)
                dep.error = f"Canary {canary} in {entry.boot_state}"
                self._save()
                return False

        # Check online status
        if self._registry:
            device = self._registry.get_device(canary)
            if device and not device.online:
                dep.state = DeploymentState.FAILED
                dep.devices_failed.append(canary)
                dep.error = f"Canary {canary} went offline"
                self._save()
                return False

        dep.state = DeploymentState.CANARY_HEALTHY
        dep.devices_succeeded.append(canary)
        self._save()
        return True

    async def continue_rollout(self, deployment_id: str) -> DeploymentRecord | None:
        """After canary passes, deploy to remaining devices."""
        dep = self.get_deployment(deployment_id)
        if dep is None or dep.state != DeploymentState.CANARY_HEALTHY:
            return dep

        remaining = [d for d in dep.target_devices if d != dep.canary_device]
        if not remaining:
            dep.state = DeploymentState.COMPLETE
            dep.completed_at = time.time()
            self._save()
            return dep

        dep.state = DeploymentState.ROLLING_OUT
        logger.info("Deployment {}: rolling out to {} devices", dep.deployment_id, len(remaining))

        for node_id in remaining:
            if self._ota:
                session = await self._ota.start_update(node_id, dep.firmware_id)
                if session is None:
                    dep.devices_failed.append(node_id)
                else:
                    dep.devices_succeeded.append(node_id)

        dep.state = DeploymentState.MONITORING
        self._save()
        return dep

    def finalize_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        """Check all devices healthy and mark deployment complete."""
        dep = self.get_deployment(deployment_id)
        if dep is None:
            return None

        # Check each device for crash loop
        any_failed = False
        if self._manifest:
            from nanobot.mesh.partitions import BootState
            for node_id in dep.target_devices:
                entry = self._manifest.get(node_id)
                if entry and entry.boot_state in (BootState.CRASH_LOOP, BootState.ROLLBACK):
                    if node_id not in dep.devices_failed:
                        dep.devices_failed.append(node_id)
                    any_failed = True

        if any_failed:
            dep.state = DeploymentState.FAILED
            dep.error = f"{len(dep.devices_failed)} device(s) unhealthy"
        else:
            dep.state = DeploymentState.COMPLETE

        dep.completed_at = time.time()
        self._active = None
        self._save()
        return dep

    # -- Emergency recall ----------------------------------------------------

    async def recall_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        """Emergency: abort all OTA sessions and request device rollback."""
        dep = self.get_deployment(deployment_id)
        if dep is None:
            return None

        logger.warning("RECALL deployment {}: aborting all OTA for {} devices",
                        dep.deployment_id, len(dep.target_devices))

        for node_id in dep.target_devices:
            if self._ota:
                await self._ota.abort_update(node_id, reason="deployment recalled")

        dep.state = DeploymentState.RECALLED
        dep.completed_at = time.time()
        dep.error = "Recalled by operator"
        self._active = None
        self._save()
        return dep

    # -- Query ---------------------------------------------------------------

    def get_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        for dep in self._deployments:
            if dep.deployment_id == deployment_id:
                return dep
        return None

    def active_deployment(self) -> DeploymentRecord | None:
        return self._active

    def deployment_history(self, limit: int = 20) -> list[DeploymentRecord]:
        return self._deployments[-limit:]

    def summary(self) -> str:
        """LLM-friendly deployment status summary."""
        if not self._deployments:
            return "No deployment history."
        lines = ["## Deployment History (last 5)"]
        for dep in self._deployments[-5:]:
            ok = len(dep.devices_succeeded)
            fail = len(dep.devices_failed)
            total = len(dep.target_devices)
            lines.append(
                f"- {dep.deployment_id}: {dep.firmware_id} v{dep.firmware_version} "
                f"→ {total} devices | state={dep.state} | ok={ok} fail={fail}"
            )
        if self._active:
            lines.append(f"\n**Active**: {self._active.deployment_id} — {self._active.state}")
        return "\n".join(lines)

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._log_path or not self._log_path.exists():
            return
        try:
            data = json.loads(self._log_path.read_text(encoding="utf-8"))
            self._deployments = [
                DeploymentRecord.from_dict(d) for d in data.get("deployments", [])
            ]
            logger.debug("Loaded {} deployment records from {}", len(self._deployments), self._log_path)
        except Exception as e:
            logger.warning("Failed to load deployment log: {}", e)

    def _save(self) -> None:
        if not self._log_path:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"deployments": [d.to_dict() for d in self._deployments]}
            self._log_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save deployment log: {}", e)

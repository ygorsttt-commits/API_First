from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from app.ai.gateway import AIGateway
from app.config import Settings
from app.deploy.targets import DeployTarget
from app.executor.sandbox import Sandbox
from app.validation.checks import CheckOutcome
from app.workspace.manager import WorkspaceManager


class StepFailed(Exception):
    """A step could not complete. The message is shown to users (it is redacted before storage)."""


class PermissionDenied(StepFailed):
    pass


@dataclass
class NewArtifact:
    kind: str
    name: str
    content: str | dict[str, Any] | list[Any]
    content_type: str = "application/json"
    simulated: bool = False


@dataclass
class StepOutput:
    summary: dict[str, Any] = field(default_factory=dict)
    artifacts: list[NewArtifact] = field(default_factory=list)
    validations: list[CheckOutcome] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepContext:
    """What a capability may see and use. Services are only reachable if the permission was granted."""

    project_id: str
    run_id: str
    run_kind: str
    settings: Settings
    inputs: dict[str, Any]
    state: dict[str, Any]
    granted: frozenset[str]
    _gateway: AIGateway | None = None
    _workspace: WorkspaceManager | None = None
    _sandbox: Sandbox | None = None
    _deploy_target: DeployTarget | None = None
    _events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _need(self, perm: str) -> None:
        if perm not in self.granted:
            raise PermissionDenied(f"permission '{perm}' was not granted to this step")

    @property
    def gateway(self) -> AIGateway:
        self._need("llm")
        assert self._gateway is not None
        return self._gateway

    @property
    def workspace(self) -> WorkspaceManager:
        if "workspace:write" not in self.granted:
            self._need("workspace:read")
        assert self._workspace is not None
        return self._workspace

    def require_write(self) -> WorkspaceManager:
        self._need("workspace:write")
        assert self._workspace is not None
        return self._workspace

    @property
    def sandbox(self) -> Sandbox:
        self._need("sandbox:exec")
        assert self._sandbox is not None
        return self._sandbox

    @property
    def deploy_target(self) -> DeployTarget:
        self._need("deploy:execute")
        assert self._deploy_target is not None
        return self._deploy_target

    def log(self, message: str, level: str = "info", **data: Any) -> None:
        with self._lock:
            self._events.append((level, message, data))

    def drain_events(self) -> list[tuple[str, str, dict[str, Any]]]:
        with self._lock:
            events, self._events = self._events, []
        return events

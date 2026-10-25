from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PlannedResource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str  # e.g. aws_apprunner_service.app
    file: str


class DeployPlan(BaseModel):
    """Built deterministically by the backend (never by the AI) from the validated workspace."""

    model_config = ConfigDict(extra="forbid")
    environment: Literal["dev"]
    target: Literal["simulated", "aws"]
    simulated: bool
    region: str | None
    workspace_sha256: str
    build_run_id: str
    resources: list[PlannedResource]
    checks: dict[str, int]  # status -> count
    blocking_issues: list[str]
    warnings: list[str]
    estimated_cost: str
    required_approval_role: Literal["deployer"]
    steps: list[str]
    rollback_instructions: list[str]

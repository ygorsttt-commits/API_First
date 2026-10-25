from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=10, max_length=20_000)
    start: bool = True  # immediately queue the requirements run

    @field_validator("name", "prompt")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ProjectOut(ORM):
    id: str
    name: str
    prompt: str
    status: str
    failed_stage: str | None
    created_at: datetime
    updated_at: datetime


class StepOut(ORM):
    id: str
    position: int
    name: str
    capability: str
    status: str
    attempts: int
    max_attempts: int
    timeout_seconds: int
    error: str | None
    output_summary: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None


class RunOut(ORM):
    id: str
    project_id: str
    kind: str
    status: str
    requested_by: str
    error: str | None
    provider: str
    simulated: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunOut):
    steps: list[StepOut]


class EventOut(ORM):
    id: int
    run_id: str
    step: str | None
    level: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class ArtifactMeta(ORM):
    id: str
    run_id: str | None
    kind: str
    name: str
    content_type: str
    sha256: str
    size: int
    version: int
    simulated: bool
    created_at: datetime


class ArtifactOut(ArtifactMeta):
    content: str


class ValidationOut(ORM):
    id: str
    run_id: str
    check_id: str
    category: str
    status: str
    summary: str
    log: str
    tool: str
    executed: bool
    duration_ms: int
    created_at: datetime


class ApprovalOut(ORM):
    id: str
    kind: str
    status: str
    content_hash: str
    approved_by: str
    comment: str | None
    invalidated_reason: str | None
    created_at: datetime
    invalidated_at: datetime | None


class ApprovalCreate(BaseModel):
    kind: Literal["requirements", "plan", "deploy"]
    expected_hash: str = Field(min_length=64, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)


class RunCreate(BaseModel):
    kind: Literal["requirements", "plan", "build", "deploy_plan"]
    feedback: str | None = Field(default=None, max_length=4000)


class ReviewState(BaseModel):
    """Everything the UI needs to drive approvals safely."""

    status: str
    hashes: dict[str, str | None]
    approvals: dict[str, dict[str, Any]]
    blocking_issues: list[str]
    can_start: dict[str, bool]


class FileEntry(BaseModel):
    path: str
    size: int


class AuditOut(ORM):
    id: int
    actor: str
    action: str
    project_id: str | None
    details: dict[str, Any]
    created_at: datetime


class PublicConfig(BaseModel):
    demo_mode: bool
    llm_provider: str
    llm_simulated: bool
    model: str | None
    deploy_target: str
    deploy_simulated: bool
    sandbox: dict[str, Any]
    auth_mode: str
    user: dict[str, Any]

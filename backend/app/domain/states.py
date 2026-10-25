"""Project lifecycle state machine. The only place where project status transitions are defined."""

from __future__ import annotations

from enum import StrEnum


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    REQUIREMENTS_RUNNING = "requirements_running"
    REQUIREMENTS_REVIEW = "requirements_review"
    PLAN_RUNNING = "plan_running"
    PLAN_REVIEW = "plan_review"
    BUILD_RUNNING = "build_running"
    BUILD_REVIEW = "build_review"
    DEPLOY_PLAN_RUNNING = "deploy_plan_running"
    DEPLOY_REVIEW = "deploy_review"
    DEPLOYING = "deploying"
    DELIVERED = "delivered"
    FAILED = "failed"


class RunKind(StrEnum):
    REQUIREMENTS = "requirements"
    PLAN = "plan"
    BUILD = "build"
    DEPLOY_PLAN = "deploy_plan"
    DEPLOY = "deploy"


S = ProjectStatus

# Status the project enters while a run of this kind is executing, and on success.
RUNNING_STATUS: dict[RunKind, ProjectStatus] = {
    RunKind.REQUIREMENTS: S.REQUIREMENTS_RUNNING,
    RunKind.PLAN: S.PLAN_RUNNING,
    RunKind.BUILD: S.BUILD_RUNNING,
    RunKind.DEPLOY_PLAN: S.DEPLOY_PLAN_RUNNING,
    RunKind.DEPLOY: S.DEPLOYING,
}
SUCCESS_STATUS: dict[RunKind, ProjectStatus] = {
    RunKind.REQUIREMENTS: S.REQUIREMENTS_REVIEW,
    RunKind.PLAN: S.PLAN_REVIEW,
    RunKind.BUILD: S.BUILD_REVIEW,
    RunKind.DEPLOY_PLAN: S.DEPLOY_REVIEW,
    RunKind.DEPLOY: S.DELIVERED,
}

_REVIEW_STATES = {S.REQUIREMENTS_REVIEW, S.PLAN_REVIEW, S.BUILD_REVIEW, S.DEPLOY_REVIEW, S.DELIVERED}

# From which project statuses a run of each kind may be started.
ALLOWED_START: dict[RunKind, set[ProjectStatus]] = {
    # Requirements can always be regenerated from a stable state; this invalidates downstream approvals.
    RunKind.REQUIREMENTS: {S.DRAFT, S.FAILED} | _REVIEW_STATES,
    RunKind.PLAN: {S.REQUIREMENTS_REVIEW, S.PLAN_REVIEW, S.BUILD_REVIEW, S.DEPLOY_REVIEW, S.FAILED},
    RunKind.BUILD: {S.PLAN_REVIEW, S.BUILD_REVIEW, S.DEPLOY_REVIEW, S.FAILED},
    RunKind.DEPLOY_PLAN: {S.BUILD_REVIEW, S.DEPLOY_REVIEW, S.FAILED},
    RunKind.DEPLOY: {S.DEPLOY_REVIEW},
}


class TransitionError(Exception):
    pass


def check_can_start(current: str, kind: RunKind) -> None:
    status = ProjectStatus(current)
    if status not in ALLOWED_START[kind]:
        raise TransitionError(f"cannot start '{kind}' run while project is '{status}'")

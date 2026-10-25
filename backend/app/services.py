"""Application services: the backend-controlled rules for runs, artifacts and approvals."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import Settings
from app.domain.hashing import canonical_json, combine, sha256_text
from app.domain.states import RUNNING_STATUS, ProjectStatus, RunKind, TransitionError, check_can_start
from app.models import Approval, Artifact, Project, Run, RunEvent, RunStep, utcnow
from app.security.auth import Actor
from app.security.redaction import redact


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# Creating an artifact of a given kind invalidates approvals that depended on the previous version.
_INVALIDATES: dict[str, tuple[str, ...]] = {
    "requirements": ("requirements", "plan", "deploy"),
    "architecture": ("plan", "deploy"),
    "task_plan": ("plan", "deploy"),
    "workspace_snapshot": ("deploy",),
    "deploy_plan": ("deploy",),
}

# Approval kind -> run started automatically once approved.
_NEXT_RUN = {"requirements": RunKind.PLAN, "plan": RunKind.BUILD, "deploy": RunKind.DEPLOY}
_APPROVAL_ROLE = {"requirements": "approver", "plan": "approver", "deploy": "deployer"}
_REVIEW_STATUS = {
    "requirements": ProjectStatus.REQUIREMENTS_REVIEW,
    "plan": ProjectStatus.PLAN_REVIEW,
    "deploy": ProjectStatus.DEPLOY_REVIEW,
}


# ------------------------------------------------------------------ events & artifacts


def emit(
    session: Session, run: Run, message: str, level: str = "info", step: str | None = None, **data: Any
) -> None:
    session.add(
        RunEvent(
            run_id=run.id,
            project_id=run.project_id,
            step=step,
            level=level,
            message=redact(message)[:4000],
            data=json.loads(redact(json.dumps(data, default=str))),
        )
    )


def latest_artifact(session: Session, project_id: str, kind: str) -> Artifact | None:
    return session.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.kind == kind)
        .order_by(Artifact.version.desc())
        .limit(1)
    ).first()


def artifact_json(session: Session, project_id: str, kind: str) -> dict[str, Any] | None:
    art = latest_artifact(session, project_id, kind)
    return json.loads(art.content) if art else None


def add_artifact(
    session: Session,
    settings: Settings,
    project: Project,
    run: Run | None,
    *,
    kind: str,
    name: str,
    content: str | dict[str, Any] | list[Any],
    content_type: str = "application/json",
    simulated: bool,
) -> Artifact:
    text = canonical_json(content) if not isinstance(content, str) else content
    size = len(text.encode("utf-8"))
    if size > settings.max_artifact_bytes:
        raise ServiceError(f"artifact {kind} is {size} bytes, above the limit", 413)
    prev = latest_artifact(session, project.id, kind)
    art = Artifact(
        project_id=project.id,
        run_id=run.id if run else None,
        kind=kind,
        name=name,
        content_type=content_type,
        content=text,
        sha256=sha256_text(text),
        size=size,
        version=(prev.version + 1) if prev else 1,
        simulated=simulated,
    )
    session.add(art)
    session.flush()
    if kinds := _INVALIDATES.get(kind):
        invalidate_approvals(session, project.id, kinds, f"new {kind} v{art.version} was generated")
    return art


# ------------------------------------------------------------------ approvals


def current_hashes(session: Session, project: Project) -> dict[str, str | None]:
    req = latest_artifact(session, project.id, "requirements")
    arch = latest_artifact(session, project.id, "architecture")
    plan = latest_artifact(session, project.id, "task_plan")
    snap = latest_artifact(session, project.id, "workspace_snapshot")
    dplan = latest_artifact(session, project.id, "deploy_plan")
    req_h = req.sha256 if req else None
    plan_h = combine(req_h, arch.sha256, plan.sha256) if (req_h and arch and plan) else None
    deploy_h = combine(plan_h, snap.sha256, dplan.sha256) if (plan_h and snap and dplan) else None
    return {"requirements": req_h, "plan": plan_h, "deploy": deploy_h}


def active_approval(session: Session, project_id: str, kind: str) -> Approval | None:
    return session.scalars(
        select(Approval)
        .where(Approval.project_id == project_id, Approval.kind == kind, Approval.status == "active")
        .order_by(Approval.created_at.desc())
        .limit(1)
    ).first()


def approval_state(session: Session, project: Project, kind: str) -> tuple[bool, str]:
    """An approval is valid only if it is active AND its hash equals the current content hash."""
    appr = active_approval(session, project.id, kind)
    if appr is None:
        return False, f"no active {kind} approval"
    current = current_hashes(session, project)[kind]
    if current is None or current != appr.content_hash:
        return False, f"{kind} content changed since it was approved"
    return True, "valid"


def invalidate_approvals(session: Session, project_id: str, kinds: tuple[str, ...], reason: str) -> None:
    for appr in session.scalars(
        select(Approval).where(
            Approval.project_id == project_id, Approval.kind.in_(kinds), Approval.status == "active"
        )
    ):
        appr.status = "invalidated"
        appr.invalidated_reason = reason
        appr.invalidated_at = utcnow()


def blocking_issues(session: Session, project: Project) -> list[str]:
    """Reasons a deployment may not be approved."""
    issues: list[str] = []
    dplan = artifact_json(session, project.id, "deploy_plan")
    snap = latest_artifact(session, project.id, "workspace_snapshot")
    if dplan is None:
        return ["no deploy plan prepared"]
    if snap is None or dplan.get("workspace_sha256") != snap.sha256:
        issues.append("deploy plan is stale: workspace changed after it was prepared")
    issues += list(dplan.get("blocking_issues", []))
    ok, reason = approval_state(session, project, "plan")
    if not ok:
        issues.append(f"plan approval not valid: {reason}")
    return issues


def approve(
    session: Session,
    settings: Settings,
    project: Project,
    actor: Actor,
    *,
    kind: str,
    expected_hash: str,
    comment: str | None,
) -> tuple[Approval, Run | None]:
    if kind not in _NEXT_RUN:
        raise ServiceError(f"unknown approval kind '{kind}'")
    role = _APPROVAL_ROLE[kind]
    if not actor.has(role):
        raise ServiceError(f"role '{role}' is required to approve {kind}", 403)
    if project.status != _REVIEW_STATUS[kind]:
        raise ServiceError(
            f"project is '{project.status}', {kind} can only be approved in '{_REVIEW_STATUS[kind]}'", 409
        )
    current = current_hashes(session, project)[kind]
    if current is None:
        raise ServiceError(f"nothing to approve for {kind}", 409)
    if expected_hash != current:
        raise ServiceError("the content changed since you reviewed it; reload and review again", 409)
    if kind == "deploy":
        issues = blocking_issues(session, project)
        if issues:
            raise ServiceError("deployment is blocked: " + "; ".join(issues), 409)

    invalidate_approvals(session, project.id, (kind,), "superseded by a newer approval")
    artifact_ids = [a.id for k in _hash_kinds(kind) if (a := latest_artifact(session, project.id, k))]
    appr = Approval(
        project_id=project.id,
        kind=kind,
        content_hash=current,
        artifact_ids=artifact_ids,
        approved_by=actor.user_id,
        comment=(comment or None),
    )
    session.add(appr)
    session.flush()
    audit(session, actor.user_id, f"approve_{kind}", project.id, content_hash=current, comment=comment or "")
    run = start_run(session, settings, project, actor, _NEXT_RUN[kind])
    return appr, run


def _hash_kinds(kind: str) -> tuple[str, ...]:
    return {
        "requirements": ("requirements",),
        "plan": ("requirements", "architecture", "task_plan"),
        "deploy": ("requirements", "architecture", "task_plan", "workspace_snapshot", "deploy_plan"),
    }[kind]


# ------------------------------------------------------------------ runs


def start_run(
    session: Session,
    settings: Settings,
    project: Project,
    actor: Actor,
    kind: RunKind,
    feedback: str | None = None,
) -> Run:
    from app.orchestration.definitions import RUN_DEFINITIONS

    required_role = "deployer" if kind == RunKind.DEPLOY else "editor"
    if not actor.has(required_role):
        raise ServiceError(f"role '{required_role}' is required to start a {kind} run", 403)
    try:
        check_can_start(project.status, kind)
    except TransitionError as exc:
        raise ServiceError(str(exc), 409) from None

    if kind == RunKind.PLAN:
        ok, reason = approval_state(session, project, "requirements")
        if not ok:
            raise ServiceError(f"requirements must be approved first ({reason})", 409)
    elif kind in (RunKind.BUILD, RunKind.DEPLOY_PLAN):
        ok, reason = approval_state(session, project, "plan")
        if not ok:
            raise ServiceError(f"plan must be approved first ({reason})", 409)
        if kind == RunKind.DEPLOY_PLAN and latest_artifact(session, project.id, "workspace_snapshot") is None:
            raise ServiceError("no build output to deploy yet", 409)
    elif kind == RunKind.DEPLOY:
        ok, reason = approval_state(session, project, "deploy")
        if not ok:
            raise ServiceError(f"deployment requires a valid deploy approval ({reason})", 409)

    if session.scalars(
        select(Run).where(Run.project_id == project.id, Run.status.in_(("queued", "running")))
    ).first():
        raise ServiceError("another run is already in progress for this project", 409)

    definition = RUN_DEFINITIONS[kind]
    simulated = (
        (settings.deploy_target == "simulated")
        if kind == RunKind.DEPLOY
        else (settings.llm_provider == "demo")
    )
    run = Run(
        project_id=project.id,
        kind=kind.value,
        requested_by=actor.user_id,
        input={"feedback": (feedback or "")[:4000]},
        provider=settings.llm_provider,
        simulated=simulated,
    )
    session.add(run)
    session.flush()
    for pos, step in enumerate(definition.steps):
        session.add(
            RunStep(
                run_id=run.id,
                position=pos,
                name=step.name,
                capability=step.capability,
                max_attempts=step.max_attempts,
                timeout_seconds=step.timeout_seconds,
            )
        )
    project.status = RUNNING_STATUS[kind].value
    project.failed_stage = None
    emit(session, run, f"{kind.value} run queued by {actor.user_id}")
    audit(
        session,
        actor.user_id,
        f"start_run_{kind.value}",
        project.id,
        run_id=run.id,
        feedback=(feedback or "")[:500],
    )
    return run

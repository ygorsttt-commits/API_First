"""HTTP API. Every project-scoped query is filtered by the caller's user id, so one user can never
read or act on another user's projects (a foreign id behaves exactly like a missing one: 404)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas as s
from app.audit import audit
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.states import ALLOWED_START, ProjectStatus, RunKind
from app.executor.sandbox import build_sandbox
from app.models import Approval, Artifact, AuditLog, Project, Run, RunEvent, ValidationResult
from app.security.auth import Actor, current_actor, require
from app.services import (
    ServiceError,
    approval_state,
    approve,
    blocking_issues,
    current_hashes,
    latest_artifact,
    start_run,
)

router = APIRouter(prefix="/api")


def _raise(exc: ServiceError) -> None:
    raise HTTPException(exc.status_code, str(exc))


def get_project(project_id: str, session: Session, actor: Actor) -> Project:
    project = session.scalars(
        select(Project).where(Project.id == project_id, Project.owner_id == actor.user_id)
    ).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


def get_run(run_id: str, session: Session, actor: Actor) -> Run:
    run = session.scalars(
        select(Run).join(Project).where(Run.id == run_id, Project.owner_id == actor.user_id)
    ).first()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


# ------------------------------------------------------------------ meta


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    from sqlalchemy import text

    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/config", response_model=s.PublicConfig)
def public_config(settings: Settings = Depends(get_settings), actor: Actor = Depends(current_actor)):
    ok, reason = build_sandbox(settings).available()
    return s.PublicConfig(
        demo_mode=settings.demo_mode,
        llm_provider=settings.llm_provider,
        llm_simulated=settings.llm_provider == "demo",
        model=settings.anthropic_model if settings.llm_provider == "anthropic" else None,
        deploy_target=settings.deploy_target,
        deploy_simulated=settings.deploy_target == "simulated",
        sandbox={"backend": settings.sandbox_backend, "available": ok, "detail": reason},
        auth_mode=settings.auth_mode,
        user={"id": actor.user_id, "roles": sorted(actor.roles)},
    )


# ------------------------------------------------------------------ projects


@router.get("/projects", response_model=list[s.ProjectOut])
def list_projects(session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))):
    return session.scalars(
        select(Project).where(Project.owner_id == actor.user_id).order_by(Project.created_at.desc())
    ).all()


@router.post("/projects", response_model=s.ProjectOut, status_code=201)
def create_project(
    body: s.ProjectCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require("editor")),
):
    project = Project(
        owner_id=actor.user_id, name=body.name, prompt=body.prompt, status=ProjectStatus.DRAFT.value
    )
    session.add(project)
    session.flush()
    audit(session, actor.user_id, "create_project", project.id, name=body.name)
    if body.start:
        try:
            start_run(session, settings, project, actor, RunKind.REQUIREMENTS)
        except ServiceError as exc:
            session.rollback()
            _raise(exc)
    session.commit()
    return project


@router.get("/projects/{project_id}", response_model=s.ProjectOut)
def read_project(
    project_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    return get_project(project_id, session, actor)


@router.get("/projects/{project_id}/review", response_model=s.ReviewState)
def review_state(
    project_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    project = get_project(project_id, session, actor)
    approvals = {}
    for kind in ("requirements", "plan", "deploy"):
        valid, reason = approval_state(session, project, kind)
        approvals[kind] = {"valid": valid, "reason": reason}
    current = ProjectStatus(project.status)
    busy = (
        session.scalars(
            select(Run).where(Run.project_id == project.id, Run.status.in_(("queued", "running")))
        ).first()
        is not None
    )
    return s.ReviewState(
        status=project.status,
        hashes=current_hashes(session, project),
        approvals=approvals,
        blocking_issues=blocking_issues(session, project) if project.status == "deploy_review" else [],
        can_start={
            k.value: (not busy and current in ALLOWED_START[k]) for k in RunKind if k != RunKind.DEPLOY
        },
    )


# ------------------------------------------------------------------ runs


@router.post("/projects/{project_id}/runs", response_model=s.RunOut, status_code=201)
def create_run(
    project_id: str,
    body: s.RunCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(require("editor")),
):
    project = get_project(project_id, session, actor)
    try:
        run = start_run(session, settings, project, actor, RunKind(body.kind), body.feedback)
    except ServiceError as exc:
        session.rollback()
        _raise(exc)
    session.commit()
    return run


@router.get("/projects/{project_id}/runs", response_model=list[s.RunOut])
def list_runs(
    project_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    project = get_project(project_id, session, actor)
    return session.scalars(
        select(Run).where(Run.project_id == project.id).order_by(Run.created_at.desc())
    ).all()


@router.get("/runs/{run_id}", response_model=s.RunDetail)
def read_run(run_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))):
    return get_run(run_id, session, actor)


@router.get("/runs/{run_id}/events", response_model=list[s.EventOut])
def run_events(
    run_id: str,
    after: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
):
    run = get_run(run_id, session, actor)
    return session.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run.id, RunEvent.id > after)
        .order_by(RunEvent.id)
        .limit(limit)
    ).all()


# ------------------------------------------------------------------ artifacts & files


@router.get("/projects/{project_id}/artifacts", response_model=list[s.ArtifactMeta])
def list_artifacts(
    project_id: str,
    kind: str | None = None,
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
):
    project = get_project(project_id, session, actor)
    q = select(Artifact).where(Artifact.project_id == project.id)
    if kind:
        q = q.where(Artifact.kind == kind)
    return session.scalars(q.order_by(Artifact.created_at.desc())).all()


@router.get("/projects/{project_id}/artifacts/latest/{kind}", response_model=s.ArtifactOut)
def latest_artifact_route(
    project_id: str,
    kind: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
):
    project = get_project(project_id, session, actor)
    art = latest_artifact(session, project.id, kind)
    if art is None:
        raise HTTPException(404, f"no {kind} artifact yet")
    return art


@router.get("/artifacts/{artifact_id}", response_model=s.ArtifactOut)
def read_artifact(
    artifact_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    art = session.scalars(
        select(Artifact).join(Project).where(Artifact.id == artifact_id, Project.owner_id == actor.user_id)
    ).first()
    if art is None:
        raise HTTPException(404, "artifact not found")
    return art


def _snapshot(session: Session, project: Project) -> dict[str, str]:
    snap = latest_artifact(session, project.id, "workspace_snapshot")
    return json.loads(snap.content)["files"] if snap else {}


@router.get("/projects/{project_id}/files", response_model=list[s.FileEntry])
def list_files(
    project_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    files = _snapshot(session, get_project(project_id, session, actor))
    return [s.FileEntry(path=p, size=len(c.encode())) for p, c in sorted(files.items())]


@router.get("/projects/{project_id}/files/content")
def file_content(
    project_id: str,
    path: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
) -> dict[str, str]:
    files = _snapshot(session, get_project(project_id, session, actor))
    if path not in files:
        raise HTTPException(404, "file not found")
    return {"path": path, "content": files[path]}


@router.get("/projects/{project_id}/validations", response_model=list[s.ValidationOut])
def list_validations(
    project_id: str,
    run_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
):
    project = get_project(project_id, session, actor)
    if run_id is None:
        last = session.scalars(
            select(Run)
            .where(Run.project_id == project.id, Run.kind == "build")
            .order_by(Run.created_at.desc())
            .limit(1)
        ).first()
        if last is None:
            return []
        run_id = last.id
    return session.scalars(
        select(ValidationResult).where(
            ValidationResult.project_id == project.id, ValidationResult.run_id == run_id
        )
    ).all()


# ------------------------------------------------------------------ approvals


@router.get("/projects/{project_id}/approvals", response_model=list[s.ApprovalOut])
def list_approvals(
    project_id: str, session: Session = Depends(get_session), actor: Actor = Depends(require("viewer"))
):
    project = get_project(project_id, session, actor)
    return session.scalars(
        select(Approval).where(Approval.project_id == project.id).order_by(Approval.created_at.desc())
    ).all()


@router.post("/projects/{project_id}/approvals", response_model=s.ApprovalOut, status_code=201)
def create_approval(
    project_id: str,
    body: s.ApprovalCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: Actor = Depends(current_actor),
):
    project = get_project(project_id, session, actor)
    try:
        appr, _ = approve(
            session,
            settings,
            project,
            actor,
            kind=body.kind,
            expected_hash=body.expected_hash,
            comment=body.comment,
        )
    except ServiceError as exc:
        session.rollback()
        _raise(exc)
    session.commit()
    return appr


# ------------------------------------------------------------------ audit


@router.get("/audit", response_model=list[s.AuditOut])
def list_audit(
    project_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Actor = Depends(require("viewer")),
):
    q = select(AuditLog).where(AuditLog.actor == actor.user_id)
    if project_id:
        get_project(project_id, session, actor)
        q = select(AuditLog).where(AuditLog.project_id == project_id)
    return session.scalars(q.order_by(AuditLog.id.desc()).limit(500)).all()

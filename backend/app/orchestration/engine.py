"""Deterministic run executor.

For each step of a run definition the engine: checks the capability's permissions against what the run
grants, loads fresh inputs from the database, executes the capability in a worker thread with a timeout,
validates every artifact against its schema, persists results, and retries up to the step's limit.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.demo_provider import DemoProvider
from app.ai.gateway import AIGateway, GatewayError
from app.ai.provider import LLMProvider
from app.ai.schemas import ArchitectureSpec, RequirementsSpec, SecurityReview, TaskPlan
from app.config import Settings
from app.deploy.schemas import DeployPlan
from app.deploy.targets import DeployTarget, build_deploy_target
from app.domain.states import SUCCESS_STATUS, ProjectStatus, RunKind
from app.executor.sandbox import Sandbox, build_sandbox
from app.models import Project, Run, RunStep, ValidationResult, utcnow
from app.orchestration.capabilities import CAPABILITIES
from app.orchestration.context import StepContext, StepFailed, StepOutput
from app.orchestration.definitions import RUN_DEFINITIONS
from app.security.redaction import redact
from app.services import (
    active_approval,
    add_artifact,
    approval_state,
    artifact_json,
    blocking_issues,
    emit,
    latest_artifact,
)
from app.workspace.manager import WorkspaceManager

log = logging.getLogger("toolkit.engine")

ARTIFACT_SCHEMAS: dict[str, type[BaseModel]] = {
    "requirements": RequirementsSpec,
    "architecture": ArchitectureSpec,
    "task_plan": TaskPlan,
    "security_review": SecurityReview,
    "deploy_plan": DeployPlan,
}


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings)
    return DemoProvider()


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        provider: LLMProvider | None = None,
        sandbox: Sandbox | None = None,
        deploy_target: DeployTarget | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self._provider = provider
        self.sandbox = sandbox or build_sandbox(settings)
        self.deploy_target = deploy_target or build_deploy_target(settings)
        self.workspace = WorkspaceManager(
            settings.workspaces_dir, settings.max_files_per_workspace, settings.max_file_bytes
        )

    @property
    def gateway(self) -> AIGateway:
        if self._provider is None:
            self._provider = build_provider(self.settings)
        return AIGateway(self._provider, self.settings)

    # ------------------------------------------------------------------ inputs

    def _load_inputs(self, session: Session, project: Project, run: Run) -> dict[str, Any]:
        pid = project.id
        snap = latest_artifact(session, pid, "workspace_snapshot")
        req_art = latest_artifact(session, pid, "requirements")
        inputs: dict[str, Any] = {
            "prompt": project.prompt,
            "feedback": (run.input or {}).get("feedback", ""),
            "requirements": artifact_json(session, pid, "requirements"),
            "architecture": artifact_json(session, pid, "architecture"),
            "task_plan": artifact_json(session, pid, "task_plan"),
            "planning_simulated": bool(req_art and req_art.simulated),
            "snapshot_files": json.loads(snap.content)["files"] if snap else None,
            "snapshot_sha": snap.sha256 if snap else None,
            "deploy_plan": artifact_json(session, pid, "deploy_plan"),
            "security_review": artifact_json(session, pid, "security_review"),
        }
        build_run = session.scalars(
            select(Run)
            .where(Run.project_id == pid, Run.kind == RunKind.BUILD.value, Run.status == "succeeded")
            .order_by(Run.created_at.desc())
            .limit(1)
        ).first()
        if build_run is not None:
            inputs["build_run_id"] = build_run.id
            inputs["build_validations"] = [
                {"check_id": v.check_id, "category": v.category, "status": v.status, "summary": v.summary}
                for v in session.scalars(
                    select(ValidationResult).where(ValidationResult.run_id == build_run.id)
                )
            ]
        if run.kind == RunKind.DEPLOY.value:
            inputs["deploy_approval_check"] = approval_state(session, project, "deploy")
            inputs["blocking_issues"] = blocking_issues(session, project)
        return inputs

    # ------------------------------------------------------------------ persistence

    def _persist(self, session: Session, project: Project, run: Run, step: RunStep, out: StepOutput) -> None:
        for art in out.artifacts:
            schema = ARTIFACT_SCHEMAS.get(art.kind)
            if schema is not None:
                validated = schema.model_validate(art.content)  # raises ValidationError
                content: Any = validated.model_dump()
            else:
                content = art.content
            a = add_artifact(
                session,
                self.settings,
                project,
                run,
                kind=art.kind,
                name=art.name,
                content=content,
                content_type=art.content_type,
                simulated=art.simulated,
            )
            emit(
                session,
                run,
                f"artifact {art.kind} v{a.version} stored",
                step=step.name,
                artifact_id=a.id,
                simulated=art.simulated,
            )
        for o in out.validations:
            session.add(
                ValidationResult(
                    project_id=project.id,
                    run_id=run.id,
                    check_id=o.check_id,
                    category=o.category,
                    status=o.status,
                    summary=redact(o.summary)[:2000],
                    log=redact(o.log)[:200_000],
                    tool=o.tool,
                    executed=o.executed,
                    duration_ms=o.duration_ms,
                )
            )
        step.output_summary = json.loads(redact(json.dumps(out.summary, default=str)))

    # ------------------------------------------------------------------ execution

    def execute(self, run_id: str) -> str:
        with self.session_factory() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise ValueError(f"run {run_id} not found")
            project = session.get(Project, run.project_id)
            assert project is not None
            kind = RunKind(run.kind)
            definition = RUN_DEFINITIONS[kind]
            if run.status not in ("queued", "running"):
                return run.status
            run.status = "running"
            run.started_at = run.started_at or utcnow()
            emit(session, run, f"{kind.value} run started")
            session.commit()

            state: dict[str, Any] = {}
            failed = False
            for step_def, step in zip(definition.steps, run.steps, strict=True):
                if failed:
                    step.status = "skipped"
                    continue
                cap = CAPABILITIES[step_def.capability]
                missing = cap.permissions - definition.permissions
                if missing:
                    failed = True
                    self._fail_step(
                        session, run, step, f"capability requires ungranted permissions {sorted(missing)}"
                    )
                    continue
                if not self._run_step(session, project, run, step, cap, state):
                    failed = True
            if failed:
                run.status = "failed"
                run.error = next((s.error for s in run.steps if s.status == "failed"), "run failed")
                project.status = ProjectStatus.FAILED.value
                project.failed_stage = kind.value
                emit(session, run, f"{kind.value} run failed: {run.error}", level="error")
            else:
                run.status = "succeeded"
                project.status = SUCCESS_STATUS[kind].value
                if kind == RunKind.DEPLOY:
                    appr = active_approval(session, project.id, "deploy")
                    if appr is not None:
                        appr.status = "consumed"  # single use
                emit(session, run, f"{kind.value} run succeeded")
            run.finished_at = utcnow()
            run.locked_by = None
            session.commit()
            return run.status

    def _fail_step(self, session: Session, run: Run, step: RunStep, message: str) -> None:
        step.status = "failed"
        step.error = redact(message)[:4000]
        step.finished_at = utcnow()
        emit(session, run, f"step {step.name} failed: {message}", level="error", step=step.name)
        session.commit()

    def _run_step(self, session: Session, project: Project, run: Run, step: RunStep, cap, state) -> bool:
        while step.attempts < step.max_attempts:
            step.attempts += 1
            step.status = "running"
            step.started_at = utcnow()
            step.error = None
            emit(
                session,
                run,
                f"step {step.name} started (attempt {step.attempts}/{step.max_attempts})",
                step=step.name,
            )
            session.commit()

            ctx = StepContext(
                project_id=project.id,
                run_id=run.id,
                run_kind=run.kind,
                settings=self.settings,
                inputs=self._load_inputs(session, project, run),
                state=dict(state),
                granted=cap.permissions,
                _gateway=self.gateway if "llm" in cap.permissions else None,
                _workspace=self.workspace
                if cap.permissions & {"workspace:read", "workspace:write"}
                else None,
                _sandbox=self.sandbox if "sandbox:exec" in cap.permissions else None,
                _deploy_target=self.deploy_target if "deploy:execute" in cap.permissions else None,
            )
            pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"step-{step.name}"
            )
            error: str | None = None
            try:
                future = pool.submit(cap.fn, ctx)
                out: StepOutput = future.result(timeout=step.timeout_seconds)
                for level, message, data in ctx.drain_events():
                    emit(session, run, message, level=level, step=step.name, **data)
                self._persist(session, project, run, step, out)
                step.status = "succeeded"
                step.finished_at = utcnow()
                state.update(out.state)
                session.commit()
                return True
            except concurrent.futures.TimeoutError:
                error = f"timed out after {step.timeout_seconds}s"
            except (StepFailed, GatewayError) as exc:
                error = str(exc)
            except ValidationError as exc:
                error = (
                    f"output failed schema validation: {exc.error_count()} error(s): {exc.errors()[0]['msg']}"
                )
            except Exception as exc:  # unexpected bug: record, never leak a traceback to users
                log.exception("step %s crashed", step.name)
                error = f"internal error ({type(exc).__name__})"
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            session.rollback()
            for level, message, data in ctx.drain_events():
                emit(session, run, message, level=level, step=step.name, **data)
            step.error = redact(error or "unknown error")[:4000]
            emit(
                session,
                run,
                f"step {step.name} attempt {step.attempts} failed: {step.error}",
                level="error",
                step=step.name,
            )
            session.commit()
        step.status = "failed"
        step.finished_at = utcnow()
        session.commit()
        return False

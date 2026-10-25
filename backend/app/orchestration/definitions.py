"""Deterministic run definitions: which steps run, in which order, with which limits and permissions.

Permissions:
  llm               call the AI gateway
  artifacts:read    read approved artifacts
  workspace:write   materialise files into the project workspace
  workspace:read    read the project workspace
  sandbox:exec      run registry tools inside the sandbox
  deploy:execute    call the deploy target (only granted to deploy runs)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.states import RunKind


@dataclass(frozen=True)
class StepDef:
    name: str
    capability: str
    timeout_seconds: int
    max_attempts: int = 1


@dataclass(frozen=True)
class RunDef:
    kind: RunKind
    permissions: frozenset[str]
    steps: tuple[StepDef, ...]


RUN_DEFINITIONS: dict[RunKind, RunDef] = {
    RunKind.REQUIREMENTS: RunDef(
        RunKind.REQUIREMENTS,
        frozenset({"llm"}),
        (StepDef("analyze_requirements", "requirements_analyst", 420, 2),),
    ),
    RunKind.PLAN: RunDef(
        RunKind.PLAN,
        frozenset({"llm", "artifacts:read"}),
        (
            StepDef("design_architecture", "architect", 420, 2),
            StepDef("plan_tasks", "planner", 420, 2),
            StepDef("write_documentation", "documentation_writer", 30),
        ),
    ),
    RunKind.BUILD: RunDef(
        RunKind.BUILD,
        frozenset({"llm", "artifacts:read", "workspace:write", "workspace:read", "sandbox:exec"}),
        (
            StepDef("generate_code", "developer", 600, 2),
            StepDef("generate_tests", "tester", 600, 2),
            StepDef("generate_infrastructure", "infra_engineer", 600, 2),
            StepDef("materialize_workspace", "workspace_writer", 60),
            StepDef("run_validations", "validator", 1500),
            StepDef("security_review", "security_reviewer", 420, 2),
        ),
    ),
    RunKind.DEPLOY_PLAN: RunDef(
        RunKind.DEPLOY_PLAN,
        frozenset({"artifacts:read", "workspace:read"}),
        (StepDef("prepare_release", "release_manager", 60),),
    ),
    RunKind.DEPLOY: RunDef(
        RunKind.DEPLOY,
        frozenset({"artifacts:read", "workspace:read", "sandbox:exec", "deploy:execute"}),
        (
            StepDef("verify_approval", "approval_gate", 30),
            StepDef("deploy", "deployer", 1800),
            StepDef("smoke_test", "smoke_tester", 300),
            StepDef("release_report", "release_reporter", 30),
        ),
    ),
}

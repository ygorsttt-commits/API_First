"""Capabilities: one function per pipeline responsibility, each with explicitly declared permissions.

A capability receives a StepContext (inputs loaded by the engine, services gated by permission) and
returns a StepOutput. It never touches the database directly; the engine validates and persists.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai.schemas import ArchitectureSpec, CodeBundle, RequirementsSpec, SecurityReview, TaskPlan
from app.deploy.schemas import DeployPlan, PlannedResource
from app.deploy.targets import DeployBlocked
from app.executor.sandbox import SandboxUnavailable
from app.executor.tools import get_tool
from app.orchestration.context import NewArtifact, StepContext, StepFailed, StepOutput
from app.validation.checks import BLOCKING_CATEGORIES, CheckOutcome, run_tool_check, run_validation_suite
from app.workspace.manager import PathPolicyError, diff_snapshots, snapshot_hash


@dataclass(frozen=True)
class Capability:
    name: str
    permissions: frozenset[str]
    fn: Callable[[StepContext], StepOutput]
    description: str


def _feedback(ctx: StepContext) -> dict[str, str]:
    fb = (ctx.inputs.get("feedback") or "").strip()
    return {"review_feedback": fb} if fb else {}


def _require(ctx: StepContext, key: str) -> dict[str, Any]:
    value = ctx.inputs.get(key)
    if not value:
        raise StepFailed(f"required input '{key}' is missing")
    return value  # type: ignore[no-any-return]


# ------------------------------------------------------------------ analysis & planning


def requirements_analyst(ctx: StepContext) -> StepOutput:
    context = {}
    if ctx.inputs.get("feedback") and ctx.inputs.get("requirements"):
        context["previous_requirements"] = ctx.inputs["requirements"]
    res = ctx.gateway.generate(
        task="requirements_analyst",
        schema=RequirementsSpec,
        instructions=(
            "Analyse the software request below. Produce functional and non-functional requirements, "
            "explicit assumptions, testable acceptance criteria (Given/When/Then) that reference requirement "
            "ids, open questions for anything ambiguous, and what is out of scope. Do not invent business "
            "facts: when something is unknown, add an open question instead."
        ),
        untrusted={"user_prompt": ctx.inputs["prompt"], **_feedback(ctx)},
        context=context or None,
    )
    ctx.log(f"requirements produced by {res.provider} in {res.attempts} attempt(s)")
    spec = res.output
    return StepOutput(
        summary={
            "functional": len(spec.functional_requirements),
            "open_questions": len(spec.open_questions),
            "attempts": res.attempts,
            "simulated": res.simulated,
        },
        artifacts=[
            NewArtifact("requirements", "requirements.json", spec.model_dump(), simulated=res.simulated)
        ],
    )


def architect(ctx: StepContext) -> StepOutput:
    res = ctx.gateway.generate(
        task="architect",
        schema=ArchitectureSpec,
        instructions=(
            "Design the simplest architecture that satisfies the approved requirements: components, data model, "
            "API endpoints, key decisions with rationale and alternatives, risks with mitigations, and the "
            "deployment approach for an AWS dev environment. Prefer a modular monolith."
        ),
        untrusted=_feedback(ctx),
        context={"requirements": _require(ctx, "requirements")},
    )
    a = res.output
    return StepOutput(
        summary={
            "components": len(a.components),
            "endpoints": len(a.api_endpoints),
            "simulated": res.simulated,
        },
        artifacts=[NewArtifact("architecture", "architecture.json", a.model_dump(), simulated=res.simulated)],
    )


def planner(ctx: StepContext) -> StepOutput:
    res = ctx.gateway.generate(
        task="planner",
        schema=TaskPlan,
        instructions=(
            "Break the work into a small dependency-ordered task plan. Each task names the capability that owns "
            "it and the acceptance criteria ids it satisfies. Dependencies must form a DAG."
        ),
        untrusted=_feedback(ctx),
        context={
            "requirements": _require(ctx, "requirements"),
            "architecture": _require(ctx, "architecture"),
        },
    )
    return StepOutput(
        summary={"tasks": len(res.output.tasks), "simulated": res.simulated},
        artifacts=[
            NewArtifact("task_plan", "task_plan.json", res.output.model_dump(), simulated=res.simulated)
        ],
    )


def documentation_writer(ctx: StepContext) -> StepOutput:
    req = RequirementsSpec.model_validate(_require(ctx, "requirements"))
    arch = ArchitectureSpec.model_validate(_require(ctx, "architecture"))
    plan = TaskPlan.model_validate(_require(ctx, "task_plan"))
    lines = [f"# {req.project_name}", "", req.summary, "", "## Functional requirements", ""]
    lines += [f"- **{r.id}** ({r.priority}) {r.title}: {r.description}" for r in req.functional_requirements]
    lines += ["", "## Non-functional requirements", ""]
    lines += [
        f"- **{r.id}** ({r.priority}) {r.title}: {r.description}" for r in req.non_functional_requirements
    ]
    lines += ["", "## Acceptance criteria", ""]
    lines += [
        f"- **{c.id}** [{c.requirement_id}] Given {c.given}, when {c.when}, then {c.then}."
        for c in req.acceptance_criteria
    ]
    lines += ["", "## Assumptions", ""] + [f"- {a}" for a in req.assumptions]
    lines += ["", "## Open questions", ""] + [f"- {q}" for q in req.open_questions]
    lines += ["", "## Architecture", "", arch.overview, "", f"Style: {arch.style}", "", "### Components", ""]
    lines += [f"- **{c.name}** ({c.technology}): {c.responsibility}" for c in arch.components]
    lines += ["", "### API", ""] + [f"- `{e.method} {e.path}` {e.description}" for e in arch.api_endpoints]
    lines += ["", "### Decisions", ""]
    lines += [
        f"- **{d.title}**: {d.decision}. {d.rationale} (alternatives: {', '.join(d.alternatives) or '-'})"
        for d in arch.decisions
    ]
    lines += ["", "### Risks", ""] + [
        f"- [{r.severity}] {r.description} -> {r.mitigation}" for r in arch.risks
    ]
    lines += ["", "## Task plan", ""]
    lines += [
        f"- **{t.id}** {t.title} ({t.capability}; depends on {', '.join(t.depends_on) or 'nothing'})"
        for t in plan.tasks
    ]
    simulated = bool(ctx.inputs.get("planning_simulated"))
    return StepOutput(
        summary={"sections": 8},
        artifacts=[
            NewArtifact(
                "documentation", "PROJECT.md", "\n".join(lines) + "\n", "text/markdown", simulated=simulated
            )
        ],
    )


# ------------------------------------------------------------------ code generation

_PATH_SCOPES = {
    "developer": (
        "app/",
        "requirements.txt",
        "requirements-dev.txt",
        "README.md",
        "ruff.toml",
        "pyproject.toml",
        ".gitignore",
    ),
    "tester": ("tests/", "conftest.py", "pytest.ini"),
    "infra_engineer": ("infra/", ".github/workflows/", "Dockerfile", ".dockerignore"),
}
_CODEGEN_INSTRUCTIONS = {
    "developer": "Write the application source code for the approved architecture. Python 3.12, FastAPI, typed, "
    "small modules, input validation, GET /health. Pin dependencies with ==. Only write under: ",
    "tester": "Write pytest tests that exercise every endpoint and acceptance criterion using FastAPI's TestClient. "
    "Tests must not use the network. Only write under: ",
    "infra_engineer": "Write a Dockerfile (non-root), Terraform for an AWS dev environment (remote S3 state, no "
    "hard-coded account/region, least-privilege IAM, GitHub OIDC deploy role), and GitHub Actions "
    "workflows for CI (lint, types, tests, dependency audit, secret scan, terraform fmt/validate, "
    "IaC scan) and a manual dev deploy gated by a protected environment. Only write under: ",
}


def _codegen(role: str) -> Callable[[StepContext], StepOutput]:
    def run(ctx: StepContext) -> StepOutput:
        ws = ctx.require_write()
        res = ctx.gateway.generate(
            task=role,
            schema=CodeBundle,
            instructions=_CODEGEN_INSTRUCTIONS[role] + ", ".join(_PATH_SCOPES[role]),
            untrusted=_feedback(ctx),
            context={
                "requirements": _require(ctx, "requirements"),
                "architecture": _require(ctx, "architecture"),
                "task_plan": _require(ctx, "task_plan"),
            },
        )
        try:
            files = ws.validate_files({f.path: f.content for f in res.output.files}, _PATH_SCOPES[role])
        except PathPolicyError as exc:
            raise StepFailed(f"generated file rejected by path policy: {exc}") from None
        ctx.log(f"{role} produced {len(files)} file(s)", files=sorted(files))
        return StepOutput(
            summary={"files": len(files), "simulated": res.simulated},
            state={f"bundle:{role}": files, "codegen_simulated": res.simulated},
        )

    return run


def workspace_writer(ctx: StepContext) -> StepOutput:
    ws = ctx.require_write()
    files: dict[str, str] = {}
    for role in ("developer", "tester", "infra_engineer"):
        bundle = ctx.state.get(f"bundle:{role}")
        if bundle is None:
            raise StepFailed(f"missing output of {role}")
        overlap = set(files) & set(bundle)
        if overlap:
            raise StepFailed(
                f"{role} tried to overwrite files owned by another capability: {sorted(overlap)}"
            )
        files.update(bundle)
    try:
        path = ws.replace_contents(ctx.project_id, files)
    except PathPolicyError as exc:
        raise StepFailed(str(exc)) from None
    previous = ctx.inputs.get("snapshot_files") or {}
    changes = diff_snapshots(previous, files)
    simulated = bool(ctx.state.get("codegen_simulated"))
    counts = Counter(c.change for c in changes)
    ctx.log(f"workspace written: {len(files)} files ({dict(counts)})")
    return StepOutput(
        summary={"files": len(files), "changes": dict(counts), "snapshot": snapshot_hash(files)[:12]},
        artifacts=[
            NewArtifact("workspace_snapshot", "workspace.json", {"files": files}, simulated=simulated),
            NewArtifact(
                "diff",
                "changes.json",
                [{"path": c.path, "change": c.change, "diff": c.diff} for c in changes],
                simulated=simulated,
            ),
        ],
        state={"workspace_path": str(path), "files": files},
    )


# ------------------------------------------------------------------ validation & review


def validator(ctx: StepContext) -> StepOutput:
    files: dict[str, str] = ctx.state.get("files") or {}
    path = ctx.state.get("workspace_path")
    if not files or not path:
        raise StepFailed("workspace was not materialised")
    outcomes = run_validation_suite(Path(path), files, ctx.sandbox)
    counts = Counter(o.status for o in outcomes)
    for o in outcomes:
        ctx.log(
            f"[{o.status}] {o.check_id}: {o.summary}",
            level="warning" if o.status in ("failed", "error") else "info",
        )
    report = {
        "counts": dict(counts),
        "checks": [
            {
                "check_id": o.check_id,
                "category": o.category,
                "status": o.status,
                "summary": o.summary,
                "executed": o.executed,
                "tool": o.tool,
                "duration_ms": o.duration_ms,
            }
            for o in outcomes
        ],
    }
    return StepOutput(
        summary={"counts": dict(counts)},
        validations=outcomes,
        artifacts=[NewArtifact("validation_report", "validation_report.json", report, simulated=False)],
        state={"validation_results": report["checks"]},
    )


def security_reviewer(ctx: StepContext) -> StepOutput:
    checks = ctx.state.get("validation_results") or []
    res = ctx.gateway.generate(
        task="security_reviewer",
        schema=SecurityReview,
        instructions=(
            "Review the validation results of the generated project and the approved architecture. Summarise the "
            "security posture, list concrete risks with severity and mitigation, and recommend proceed, "
            "proceed_with_caution or block. Failed secret, SAST or IaC checks must lead to block. Skipped checks "
            "are not evidence of safety."
        ),
        context={"validation_results": checks, "architecture": _require(ctx, "architecture")},
    )
    return StepOutput(
        summary={
            "recommendation": res.output.recommendation,
            "risks": len(res.output.risks),
            "simulated": res.simulated,
        },
        artifacts=[
            NewArtifact(
                "security_review", "security_review.json", res.output.model_dump(), simulated=res.simulated
            )
        ],
    )


# ------------------------------------------------------------------ release

_RESOURCE = re.compile(r'^resource\s+"([A-Za-z0-9_]+)"\s+"([A-Za-z0-9_\-]+)"', re.M)


def release_manager(ctx: StepContext) -> StepOutput:
    files: dict[str, str] = _require(ctx, "snapshot_files")
    checks: list[dict[str, Any]] = ctx.inputs.get("build_validations") or []
    resources = [
        PlannedResource(address=f"{m.group(1)}.{m.group(2)}", file=p)
        for p, c in sorted(files.items())
        if p.endswith(".tf")
        for m in _RESOURCE.finditer(c)
    ]
    counts = Counter(c["status"] for c in checks)
    blocking = [
        f"check '{c['check_id']}' {c['status']}: {c['summary'][:200]}"
        for c in checks
        if c["status"] in ("failed", "error") and c["category"] in BLOCKING_CATEGORIES
    ]
    if not checks:
        blocking.append("no validation results for the current build")
    review = ctx.inputs.get("security_review") or {}
    if review.get("recommendation") == "block":
        blocking.append("security review recommends blocking the release")
    warnings = [
        f"check '{c['check_id']}' skipped: {c['summary'][:200]}" for c in checks if c["status"] == "skipped"
    ]
    target = ctx.settings.deploy_target
    simulated = target == "simulated"
    if simulated:
        warnings.insert(0, "DEPLOY_TARGET=simulated: approving will NOT create any cloud resource.")
    plan = DeployPlan(
        environment="dev",
        target=target,
        simulated=simulated,
        region=ctx.settings.aws_region,
        workspace_sha256=_require(ctx, "snapshot_sha"),
        build_run_id=ctx.inputs.get("build_run_id") or "",
        resources=resources,
        checks=dict(counts),
        blocking_issues=blocking,
        warnings=warnings,
        estimated_cost="not estimated: no pricing integration; review resources before approving",
        required_approval_role="deployer",
        steps=[
            "Re-verify the deploy approval against the current plan hash",
            "Simulated: record the resources a terraform apply would manage"
            if simulated
            else "terraform plan with short-lived OIDC credentials, then apply the approved plan",
            "Run the smoke test (GET /health) against the built application",
            "Publish the release report with rollback instructions",
        ],
        rollback_instructions=[
            "Re-run the deploy-dev workflow from the previous good commit (immutable image tags make this exact).",
            "Or point App Runner back to the previous image tag: terraform apply -var image_tag=<previous-sha>.",
            "If infrastructure changes caused the issue, revert the Terraform commit and apply the reviewed plan.",
            "Nothing to roll back for a simulated deployment.",
        ],
    )
    ctx.log(f"deploy plan: {len(resources)} resources, {len(blocking)} blocking issue(s)")
    return StepOutput(
        summary={"resources": len(resources), "blocking_issues": len(blocking), "simulated": simulated},
        artifacts=[NewArtifact("deploy_plan", "deploy_plan.json", plan.model_dump(), simulated=simulated)],
    )


def approval_gate(ctx: StepContext) -> StepOutput:
    ok, reason = ctx.inputs.get("deploy_approval_check", (False, "not evaluated"))
    if not ok:
        raise StepFailed(f"deploy approval is not valid: {reason}")
    issues = ctx.inputs.get("blocking_issues") or []
    if issues:
        raise StepFailed("deployment blocked: " + "; ".join(issues))
    ctx.log("deploy approval verified against current content hash")
    return StepOutput(summary={"approval": "valid"})


def deployer(ctx: StepContext) -> StepOutput:
    plan = DeployPlan.model_validate(_require(ctx, "deploy_plan"))
    target = ctx.deploy_target
    if plan.target != target.name:
        raise StepFailed(f"deploy plan targets '{plan.target}' but the configured target is '{target.name}'")
    try:
        outcome = target.deploy(plan)
    except DeployBlocked as exc:
        raise StepFailed(str(exc)) from None
    if outcome.status != "succeeded":
        raise StepFailed(outcome.summary)
    ctx.log(outcome.summary)
    result = {
        "target": target.name,
        "simulated": outcome.simulated,
        "summary": outcome.summary,
        "details": outcome.details,
        "endpoint": outcome.endpoint,
    }
    return StepOutput(
        summary={"simulated": outcome.simulated},
        artifacts=[NewArtifact("deploy_result", "deploy_result.json", result, simulated=outcome.simulated)],
        state={"deploy_result": result},
    )


def smoke_tester(ctx: StepContext) -> StepOutput:
    files: dict[str, str] = _require(ctx, "snapshot_files")
    ws = ctx.workspace
    on_disk = ws.read_all(ctx.project_id)
    if snapshot_hash(on_disk) != snapshot_hash(files):
        raise StepFailed("workspace on disk does not match the approved snapshot")
    try:
        outcome = run_tool_check("smoke-health", ws.path_for(ctx.project_id), files, ctx.sandbox)
    except SandboxUnavailable as exc:  # pragma: no cover - run_tool_check already maps this
        outcome = CheckOutcome("smoke-health", "smoke", "smoke-health", "skipped", str(exc), "", False)
    tool = get_tool("smoke-health")
    outcome.summary = f"{tool.description}: {outcome.summary}"
    ctx.log(f"[{outcome.status}] smoke test: {outcome.summary}")
    if outcome.status in ("failed", "error"):
        raise StepFailed(f"smoke test {outcome.status}: {outcome.summary}")
    return StepOutput(
        summary={"smoke": outcome.status},
        validations=[outcome],
        state={"smoke": {"status": outcome.status, "summary": outcome.summary, "executed": outcome.executed}},
    )


def release_reporter(ctx: StepContext) -> StepOutput:
    plan = DeployPlan.model_validate(_require(ctx, "deploy_plan"))
    result = ctx.state.get("deploy_result") or {}
    smoke = ctx.state.get("smoke") or {}
    simulated = bool(result.get("simulated", True))
    lines = [
        "# Release report — dev",
        "",
        "> **SIMULATED DEPLOYMENT** — no cloud resources were created or changed."
        if simulated
        else "> Real deployment to the dev environment.",
        "",
        f"- Target: `{plan.target}`",
        f"- Workspace snapshot: `{plan.workspace_sha256[:16]}`",
        f"- Deploy outcome: {result.get('summary', 'n/a')}",
        f"- Smoke test: **{smoke.get('status', 'n/a')}** — {smoke.get('summary', '')}",
        f"- Endpoint: {result.get('endpoint') or 'none (simulated)'}",
        "",
        "## Resources",
        "",
        *[f"- `{r.address}` ({r.file})" for r in plan.resources],
        "",
        "## Rollback",
        "",
        *[f"1. {s}" for s in plan.rollback_instructions],
        "",
    ]
    return StepOutput(
        summary={"simulated": simulated},
        artifacts=[
            NewArtifact(
                "release_report", "RELEASE.md", "\n".join(lines), "text/markdown", simulated=simulated
            )
        ],
    )


CAPABILITIES: dict[str, Capability] = {
    c.name: c
    for c in [
        Capability("requirements_analyst", frozenset({"llm"}), requirements_analyst, "Requirements analysis"),
        Capability("architect", frozenset({"llm", "artifacts:read"}), architect, "Architecture design"),
        Capability("planner", frozenset({"llm", "artifacts:read"}), planner, "Task planning"),
        Capability(
            "documentation_writer", frozenset({"artifacts:read"}), documentation_writer, "Documentation"
        ),
        Capability(
            "developer",
            frozenset({"llm", "artifacts:read", "workspace:write"}),
            _codegen("developer"),
            "Application code generation",
        ),
        Capability(
            "tester",
            frozenset({"llm", "artifacts:read", "workspace:write"}),
            _codegen("tester"),
            "Test generation",
        ),
        Capability(
            "infra_engineer",
            frozenset({"llm", "artifacts:read", "workspace:write"}),
            _codegen("infra_engineer"),
            "Terraform and CI/CD generation",
        ),
        Capability(
            "workspace_writer", frozenset({"workspace:write"}), workspace_writer, "Workspace materialisation"
        ),
        Capability(
            "validator", frozenset({"workspace:read", "sandbox:exec"}), validator, "DevSecOps validations"
        ),
        Capability(
            "security_reviewer", frozenset({"llm", "artifacts:read"}), security_reviewer, "Security review"
        ),
        Capability(
            "release_manager",
            frozenset({"artifacts:read", "workspace:read"}),
            release_manager,
            "Deploy plan preparation",
        ),
        Capability("approval_gate", frozenset({"artifacts:read"}), approval_gate, "Approval verification"),
        Capability("deployer", frozenset({"artifacts:read", "deploy:execute"}), deployer, "Deployment"),
        Capability(
            "smoke_tester", frozenset({"workspace:read", "sandbox:exec"}), smoke_tester, "Smoke tests"
        ),
        Capability("release_reporter", frozenset({"artifacts:read"}), release_reporter, "Release report"),
    ]
}

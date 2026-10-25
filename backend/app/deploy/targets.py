"""Deploy targets. Every target is only ever invoked by a deploy run, which requires a valid,
hash-bound deploy approval from a user with the `deployer` role."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import Settings
from app.deploy.schemas import DeployPlan


class DeployBlocked(Exception):
    pass


@dataclass
class DeployOutcome:
    simulated: bool
    status: str  # succeeded | failed
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    endpoint: str | None = None


class DeployTarget(Protocol):
    name: str
    simulated: bool

    def deploy(self, plan: DeployPlan) -> DeployOutcome: ...


class SimulatedDeployTarget:
    """Demo target: touches no cloud account and creates no billable resource."""

    name = "simulated"
    simulated = True

    def deploy(self, plan: DeployPlan) -> DeployOutcome:
        return DeployOutcome(
            simulated=True,
            status="succeeded",
            summary=f"SIMULATED: no cloud call was made. A real apply would manage {len(plan.resources)} "
            "Terraform resources in the dev environment.",
            details={"would_manage": [r.address for r in plan.resources]},
            endpoint=None,
        )


class AwsTerraformDeployTarget:
    """Real AWS deploy target.

    Intended flow (not enabled in this build): run `terraform plan` inside the sandbox with
    short-lived credentials obtained by assuming AWS_DEPLOY_ROLE_ARN through OIDC, persist and show the
    plan, require a deploy approval bound to the plan hash, then `terraform apply` that exact plan.
    Until that is implemented and reviewed, this target refuses to run.
    """

    name = "aws"
    simulated = False

    def __init__(self, settings: Settings):
        self.settings = settings

    def deploy(self, plan: DeployPlan) -> DeployOutcome:
        missing = [
            n
            for n, v in (
                ("AWS_REGION", self.settings.aws_region),
                ("AWS_DEPLOY_ROLE_ARN", self.settings.aws_deploy_role_arn),
            )
            if not v
        ]
        if missing:
            raise DeployBlocked(f"AWS deploy target is not configured: missing {', '.join(missing)}")
        raise DeployBlocked(
            "AWS deploy execution is not enabled in this build. Use the generated deploy-dev GitHub "
            "workflow (plan + protected-environment approval + apply) or keep DEPLOY_TARGET=simulated."
        )


def build_deploy_target(settings: Settings) -> DeployTarget:
    if settings.deploy_target == "aws":
        return AwsTerraformDeployTarget(settings)
    return SimulatedDeployTarget()

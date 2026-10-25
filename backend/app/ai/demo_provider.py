"""Deterministic provider for demo mode. Never calls a network service.

Every output it produces is flagged `simulated` by the gateway so the UI can label it. Generated
*code* is still real code: the validation stage executes real tools on it and reports real results.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, TypeVar

from pydantic import BaseModel

from app.ai import demo_codegen as cg
from app.ai.provider import ProviderError, StructuredRequest
from app.ai.schemas import (
    AcceptanceCriterion,
    ArchitectureSpec,
    CodeBundle,
    Component,
    Decision,
    Endpoint,
    Entity,
    EntityField,
    GeneratedFile,
    PlanTask,
    Requirement,
    RequirementsSpec,
    Risk,
    SecurityReview,
    TaskPlan,
)

T = TypeVar("T", bound=BaseModel)

# keyword (accent-free, lowercase) -> (Entity name, [(field, type, required)], product name)
_LEXICON: list[tuple[tuple[str, ...], str, list[tuple[str, str, bool]], str]] = [
    (
        ("tarefa", "task", "todo", "afazer"),
        "Task",
        [("title", "string", True), ("description", "text", False), ("done", "boolean", False)],
        "Task Manager",
    ),
    (
        ("produto", "product", "estoque", "inventory", "inventario"),
        "Product",
        [("name", "string", True), ("price", "number", True), ("quantity", "integer", True)],
        "Inventory Service",
    ),
    (
        ("cliente", "customer", "crm"),
        "Customer",
        [("name", "string", True), ("email", "string", True), ("phone", "string", False)],
        "Customer Registry",
    ),
    (
        ("livro", "book", "biblioteca", "library"),
        "Book",
        [("title", "string", True), ("author", "string", True), ("year", "integer", False)],
        "Library Catalog",
    ),
    (
        ("pedido", "order"),
        "Order",
        [("customer_name", "string", True), ("total", "number", True), ("status", "string", False)],
        "Order Service",
    ),
    (
        ("evento", "event", "agenda"),
        "Event",
        [("title", "string", True), ("starts_at", "datetime", True), ("location", "string", False)],
        "Event Scheduler",
    ),
    (
        ("nota", "note", "anotacao"),
        "Note",
        [("title", "string", True), ("body", "text", False)],
        "Notes Service",
    ),
]
_DEFAULT = ("Item", [("name", "string", True), ("description", "text", False)], "Item Service")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def detect_domain(text: str) -> tuple[str, list[tuple[str, str, bool]], str]:
    norm = _normalize(text)
    best: tuple[int, int] | None = None  # (position, lexicon index)
    for idx, (keywords, *_rest) in enumerate(_LEXICON):
        for kw in keywords:
            m = re.search(rf"\b{kw}", norm)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), idx)
    if best is None:
        return _DEFAULT
    _, name, fields, product = _LEXICON[best[1]]
    return name, fields, product


class DemoProvider:
    name = "demo"
    simulated = True

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> T | dict[str, Any]:
        handler = {
            "requirements_analyst": self._requirements,
            "architect": self._architecture,
            "planner": self._plan,
            "developer": self._code,
            "tester": self._tests,
            "infra_engineer": self._infra,
            "security_reviewer": self._security,
        }.get(request.task)
        if handler is None:
            raise ProviderError(f"demo provider has no handler for task '{request.task}'")
        result = handler(request)
        if not isinstance(result, schema):
            raise ProviderError(f"demo handler for {request.task} returned {type(result).__name__}")
        return result

    # ------------------------------------------------------------------ requirements
    def _requirements(self, req: StructuredRequest) -> RequirementsSpec:
        prompt = req.untrusted.get("user_prompt", "")
        feedback = req.untrusted.get("review_feedback", "")
        entity, _fields, product = detect_domain(prompt)
        plural = cg.EntitySpec(entity, ()).plural
        frs = [
            Requirement(
                id="FR-1",
                title=f"Create {entity}",
                priority="must",
                description=f"Users can create a {entity.lower()} with validated input.",
            ),
            Requirement(
                id="FR-2",
                title=f"List {plural}",
                priority="must",
                description=f"Users can list all {plural}.",
            ),
            Requirement(
                id="FR-3",
                title=f"View {entity}",
                priority="must",
                description=f"Users can fetch a single {entity.lower()} by id.",
            ),
            Requirement(
                id="FR-4",
                title=f"Update {entity}",
                priority="should",
                description=f"Users can replace the data of an existing {entity.lower()}.",
            ),
            Requirement(
                id="FR-5",
                title=f"Delete {entity}",
                priority="should",
                description=f"Users can delete a {entity.lower()}.",
            ),
            Requirement(
                id="FR-6",
                title="Health check",
                priority="must",
                description="The service exposes GET /health for monitoring and smoke tests.",
            ),
        ]
        nfrs = [
            Requirement(
                id="NFR-1",
                title="Input validation",
                priority="must",
                description="Invalid payloads are rejected with HTTP 422.",
            ),
            Requirement(
                id="NFR-2",
                title="Automated tests",
                priority="must",
                description="Every endpoint is covered by automated tests run in CI.",
            ),
            Requirement(
                id="NFR-3",
                title="Infrastructure as code",
                priority="must",
                description="The dev environment is described in Terraform and deployed via CI with approval.",
            ),
            Requirement(
                id="NFR-4",
                title="No secrets in code",
                priority="must",
                description="Credentials come from the environment or OIDC; none are committed.",
            ),
        ]
        acs = [
            AcceptanceCriterion(
                id="AC-1",
                requirement_id="FR-1",
                given="a valid payload",
                when=f"POST /{plural} is called",
                then="the API returns 201 and the new id",
            ),
            AcceptanceCriterion(
                id="AC-2",
                requirement_id="FR-2",
                given=f"existing {plural}",
                when=f"GET /{plural} is called",
                then="all of them are returned",
            ),
            AcceptanceCriterion(
                id="AC-3",
                requirement_id="FR-3",
                given="an unknown id",
                when=f"GET /{plural}/{{id}} is called",
                then="the API returns 404",
            ),
            AcceptanceCriterion(
                id="AC-4",
                requirement_id="FR-4",
                given=f"an existing {entity.lower()}",
                when=f"PUT /{plural}/{{id}} is called",
                then="the stored data is replaced",
            ),
            AcceptanceCriterion(
                id="AC-5",
                requirement_id="FR-5",
                given=f"an existing {entity.lower()}",
                when=f"DELETE /{plural}/{{id}} is called",
                then="it returns 204 and is gone",
            ),
            AcceptanceCriterion(
                id="AC-6",
                requirement_id="FR-6",
                given="the service is running",
                when="GET /health is called",
                then='it returns 200 {"status": "ok"}',
            ),
            AcceptanceCriterion(
                id="AC-7",
                requirement_id="NFR-1",
                given="a payload with an empty required field",
                when="it is submitted",
                then="the API returns 422",
            ),
        ]
        assumptions = [
            "Single-tenant service; authentication is deferred until the open question is answered.",
            "In-memory storage is acceptable for the first iteration in the dev environment.",
            "AWS is the target cloud; account, region and domain are not assumed and must be provided.",
        ]
        if feedback.strip():
            assumptions.append("Reviewer feedback considered: " + feedback.strip()[:500])
        excerpt = " ".join(prompt.split())[:240]
        return RequirementsSpec(
            project_name=product,
            summary=f'[demo analysis] REST service managing {plural}. Original request: "{excerpt}"',
            functional_requirements=frs,
            non_functional_requirements=nfrs,
            assumptions=assumptions,
            acceptance_criteria=acs,
            open_questions=[
                "Is user authentication required? If so, which identity provider?",
                "Which persistent database should replace in-memory storage?",
                "Which AWS account and region should host the dev environment?",
                "What request volume and availability target are expected?",
            ],
            out_of_scope=["Production environment", "Frontend UI for the generated service", "Billing"],
        )

    # ------------------------------------------------------------------ architecture
    def _architecture(self, req: StructuredRequest) -> ArchitectureSpec:
        reqs = req.context.get("requirements", {})
        text = " ".join(
            [reqs.get("project_name", ""), reqs.get("summary", "")]
            + [r.get("title", "") for r in reqs.get("functional_requirements", [])]
        )
        entity, fields, _ = detect_domain(text)
        spec = cg.EntitySpec(entity, ())
        p = spec.plural
        return ArchitectureSpec(
            overview=f"A single stateless Python service exposing a REST API for {p}, packaged as a container "
            "and deployed to AWS App Runner in the dev environment.",
            style="Modular monolith (single service)",
            components=[
                Component(
                    name="HTTP API", responsibility="Routing, validation, error mapping", technology="FastAPI"
                ),
                Component(
                    name="Domain models",
                    responsibility="Payload and entity schemas",
                    technology="Pydantic v2",
                ),
                Component(
                    name="Repository",
                    responsibility="Persistence abstraction (in-memory in MVP)",
                    technology="Python",
                ),
                Component(
                    name="Infrastructure",
                    responsibility="ECR, App Runner, IAM via OIDC",
                    technology="Terraform + GitHub Actions",
                ),
            ],
            data_model=[
                Entity(
                    name=entity,
                    fields=[
                        EntityField(name=n, type=t, required=r)  # type: ignore[arg-type]
                        for n, t, r in fields
                    ],
                )
            ],
            api_endpoints=[
                Endpoint(method="GET", path="/health", description="Liveness check"),
                Endpoint(method="GET", path=f"/{p}", description=f"List {p}"),
                Endpoint(method="POST", path=f"/{p}", description=f"Create {entity.lower()}"),
                Endpoint(method="GET", path=f"/{p}/{{id}}", description=f"Get {entity.lower()}"),
                Endpoint(method="PUT", path=f"/{p}/{{id}}", description=f"Replace {entity.lower()}"),
                Endpoint(method="DELETE", path=f"/{p}/{{id}}", description=f"Delete {entity.lower()}"),
            ],
            decisions=[
                Decision(
                    title="Runtime",
                    decision="Python 3.12 + FastAPI",
                    rationale="Typed, fast to build, first-class OpenAPI.",
                    alternatives=["Node.js + Fastify", "Go + chi"],
                ),
                Decision(
                    title="Hosting",
                    decision="AWS App Runner for dev",
                    rationale="Managed HTTPS container hosting without cluster management.",
                    alternatives=["ECS Fargate", "Lambda + API Gateway"],
                ),
                Decision(
                    title="CI/CD auth",
                    decision="GitHub OIDC with a scoped IAM role",
                    rationale="No long-lived AWS keys; role limited to one repo and environment.",
                    alternatives=["Static IAM user keys (rejected)"],
                ),
            ],
            risks=[
                Risk(
                    description="In-memory storage loses data on restart",
                    severity="medium",
                    mitigation="Introduce a managed database before any non-dev use.",
                ),
                Risk(
                    description="API has no authentication",
                    severity="high",
                    mitigation="Resolve the open question; add auth before exposing beyond dev.",
                ),
            ],
            deployment="Container image in ECR, App Runner service per environment, Terraform state in S3 with "
            "locking, deploy workflow gated by a protected GitHub environment.",
        )

    # ------------------------------------------------------------------ plan
    def _plan(self, req: StructuredRequest) -> TaskPlan:
        ac_ids = [c["id"] for c in req.context.get("requirements", {}).get("acceptance_criteria", [])]
        return TaskPlan(
            milestones=["Service skeleton", "Feature complete with tests", "Dev environment ready"],
            tasks=[
                PlanTask(
                    id="T-1",
                    title="Scaffold service",
                    capability="development",
                    depends_on=[],
                    description="Create the FastAPI app, models and repository.",
                    acceptance_criteria_ids=[a for a in ac_ids if a == "AC-6"],
                ),
                PlanTask(
                    id="T-2",
                    title="Implement CRUD endpoints",
                    capability="development",
                    depends_on=["T-1"],
                    description="Implement create/list/get/update/delete with validation.",
                    acceptance_criteria_ids=[a for a in ac_ids if a != "AC-6"],
                ),
                PlanTask(
                    id="T-3",
                    title="Automated tests",
                    capability="testing",
                    depends_on=["T-2"],
                    description="API tests covering every endpoint and validation errors.",
                    acceptance_criteria_ids=ac_ids,
                ),
                PlanTask(
                    id="T-4",
                    title="Security scans",
                    capability="security",
                    depends_on=["T-2"],
                    description="Secret scanning, SAST, dependency and IaC policy checks.",
                    acceptance_criteria_ids=[],
                ),
                PlanTask(
                    id="T-5",
                    title="Terraform and CI/CD",
                    capability="infrastructure",
                    depends_on=["T-1"],
                    description="Terraform for ECR/App Runner/IAM and GitHub Actions workflows.",
                    acceptance_criteria_ids=[],
                ),
                PlanTask(
                    id="T-6",
                    title="Controlled dev release",
                    capability="release",
                    depends_on=["T-3", "T-4", "T-5"],
                    description="Prepare deploy plan, obtain approval, deploy to dev and smoke test.",
                    acceptance_criteria_ids=[a for a in ac_ids if a == "AC-6"],
                ),
            ],
        )

    # ------------------------------------------------------------------ code
    def _entity(self, req: StructuredRequest) -> tuple[str, cg.EntitySpec]:
        arch = req.context.get("architecture", {})
        reqs = req.context.get("requirements", {})
        model = (arch.get("data_model") or [{}])[0]
        if not model:
            raise ProviderError("architecture has no data model")
        name = re.sub(r"[^A-Za-z0-9]", "", model["name"]) or "Item"
        fields = tuple(
            cg.FieldSpec(re.sub(r"[^a-z0-9_]", "_", f["name"].lower()), f["type"], bool(f["required"]))
            for f in model.get("fields", [])
        )
        return reqs.get("project_name", "Generated Service"), cg.EntitySpec(
            name[0].upper() + name[1:], fields
        )

    @staticmethod
    def _bundle(files: dict[str, str], purpose: str, notes: list[str]) -> CodeBundle:
        return CodeBundle(
            files=[GeneratedFile(path=p, content=c, purpose=purpose) for p, c in files.items()], notes=notes
        )

    def _code(self, req: StructuredRequest) -> CodeBundle:
        project, entity = self._entity(req)
        return self._bundle(
            cg.render_app(project, entity),
            "application",
            [f"Rendered deterministic FastAPI service for entity {entity.name}."],
        )

    def _tests(self, req: StructuredRequest) -> CodeBundle:
        _, entity = self._entity(req)
        return self._bundle(cg.render_tests(entity), "tests", ["API tests derived from the data model."])

    def _infra(self, req: StructuredRequest) -> CodeBundle:
        project, _ = self._entity(req)
        return self._bundle(
            cg.render_infra(project),
            "infrastructure",
            ["Terraform for AWS dev (App Runner) and GitHub Actions with OIDC."],
        )

    # ------------------------------------------------------------------ security
    def _security(self, req: StructuredRequest) -> SecurityReview:
        checks: list[dict[str, Any]] = req.context.get("validation_results", [])
        failed = [c for c in checks if c.get("status") in ("failed", "error")]
        skipped = [c for c in checks if c.get("status") == "skipped"]
        risks = [
            Risk(
                description=f"Check '{c['check_id']}' {c['status']}: {c.get('summary', '')[:200]}",
                severity="high" if c.get("category") in ("secrets", "sast", "iac") else "medium",
                mitigation="Fix the reported findings and re-run the build.",
            )
            for c in failed
        ]
        risks += [
            Risk(
                description=f"Check '{c['check_id']}' was skipped: {c.get('summary', '')[:200]}",
                severity="low",
                mitigation="Run this check in CI where the tool is available.",
            )
            for c in skipped
        ]
        risks.append(
            Risk(
                description="Generated API has no authentication",
                severity="medium",
                mitigation="Keep it in dev only until authentication is implemented.",
            )
        )
        blocking = any(c.get("category") in ("secrets", "sast", "iac") for c in failed)
        recommendation = "block" if blocking else ("proceed_with_caution" if failed or skipped else "proceed")
        return SecurityReview(
            summary=f"[demo review] {len(checks)} checks evaluated: {len(failed)} failed/error, "
            f"{len(skipped)} skipped.",
            risks=risks,
            recommendation=recommendation,  # type: ignore[arg-type]
        )

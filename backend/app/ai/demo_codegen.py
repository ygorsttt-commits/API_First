"""Deterministic code generator used by the demo provider.

It renders a small but real FastAPI service, its tests, a Dockerfile, Terraform for an AWS dev
environment and GitHub Actions workflows from the approved architecture's data model. Output is
real code that the validation stage actually lints, type-checks and tests inside the sandbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Library versions match the sandbox image (sandbox/requirements.txt) so tests run offline.
PINNED_REQUIREMENTS = """fastapi==0.162.0
pydantic==2.14.1
uvicorn==0.54.0
"""
PINNED_DEV_REQUIREMENTS = """-r requirements.txt
httpx==0.28.1
pytest==9.1.1
ruff==0.16.9
mypy==2.3.1
bandit==1.9.4
"""

_PY_TYPES = {
    "string": "str",
    "text": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "datetime": "datetime",
}
_SAMPLES = {
    "string": '"example"',
    "text": '"some details"',
    "integer": "1",
    "number": "9.5",
    "boolean": "True",
    "datetime": '"2026-01-01T09:00:00Z"',
}
_UPDATED_SAMPLES = {
    "string": '"updated"',
    "text": '"changed details"',
    "integer": "2",
    "number": "10.5",
    "boolean": "False",
    "datetime": '"2026-02-01T09:00:00Z"',
}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    required: bool


@dataclass(frozen=True)
class EntitySpec:
    name: str  # PascalCase
    fields: tuple[FieldSpec, ...]

    @property
    def snake(self) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.name).lower()

    @property
    def plural(self) -> str:
        s = self.snake
        if s.endswith("y") and not s.endswith(("ay", "ey", "oy", "uy")):
            return s[:-1] + "ies"
        if s.endswith(("s", "x", "ch", "sh")):
            return s + "es"
        return s + "s"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "app")[:40].strip("-")


def _field_line(f: FieldSpec) -> str:
    py = _PY_TYPES[f.type]
    if f.type == "boolean":
        return f"    {f.name}: bool = False"
    if f.required and f.type in ("string", "text"):
        return f"    {f.name}: str = Field(min_length=1, max_length=2000)"
    if f.required:
        return f"    {f.name}: {py}"
    return f"    {f.name}: {py} | None = None"


def _payload(entity: EntitySpec, samples: dict[str, str]) -> str:
    items = ", ".join(f'"{f.name}": {samples[f.type]}' for f in entity.fields)
    return "{" + items + "}"


def render_app(project_name: str, entity: EntitySpec) -> dict[str, str]:
    e, s, p = entity.name, entity.snake, entity.plural
    uses_datetime = any(f.type == "datetime" for f in entity.fields)
    needs_field = any(f.required and f.type in ("string", "text") for f in entity.fields)

    model_imports = []
    if uses_datetime:
        model_imports.append("from datetime import datetime\n")
    pyd = "from pydantic import BaseModel, Field" if needs_field else "from pydantic import BaseModel"
    model_imports.append(("\n" if uses_datetime else "") + pyd)
    field_lines = "\n".join(_field_line(f) for f in entity.fields)

    models = f'''"""Data models for {project_name}."""

{"".join(model_imports)}


class {e}Create(BaseModel):
{field_lines}


class {e}({e}Create):
    id: int
'''

    repository = f'''"""In-memory repository. Replace with a database adapter for production use."""

from threading import Lock

from app.models import {e}, {e}Create


class {e}Repository:
    def __init__(self) -> None:
        self._items: dict[int, {e}] = {{}}
        self._next_id = 1
        self._lock = Lock()

    def list(self) -> list[{e}]:
        with self._lock:
            return list(self._items.values())

    def get(self, item_id: int) -> {e} | None:
        with self._lock:
            return self._items.get(item_id)

    def create(self, payload: {e}Create) -> {e}:
        with self._lock:
            item = {e}(id=self._next_id, **payload.model_dump())
            self._items[item.id] = item
            self._next_id += 1
            return item

    def update(self, item_id: int, payload: {e}Create) -> {e} | None:
        with self._lock:
            if item_id not in self._items:
                return None
            item = {e}(id=item_id, **payload.model_dump())
            self._items[item_id] = item
            return item

    def delete(self, item_id: int) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None
'''

    main = f'''"""{project_name} HTTP API."""

from fastapi import FastAPI, HTTPException, Response, status

from app.models import {e}, {e}Create
from app.repository import {e}Repository

app = FastAPI(title="{project_name}", version="0.1.0")
repository = {e}Repository()

NOT_FOUND = "{e} not found"


@app.get("/health")
def health() -> dict[str, str]:
    return {{"status": "ok"}}


@app.get("/{p}")
def list_{p}() -> list[{e}]:
    return repository.list()


@app.post("/{p}", status_code=status.HTTP_201_CREATED)
def create_{s}(payload: {e}Create) -> {e}:
    return repository.create(payload)


@app.get("/{p}/{{item_id}}")
def get_{s}(item_id: int) -> {e}:
    item = repository.get(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return item


@app.put("/{p}/{{item_id}}")
def update_{s}(item_id: int, payload: {e}Create) -> {e}:
    item = repository.update(item_id, payload)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return item


@app.delete("/{p}/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_{s}(item_id: int) -> Response:
    if not repository.delete(item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
'''

    slug = slugify(project_name)
    readme = f"""# {project_name}

Generated by the AI Software Delivery Toolkit.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Test and lint

```bash
ruff check . && ruff format --check . && mypy app && pytest -q
```

## Endpoints

- `GET /health`
- `GET /{p}` · `POST /{p}`
- `GET /{p}/{{id}}` · `PUT /{p}/{{id}}` · `DELETE /{p}/{{id}}`

## Infrastructure

Terraform for an AWS **dev** environment lives in `infra/terraform`. Nothing is applied automatically:
the `deploy-dev` workflow runs `terraform plan`, and `apply` only runs after a reviewer approves the
GitHub `dev` environment. AWS access uses GitHub OIDC (no long-lived keys).

Known limitations: storage is in memory and the API has no authentication yet (see open questions).

Service slug: `{slug}`
"""

    ruff_toml = """line-length = 100
target-version = "py312"

[lint]
select = ["E", "F", "I", "B"]
"""

    return {
        "app/__init__.py": "",
        "app/models.py": models,
        "app/repository.py": repository,
        "app/main.py": main,
        "requirements.txt": PINNED_REQUIREMENTS,
        "requirements-dev.txt": PINNED_DEV_REQUIREMENTS,
        "ruff.toml": ruff_toml,
        "README.md": readme,
        ".gitignore": ".venv/\n__pycache__/\n.pytest_cache/\n.terraform/\n*.tfstate*\n*.tfplan\n",
    }


def render_tests(entity: EntitySpec) -> dict[str, str]:
    e, p = entity.name, entity.plural
    create = _payload(entity, _SAMPLES)
    update = _payload(entity, _UPDATED_SAMPLES)
    comparable = [f for f in entity.fields if f.type not in ("datetime",)]
    first_cmp = comparable[0].name if comparable else None
    required_str = next((f for f in entity.fields if f.required and f.type in ("string", "text")), None)

    lines = [
        f'"""API tests for the {e} service."""',
        "",
        "from fastapi.testclient import TestClient",
        "",
        "from app.main import app",
        "",
        "client = TestClient(app)",
        "",
        f"CREATE = {create}",
        f"UPDATE = {update}",
        "",
        "",
        "def test_health() -> None:",
        '    response = client.get("/health")',
        "    assert response.status_code == 200",
        '    assert response.json() == {"status": "ok"}',
        "",
        "",
        "def test_create_get_list() -> None:",
        f'    created = client.post("/{p}", json=CREATE)',
        "    assert created.status_code == 201",
        "    body = created.json()",
        '    assert isinstance(body["id"], int)',
    ]
    if first_cmp:
        lines.append(f'    assert body["{first_cmp}"] == CREATE["{first_cmp}"]')
    lines += [
        f"    fetched = client.get(f\"/{p}/{{body['id']}}\")",
        "    assert fetched.status_code == 200",
        f'    listed = client.get("/{p}")',
        '    assert any(item["id"] == body["id"] for item in listed.json())',
        "",
        "",
        "def test_update_and_delete() -> None:",
        f'    item_id = client.post("/{p}", json=CREATE).json()["id"]',
        f'    updated = client.put(f"/{p}/{{item_id}}", json=UPDATE)',
        "    assert updated.status_code == 200",
    ]
    if first_cmp:
        lines.append(f'    assert updated.json()["{first_cmp}"] == UPDATE["{first_cmp}"]')
    lines += [
        f'    assert client.delete(f"/{p}/{{item_id}}").status_code == 204',
        f'    assert client.get(f"/{p}/{{item_id}}").status_code == 404',
        "",
        "",
        "def test_unknown_id_returns_404() -> None:",
        f'    assert client.get("/{p}/999999").status_code == 404',
        f'    assert client.delete("/{p}/999999").status_code == 404',
    ]
    if required_str:
        lines += [
            "",
            "",
            "def test_rejects_invalid_payload() -> None:",
            f'    invalid = {{**CREATE, "{required_str.name}": ""}}',
            f'    assert client.post("/{p}", json=invalid).status_code == 422',
        ]
    lines.append("")
    return {"tests/__init__.py": "", "tests/test_api.py": "\n".join(lines)}


def render_infra(project_name: str) -> dict[str, str]:
    slug = slugify(project_name)
    dockerfile = """FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN useradd --create-home --uid 10001 appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""
    versions_tf = """terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }

  # Remote state is configured per environment at init time:
  #   terraform init -backend-config=environments/dev.s3.tfbackend
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
"""
    variables_tf = f"""variable "aws_region" {{
  description = "AWS region for this environment. No default on purpose: it must be chosen explicitly."
  type        = string
}}

variable "environment" {{
  description = "Deployment environment name."
  type        = string

  validation {{
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }}
}}

variable "project_name" {{
  description = "Short name used to prefix resources."
  type        = string
  default     = "{slug}"
}}

variable "image_tag" {{
  description = "Immutable container image tag to deploy (for example the git commit SHA)."
  type        = string
}}

variable "container_port" {{
  description = "Port the container listens on."
  type        = number
  default     = 8000
}}

variable "cpu" {{
  description = "App Runner vCPU units."
  type        = string
  default     = "256"
}}

variable "memory" {{
  description = "App Runner memory in MB."
  type        = string
  default     = "512"
}}

variable "github_oidc_provider_arn" {{
  description = "ARN of the existing GitHub OIDC identity provider in the account (not created here)."
  type        = string
}}

variable "github_repository" {{
  description = "GitHub repository allowed to deploy, in owner/name form."
  type        = string
}}
"""
    main_tf = """locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}

data "aws_iam_policy_document" "apprunner_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_ecr_access" {
  name               = "${local.name}-ecr-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_assume.json
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_ecr_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

resource "aws_apprunner_service" "app" {
  service_name = local.name

  source_configuration {
    auto_deployments_enabled = false

    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port = tostring(var.container_port)
      }
    }
  }

  instance_configuration {
    cpu    = var.cpu
    memory = var.memory
  }

  health_check_configuration {
    protocol = "HTTP"
    path     = "/health"
  }

  depends_on = [aws_iam_role_policy_attachment.apprunner_ecr_access]
}
"""
    iam_tf = """# Least-privilege role assumed by GitHub Actions through OIDC for the dev deploy workflow.
# Only the configured repository, on the protected "dev" environment, can assume it.

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${local.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPushThisRepo"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  statement {
    sid = "AppRunnerThisService"
    actions = [
      "apprunner:DescribeService",
      "apprunner:UpdateService",
      "apprunner:StartDeployment",
    ]
    resources = [aws_apprunner_service.app.arn]
  }

  statement {
    sid       = "PassAppRunnerEcrRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.apprunner_ecr_access.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
"""
    outputs_tf = """output "service_url" {
  description = "Public HTTPS URL of the App Runner service."
  value       = "https://${aws_apprunner_service.app.service_url}"
}

output "ecr_repository_url" {
  description = "ECR repository for application images."
  value       = aws_ecr_repository.app.repository_url
}

output "github_deploy_role_arn" {
  description = "Role ARN to store as the AWS_DEPLOY_ROLE_ARN variable of the GitHub dev environment."
  value       = aws_iam_role.github_deploy.arn
}
"""
    tfvars_example = f"""# Copy to dev.tfvars and fill in. Do not commit account identifiers you consider sensitive.
aws_region               = "REPLACE_ME"
environment              = "dev"
project_name             = "{slug}"
image_tag                = "REPLACE_WITH_COMMIT_SHA"
github_oidc_provider_arn = "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
github_repository        = "OWNER/REPO"
"""
    backend_example = f"""# Copy to dev.s3.tfbackend. The bucket and lock table must already exist.
bucket         = "REPLACE_ME-terraform-state"
key            = "{slug}/dev/terraform.tfstate"
region         = "REPLACE_ME"
dynamodb_table = "REPLACE_ME-terraform-locks"
encrypt        = true
"""
    ci = """name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy app
      - run: pytest -q
      - run: bandit -r app -q

  dependency-audit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pip-audit==2.7.3
      - run: pip-audit -r requirements.txt

  secrets:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  terraform:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: infra/terraform
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.9.8
      - run: terraform fmt -check -recursive
      - run: terraform init -backend=false
      - run: terraform validate
      - uses: bridgecrewio/checkov-action@v12
        with:
          directory: infra/terraform
          framework: terraform
"""
    deploy = """name: deploy-dev

# Manual trigger only. "apply" runs in the protected "dev" environment, which must be configured
# in GitHub with required reviewers so a human approves the reviewed plan before any change.
on:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: deploy-dev
  cancel-in-progress: false

jobs:
  plan:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    environment: dev-plan
    permissions:
      contents: read
      id-token: write
    defaults:
      run:
        working-directory: infra/terraform
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.9.8
      - run: terraform init -backend-config=environments/dev.s3.tfbackend
      - run: >-
          terraform plan -input=false -out=dev.tfplan
          -var-file=environments/dev.tfvars
          -var="image_tag=${{ github.sha }}"
      - uses: actions/upload-artifact@v4
        with:
          name: dev-tfplan
          path: infra/terraform/dev.tfplan
          retention-days: 3

  apply:
    needs: plan
    runs-on: ubuntu-latest
    timeout-minutes: 30
    environment: dev
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build and push image
        run: |
          IMAGE="${{ steps.ecr.outputs.registry }}/${{ vars.ECR_REPOSITORY }}:${{ github.sha }}"
          docker build -t "$IMAGE" .
          docker push "$IMAGE"
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.9.8
      - uses: actions/download-artifact@v4
        with:
          name: dev-tfplan
          path: infra/terraform
      - working-directory: infra/terraform
        run: |
          terraform init -backend-config=environments/dev.s3.tfbackend
          terraform apply -input=false dev.tfplan
      - name: Smoke test
        working-directory: infra/terraform
        run: |
          URL="$(terraform output -raw service_url)"
          curl --fail --retry 10 --retry-delay 15 --retry-all-errors "$URL/health"
"""
    return {
        "Dockerfile": dockerfile,
        ".dockerignore": ".git\n.venv\n__pycache__\ntests\ninfra\n.github\n",
        "infra/terraform/versions.tf": versions_tf,
        "infra/terraform/variables.tf": variables_tf,
        "infra/terraform/main.tf": main_tf,
        "infra/terraform/iam_github.tf": iam_tf,
        "infra/terraform/outputs.tf": outputs_tf,
        "infra/terraform/environments/dev.tfvars.example": tfvars_example,
        "infra/terraform/environments/dev.s3.tfbackend.example": backend_example,
        ".github/workflows/ci.yml": ci,
        ".github/workflows/deploy-dev.yml": deploy,
    }

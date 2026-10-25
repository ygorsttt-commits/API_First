"""Tool registry: the complete list of commands the platform may run in the sandbox.

Commands are fixed argv lists defined here. Nothing produced by a model is ever turned into a
command line; generated code can only influence *what the tools read*, never *which tool runs*.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    id: str
    category: str  # format|lint|types|tests|build|sast|iac|smoke
    argv: tuple[str, ...]
    description: str
    timeout_seconds: int = 120
    env: dict[str, str] = field(default_factory=dict)
    # Path (relative to workspace) that must exist for the tool to be meaningful.
    requires_path: str | None = None
    # Extra capability the sandbox image must declare (e.g. offline terraform providers).
    requires_feature: str | None = None


_PY_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp", "XDG_CACHE_HOME": "/tmp/.cache"}

_SMOKE = (
    "import json,sys\n"
    "from fastapi.testclient import TestClient\n"
    "from app.main import app\n"
    "r = TestClient(app).get('/health')\n"
    "print(json.dumps({'status_code': r.status_code, 'body': r.json()}))\n"
    "sys.exit(0 if r.status_code == 200 else 1)\n"
)

TOOLS: dict[str, ToolSpec] = {
    t.id: t
    for t in [
        ToolSpec(
            "ruff-format",
            "format",
            ("ruff", "format", "--check", "--diff", "--no-cache", "."),
            "Formatting check (ruff format)",
            env=_PY_ENV,
        ),
        ToolSpec(
            "ruff-lint",
            "lint",
            ("ruff", "check", "--no-cache", "--output-format", "concise", "."),
            "Lint (ruff)",
            env=_PY_ENV,
        ),
        ToolSpec(
            "mypy",
            "types",
            ("mypy", "--cache-dir", "/tmp/.mypy_cache", "app"),
            "Static type check (mypy)",
            env=_PY_ENV,
            requires_path="app",
        ),
        ToolSpec(
            "pytest",
            "tests",
            ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"),
            "Automated tests (pytest)",
            timeout_seconds=180,
            env=_PY_ENV,
            requires_path="tests",
        ),
        ToolSpec(
            "import-build",
            "build",
            ("python", "-c", "import app.main; print('import ok')"),
            "Build check: application imports cleanly",
            env=_PY_ENV,
            requires_path="app/main.py",
        ),
        ToolSpec(
            "bandit",
            "sast",
            ("bandit", "-r", "app", "-q", "-f", "txt"),
            "SAST (bandit)",
            env=_PY_ENV,
            requires_path="app",
        ),
        ToolSpec(
            "terraform-fmt",
            "iac",
            ("terraform", "fmt", "-check", "-recursive", "-diff", "infra/terraform"),
            "Terraform formatting",
            env={"HOME": "/tmp", "TF_IN_AUTOMATION": "1"},
            requires_path="infra/terraform",
        ),
        ToolSpec(
            "terraform-validate",
            "iac",
            (
                "sh",
                "-c",
                "cp -r infra/terraform /tmp/tf && cd /tmp/tf && "
                "terraform init -backend=false -input=false -no-color >/dev/null && terraform validate -no-color",
            ),
            "Terraform validate (needs offline provider mirror in the sandbox image)",
            env={"HOME": "/tmp", "TF_IN_AUTOMATION": "1"},
            requires_path="infra/terraform",
            requires_feature="terraform-providers",
        ),
        ToolSpec(
            "checkov",
            "iac",
            (
                "checkov",
                "-d",
                "infra/terraform",
                "--framework",
                "terraform",
                "--compact",
                "--quiet",
                "--skip-download",
                "--output",
                "cli",
            ),
            "IaC security scan (checkov)",
            timeout_seconds=240,
            env=_PY_ENV,
            requires_path="infra/terraform",
            requires_feature="checkov",
        ),
        ToolSpec(
            "smoke-health",
            "smoke",
            ("python", "-c", _SMOKE),
            "Smoke test: GET /health on the built application (in sandbox)",
            env=_PY_ENV,
            requires_path="app/main.py",
        ),
    ]
}

VALIDATION_TOOL_IDS = (
    "ruff-format",
    "ruff-lint",
    "mypy",
    "import-build",
    "pytest",
    "bandit",
    "terraform-fmt",
    "terraform-validate",
    "checkov",
)


def get_tool(tool_id: str) -> ToolSpec:
    try:
        return TOOLS[tool_id]
    except KeyError:
        raise ValueError(f"unknown tool '{tool_id}'") from None

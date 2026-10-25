"""Validation suite run over a generated workspace.

Two kinds of checks:
- built-in checks: pure text analysis in-process (secret scanning, dependency pinning, IaC and
  workflow policies). They never execute workspace content.
- tool checks: real tools from the registry, executed only inside the sandbox.

Every outcome is one of passed | failed | error | skipped, and `executed` says whether a check
actually ran. A skipped check is never reported as passed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.executor.sandbox import Sandbox, SandboxUnavailable
from app.executor.tools import TOOLS, VALIDATION_TOOL_IDS
from app.security.redaction import scan_text


@dataclass
class CheckOutcome:
    check_id: str
    category: str
    tool: str
    status: str  # passed | failed | error | skipped
    summary: str
    log: str
    executed: bool
    duration_ms: int = 0


# ------------------------------------------------------------------ built-in checks


def check_secrets(files: dict[str, str]) -> CheckOutcome:
    started = time.monotonic()
    findings = []
    for path, content in files.items():
        for f in scan_text(content):
            findings.append(f"{path}:{f.line} [{f.rule}] {f.preview}")
    status = "failed" if findings else "passed"
    summary = (
        f"{len(findings)} potential secret(s) found"
        if findings
        else f"no secrets found in {len(files)} files"
    )
    return CheckOutcome(
        "secret-scan",
        "secrets",
        "builtin:secret-scanner",
        status,
        summary,
        "\n".join(findings),
        True,
        int((time.monotonic() - started) * 1000),
    )


_PIN = re.compile(r"^[A-Za-z0-9_.\-\[\],]+==[A-Za-z0-9_.\-+]+$")


def check_dependency_policy(files: dict[str, str]) -> CheckOutcome:
    reqs = {p: c for p, c in files.items() if re.fullmatch(r"requirements(-[a-z]+)?\.txt", p.split("/")[-1])}
    if not reqs:
        return CheckOutcome(
            "dependency-policy",
            "deps",
            "builtin:dependency-policy",
            "skipped",
            "no requirements files found",
            "",
            False,
        )
    problems = []
    for path, content in reqs.items():
        for n, raw in enumerate(content.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-r "):
                continue
            if line.startswith(("-e", "--", "git+", "http:", "https:")) or "://" in line:
                problems.append(f"{path}:{n} non-registry or editable requirement: {line}")
            elif not _PIN.match(line):
                problems.append(f"{path}:{n} dependency is not pinned with '==': {line}")
    status = "failed" if problems else "passed"
    summary = (
        f"{len(problems)} dependency policy violation(s)"
        if problems
        else "all dependencies pinned to exact versions (vulnerability database lookup not performed here; "
        "pip-audit runs in the generated CI)"
    )
    return CheckOutcome(
        "dependency-policy", "deps", "builtin:dependency-policy", status, summary, "\n".join(problems), True
    )


_IAC_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "open-ingress",
        re.compile(r'cidr_blocks\s*=\s*\[[^\]]*"0\.0\.0\.0/0"'),
        "ingress/egress open to 0.0.0.0/0",
    ),
    (
        "wildcard-action",
        re.compile(r'actions\s*=\s*\[\s*"\*"\s*\]|"Action"\s*:\s*"\*"'),
        "IAM wildcard action",
    ),
    ("admin-policy", re.compile(r"AdministratorAccess"), "AdministratorAccess policy referenced"),
    (
        "static-credentials",
        re.compile(r"^\s*(access_key|secret_key)\s*=", re.M),
        "static AWS credentials in provider",
    ),
    ("public-acl", re.compile(r'acl\s*=\s*"public-read'), "public S3 ACL"),
    ("unencrypted-flag", re.compile(r"encrypted\s*=\s*false"), "encryption explicitly disabled"),
]


def check_iac_policy(files: dict[str, str]) -> CheckOutcome:
    tf = {p: c for p, c in files.items() if p.endswith(".tf")}
    if not tf:
        return CheckOutcome(
            "iac-policy", "iac", "builtin:iac-policy", "skipped", "no Terraform files", "", False
        )
    problems = []
    for path, content in tf.items():
        for rule, pattern, msg in _IAC_RULES:
            for m in pattern.finditer(content):
                line = content.count("\n", 0, m.start()) + 1
                problems.append(f"{path}:{line} [{rule}] {msg}")
        if re.search(r"backend\s+\"local\"", content):
            problems.append(f"{path} [local-backend] remote state backend expected")
    status = "failed" if problems else "passed"
    summary = (
        f"{len(problems)} IaC policy violation(s)"
        if problems
        else f"{len(tf)} Terraform files comply with policy"
    )
    return CheckOutcome("iac-policy", "iac", "builtin:iac-policy", status, summary, "\n".join(problems), True)


def check_workflow_policy(files: dict[str, str]) -> CheckOutcome:
    wf = {
        p: c for p, c in files.items() if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    }
    if not wf:
        return CheckOutcome(
            "workflow-policy", "iac", "builtin:workflow-policy", "skipped", "no workflows", "", False
        )
    problems = []
    for path, content in wf.items():
        if not re.search(r"^permissions:", content, re.M):
            problems.append(f"{path}: top-level 'permissions' not declared (defaults may be too broad)")
        if "pull_request_target" in content:
            problems.append(f"{path}: uses pull_request_target")
        if re.search(r"AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)", content):
            problems.append(f"{path}: static AWS keys referenced; use OIDC role-to-assume")
        for m in re.finditer(r"uses:\s*([^\s@]+)(@\S+)?", content):
            if not m.group(2) and not m.group(1).startswith("./"):
                problems.append(f"{path}: action '{m.group(1)}' is not pinned to a version")
        if "terraform apply" in content and not re.search(r"^\s+environment:\s*\S+", content, re.M):
            problems.append(f"{path}: terraform apply without a protected environment gate")
    status = "failed" if problems else "passed"
    summary = (
        f"{len(problems)} workflow policy violation(s)"
        if problems
        else f"{len(wf)} workflows comply with policy"
    )
    return CheckOutcome(
        "workflow-policy", "iac", "builtin:workflow-policy", status, summary, "\n".join(problems), True
    )


# ------------------------------------------------------------------ tool checks


def _first_lines(text: str, n: int = 3) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[:400] if lines else "(no output)"


def run_tool_check(tool_id: str, workspace: Path, files: dict[str, str], sandbox: Sandbox) -> CheckOutcome:
    tool = TOOLS[tool_id]
    base = CheckOutcome(tool.id, tool.category, tool.id, "skipped", "", "", False)
    if tool.requires_path and not any(
        p == tool.requires_path or p.startswith(tool.requires_path + "/") for p in files
    ):
        base.summary = f"not applicable: '{tool.requires_path}' not present"
        return base
    ok, reason = sandbox.available()
    if not ok:
        base.summary = f"not executed: {reason}"
        return base
    if tool.requires_feature and tool.requires_feature not in sandbox.features():
        base.summary = (
            f"not executed: sandbox image lacks feature '{tool.requires_feature}' "
            "(see docs/SECURITY.md#sandbox-image); this check runs in CI"
        )
        return base
    try:
        res = sandbox.run(tool, workspace)
    except SandboxUnavailable as exc:
        base.summary = f"not executed: {exc}"
        return base
    log = res.output
    if res.timed_out:
        return CheckOutcome(
            tool.id,
            tool.category,
            tool.id,
            "error",
            f"timed out after {res.duration_ms} ms",
            log,
            True,
            res.duration_ms,
        )
    if res.exit_code == 0:
        status, summary = "passed", _first_lines(log, 2)
    elif res.exit_code in (125, 126, 127):
        status, summary = "error", f"tool could not start (exit {res.exit_code}): {_first_lines(log)}"
    else:
        status, summary = "failed", f"exit {res.exit_code}: {_first_lines(log)}"
    return CheckOutcome(tool.id, tool.category, tool.id, status, summary, log, True, res.duration_ms)


def run_validation_suite(workspace: Path, files: dict[str, str], sandbox: Sandbox) -> list[CheckOutcome]:
    outcomes = [
        check_secrets(files),
        check_dependency_policy(files),
        check_iac_policy(files),
        check_workflow_policy(files),
    ]
    for tool_id in VALIDATION_TOOL_IDS:
        outcomes.append(run_tool_check(tool_id, workspace, files, sandbox))
    return outcomes


# Categories whose failure blocks a deployment plan.
BLOCKING_CATEGORIES = {"secrets", "tests", "sast", "iac", "build", "deps", "lint", "types", "format"}

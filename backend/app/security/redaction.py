"""Secret detection and redaction.

Used in three places: before text is sent to an LLM, before text is written to logs/events/audit,
and as the built-in secret scanner over generated workspaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (rule id, pattern). Patterns are deliberately conservative to keep false positives low.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "aws-secret-access-key",
        re.compile(r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
    ),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-style-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "generic-credential-assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api_?key|access_?token|auth_?token)\b\s*[:=]\s*"
            r"['\"](?!\s*$)(?!change-?me)(?!example)(?!<)[^'\"\s]{8,}['\"]"
        ),
    ),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
]

REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class SecretFinding:
    rule: str
    line: int
    preview: str  # already redacted


def redact(text: str, extra_values: list[str] | None = None) -> str:
    """Replace known secret shapes and any explicitly provided secret values."""
    if not text:
        return text
    for value in extra_values or []:
        if value and len(value) >= 6:
            text = text.replace(value, REDACTED)
    for _, pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_obj(obj: object, extra_values: list[str] | None = None) -> object:
    """Recursively redact strings inside dict/list structures."""
    if isinstance(obj, str):
        return redact(obj, extra_values)
    if isinstance(obj, dict):
        return {k: redact_obj(v, extra_values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, extra_values) for v in obj]
    return obj


def scan_text(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(SecretFinding(rule=rule, line=lineno, preview=redact(line.strip())[:160]))
    return findings

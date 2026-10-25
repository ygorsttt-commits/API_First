"""LLMProvider interface. Providers only turn a request into a candidate object of the requested schema;
validation, retries, redaction and limits live in the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredRequest:
    task: str  # capability name, e.g. "requirements_analyst"
    system: str
    user: str  # fully assembled user message (untrusted parts already fenced and redacted)
    # Structured, already-validated context the provider may use directly (demo provider relies on it).
    context: dict[str, Any] = field(default_factory=dict)
    # The redacted untrusted inputs by label (also fenced inside `user`).
    untrusted: dict[str, str] = field(default_factory=dict)
    # Feedback from a previous failed validation attempt, if any.
    validation_feedback: str | None = None


class ProviderError(Exception):
    """Non-retryable provider failure (auth, refusal, misconfiguration)."""


class ProviderTransientError(Exception):
    """Retryable provider failure (rate limit, overload, network)."""


class LLMProvider(Protocol):
    name: str
    simulated: bool  # True when outputs are not produced by a real model

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> T | dict[str, Any]:
        """Return an instance of `schema` or a raw dict to be validated by the gateway."""
        ...

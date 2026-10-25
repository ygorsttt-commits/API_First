"""Claude provider using the official Anthropic SDK with structured outputs.

The API key is read from settings (SecretStr) and only ever handed to the SDK client.
"""

from __future__ import annotations

from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.ai.provider import ProviderError, ProviderTransientError, StructuredRequest
from app.config import Settings

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider:
    name = "anthropic"
    simulated = False

    def __init__(self, settings: Settings, client: Any | None = None):
        if client is None:
            if not settings.anthropic_api_key:
                raise ProviderError("ANTHROPIC_API_KEY is not configured")
            client = anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                timeout=settings.llm_timeout_seconds,
                max_retries=2,
            )
        self._client = client
        self._settings = settings

    def generate_structured(self, request: StructuredRequest, schema: type[T]) -> T | dict[str, Any]:
        user = request.user
        if request.validation_feedback:
            user += (
                "\n\nYour previous answer failed validation with these errors; return a corrected, "
                f"complete answer:\n{request.validation_feedback}"
            )
        kwargs: dict[str, Any] = {
            "model": self._settings.anthropic_model,
            "max_tokens": self._settings.llm_max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": user}],
            "output_format": schema,
            "output_config": {"effort": self._settings.anthropic_effort},
        }
        if self._settings.anthropic_enable_fallbacks:
            # Server-side refusal fallback: re-runs a declined request on a fallback model in the same call.
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            response = self._client.beta.messages.parse(**kwargs)
        except anthropic.AuthenticationError:
            raise ProviderError("authentication with the Anthropic API failed") from None
        except anthropic.PermissionDeniedError:
            raise ProviderError("the configured Anthropic key lacks permission for this request") from None
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"bad request: {exc.message}") from None
        except anthropic.RateLimitError:
            raise ProviderTransientError("rate limited") from None
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderTransientError(f"server error {exc.status_code}") from None
            raise ProviderError(f"API error {exc.status_code}") from None
        except anthropic.APIConnectionError:
            raise ProviderTransientError("connection error") from None

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ProviderError(f"model declined the request (category={category})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("output hit max_tokens before completing; raise LLM_MAX_OUTPUT_TOKENS")
        parsed = response.parsed_output
        if parsed is None:
            raise ProviderTransientError("no parsed output returned")
        return parsed

"""Application settings. Values come from environment variables (prefix-free) or a .env file.

Secrets (API keys, tokens) are held as SecretStr so they never render in reprs or logs.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "dev", "prod"] = "local"
    database_url: str = "postgresql+psycopg://toolkit:toolkit@localhost:5432/toolkit"
    data_dir: Path = Path("./var")

    # --- AI gateway ---
    # "demo" never calls an external service. "anthropic" requires ANTHROPIC_API_KEY.
    llm_provider: Literal["demo", "anthropic"] = "demo"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    anthropic_enable_fallbacks: bool = True
    llm_max_output_tokens: int = 16000
    llm_timeout_seconds: float = 300.0
    llm_max_prompt_chars: int = 60_000

    # --- Auth ---
    # demo: unauthenticated requests act as the local demo user (only allowed when app_env is local/test).
    # token: every request needs "Authorization: Bearer <token>"; tokens map to a user and roles.
    auth_mode: Literal["demo", "token"] = "demo"
    # Format: "token1=user1:viewer,editor,approver;token2=user2:viewer". Stored only as hashes in memory.
    api_tokens: SecretStr | None = None

    # --- Sandbox / executor ---
    sandbox_backend: Literal["docker", "disabled"] = "docker"
    sandbox_image: str = "delivery-toolkit-sandbox:latest"
    sandbox_cpus: float = 1.0
    sandbox_memory_mb: int = 512
    sandbox_pids_limit: int = 256
    sandbox_timeout_seconds: int = 180
    sandbox_max_output_bytes: int = 200_000
    # When the worker runs inside a container, the host path that corresponds to DATA_DIR
    # (Docker bind mounts are resolved by the host daemon).
    sandbox_host_data_dir: Path | None = None

    # --- Limits ---
    max_files_per_workspace: int = 200
    max_file_bytes: int = 256_000
    max_artifact_bytes: int = 2_000_000
    worker_poll_seconds: float = 1.0

    # --- Deploy ---
    # "simulated" never touches a cloud account. "aws" requires explicit configuration and approvals.
    deploy_target: Literal["simulated", "aws"] = "simulated"
    aws_region: str | None = None
    aws_deploy_role_arn: str | None = None

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, v: Path) -> Path:
        return v.expanduser().resolve()

    @property
    def demo_mode(self) -> bool:
        """True when no real external integration is active. Shown prominently in the UI."""
        return self.llm_provider == "demo" or self.deploy_target == "simulated"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    def token_table(self) -> dict[str, tuple[str, frozenset[str]]]:
        """Return {sha256(token): (user_id, roles)} parsed from API_TOKENS."""
        table: dict[str, tuple[str, frozenset[str]]] = {}
        if not self.api_tokens:
            return table
        for entry in self.api_tokens.get_secret_value().split(";"):
            entry = entry.strip()
            if not entry or "=" not in entry:
                continue
            token, rest = entry.split("=", 1)
            user, _, roles = rest.partition(":")
            digest = hashlib.sha256(token.strip().encode()).hexdigest()
            table[digest] = (user.strip(), frozenset(r.strip() for r in roles.split(",") if r.strip()))
        return table


@lru_cache
def get_settings() -> Settings:
    return Settings()

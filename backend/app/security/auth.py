"""Request authentication and role-based authorization.

Roles:
  viewer   - read projects, runs, artifacts
  editor   - create projects, start generation runs
  approver - approve requirements and plans
  deployer - approve and trigger deployments (kept separate from approver on purpose)
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings

ALL_ROLES = frozenset({"viewer", "editor", "approver", "deployer"})
DEMO_USER_ID = "demo-user"


@dataclass(frozen=True)
class Actor:
    user_id: str
    roles: frozenset[str]

    def has(self, role: str) -> bool:
        return role in self.roles


def resolve_actor(authorization: str | None, settings: Settings) -> Actor:
    if settings.auth_mode == "demo":
        if settings.app_env not in ("local", "test"):
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "demo auth is not allowed in this env")
        return Actor(DEMO_USER_ID, ALL_ROLES)

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    digest = hashlib.sha256(token.encode()).hexdigest()
    for known, (user, roles) in settings.token_table().items():
        if hmac.compare_digest(known, digest):
            return Actor(user, roles & ALL_ROLES)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


def current_actor(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Actor:
    return resolve_actor(authorization, settings)


def require(role: str):
    def _dep(actor: Actor = Depends(current_actor)) -> Actor:
        if not actor.has(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role '{role}' required")
        return actor

    return _dep

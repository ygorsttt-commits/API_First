from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.security.redaction import redact_obj

log = logging.getLogger("toolkit.audit")


def audit(session: Session, actor: str, action: str, project_id: str | None = None, **details: Any) -> None:
    """Record an important action. Details are redacted before being stored or logged."""
    clean = redact_obj(details)
    assert isinstance(clean, dict)
    session.add(AuditLog(actor=actor, action=action, project_id=project_id, details=clean))
    log.info("audit actor=%s action=%s project=%s", actor, action, project_id)

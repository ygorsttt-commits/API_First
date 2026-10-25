"""Background worker: claims queued runs from PostgreSQL and executes them.

Run with:  python -m app.worker
Claiming uses SELECT ... FOR UPDATE SKIP LOCKED, so several workers can run safely.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.db import session_factory
from app.models import Project, Run, utcnow
from app.orchestration.engine import Orchestrator

log = logging.getLogger("toolkit.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
STALE_AFTER = timedelta(hours=2)


def claim_next_run() -> str | None:
    with session_factory()() as session:
        stmt = (
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = session.scalars(stmt).first()
        if run is None:
            return None
        run.status = "running"
        run.locked_by = WORKER_ID
        run.started_at = utcnow()
        session.commit()
        return run.id


def recover_stale_runs() -> int:
    """Mark runs left 'running' by a dead worker as failed so the project can be retried."""
    cutoff = utcnow() - STALE_AFTER
    with session_factory()() as session:
        stale = session.scalars(select(Run).where(Run.status == "running", Run.started_at < cutoff)).all()
        for run in stale:
            run.status = "failed"
            run.error = "worker lost while running (stale run recovered)"
            run.finished_at = utcnow()
            session.execute(
                update(Project)
                .where(Project.id == run.project_id)
                .values(status="failed", failed_stage=run.kind)
            )
        session.commit()
        return len(stale)


def process_available(orchestrator: Orchestrator, max_runs: int | None = None) -> int:
    done = 0
    while max_runs is None or done < max_runs:
        run_id = claim_next_run()
        if run_id is None:
            break
        log.info("executing run %s", run_id)
        orchestrator.execute(run_id)
        done += 1
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    orchestrator = Orchestrator(settings, session_factory())
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if n := recover_stale_runs():
        log.warning("recovered %s stale run(s)", n)
    ok, reason = orchestrator.sandbox.available()
    log.info(
        "worker %s started (provider=%s, sandbox=%s: %s, deploy_target=%s)",
        WORKER_ID,
        settings.llm_provider,
        orchestrator.sandbox.name,
        reason,
        settings.deploy_target,
    )
    while not stopping:
        if process_available(orchestrator, max_runs=1) == 0:
            time.sleep(settings.worker_poll_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    main()

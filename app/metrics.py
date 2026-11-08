"""Métricas simples em memória: um middleware registra cada requisição."""

import time
from collections import Counter, deque
from datetime import UTC, datetime

from fastapi import Request

# Rotas que não entram nas métricas (o painel consulta /metrics o tempo todo)
IGNORED_PATHS = {"/metrics", "/painel", "/favicon.ico"}

_started_at = time.time()
_total_requests = 0
_total_errors = 0
_total_ms = 0.0
_by_route: Counter[str] = Counter()
_recent: deque[dict] = deque(maxlen=50)


async def metrics_middleware(request: Request, call_next):
    global _total_requests, _total_errors, _total_ms

    start = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - start) * 1000, 2)

    path = request.url.path
    if path in IGNORED_PATHS:
        return response

    # Usa o molde da rota (/tasks/{id}) para agrupar, e não o caminho real (/tasks/1)
    route = request.scope.get("route")
    template = getattr(route, "path", path)

    _total_requests += 1
    _total_ms += ms
    if response.status_code >= 400:
        _total_errors += 1
    _by_route[f"{request.method} {template}"] += 1
    _recent.appendleft({
        "time": datetime.now(UTC).isoformat(),
        "method": request.method,
        "path": path,
        "status": response.status_code,
        "ms": ms,
    })
    return response


def get_metrics() -> dict:
    return {
        "uptime_seconds": round(time.time() - _started_at, 1),
        "total_requests": _total_requests,
        "total_errors": _total_errors,
        "avg_ms": round(_total_ms / _total_requests, 2) if _total_requests else 0,
        "by_route": dict(_by_route),
        "recent": list(_recent),
    }

"""Ponto de entrada da API."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.database import create_table_if_missing
from app.metrics import get_metrics, metrics_middleware
from app.routes import tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ao iniciar: no ambiente local, garante que a tabela existe
    if os.getenv("DYNAMODB_ENDPOINT"):
        create_table_if_missing()
    yield


app = FastAPI(title="API_First - Tarefas", version="0.2.0", lifespan=lifespan)

app.middleware("http")(metrics_middleware)
app.include_router(tasks.router)


@app.get("/health", operation_id="getHealth")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", operation_id="getMetrics")
def metrics() -> dict:
    return get_metrics()


# Painel web (não faz parte do contrato da API, por isso fica fora do /docs)
PAINEL = Path(__file__).parent / "static" / "painel.html"


@app.get("/painel", include_in_schema=False)
def painel() -> FileResponse:
    return FileResponse(PAINEL)

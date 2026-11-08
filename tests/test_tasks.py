"""Testes das rotas da API (rodar com: docker compose exec api pytest)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import tasks

client = TestClient(app)


@pytest.fixture(autouse=True)
def limpar_tarefas():
    """Cada teste começa com a lista vazia."""
    tasks._tasks.clear()
    tasks._next_id = 1


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_criar_e_listar():
    r = client.post("/tasks", json={"title": "Estudar"})
    assert r.status_code == 201
    assert r.json() == {"id": 1, "title": "Estudar", "done": False}

    r = client.get("/tasks")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_buscar_tarefa():
    client.post("/tasks", json={"title": "Estudar"})
    r = client.get("/tasks/1")
    assert r.status_code == 200
    assert r.json()["title"] == "Estudar"


def test_atualizar_parcial():
    client.post("/tasks", json={"title": "Estudar"})
    r = client.put("/tasks/1", json={"done": True})
    assert r.status_code == 200
    assert r.json() == {"id": 1, "title": "Estudar", "done": True}


def test_apagar():
    client.post("/tasks", json={"title": "Estudar"})
    assert client.delete("/tasks/1").status_code == 204
    assert client.get("/tasks/1").status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_tarefa_inexistente_404(method):
    kwargs = {"json": {"done": True}} if method == "put" else {}
    r = getattr(client, method)("/tasks/99", **kwargs)
    assert r.status_code == 404
    assert r.json() == {"detail": "Tarefa não encontrada"}


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": "x" * 201}])
def test_criar_invalido_422(body):
    assert client.post("/tasks", json=body).status_code == 422


def test_metrics_conta_requisicoes():
    antes = client.get("/metrics").json()["total_requests"]
    client.get("/health")
    client.get("/tasks/99")
    m = client.get("/metrics").json()
    assert m["total_requests"] == antes + 2
    assert m["total_errors"] >= 1
    assert "GET /tasks/{id}" in m["by_route"]

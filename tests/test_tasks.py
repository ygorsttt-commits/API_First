"""Testes das rotas da API (rodar com: docker compose exec api pytest).

Usa o moto: um DynamoDB falso em memória, recriado a cada teste.
"""

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.database import create_table_if_missing
from app.main import app

client = TestClient(app)
ID_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def dynamodb_falso(monkeypatch):
    """Cada teste começa com uma tabela vazia no DynamoDB falso."""
    monkeypatch.delenv("DYNAMODB_ENDPOINT", raising=False)  # não usar o DynamoDB Local
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        create_table_if_missing()
        yield


def criar(title: str = "Estudar") -> dict:
    return client.post("/tasks", json={"title": title}).json()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_criar_e_listar():
    r = client.post("/tasks", json={"title": "Estudar"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Estudar" and body["done"] is False
    assert len(body["id"]) == 36  # UUID

    r = client.get("/tasks")
    assert r.status_code == 200
    assert r.json() == [body]


def test_buscar_tarefa():
    task = criar()
    r = client.get(f"/tasks/{task['id']}")
    assert r.status_code == 200
    assert r.json() == task


def test_atualizar_parcial():
    task = criar()
    r = client.put(f"/tasks/{task['id']}", json={"done": True})
    assert r.status_code == 200
    assert r.json() == {**task, "done": True}


def test_apagar():
    task = criar()
    assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert client.get(f"/tasks/{task['id']}").status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_tarefa_inexistente_404(method):
    kwargs = {"json": {"done": True}} if method == "put" else {}
    r = getattr(client, method)(f"/tasks/{ID_INEXISTENTE}", **kwargs)
    assert r.status_code == 404
    assert r.json() == {"detail": "Tarefa não encontrada"}


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": "x" * 201}])
def test_criar_invalido_422(body):
    assert client.post("/tasks", json=body).status_code == 422


def test_metrics_conta_requisicoes():
    antes = client.get("/metrics").json()["total_requests"]
    client.get("/health")
    client.get(f"/tasks/{ID_INEXISTENTE}")
    m = client.get("/metrics").json()
    assert m["total_requests"] == antes + 2
    assert m["total_errors"] >= 1
    assert "GET /tasks/{id}" in m["by_route"]

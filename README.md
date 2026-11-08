# API_First

API REST de tarefas construída no estilo **API-First** (contrato OpenAPI antes do código), empacotada em Docker e publicada na AWS com Terraform e CI/CD.

> Projeto de estudo de desenvolvimento backend e DevOps.

## Stack

| Camada | Tecnologia |
|---|---|
| Contrato | OpenAPI 3.1 ([`openapi.yaml`](openapi.yaml)) |
| API | Python 3.12 + FastAPI |
| Banco | DynamoDB (local: DynamoDB Local) |
| Container | Docker + Docker Compose |
| Infra | Terraform → AWS (ECR, ECS Fargate, ALB, DynamoDB) |
| CI/CD | GitHub Actions |

## Arquitetura

```
Navegador ──▶ ALB ──▶ ECS Fargate (container FastAPI) ──▶ DynamoDB
                              ▲
                    imagem vem do ECR
```

## Rodando localmente

Pré-requisito: **Docker Desktop** aberto. Não é preciso instalar Python.

```bash
docker compose up -d          # sobe API + DynamoDB Local
docker compose exec api pytest   # roda os testes
docker compose exec api ruff check .   # lint
docker compose logs -f api    # acompanha os logs
docker compose down           # desliga (dados ficam no volume)
```

| Endereço | O que é |
|---|---|
| http://localhost:8080/painel | Painel de teste e observabilidade |
| http://localhost:8080/docs | Documentação interativa (Swagger) |
| http://localhost:8080/health | Health check |

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | Status da API |
| GET | `/metrics` | Métricas (requisições, erros, latência) |
| GET | `/tasks` | Lista tarefas |
| POST | `/tasks` | Cria tarefa |
| GET | `/tasks/{id}` | Busca tarefa |
| PUT | `/tasks/{id}` | Atualiza tarefa |
| DELETE | `/tasks/{id}` | Apaga tarefa |

## Estrutura

```
├── .github/        # templates de PR, CODEOWNERS, Dependabot (e workflows de CI/CD)
├── app/            # código da API
├── tests/          # testes pytest
├── infra/          # Terraform (AWS)
├── openapi.yaml    # contrato da API (fonte da verdade)
├── Dockerfile
└── docker-compose.yml
```

## Como contribuir

1. Crie uma branch a partir da `main`: `git checkout -b feat/minha-mudanca`
2. Mudou a API? Atualize primeiro o `openapi.yaml`.
3. Commits no padrão [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `infra:`
4. Rode testes e lint antes do push.
5. Abra um Pull Request — a `main` só recebe mudanças via PR.

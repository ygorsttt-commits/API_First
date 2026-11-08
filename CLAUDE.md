# API_First

Projeto de estudo do Ygor para aprender Git, GitHub, AWS e desenvolvimento de APIs no estilo API-First (definir o contrato da API antes de implementar).

## Como trabalhar neste projeto
- Responder sempre em português, de forma simples e curta.
- O Ygor está aprendendo: explicar o passo e o porquê, sem textos longos.
- Pedidos são curtos e às vezes imprecisos: interpretar a **intenção**, não a letra. Completar com os padrões abaixo em vez de perguntar o óbvio. Perguntar só decisões que mudam o rumo.
- Se o pedido conflitar com os padrões (custo, segurança, boas práticas), seguir o padrão e avisar em uma linha.
- Economizar tokens: não repetir contexto, não listar opções que não serão usadas, dar uma recomendação direta.
- **Antes de criar ou alterar qualquer arquivo**: apresentar o plano (passos, lista de arquivos, o que cada um faz e esforço estimado: baixo/médio/alto) e **esperar a autorização do Ygor**. Só então executar. (Exceção: atualizar este CLAUDE.md quando ele pedir.)
- Manter este arquivo atualizado conforme o projeto avança (decisões, stack, estrutura, próximos passos).

## Stack
- API: Python + FastAPI (contrato OpenAPI em `openapi.yaml`)
- Container: Docker
- AWS: ECR (imagens) + ECS Fargate (execução) + ALB + VPC
- Infraestrutura: Terraform (nada criado na mão pelo console)

## Padrões (aplicar sem precisar pedir)
- **API-First**: toda rota nova começa no `openapi.yaml`; o código segue o contrato.
- **API**: REST, recursos no plural (`/users`), JSON, erros no formato `{"detail": "..."}`, rota `/health` para o ALB.
- **Python**: código simples, com type hints, testes com `pytest`.
- **Terraform**: estilo oficial HashiCorp (usar a skill `terraform:terraform-style-guide`), variáveis em `variables.tf`, saídas em `outputs.tf`, tags `Project = "API_First"`.
- **Custo**: priorizar o mais barato para estudo (sem NAT Gateway, menor tamanho de Fargate); lembrar `terraform destroy` ao final.
- **Segurança**: nunca commitar segredos ou `.tfstate`; permissões mínimas no IAM.
- **Git**: commits pequenos, mensagens em português no imperativo ("Adiciona rota de usuários").

## Estrutura planejada
```
openapi.yaml   # contrato da API
app/           # código FastAPI
tests/         # testes pytest
Dockerfile
infra/         # Terraform
```

## Organização de arquivos
- Começar com poucos arquivos; dividir só quando um passar de ~200 linhas ou misturar responsabilidades.
- FastAPI: `app/main.py` (inicia a API), `app/routes/` (um arquivo por recurso), `app/schemas.py` (modelos de dados), `app/services/` (regras de negócio, quando houver).
- Terraform (`infra/`): um arquivo por assunto: `providers.tf`, `network.tf`, `ecr.tf`, `ecs.tf`, `alb.tf`, `variables.tf`, `outputs.tf`.
- Testes espelham o código: `tests/test_<recurso>.py`.

## Decisões
- Caso de uso: API de tarefas (CRUD).
- Banco: **DynamoDB** (free tier permanente; prioridade é custo ~zero). Local: container `amazon/dynamodb-local` com volume `dynamodb-data`. `id` = UUID (string). Na AWS a tabela será criada pelo Terraform; localmente a API cria ao iniciar. Testes usam `moto`.
- Desenvolvimento **dentro do container** (Docker Compose + reload; Dev Containers no VS Code). Sem Python instalado na máquina.
- Testar tudo localmente antes da AWS.
- Painel web em `/painel` (HTML+JS servido pela API) para testar a API e ver observabilidade via `GET /metrics` (requisições, erros, tempo médio, por rota, últimas requisições).

## Estado atual
- Repositório: https://github.com/ygorsttt-commits/API_First (branch `main`)
- Ambiente: Windows 11, WSL2 (sem distro Linux), Docker Desktop 29.9 instalado e testado. Docker Desktop precisa estar aberto.
- Feito: contrato v0.2.0, API + DynamoDB Local (persistência testada), métricas, painel, 12 testes. Último commit no GitHub: `41090ae` (antes do DynamoDB).
- Subagente `professor` em `.claude/agents/professor.md`: professor de dev e DevOps que guia o aprendizado

## Próximos passos (até o teste local)
1. ~~Contrato `openapi.yaml` + `.gitignore`~~ ✅
2. ~~Container de dev: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `requirements.txt`~~ ✅ (imagem `api_first-api` builda)
3. ~~API: `app/main.py`, `app/schemas.py`, `app/routes/tasks.py`~~ ✅ (rotas testadas via curl)
4. ~~Métricas: `app/metrics.py` + `GET /metrics`~~ ✅
5. ~~Painel: `app/static/painel.html` + `GET /painel`~~ ✅
6. ~~Testes: `tests/test_tasks.py`~~ ✅ (12 passando: `docker compose exec api pytest`)
7. Teste local: `docker compose up` → http://localhost:8080/painel

Obs.: porta local é **8080** e publicada só em IPv4 (`127.0.0.1:8080:8000`): o encaminhamento IPv6 do Docker trava neste PC.
8. (opcional) `.devcontainer/devcontainer.json`

Depois: conta AWS (IAM, MFA, orçamento), AWS CLI, Terraform → deploy no ECS.

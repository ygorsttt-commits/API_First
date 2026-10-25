# Plano de implementação — AI Software Delivery Toolkit

Status atualizado ao fim de cada fase. Legenda: ✅ concluído · 🟡 parcial · ⏳ pendente.

## Inspeção inicial (Fase 1) ✅

| Item | Situação encontrada |
|---|---|
| Repositório | Vazio (apenas `README.md` com o título). Nada a preservar além dele. |
| Python | 3.13 no host; sandbox usa `python:3.12-slim`. |
| Node | 22.x, npm 10, pnpm 10. |
| PostgreSQL | 16 instalado localmente (cluster precisa ser iniciado: `service postgresql start`). |
| Docker | CLI 29 + Compose v5; o daemon não sobe sozinho no ambiente de desenvolvimento (iniciar `dockerd`). `--network none`, `--memory`, `--cpus`, `--read-only` funcionam. |
| Terraform | Não instalado. Binário baixável de releases.hashicorp.com; **registry.terraform.io bloqueado** pelo proxy, então `terraform init/validate` local não baixa providers. `terraform fmt` funciona offline. |
| Scanners | ruff, mypy, pytest presentes; bandit via pip; gitleaks/checkov/semgrep ausentes. |

### Decisões adotadas (pequenas, documentadas)

- **Fila de jobs no PostgreSQL** (`SELECT ... FOR UPDATE SKIP LOCKED`) em vez de Redis/Celery — menos uma peça no MVP.
- **Orquestração determinística**: cada tipo de execução é uma lista fixa de etapas com timeout, tentativas, permissões e schemas de entrada/saída. A IA não escolhe a próxima etapa.
- **Aprovações vinculadas a hash** (SHA-256 do conteúdo canônico aprovado). Qualquer mudança invalida a aprovação.
- **Execução de código gerado só no sandbox Docker** (sem rede, read-only, limites de CPU/memória/PIDs/tempo/saída). Sem Docker, checagens que executam código ficam `skipped` — nunca rodam no host.
- **Comandos vêm de um registro de ferramentas fixo** (argv pré-definido). O modelo nunca fornece comandos.
- **Frontend fala com a API por um proxy server-side do Next.js**: o token da API fica no servidor, nunca no browser.
- **Testes do backend** rodam em SQLite por padrão (rápido) e em PostgreSQL quando `TEST_DATABASE_URL` está definido (CI faz os dois).
- **Scanners embutidos** (secret scanning, políticas de IaC, pinagem de dependências) rodam em processo por serem só leitura de texto; ferramentas externas (ruff, bandit, pytest, terraform) rodam no sandbox.

## Fases

| Fase | Escopo | Status |
|---|---|---|
| 1 | Inspeção, plano, documentação inicial | ✅ |
| 2 | Frontend e API mínimos, health check, configuração, testes, README | ✅ |
| 3 | Banco (SQLAlchemy + Alembic): projetos, execuções, etapas, eventos, artefatos, aprovações, auditoria | ✅ |
| 4 | Interface funcional + modo demo identificado | ✅ |
| 5 | Gateway de IA (`LLMProvider`, Demo, Claude), saídas estruturadas validadas | ✅ |
| 6 | Worker, orquestração, workspaces isolados, geração de código | ✅ |
| 7 | Testes, scanners e relatórios DevSecOps no sandbox | ✅ (ver limitações) |
| 8 | Terraform + GitHub Actions gerados para o projeto do usuário; CI do próprio toolkit | 🟡 `terraform validate` local bloqueado pelo registry; roda no CI |
| 9 | Integração GitHub e deploy AWS dev com aprovação | 🟡 interfaces + alvo simulado; alvo AWS recusa execução até ser configurado |
| 10 | Endurecimento, E2E, documentação completa | 🟡 E2E da API coberto; E2E de browser pendente |

## Próximos passos

1. `GitHubProvider` real (GitHub App, criação de repositório/PR a partir do workspace).
2. `AwsTerraformDeployTarget`: `terraform plan` no sandbox com credenciais OIDC temporárias, exibir plano, `apply` só após aprovação vinculada ao hash do plano.
3. Mirror local de providers Terraform para `terraform validate` offline no sandbox.
4. Autenticação real (OIDC/SSO) substituindo tokens estáticos; RBAC por organização.
5. Testes E2E de navegador (Playwright) no CI.
6. Streaming de eventos (SSE) no lugar de polling.

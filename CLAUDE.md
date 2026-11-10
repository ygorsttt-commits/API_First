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

## Boas práticas DevOps (OBRIGATÓRIAS)
O Ygor não tem experiência para pegar desvios: **Claude é responsável por seguir estas regras sem que ele precise pedir**. Se uma regra precisar ser quebrada (ex.: falta CD), avisar ANTES, explicar o risco e pedir autorização. Ao fim de cada etapa, conferir esta lista.

Fontes: [HashiCorp — Terraform workflow](https://developer.hashicorp.com/terraform/intro/core-workflow) e [Running Terraform in automation](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform) · [AWS Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html) · [DORA capabilities](https://dora.dev/capabilities/) · [GitHub Actions security hardening](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions) · [The Twelve-Factor App](https://12factor.net/pt_br/)

**Fluxo de mudança (código e infra)**
1. Toda mudança nasce numa branch e entra na `main` só por PR com CI verde. (DORA: version control, trunk-based development)
2. Infra: `plan` → revisão no PR → merge → `apply` **a partir da `main`**. Nunca `apply` antes do merge. O revisor deve ver o `plan` (o que cria/altera/destrói e custo) antes de aprovar. (HashiCorp core workflow; AWS OPS: "make frequent, small, reversible changes")
3. `apply` sempre de um plano salvo (`plan -out` → `apply arquivo.tfplan`), para executar exatamente o que foi revisado. Conferir que não há `destroy`/`replace` inesperado. (HashiCorp automation)
4. A `main` deve refletir exatamente o que existe na nuvem; nada criado à mão no console (sem drift). (AWS OPS: IaC; HashiCorp)
5. Mudanças pequenas e frequentes; uma etapa = um PR. (DORA: working in small batches)

**Build e deploy**
6. Build once, deploy many: a imagem é construída uma vez, com tag imutável = commit, e a mesma imagem é promovida entre ambientes. (DORA: deployment automation; 12-Factor V. Build, release, run)
7. Configuração por variáveis de ambiente, nunca no código. Dev e produção o mais parecidos possível. (12-Factor III e X)
8. Testes automatizados e scan de segurança no CI antes do merge. (DORA: continuous integration, test automation; AWS SEC)
9. Toda mudança deve ter caminho de volta (rollback: tag anterior da imagem / revert do PR). (AWS REL)

**Segurança**
10. Menor privilégio em IAM: cada role só com as ações e recursos de que precisa. (AWS SEC 3)
11. Sem credenciais de longa duração: humanos via SSO, CI/CD via OIDC. Nunca chaves de acesso no repositório ou nos secrets. (AWS SEC 2; GitHub hardening)
12. GitHub Actions: `permissions` mínimas por workflow e actions de terceiros fixadas pelo **SHA completo do commit** (tag pode ser movida). (GitHub hardening)
13. Nunca commitar segredos, `.tfstate` ou `.tfvars`. State em backend remoto criptografado com lock quando houver CI/CD. (HashiCorp; AWS SEC)
14. Criptografia em repouso e acesso público bloqueado por padrão (S3, bancos). (AWS SEC 8)

**Operação e custo**
15. Logs centralizados e health check em todo serviço. (AWS OPS: observability; 12-Factor XI)
16. Tags em todos os recursos (`Project`, `ManagedBy`). (AWS COST: cost allocation)
17. Antes de criar algo que custa: mostrar custo/hora e custo/mês; desligar (`destroy`) o que não está em uso. Alertas de orçamento ativos. (AWS COST)

**Desvios conhecidos (dívida técnica a corrigir)**
- Infra criada com `apply` antes do merge (PRs #10 e infra/ecs-fargate) — corrigido a partir daqui pela regra 2.
- ~~State do Terraform local (regra 13)~~ ✅ state da app em `s3://api-first-tfstate-265469156400/app/terraform.tfstate` (lock nativo `use_lockfile`).
- ~~Actions fixadas por tag, não por SHA (regra 12)~~ ✅ corrigido (Dependabot mantém os SHAs atualizados).
- Deploy manual do PC, sem CD/OIDC (regras 6 e 11) — resolver nas Fases 3 e 5.
- Usuário SSO com AdministratorAccess (regra 10) — aceitável para conta pessoal de estudo; revisar depois.
- Role `api-first-github-deploy` com AdministratorAccess (regra 10) — mitigado: só o GitHub Environment `aws` (aprovação manual) pode assumir. Refinar para permissões mínimas.
- State do `infra/bootstrap/` é local (por design: ele cria o bucket). Guardar o arquivo `infra/bootstrap/terraform.tfstate`; não apagar.
- Sem rollback documentado (regra 9) — documentar com o CD.

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
- **Git (fluxo profissional)**: nunca commitar direto na `main`. Todo trabalho em branch (`feat/`, `fix/`, `docs/`, `chore/`, `ci/`, `infra/`) + Pull Request. Commits em Conventional Commits com descrição em português (`feat: adiciona rota de usuários`). Sem `gh` instalado: fazer push da branch e passar o link para o Ygor abrir o PR.
- **Qualidade**: lint com `ruff` (config em `pyproject.toml`); rodar `docker compose exec api ruff check .` e `pytest` antes de commitar.
- **Dependências**: `requirements.txt` = produção (vai para a imagem); `requirements-dev.txt` = teste/lint (só no compose via `INSTALL_DEV=true` e no CI). Dockerfile roda `apt-get upgrade` para correções de segurança.
- **Windows**: sem `make`; comandos ficam documentados no README.

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
- AWS sem ALB por enquanto (custo fixo ~US$ 23/mês parado): ECS Fargate com IP público. ALB entra depois, como etapa de estudo. Dev/prod separados e OIDC também ficam para depois — foco atual: ver o Terraform criando infra.
- Terraform em `infra/` (state local por enquanto): `terraform.tf`, `providers.tf`, `variables.tf`, `dynamodb.tf`, `ecr.tf`, `network.tf` (VPC padrão + SG só p/ o IP do Ygor), `iam.tf`, `ecs.tf`, `outputs.tf`. Rodar com o perfil `estudos`. `infra/terraform.tfvars` (local, fora do Git) define `allowed_cidr` e `image_tag`.
- Deploy manual: build → push no ECR com tag = hash curto do commit → `image_tag` no tfvars → `terraform apply`. No Windows o `docker login` no ECR falha (credential store): usar `DOCKER_CONFIG` temporário com o auth gravado direto.
- IP público do container muda a cada reinício: obter via `aws ecs list-tasks` → `describe-tasks` (ENI) → `ec2 describe-network-interfaces`.
- Para zerar custo do ECS sem perder DynamoDB/ECR: `terraform destroy -target=aws_ecs_service.api` (ou destroy completo).
- Painel web em `/painel` (HTML+JS servido pela API) para testar a API e ver observabilidade via `GET /metrics` (requisições, erros, tempo médio, por rota, últimas requisições).

## Estado atual
- Repositório: https://github.com/ygorsttt-commits/API_First (branch `main`)
- Ambiente: Windows 11, WSL2 (sem distro Linux), Docker Desktop 29.9 instalado e testado. Docker Desktop precisa estar aberto.
- Feito: contrato v0.2.0, API + DynamoDB Local (persistência testada), métricas, painel, 12 testes. Tudo commitado no GitHub (`6663174`).
- AWS: conta criada (plano Free), MFA no root, IAM Identity Center com usuário `ygor` (AdministratorAccess, sessão 8h). Região padrão `us-east-1`.
- PC: AWS CLI 2.39 + Terraform 1.17 instalados. Perfil SSO **`estudos`** (`aws sso login --profile estudos` quando expirar). Usar sempre `--profile estudos` / `AWS_PROFILE=estudos`.
- Orçamentos criados via CLI (e-mail ygorsttt@gmail.com): `alerta-gasto-zero` (> US$ 0,01) e `limite-mensal` (US$ 5: 85% real / 100% previsto).
- Se a AWS der "Signature expired": relógio do PC atrasado → sincronizar hora do Windows.
- Subagente `professor` em `.claude/agents/professor.md`: professor de dev e DevOps que guia o aprendizado

## Plano CI/CD (padrão empresa)
Fluxo: branch → PR → CI (lint, testes, OpenAPI, build Docker, Trivy, terraform plan) → revisão → merge na `main` protegida → CD (build → ECR → aprovação manual no Environment `dev` → terraform apply → smoke test `/health`). GitHub acessa a AWS via **OIDC** (sem chaves). State do Terraform em S3. Workflow `destroy` para zerar custo.
1. ~~Base do repo~~ ✅ (PR #2)
2. ~~CI~~ ✅ (`ci.yml`: qualidade, contrato, imagem/Trivy; PRs #8, #9). Ruleset `protege-main` ativo: exige PR + 3 checks verdes.
3. ~~Bootstrap AWS (`infra/bootstrap/`): S3 do state + OIDC~~ ✅ (PR #13)
4. Infra da app (`infra/`): DynamoDB, ECR, VPC, ECS, ALB — em andamento: state no S3 ✅ (PR #14), `terraform plan` no CI via OIDC ✅ (PR #15).
   - Job "Terraform plan" roda só em PRs, com a role só-leitura `api-first-github-plan`. Usa as *variables* do repositório `TF_ALLOWED_CIDR` e `TF_IMAGE_TAG` (atualizar se o IP ou a imagem mudarem).
   - O GitHub envia o `sub` do OIDC com IDs: `repo:ygorsttt-commits@250064056/API_First@1432740330:...` (PR #16). A confiança das roles usa esse formato.
   - Local: rodar Terraform com `$env:AWS_PROFILE='estudos'` (o backend S3 não lê o tfvars).
5. CD: `cd.yml` + `destroy.yml`

## Histórico: até o teste local
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

# Gitinho

Agente conversacional que responde, com precisão, perguntas em linguagem
natural sobre uma organização do GitHub. Estilo ChatGPT: sidebar de
conversas, histórico persistente, streaming token-a-token, exportação
para Excel.

> **Fase 1: read-only.** Permissões da GitHub App restritas a leitura.
> Tools de escrita não estão registradas no runtime. Fase 2 (futura)
> adicionará escrita com confirmação humana.

## Capacidades (exemplos de perguntas)

- Qual o último issue criado pelo usuário X?
- Quantos PR/issues foram feitos pelo usuário Y este mês?
- Quantos datapackages possuímos? Quantos públicos e privados?
- Liste todos os repositórios com campos A, B, C e gere um Excel.
- Qual o último commit do usuário Z no repositório B?
- Quantos PRs estão abertos em toda a organização?
- Quais repositórios não recebem atualização há mais de 180 dias?
- Quais repositórios têm mais de 1 branch?
- Relatório de atividade por usuário (issues, commits, PRs, reviews,
  comentários, último commit).

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16
- **LLM**: Azure AI Foundry (OpenAI / Anthropic / etc) via OpenAI SDK
- **Agente**: OpenAI tool-calling com tools tipadas e auditadas
- **GitHub**: GitHub App (read-only) + GraphQL v4 + MCP server oficial
- **Frontend**: React 18 + Vite + TypeScript
- **Deploy**: Docker + Easy Panel

Documentação completa em [`docs/PLAN.md`](docs/PLAN.md),
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) e
[`docs/SECURITY.md`](docs/SECURITY.md).

## Estrutura

```
gitinho/
├── backend/        FastAPI + agent + tools
├── frontend/       React UI tipo ChatGPT
├── deploy/         docker-compose.yml + instruções Easy Panel
├── docs/           PLAN.md, ARCHITECTURE.md, SECURITY.md
├── legacy/         Stack Node.js original (preservada para referência)
└── .env.example
```

## Setup local (dev)

### 1. Pré-requisitos

- Docker Desktop
- Python 3.12 + Node 20 (apenas se quiser rodar fora do container)
- Uma **GitHub App** instalada na organização alvo com permissões
  read-only (veja `docs/PLAN.md` §3 e `docs/SECURITY.md`)
- Uma **GitHub OAuth App** (para login dos usuários)
- Acesso a um **Azure OpenAI / Foundry** com deployments dos modelos
  configurados em `.env`

### 2. Configurar variáveis

```bash
cp .env.example .env
# Edite .env preenchendo OAUTH_*, GH_APP_*, AZURE_OPENAI_*.
# Para SESSION_SECRET, gere com:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

mkdir -p secrets
# Coloque a chave privada da GitHub App em secrets/gh-app.pem
```

### 3. Subir

```bash
cd deploy
docker compose up -d --build
```

Acesse `http://localhost:8080`.

### 4. Logs

```bash
docker compose logs -f backend
```

## Comandos úteis

| Comando | Uso |
|---|---|
| `docker compose up -d --build` | sobe tudo |
| `docker compose down` | derruba tudo |
| `docker compose exec backend alembic upgrade head` | migração manual |
| `docker compose exec backend alembic revision --autogenerate -m "X"` | nova migração |
| `docker compose exec db psql -U gitinho` | shell SQL |

## Deploy em produção (Easy Panel na sua VM Azure)

Você já tem Easy Panel rodando com um projeto onde adiciona serviços.
Adicione 3 serviços a esse projeto (`gitinho-db`, `gitinho-backend`,
`gitinho-frontend`). Passo a passo completo em
[`deploy/easy-panel.README.md`](deploy/easy-panel.README.md).

## Suporte a múltiplas organizações

Cada deploy do Gitinho atende **uma única organização** (isolamento
total de dados). Para servir uma segunda org, clone o projeto no Easy
Panel com outros valores de `ALLOWED_ORG`, `GH_APP_*` e Postgres.

## Roadmap

- **Fase 1 (atual)**: read-only, todas as perguntas do brief.
- **Fase 2**: tools de escrita (criar issue, comentar, abrir PR) com
  confirmação humana obrigatória via UI.
- **Fase 3**: sync local em DuckDB para orgs grandes, webhook listener,
  dashboards salvos.

## Licença

MIT.

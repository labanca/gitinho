# Gitinho

Agente conversacional read-only para a organização `splor-mg` no GitHub.

## Stack

- **`apps/chat`** — fork vendored do [`cgoinglove/better-chatbot`](https://github.com/cgoinglove/better-chatbot)
  (Next.js 16, Vercel AI SDK, Better Auth, Drizzle ORM, Postgres).
- **`apps/mcp`** — servidor [MCP](https://modelcontextprotocol.io)
  Python expondo ~23 ferramentas read-only sobre a API do GitHub
  (organização, repos, issues, PRs, commits, discussions, atividade,
  exports XLSX). Usa GitHub App para acesso autenticado.

A separação MCP isola toda a lógica GitHub-específica do frontend de
chat, permite reusar as tools fora do chat (CLI, cron, CI) e abre a
porta para plugar outros servidores MCP (GitHub oficial, Postgres,
filesystem, etc.) sem código nosso.

## Pré-requisitos

- Node ≥ 22
- pnpm ≥ 10 (`corepack enable && corepack prepare pnpm@latest --activate`)
- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) ≥ 0.6
- Postgres ≥ 14 (local ou via Docker Compose em `deploy/`)
- GitHub App instalada na org com permissões: metadata, contents,
  pull_requests, issues, members, actions, projects.

## Setup local (resumo)

```bash
# 1. Variáveis
cp .env.example .env
# (preencha as variáveis — veja .env.example)

# 2. Dependências
pnpm install                    # apps/chat
uv sync --directory apps/mcp    # apps/mcp

# 3. Postgres
docker compose -f deploy/docker-compose.yml up -d postgres

# 4. Dev server (chat + MCP via stdio embutido)
pnpm chat:dev
```

## Estrutura

```
gitinho/
├── apps/
│   ├── chat/           Next.js (fork do better-chatbot)
│   └── mcp/            Servidor MCP Python (gitinho-mcp)
├── deploy/             Docker Compose, Easy Panel config
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── MIGRATION_BETTER_CHATBOT.md    Plano completo da migração atual
│   ├── PLAN.md
│   └── SECURITY.md
├── secrets/
│   └── gh-app.pem      Chave privada da GitHub App (não versionado)
└── .env                Não versionado
```

## Histórico

A versão pré-migração (FastAPI + React+Vite) está congelada em:

- Tag Git: `pre-migration-2026-05-25`
- Diretório irmão: `../gitinho-legacy/` (cópia completa, fora do repo)

Detalhes da migração: [`docs/MIGRATION_BETTER_CHATBOT.md`](docs/MIGRATION_BETTER_CHATBOT.md).

## Licença

MIT.

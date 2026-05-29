# Gitinho

Agente conversacional read-only para a organização **`splor-mg`** no
GitHub (configurável via `ALLOWED_ORG`). Responde com precisão a
perguntas em linguagem natural sobre repos, issues, PRs, commits,
atividade de usuários, datapackages — e gera planilhas sob demanda.

## Capacidades

Exemplos de perguntas que o Gitinho responde com precisão:

- Quantos PRs estão abertos em toda a organização?
- Quantos datapackages possuímos? Quantos públicos e privados?
- Liste todos os repositórios com campos X, Y, Z em uma planilha.
- Qual o último commit do usuário Z no repo B?
- Quais repositórios não recebem atualização há mais de N dias?
- Sobre o que é o repo X? (lê o README direto do GitHub)
- Mostre o `mkdocs.yml` / `datapackage.json` / `pyproject.toml` do
  repo X.
- Relatório completo de atividade por usuário (issues, commits, PRs,
  reviews, comentários, última interação).
- Suba este PDF/DOCX/XLSX e me ajude a interpretar.

## Stack

Monorepo (pnpm workspace + uv workspace):

- **`apps/chat/`** — fork vendored de
  [`cgoinglove/better-chatbot`](https://github.com/cgoinglove/better-chatbot)
  (Next.js 16, Vercel AI SDK, Better Auth, Drizzle ORM, Postgres).
- **`apps/mcp/`** — servidor [MCP](https://modelcontextprotocol.io)
  Python (`gitinho-mcp`) expondo **24 tools read-only** sobre a API do
  GitHub (repos, issues, PRs, commits, discussions, atividade,
  glossário, conteúdo de arquivos, ingest de documentos). Usa GitHub
  App para acesso autenticado.

A separação chat/MCP isola toda a lógica GitHub-específica do frontend,
permite reusar as tools fora do chat (CLI, cron, CI) e abre a porta para
plugar outros servidores MCP (GitHub oficial, Postgres, filesystem,
etc.) sem código nosso.

**Custom agents prontos**: `@Datapackages` (especialista em datapackages
Frictionless) e `@Atividade` (relatórios de atividade da org).
@-mention no chat input invoca um agente com prompt e tools restritas.

**Exports** acontecem pela tool nativa `createTable` — o agente busca
os dados via MCP, e a tabela renderizada na UI tem botões nativos de
download XLSX/CSV.

## Pré-requisitos

- Node ≥ 22 (`corepack enable && corepack prepare pnpm@latest --activate`)
- pnpm ≥ 10
- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) ≥ 0.6
- Docker Engine ≥ 24 (para Postgres e MinIO locais)
- **GitHub App** instalada na org com permissões read-only (Metadata,
  Contents, Issues, Pull requests, Discussions, Members). Detalhes em
  [`docs/SECURITY.md`](docs/SECURITY.md) §2.1.
- **GitHub OAuth App** (login do usuário). Reusa
  `Ov23lit3J2ceJ03kdZlO` no `splor-mg`.
- Azure AI Foundry (endpoint v1 OpenAI-compatible).

## Setup local

```bash
# 1. Variáveis
cp .env.example .env
# Preencha: ALLOWED_ORG, BETTER_AUTH_SECRET, GITHUB_CLIENT_*, GH_APP_*,
# OPENAI_COMPATIBLE_DATA. Veja docs/DEPLOY.md §3 para detalhes.

# 2. Chave privada da GitHub App
mkdir -p secrets
cp ~/Downloads/gitinho.<data>.private-key.pem secrets/gh-app.pem
chmod 600 secrets/gh-app.pem

# 3. Dependências
pnpm install
uv sync --directory apps/mcp

# 4. Postgres + MinIO
docker compose -f apps/chat/docker/compose.yml up -d postgres minio

# 5. Dev server (chat + MCP via stdio embutido)
pnpm chat:dev
```

Abra `http://localhost:3000` e faça login com sua conta GitHub
(precisa ser membro de `splor-mg` e autorizar o app para a org).

Primeira vez, popular os agentes nomeados:

```bash
pnpm --filter chat gitinho:seed-agents
```

## Estrutura

```
gitinho/
├── apps/
│   ├── chat/           Next.js (fork do better-chatbot)
│   │   └── docker/     Dockerfile + compose.yml de produção
│   └── mcp/            Servidor MCP Python (gitinho-mcp)
├── docs/
│   ├── ARCHITECTURE.md        diagramas e fluxos
│   ├── DEPLOY.md              produção via Easy Panel
│   ├── DECISIONS.md           log de decisões estruturais
│   ├── PLAN.md                plano e status de implementação
│   ├── SECURITY.md            modelo de ameaças + controles
│   └── MIGRATION_BETTER_CHATBOT.md   histórico da migração
├── secrets/
│   └── gh-app.pem      Chave privada da GitHub App (NÃO versionado)
├── pnpm-workspace.yaml
├── pyproject.toml      uv workspace
├── .env                NÃO versionado (template em .env.example)
└── README.md
```

## Deploy em produção

Stack rodando em VM com **Easy Panel**:
`gitinho-postgres` + `gitinho-minio` + `gitinho-chat` (com MCP Python
embarcado via stdio) + `gitinho-mc-bootstrap` (cria bucket one-shot).
Passo-a-passo em [`docs/DEPLOY.md`](docs/DEPLOY.md).

Para servir uma segunda org, replique o conjunto com sufixos no mesmo
projeto do Easy Panel — cada instância tem seu próprio `ALLOWED_ORG`,
GitHub App e banco.

## Inspecionar o servidor MCP

```bash
# Lista as tools registradas
uv run --directory apps/mcp python -m gitinho_mcp.scripts.list_tools

# UI interativa para testar cada tool
uv run --directory apps/mcp mcp dev gitinho_mcp/server.py
```

## Histórico

A versão pré-migração (FastAPI + React+Vite custom) está congelada em:

- Tag Git: `pre-migration-2026-05-25`
- Diretório irmão: `../gitinho-legacy/` (cópia completa, fora do repo)

Detalhes da migração: [`docs/MIGRATION_BETTER_CHATBOT.md`](docs/MIGRATION_BETTER_CHATBOT.md).
Racional das decisões estruturais: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Licença

MIT.

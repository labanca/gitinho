# Gitinho — Arquitetura

> Visão técnica do estado atual. Detalhes operacionais em
> [`DEPLOY.md`](./DEPLOY.md); controles de segurança em
> [`SECURITY.md`](./SECURITY.md); racional das decisões em
> [`DECISIONS.md`](./DECISIONS.md).

## 1. Visão Geral

Monorepo com duas aplicações e dois serviços de infra:

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Browser do usuário (HTTPS)                        │
│  Chat tipo ChatGPT │ Threads │ Streaming │ Login GitHub OAuth        │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTPS via Easy Panel proxy
                           │ Cookie HttpOnly de sessão (Better Auth)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  apps/chat — Next.js 16 (fork better-chatbot)                        │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Better Auth: GitHub OAuth + hook de allowlist por org          │  │
│  │ App Router: /api/chat, /api/thread, /api/mcp, /api/export      │  │
│  │ Vercel AI SDK: streamText + tools nativas (createTable, etc.)  │  │
│  │ Drizzle ORM: threads, messages, agents, mcp_servers, users     │  │
│  │ File ingest: PDF/DOCX/PPTX/XLSX via tool MCP convert_document  │  │
│  └─────────────────────────┬──────────────────────────────────────┘  │
└────────────────────────────┼─────────────────────────────────────────┘
                             │ stdio (FILE_BASED_MCP_CONFIG=true)
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  apps/mcp — gitinho-mcp (Python 3.12)                                │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ FastMCP server (mcp SDK oficial)                               │  │
│  │ 25 tools auto-registradas via @mcp.tool()                      │  │
│  │  ├── repos/users/issues/pulls/commits/discussions/activity     │  │
│  │  ├── glossary (lê <org>/.github/gitinho-context.md)            │  │
│  │  └── documents (MarkItDown)                                    │  │
│  │ GitHub client: GitHub App (JWT RS256 → installation token)     │  │
│  │ OrgAllowlistError em qualquer owner ≠ ALLOWED_ORG              │  │
│  └─────────────────────────┬──────────────────────────────────────┘  │
└────────────────────────────┼─────────────────────────────────────────┘
                             │ HTTPS
                             ▼
                    ┌─────────────────────┐
                    │   api.github.com    │
                    │   (REST + GraphQL)  │
                    └─────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│  Infra (mesma rede Docker, sem portas no host além do proxy)         │
│   postgres:5432    Drizzle schema (Better Auth + chats + agents)     │
│   minio:9000/9001  S3-compat para uploads do file ingest             │
└──────────────────────────────────────────────────────────────────────┘
```

`gitinho-mcp` roda **dentro do mesmo container** que `apps/chat` via
stdio — `FILE_BASED_MCP_CONFIG=true` aponta o better-chatbot para um
`.mcp-config.json` que executa `uv run python -m gitinho_mcp`. Sem rede,
sem CORS, sem porta exposta.

## 2. Componentes em Detalhe

### 2.1 `apps/chat/` — Next.js 16 (fork do better-chatbot)

Estrutura relevante:

```
apps/chat/src/
├── app/
│   ├── api/
│   │   ├── chat/route.ts        streamText + tools (entrypoint do chat)
│   │   ├── thread/              CRUD de threads
│   │   ├── mcp/                 introspecção de servers MCP
│   │   └── export/[id]/         download de exports persistidos
│   ├── (auth)/sign-in           login Better Auth
│   ├── (chat)/                  UI principal
│   └── (public)/                rotas públicas (compartilhar thread, export)
├── components/
│   ├── chat-bot.tsx             componente principal de chat
│   ├── chat-mention-input.tsx   @-mention de agents
│   └── ...
├── lib/
│   ├── ai/
│   │   ├── prompts.ts           system prompt do Gitinho (4 camadas)
│   │   ├── agent/
│   │   │   └── gitinho-agents.ts  @Datapackages + @Atividade
│   │   ├── tools/               tools nativas (createTable, etc.)
│   │   └── ingest/
│   │       └── markdown-ingest.ts  chama convert_document do MCP
│   ├── auth/
│   │   ├── auth-instance.ts     Better Auth + hook signIn.before
│   │   └── github-org-allowlist.ts  enforce de ALLOWED_ORG
│   └── db/
│       ├── pg/schema.pg.ts      Drizzle schema
│       └── repository/          acesso por entidade
└── scripts/
    └── seed-gitinho-agents.ts   popula @Datapackages e @Atividade
```

### 2.2 `apps/mcp/` — Servidor MCP Python

```
apps/mcp/gitinho_mcp/
├── __main__.py        entry point: `python -m gitinho_mcp`
├── server.py          FastMCP("gitinho")
├── config.py          settings (env-driven via pydantic-settings)
├── github/
│   ├── app_auth.py    JWT GitHub App + installation token cacheado
│   ├── client.py      httpx async + retries + rate-limit
│   ├── graphql.py     queries nomeadas para totalCount agregado
│   └── pagination.py  iterador async de páginas REST
└── tools/
    ├── _context.py    ToolContext (env, gh client, allowed_org)
    ├── repos.py       7 tools
    ├── issues.py      3 tools
    ├── pulls.py       3 tools
    ├── commits.py     2 tools
    ├── users.py       2 tools
    ├── activity.py    2 tools
    ├── discussions.py 1 tool
    ├── glossary.py    1 tool (get_org_glossary)
    └── documents.py   1 tool (convert_document, MarkItDown)
```

Cada tool é registrada via decorator `@mcp.tool()` do SDK MCP oficial; o
schema é inferido da assinatura Python. Toda chamada ao GitHub passa por
`github/client.py`, que recusa qualquer URL cujo owner não seja
`ALLOWED_ORG` (defesa em profundidade — última linha mesmo se o App for
mal-configurado).

## 3. Fluxo de uma Pergunta

```
1. Usuário: "Quantos PRs abertos temos?"
   ↓
2. POST /api/chat
   ├── Better Auth resolve sessão → user.id
   ├── thread/message persistidos via Drizzle
   └── streamText() do Vercel AI SDK
   ↓
3. LLM (Azure Foundry) recebe:
   ├── system prompt do Gitinho (lib/ai/prompts.ts)
   ├── tools do MCP `gitinho` (descobertas via stdio na partida)
   └── tools nativas (createTable, image gen, etc.)
   ↓
4. LLM decide: chamar count_open_prs()
   ↓
5. better-chatbot envia tool call ao gitinho-mcp via stdio
   ↓
6. gitinho-mcp:
   ├── GitHub App JWT → installation token (cache 50min)
   ├── GraphQL query OrgOpenPRs com totalCount
   └── retorna {"count": 42}
   ↓
7. LLM formata em markdown + streama tokens
   ↓
8. UI renderiza:
   ├── chip "🔧 count_open_prs"
   ├── texto streamed token-a-token
   └── (se o LLM chamou createTable) tabela com botão de download
```

## 4. Precisão via GraphQL

REST exige paginação e várias chamadas (N+1) para somar contagens.
GraphQL devolve `totalCount` agregado em uma requisição.

Exemplo — contar PRs abertos da org:

```graphql
query OrgOpenPRs($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        pullRequests(states: OPEN) { totalCount }
      }
    }
  }
}
```

Tools que usam essa estratégia: `count_open_prs`, `count_open_issues`,
`count_repos`, `count_user_contributions`, `org_users_activity_report`.

O LLM **nunca** soma resultados parciais — o system prompt instrui a
chamar a tool dedicada em vez de iterar e calcular mentalmente.

## 5. Custom Agents

Implementados via mecanismo do better-chatbot. Cada agente:

- Tem `instructions.systemPrompt` em português.
- Define `mentions` (tools permitidas, mix de MCP + nativas).
- É invocado via `@nome` no chat input.
- Não substitui o agente default (sem @-mention, todas as tools disponíveis).

Definições em `apps/chat/src/lib/ai/agent/gitinho-agents.ts`; população
inicial via `pnpm --filter chat gitinho:seed-agents`.

## 6. Streaming

Vercel AI SDK + UI Message Stream:

- Frontend usa `useChat()` do AI SDK; consumo via streaming chunks.
- Eventos visuais: token, tool-invocation (chip), tool-result (resumo),
  step-finish (transição de etapa do agente).
- Mermaid e code blocks ricos renderizam em tempo real.

## 7. File Ingest

Pipeline para arquivos enviados no chat (PDF/DOCX/PPTX/XLSX):

1. UI faz upload para MinIO (via API do Next.js).
2. `apps/chat/src/lib/ai/ingest/markdown-ingest.ts` baixa o arquivo do
   MinIO e chama a tool MCP `convert_document` com o conteúdo binário.
3. `apps/mcp/gitinho_mcp/tools/documents.py` usa **MarkItDown** para
   converter para markdown.
4. O markdown é injetado no contexto da próxima mensagem do LLM.

Falhas degradam silenciosamente (loga `convert_document failed`, segue
sem o conteúdo).

## 8. Persistência (Drizzle)

Schema em `apps/chat/src/lib/db/pg/schema.pg.ts`. Tabelas principais:

| Tabela | Propósito |
|---|---|
| `user` | Conta Better Auth (id, email, role, name, image) |
| `session` | Sessão ativa (HttpOnly cookie) |
| `account` | Provedor OAuth ligado (no nosso caso, GitHub — sem tokens armazenados) |
| `verification` | Tokens de verificação Better Auth |
| `thread` | Conversa do chat |
| `message` | Mensagem de uma thread (user/assistant/tool, jsonb com tool calls) |
| `agent` | Agente customizado (@Datapackages, @Atividade, etc.) |
| `mcp_server` | Servers MCP plugados (no nosso caso, vem do `.mcp-config.json`) |
| `workflow` | Pipelines no-code (não usado em Fase 1) |

Migrations: Drizzle Kit + script `db:migrate` rodado no startup do
container `chat`. Nenhum dado é migrado da stack antiga FastAPI —
clean cutover, pois a Fase 1 anterior nunca chegou a ter dados de
produção.

## 9. Configuração (.env)

Variáveis principais. Detalhes em [`docs/DEPLOY.md`](./DEPLOY.md) §3.

```bash
# Org alvo
ALLOWED_ORG=splor-mg

# Postgres (compose interno)
POSTGRES_URL=postgres://gitinho:CHANGE_ME@postgres:5432/gitinho

# Better Auth
BETTER_AUTH_SECRET=<openssl rand -base64 32>
BETTER_AUTH_URL=https://gitinho.<seu-dominio>

# GitHub OAuth (login)
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...

# Bloqueia caminhos não-OAuth
DISABLE_EMAIL_SIGN_IN=1
DISABLE_EMAIL_SIGN_UP=1
DISABLE_SIGN_UP=1

# Azure Foundry via adapter OpenAI-compatible
OPENAI_COMPATIBLE_DATA=<JSON do helper>

# GitHub App (apps/mcp)
GH_APP_ID=...
GH_APP_INSTALLATION_ID=...
GH_APP_PRIVATE_KEY_PATH=./secrets/gh-app.pem

# MCP
FILE_BASED_MCP_CONFIG=true
NOT_ALLOW_ADD_MCP_SERVERS=1

# File ingest (MinIO)
FILE_STORAGE_TYPE=s3
FILE_STORAGE_S3_BUCKET=gitinho-uploads
FILE_STORAGE_S3_ENDPOINT=http://minio:9000
AWS_ACCESS_KEY_ID=minio
AWS_SECRET_ACCESS_KEY=...
```

## 10. Deploy

Stack rodando em uma VM Azure com **Easy Panel**:

| Service | Imagem | Notas |
|---|---|---|
| `gitinho-postgres` | Postgres 17 | Volume persistente; backup diário |
| `gitinho-minio` | `minio/minio` | Console e API só em 127.0.0.1 |
| `gitinho-chat` | build de `apps/chat/docker/Dockerfile` | MCP Python embarcado via stdio; bind 127.0.0.1:3000 |
| `gitinho-mc-bootstrap` | `minio/mc` (one-shot) | Cria bucket `gitinho-uploads` |

Proxy do Easy Panel termina TLS e roteia para `gitinho-chat:3000`.
Detalhes passo-a-passo em [`docs/DEPLOY.md`](./DEPLOY.md).

Para servir uma segunda org: replicar o conjunto com sufixos
(`gitinho-<org2>-postgres`, `gitinho-<org2>-chat`, etc.) no mesmo
projeto Easy Panel. Cada instância tem seu próprio `ALLOWED_ORG`,
GitHub App e DB.

## 11. Observabilidade

- **Logs**: stdout do container `chat` carrega Next.js + gitinho-mcp
  (stdio). `docker compose logs -f chat` mostra ambos. Formato JSON
  estruturado com `correlation_id` por requisição.
- **Métricas**: não há endpoint Prometheus em Fase 1.
- **Auditoria**: tool calls e eventos sensíveis (login negado, tentativa
  de owner fora da allowlist) ficam nos logs estruturados — não há
  tabela `audit_log` separada nesta migração.
- **Health**: Next.js responde 200 em `/`; Easy Panel monitora o port.

## 12. Testes

- **Unit/auth**: `apps/chat/src/lib/auth/github-org-allowlist.test.ts`
  cobre o enforce de allowlist por org.
- **E2E**: Playwright já configurado pelo upstream em `apps/chat/tests/`.
- **Smoke MCP**: `apps/mcp/scripts/smoke_test.py`,
  `apps/mcp/scripts/smoke_glossary.py`,
  `apps/mcp/scripts/smoke_documents.py` exercitam cada grupo de tools.
- **MCP Inspector**: `uv run --directory apps/mcp mcp dev gitinho_mcp/server.py`
  abre UI no navegador para testar tools individualmente.

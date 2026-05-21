# Gitinho — Arquitetura

> Resumo executivo das decisões técnicas. Detalhes operacionais em
> `PLAN.md`; controles de segurança em `SECURITY.md`.

## 1. Visão Geral

Aplicação web full-stack com 4 processos:

1. **frontend** — React 18 + Vite + TypeScript, build estático servido
   por Nginx.
2. **backend** — FastAPI (uvicorn) com a API HTTP, runtime do agente,
   tools e cliente GitHub.
3. **mcp** — `github/github-mcp-server` (binário oficial) rodando como
   processo filho ou container separado, exposto via stdio/sse para o
   backend.
4. **db** — PostgreSQL 16 com volume persistente.

## 2. Componentes Internos do Backend

```
app/
├── main.py              FastAPI app, lifespan, routers
├── config.py            Settings (pydantic-settings, .env-driven)
├── logging_setup.py     JSON logger + redaction filter
├── deps.py              Dependency-injection (db, settings, current_user)
│
├── auth/
│   ├── oauth.py         GitHub OAuth flow
│   ├── session.py       Cookie HttpOnly, CSRF, rotation
│   ├── allowlist.py     Membership na org alvo
│   └── csrf.py
│
├── github/
│   ├── app_auth.py      JWT GitHub App + installation token cache
│   ├── client.py        httpx async client + retries + rate-limit
│   ├── graphql.py       Queries GraphQL nomeadas (agregadas, precisas)
│   ├── pagination.py    Iterador async de páginas
│   └── allowlist.py     Bloqueia owner ≠ ALLOWED_ORG (defesa em prof.)
│
├── mcp/
│   └── client.py        Cliente MCP (stdio) para github-mcp-server
│
├── agent/
│   ├── runner.py        Pydantic-AI Agent, streaming SSE
│   ├── prompts.py       System prompt + few-shots
│   ├── tool_registry.py Carrega tools READ/WRITE conforme flag
│   ├── memory.py        Janela de contexto + sumarização leve
│   └── safety.py        Guardrails (modo write bloqueado)
│
├── tools/
│   ├── _base.py         Tool decorator com mode/audit
│   ├── repos.py
│   ├── issues.py
│   ├── pulls.py
│   ├── commits.py
│   ├── users.py
│   ├── discussions.py
│   ├── search.py
│   ├── activity.py
│   └── exports.py       Geração de XLSX
│
├── api/
│   ├── auth_routes.py
│   ├── chats.py
│   ├── messages.py
│   ├── stream.py        SSE
│   ├── exports.py
│   └── health.py
│
└── db/
    ├── base.py          Declarative base, naming convention
    ├── models.py        ORM
    ├── session.py       Async session factory
    └── repositories/    Acesso por entidade
```

## 3. Fluxo de uma Pergunta

```
┌──────────────────────────────────────────────────────────────────────┐
│ Usuário digita: "Quantos PRs abertos temos?"                         │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
   POST /api/chats/{id}/messages  → persiste msg user
                               ▼
   GET  /api/chats/{id}/stream    → abre SSE
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Agent.run_stream(history + new_msg)                                  │
│  1. LLM decide tool: count_open_prs()                                │
│  2. tool_registry.dispatch("count_open_prs", {})                     │
│      → tools.pulls.count_open_prs() → graphql.query("OrgOpenPRs")    │
│      → retorna {"count": 42}                                         │
│  3. LLM formata resposta: "A organização tem 42 PRs abertos. (...)"  │
│  4. SSE streama tokens                                               │
│  5. Persiste assistant msg + tool_calls                              │
└──────────────────────────────────────────────────────────────────────┘
```

## 4. GraphQL: Por que Importa para Precisão

REST exige paginação manual e várias chamadas (N+1) para somar contagens.
GraphQL devolve `totalCount` e dados agregados em uma única requisição.

Exemplo: contar PRs abertos da org

```graphql
query OrgOpenPRs($org: String!) {
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

Soma exata, em 1-3 requests (dependendo do nº de repos). Sem
aproximação.

## 5. Streaming

- Backend: `EventSourceResponse` (sse-starlette) com eventos:
  - `event: token` — fragmento de texto
  - `event: tool_call` — nome + args (para UI mostrar "🔧 consultando…")
  - `event: tool_result` — resumo (não payload bruto)
  - `event: done` — fim
  - `event: error` — erro com correlation_id
- Frontend: `EventSource` em `/api/chats/{id}/stream`.

## 6. Persistência de Chats

Padrão ChatGPT-like:

- Sidebar lista chats do usuário (ordem por `updated_at` desc).
- Título do chat: gerado pelo LLM leve após a 1ª mensagem
  (`generate_chat_title` background task).
- Mensagens carregam paginadas; histórico para o LLM usa janela
  + sumarização.
- Ações: renomear, arquivar (não deletar — preserva auditoria).

## 7. Configuração (.env)

```bash
# App
APP_ENV=production            # development | production
APP_BASE_URL=https://gitinho.<seu-dominio>
SESSION_SECRET=<32+ chars>
MAINTENANCE_MODE=false

# Organização alvo
ALLOWED_ORG=splor-mg

# GitHub OAuth (login dos usuários)
OAUTH_CLIENT_ID=<github oauth app id>
OAUTH_CLIENT_SECRET=<...>
OAUTH_REDIRECT_URI=${APP_BASE_URL}/auth/github/callback

# GitHub App (acesso aos dados da org)
GH_APP_ID=<numérico>
GH_APP_INSTALLATION_ID=<numérico>
GH_APP_PRIVATE_KEY_PATH=/run/secrets/gh-app.pem

# Azure OpenAI / Foundry
AZURE_OPENAI_ENDPOINT=https://<recurso>.openai.azure.com
AZURE_OPENAI_API_KEY=<...>
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_DEPLOYMENT_ORCHESTRATOR=gpt-4.1
AZURE_DEPLOYMENT_ANALYTIC=o3
AZURE_DEPLOYMENT_LIGHT=gpt-4.1-mini

# Postgres
DATABASE_URL=postgresql+psycopg://gitinho:<pwd>@db:5432/gitinho

# Modo do agente
AGENT_ALLOW_WRITE=false        # fase 1: sempre false
AGENT_MAX_STEPS=12
AGENT_TIMEOUT_S=120

# Rate-limit
RATE_LIMIT_USER_PER_MIN=60
RATE_LIMIT_IP_PER_MIN=20

# Logs
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## 8. Deploy no Easy Panel

Estratégia: cada serviço como um **App** no Easy Panel apontando para
imagem do registry (GitHub Container Registry).

- `gitinho-backend` — image `ghcr.io/<você>/gitinho-backend:<tag>`,
  porta 8000, env vars, depende de `db`.
- `gitinho-frontend` — image `ghcr.io/<você>/gitinho-frontend:<tag>`,
  porta 80 (Nginx).
- `gitinho-mcp` — image `ghcr.io/<você>/gitinho-mcp:<tag>`,
  modo stdio via socket compartilhado (ou container com porta interna).
- `gitinho-db` — Postgres oficial.

CI/CD: GitHub Actions roda lint + tests + build + push para registry; o
Easy Panel puxa pela tag (webhook ou polling).

Para uma segunda org: clonar o App no Easy Panel, trocar `ALLOWED_ORG`,
`GH_APP_*` e o `DATABASE_URL` (ou DB separado).

## 9. Observabilidade

- Logs JSON em stdout (Easy Panel coleta).
- Métricas via endpoint `/metrics` (Prometheus, opt-in).
- Tracing leve via correlation_id propagado entre tool calls.
- Health: `/healthz` (liveness) + `/readyz` (DB + GitHub App + Azure).

## 10. Testes (Fase 1 mínima)

- `pytest` + `pytest-asyncio`.
- Tools: testes com VCR / cassettes contra GitHub (gravados uma vez).
- Auth: testes de allowlist (usuário fora da org é negado).
- API: testes de smoke dos endpoints.
- Agent: teste com modelo dummy que devolve resposta canônica para
  validar streaming + persistência.

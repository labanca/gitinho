# Gitinho — Plano de Implementação (Fase 1)

> Agente conversacional para responder, com precisão, perguntas em linguagem
> natural sobre uma organização do GitHub. Read-only por padrão, preparado
> para receber capacidades de escrita em fase 2 sob aprovação explícita.

Última atualização: 2026-05-21

---

## 1. Objetivo

Construir um agente IA que conheça profundamente **uma organização do GitHub
configurável** (`splor-mg` inicialmente) e responda perguntas como:

- Qual o último issue criado pelo usuário X?
- Quantos PR/issues/respostas foram feitas pelo usuário Y este mês?
- Quantos datapackages possuímos? Quantos públicos e privados?
- Liste todos os repositórios com os campos A, B, C e gere um Excel.
- Qual o último commit feito pelo usuário Z? E no repositório A?
- Quantos PRs estão abertos em toda a org?
- Quais repositórios não recebem atualização há mais de N dias?
- Quais repositórios têm mais de 1 branch?
- Relatório completo de atividade por usuário (issues, commits, PRs,
  respostas, discussões, última interação).

**Requisitos não funcionais críticos:**

- **Precisão absoluta** — nunca aproximar números. Toda contagem vem da API
  com paginação completa ou de GraphQL agregado.
- **Memória de sessão** estilo ChatGPT (sidebar de chats, histórico
  persistente, retomada de conversa).
- **Read-only por padrão.** Permissões da GitHub App restritas a leitura.
- **Configurável para outras organizações.** Cada deploy = uma org.
- **Segurança forte** mesmo em modo "permissivo" para logs: os ativos da org
  não podem ser destruídos nem expostos para usuários fora dela.

## 2. Stack Escolhida

| Camada | Tecnologia | Motivo |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Ecossistema maduro para agentes, async-first, ótimo p/ exports. |
| Agente | **Pydantic-AI** | Tools tipadas, streaming, suporte nativo a Azure OpenAI e MCP. |
| ORM/DB | **SQLAlchemy 2 + PostgreSQL 16** | Multi-usuário, auditoria, FK estritas. |
| Migrações | **Alembic** | Padrão do ecossistema. |
| LLM | **Azure AI Foundry** (modelos OpenAI / Anthropic / etc.) | Conta corporativa do usuário. |
| MCP | **github/github-mcp-server** (oficial) | Padrão emergente, padroniza ferramentas de GitHub. |
| Cliente GitHub | **httpx + GraphQL v4** | Precisão em agregações sem N+1. |
| Auth (app) | **GitHub OAuth + org allowlist** | Login familiar, herda controle de acesso da org. |
| Auth (API GitHub) | **GitHub App (installation)** | Tokens curtos, escopo mínimo, rotação automática. |
| Frontend | **React 18 + Vite + TypeScript** | UI tipo ChatGPT, streaming nativo. |
| UI Library | **shadcn/ui + Tailwind** | Componentes acessíveis, dark/light, baixo custo. |
| Streaming | **Server-Sent Events (SSE)** | Compatível com `EventSource`, sem WebSocket. |
| Exports | **openpyxl + pandas** | Excel preciso, mantém tipos. |
| Containers | **Docker + Easy Panel** | Easy Panel já em produção na sua VM Azure. |

## 3. Modelos LLM (Azure Foundry)

> Estado da arte disponível na assinatura. Configurável via env var por papel.

| Papel | Modelo proposto (default) | Alternativas |
|---|---|---|
| Orquestrador principal | **GPT-5** ou **GPT-4.1** | Claude Sonnet 4.6 |
| Raciocínio analítico pesado | **o3** | Claude Opus 4.7 |
| Tarefas leves (títulos de chat, classificação) | **GPT-4.1-mini** | GPT-4o-mini |

Todos via Azure OpenAI / Azure AI Foundry com chave única
(`AZURE_OPENAI_API_KEY`) e endpoint (`AZURE_OPENAI_ENDPOINT`). Deployments por
modelo configuráveis (`AZURE_DEPLOYMENT_ORCHESTRATOR`, etc.).

## 4. Arquitetura

```
┌────────────────────────────────────────────────────────────────────┐
│                         Browser (React)                            │
│  Sidebar de chats │ Mensagens │ Streaming │ Login GitHub OAuth     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ HTTPS (Easy Panel proxy)
                               │ Cookie HttpOnly de sessão
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Backend (FastAPI)                            │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────────┐  │
│  │  auth/       │  │  api/          │  │  agent/                │  │
│  │  OAuth, ses- │  │  chats, msgs,  │  │  Pydantic-AI runner    │  │
│  │  são, allow- │  │  SSE stream,   │  │  + guardrails          │  │
│  │  list        │  │  exports       │  │  + memória curta       │  │
│  └──────────────┘  └────────────────┘  └────────┬───────────────┘  │
│                                                 │                  │
│                                ┌────────────────┴───────────────┐  │
│                                ▼                                ▼  │
│  ┌────────────────────────────────────┐  ┌──────────────────────┐  │
│  │  tools/ (read-only)                │  │  MCP client          │  │
│  │  repos, issues, pulls, commits,    │  │  → github-mcp-server │  │
│  │  users, discussions, exports.xlsx  │  │    (container)       │  │
│  └─────────┬──────────────────────────┘  └──────────┬───────────┘  │
│            │                                        │              │
│            ▼                                        ▼              │
│  ┌──────────────────────────┐         ┌──────────────────────────┐ │
│  │  github/client.py        │         │  github-mcp-server       │ │
│  │  httpx + GraphQL v4      │         │  (oficial)               │ │
│  │  GitHub App installation │         │                          │ │
│  └──────────┬───────────────┘         └──────────┬───────────────┘ │
└─────────────┼────────────────────────────────────┼─────────────────┘
              │                                    │
              ▼                                    ▼
        ┌─────────────────────────────────────────────────┐
        │              api.github.com                     │
        └─────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL 16 (Easy Panel)                      │
│  users │ sessions │ chats │ messages │ tool_calls │ audit_log      │
└────────────────────────────────────────────────────────────────────┘
```

## 5. Modelo de Dados

```
users
  id (UUID, PK)
  github_login (text, unique)
  github_id (bigint, unique)
  email (text, nullable)
  is_active (bool, default true)
  created_at, last_login_at

sessions
  id (UUID, PK)
  user_id (FK users)
  created_at, expires_at, revoked_at
  ip_hash (text)        -- hash, não IP em claro
  user_agent (text)

chats
  id (UUID, PK)
  user_id (FK users)
  title (text)           -- gerado por LLM leve a partir da 1ª mensagem
  org (text)             -- org alvo na época do chat
  created_at, updated_at
  archived_at (nullable)

messages
  id (UUID, PK)
  chat_id (FK chats)
  role (enum: user | assistant | tool | system)
  content (text)         -- markdown
  tool_calls (jsonb)     -- chamadas feitas pelo assistente
  tokens_in, tokens_out (int)
  model (text)
  created_at

tool_calls               -- granular, para auditoria e debugging
  id (UUID, PK)
  message_id (FK messages)
  tool_name (text)
  arguments (jsonb)
  status (enum: ok | error | denied)
  duration_ms (int)
  result_summary (text)  -- truncado, sem dados sensíveis brutos
  created_at

audit_log                -- decisões de segurança
  id (UUID, PK)
  user_id (FK users, nullable)
  event (text)           -- ex: 'login.denied', 'tool.write_blocked'
  detail (jsonb)
  created_at

exports                  -- arquivos gerados (Excel/CSV)
  id (UUID, PK)
  user_id (FK users)
  chat_id (FK chats, nullable)
  filename (text)
  bytes (bytea ou path em volume)
  mime (text)
  expires_at             -- TTL 7 dias
  created_at
```

## 6. Fluxos Principais

### 6.1 Login

1. Usuário acessa `/`.
2. Sem sessão → redireciona para `/auth/github/login`.
3. Backend monta URL de OAuth (`scope=read:org user:email`) e redireciona.
4. GitHub callback → `/auth/github/callback?code=...`.
5. Backend troca code por token de usuário (não é persistido depois do
   passo 6).
6. Backend chama `GET /user/memberships/orgs/<ALLOWED_ORG>`.
   - **Se não pertencer**: registra `login.denied` e nega.
   - **Se pertencer**: cria/atualiza `user`, abre `session`, seta cookie
     HttpOnly + Secure + SameSite=Lax, descarta o token OAuth.
7. Redireciona para `/`.

### 6.2 Conversação

1. Usuário envia mensagem em chat existente ou novo (`POST /chats/<id>/messages`).
2. Backend persiste a mensagem do usuário.
3. Inicia stream SSE (`GET /chats/<id>/stream?after_message=<uuid>`).
4. Agente:
   - Carrega últimos N pares (com sumarização leve se exceder janela).
   - Decide tool calls; chama `tools/` ou MCP.
   - Streama tokens parciais ao frontend (`event: token`).
   - Ao final, persiste mensagem `assistant` + `tool_calls`.
5. Se a resposta gera arquivo (Excel), guarda em `exports` e retorna link
   curto.

### 6.3 Geração de Excel

- Tool `export_repos_xlsx(fields=[...], filters={...})`.
- Backend gera arquivo em memória → grava em `exports` (TTL 7 dias).
- Retorna ID; frontend renderiza botão "Baixar planilha".
- Download via `GET /exports/<id>` (autenticado, verifica `user_id`).

## 7. Tools (Catálogo Fase 1, read-only)

> Todas as tools recebem implicitamente a org configurada e o `user_id` do
> caller para auditoria. Nenhuma aceita modificar parâmetros que escapem da
> org allowlist.

### 7.1 Provenientes do **GitHub MCP Server** (oficial)

Operações genéricas de leitura: `search_repositories`, `search_issues`,
`search_users`, `get_repository`, `list_issues`, `list_pull_requests`,
`get_file_contents`, etc. Servem como fallback flexível.

### 7.2 Tools customizadas (precisão garantida)

| Tool | Pergunta que responde |
|---|---|
| `list_org_repos(visibility, include_archived)` | Quantos repos? Quantos públicos/privados? |
| `count_open_prs(repo?)` | Quantos PRs abertos na org? |
| `count_open_issues(repo?)` | Quantos issues abertos? |
| `repos_without_updates(days)` | Quais repos sem atualização há N dias? |
| `repos_with_multiple_branches()` | Quais repos têm mais de 1 branch? |
| `datapackages_stats(topic="datapackage")` | Datapackages: total, públicos, privados. |
| `last_commit_by_user(login, repo?)` | Último commit por usuário (e/ou em repo X). |
| `last_commit_in_repo(repo)` | Último commit no repo. |
| `last_issue_by_user(login)` | Último issue criado pelo usuário. |
| `user_activity_summary(login, since, until)` | Issues/PRs/respostas/commits/discussões no período. |
| `org_users_activity_report(since, until)` | Relatório completo por usuário (CSV/XLSX). |
| `export_repos_xlsx(fields, filters)` | Excel customizado de repositórios. |
| `count_user_contributions(login, type, since)` | Contagem precisa por tipo (issue, PR, comment...). |

Cada tool tem:
- Descrição clara em PT-BR + EN para o LLM.
- Schema Pydantic dos argumentos (validação estrita).
- Limite de paginação (defesa em profundidade contra loops/loops do LLM).
- Resultado tipado.

## 8. Segurança

> Detalhe em `SECURITY.md`. Resumo dos controles fase 1:

1. **Read-only enforced no token.** GitHub App tem só permissões de leitura.
   Mesmo se o LLM "tentar" deletar algo, a API rejeita.
2. **Allowlist de orgs.** `ALLOWED_ORGS` env var. Requisições da app para
   qualquer outro owner são bloqueadas no `client.py` (defesa em
   profundidade).
3. **Allowlist de usuários** via membership na org alvo. Usuários fora da
   org não conseguem logar.
4. **Cookie de sessão** HttpOnly + Secure + SameSite=Lax + rotação.
5. **CSRF** com double-submit token para mutações.
6. **Rate-limit por usuário** (configurável; default 60 req/min).
7. **Tool gate**: registry tem `mode: READ | WRITE | ADMIN`. Em fase 1,
   `AGENT_ALLOW_WRITE=false` bloqueia carregamento de qualquer tool WRITE.
8. **Confirmação humana fase 2** — toda tool WRITE precisa
   `?confirm_token=<one_time>` emitido por endpoint que exige
   re-autenticação.
9. **Segredos via Easy Panel env / Azure Key Vault**, nunca commitados.
10. **CSP estrita** no frontend; sem inline scripts; sem CDN para libs
    sensíveis (Tailwind via build).
11. **Auditoria total**: toda tool call vai para `tool_calls` + `audit_log`.
12. **Sandbox de exports**: arquivos servidos com `Content-Disposition:
    attachment`, MIME fixo, TTL 7 dias, sem path traversal.
13. **Validação Pydantic** estrita em todas entradas (URL, login, datas).
14. **Postgres**: conexão TLS-only em produção, usuário com privilégios
    mínimos (sem `CREATE`/`DROP` em runtime).

## 9. Configuração Multi-Org

Cada deploy do Gitinho atende **uma única organização** (mais seguro,
isolamento total de dados). No Easy Panel, isso se traduz em adicionar **um
trio de serviços** (`db`, `backend`, `frontend`) por org no projeto
existente do usuário (`applications`). Para servir múltiplas orgs:

- Repita o trio no mesmo projeto com nomes sufixados:
  `gitinho-<org>-db`, `gitinho-<org>-backend`, `gitinho-<org>-frontend`.
- Cada backend tem env vars próprias: `ALLOWED_ORG=<org>`, `GH_APP_ID=...`,
  `GH_APP_INSTALLATION_ID=...`, `GH_APP_PRIVATE_KEY=...`, `DATABASE_URL`
  apontando para o seu próprio Postgres.
- Não há cruzamento de dados entre instâncias, nem risco de uma sessão
  acessar a org errada por bug de filtro.

Trade-off: pequena duplicação de infra; ganho: blast radius contido.

## 10. Roadmap

### Fase 1 (este plano)
- Backend FastAPI, agente, MCP, tools read-only, frontend chat, Postgres,
  OAuth, deploy em Easy Panel.
- Critério de aceite: todas as 10 perguntas do brief são respondidas com
  precisão verificável e o relatório completo de usuários é exportável.

### Fase 2 (próximos passos)
- Tools WRITE: criar issue, comentar, abrir PR, abrir branch, fechar
  issue, label, atribuir.
- Cada tool WRITE exige confirmação humana via UI (modal com diff).
- GitHub App ganha permissões de escrita por escopo, controladas via
  feature flag.
- Audit log enriquecido + rollback semi-automático.

### Fase 3 (ideias futuras)
- Sync local em DuckDB para queries instantâneas em orgs grandes.
- Webhook listener para eventos da org (frescor em tempo real).
- Dashboards salvos (sem precisar de pergunta).
- Multi-agent (planejador + executor) para queries muito complexas.

## 11. Critérios de Aceite Fase 1

- [ ] Login OAuth funcional, usuário fora da org é bloqueado.
- [ ] Chat persistente: sidebar lista, posso retomar, posso renomear, posso
      arquivar.
- [ ] Streaming de respostas com markdown.
- [ ] Todas as 10 perguntas do brief retornam números corretos comparáveis
      manualmente.
- [ ] Export Excel funciona e respeita TTL.
- [ ] `AGENT_ALLOW_WRITE=false` por padrão; nenhuma tool de escrita
      registrada.
- [ ] Deploy roda no Easy Panel como trio de serviços (db + backend +
      frontend), instruções em `deploy/easy-panel.README.md`.
- [ ] README + ARCHITECTURE + SECURITY documentam tudo.

## 12. Riscos & Mitigações

| Risco | Mitigação |
|---|---|
| LLM inventar números | Usar tools determinísticas (não pedir ao LLM para somar). Mostrar contagens vindas direto da API. |
| Janela de contexto estoura em histórico longo | Sumarização incremental + paginação na UI. |
| Rate-limit do GitHub | App tem 15k req/h por instalação; GraphQL agregado economiza chamadas. Backoff exponencial. |
| Vazamento de PII | Allowlist de org + cookies HttpOnly + sem exposição de PAT no frontend. |
| Confusão entre orgs | Um container por org. |
| Custo Azure Foundry | Default modelo orquestrador 4.1; o3 só quando o classificador detecta query analítica pesada. |
| LLM tenta usar tool de escrita | Tools de escrita não estão registradas no runtime em fase 1 (`AGENT_ALLOW_WRITE=false`). |

## 13. Estrutura de Diretórios

```
gitinho/
├── docs/
│   ├── PLAN.md              ← este arquivo
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   └── images/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── logging_setup.py
│   │   ├── deps.py
│   │   ├── auth/
│   │   ├── github/
│   │   ├── agent/
│   │   ├── tools/
│   │   ├── api/
│   │   └── db/
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── alembic.ini
├── frontend/
│   ├── src/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── deploy/
│   ├── docker-compose.yml          (apenas dev local)
│   └── easy-panel.README.md        (produção: trio de serviços)
├── legacy/                          (stack Node anterior)
├── .env.example
├── .gitignore
├── README.md
└── Makefile
```

## 14. Estado da Implementação (2026-05-21)

Fase 1 foi totalmente esqueletada nesta sessão (commit pendente). O que
está em disco no repo:

**Backend (`backend/app/`):**
- `main.py` — factory FastAPI + middleware de segurança (CSP, HSTS, X-Frame,
  Referrer-Policy, Permissions-Policy), CORS dev, lifespan structlog.
- `config.py` — Pydantic Settings com validação de `ALLOWED_ORG` e leitura
  de `GH_APP_PRIVATE_KEY` por path ou env.
- `logging_setup.py` — structlog com `_redact_processor` que mascara
  tokens, segredos e padrões `Bearer …`, `gh_…`.
- `db/models.py` + `alembic/versions/0001_initial.py` — schema completo
  (users, sessions, chats, messages, tool_calls, audit_log, exports).
- `auth/` — OAuth GitHub (state assinado via itsdangerous),
  allowlist por membership na org, sessão opaca SHA-256 + CSRF
  double-submit.
- `github/app_auth.py` + `client.py` — GitHub App (JWT RS256 → installation
  token cacheado), `_check_owner` que dispara `OrgAllowlistError` em
  qualquer requisição fora da `ALLOWED_ORG`, paginação + GraphQL com retry.
- `github/graphql.py` — queries nomeadas (`ORG_REPOS_PAGE`,
  `ORG_OPEN_PRS`, `ORG_OPEN_ISSUES`, `REPO_LAST_COMMIT`,
  `USER_LAST_ISSUE_IN_ORG`, `USER_CONTRIBUTIONS`, `ORG_MEMBERS`,
  `ORG_ID`).
- `mcp/client.py` — cliente MCP stdio que filtra qualquer tool com prefixo
  de escrita (create/update/delete/merge/close/etc).
- `tools/` — `_base.py` (ToolRegistry + ToolMode enum), `_context.py`,
  `repos.py`, `issues.py`, `pulls.py`, `commits.py`, `users.py`,
  `discussions.py`, `activity.py`, `exports.py`. Cobre as 13 tools
  customizadas listadas em §7.2.
- `agent/prompts.py` (system prompt PT-BR), `agent/tool_registry.py`
  (conversão ToolSpec → JSON Schema OpenAI), `agent/runner.py`
  (`AsyncAzureOpenAI` streaming, dispatch de tools, persistência de
  exports + ToolCall com timing e status).
- `api/` — `auth_routes.py`, `chats.py`, `messages.py`, `stream.py`
  (SSE com eventos `token | tool_call | tool_result | export | done |
  error`), `exports.py`, `health.py`. Toda rota mutadora exige CSRF;
  toda rota de chat valida `_own_chat` antes de operar.
- `Dockerfile` — baixa o binário do `github-mcp-server` do release oficial;
  entrypoint roda `alembic upgrade head` antes do uvicorn.
- `pyproject.toml` — deps: fastapi, openai, sqlalchemy[asyncio], asyncpg,
  alembic, authlib, pyjwt[crypto], sse-starlette, openpyxl, pandas,
  structlog, mcp.

**Frontend (`frontend/`):**
- `src/App.tsx`, `components/{Sidebar,ChatView,LoginScreen}.tsx` — UI tipo
  ChatGPT, EventSource consumindo SSE, renderização de `tool_call` chips e
  links de `export`.
- `src/api.ts` — wrapper de fetch injetando CSRF do cookie em mutações.
- `src/styles.css` — dark theme.
- `Dockerfile` — build em duas etapas; runtime `nginx:1.27-alpine`
  consumindo `/etc/nginx/templates/default.conf.template` via envsubst.
- `nginx.conf.template` — usa `${BACKEND_HOST}:${BACKEND_PORT}`. Default
  `backend:8000` (compose dev); no Easy Panel sobrescreve para
  `gitinho-backend:8000`. **Mesma imagem serve os dois ambientes.**

**Deploy (`deploy/`):**
- `docker-compose.yml` — só para dev local, bind em `127.0.0.1`.
- `easy-panel.README.md` — guia passo-a-passo para produção: usuário
  adiciona 3 serviços (`gitinho-db` PostgreSQL 16, `gitinho-backend` App
  com `backend/Dockerfile`, `gitinho-frontend` App com `frontend/Dockerfile`)
  ao seu projeto existente do Easy Panel. **Não há `docker-compose.prod.yml`
  — o Easy Panel gerencia os serviços individualmente.**

**Docs (`docs/`):**
- `PLAN.md` (este arquivo), `ARCHITECTURE.md`, `SECURITY.md`,
  `DECISIONS.md` (log de decisões da sessão).

**Outros:**
- `.env.example` com todas as variáveis (ALLOWED_ORG, OAUTH_*, GH_APP_*,
  AZURE_OPENAI_*, DATABASE_URL, AGENT_ALLOW_WRITE=false, MCP_GITHUB_*,
  LOG_LEVEL).
- `Makefile` com `up`, `migrate`, `revision M=...`, `shell-db`, etc.
- `legacy/` — stack Node original preservada para referência.

**O que ainda não rodou nesta máquina:**
- Nenhum `docker compose up` foi executado — código nunca foi exercitado.
- Nenhuma chave real está em `.env` (só template). O usuário precisa criar
  GitHub App, OAuth App, e configurar o Foundry quando for ao Easy Panel.
- Migrations Alembic nunca foram aplicadas; rodam automaticamente no
  entrypoint do container backend.

**Próximos passos sugeridos quando o usuário retomar:**
1. Smoke test local: `cd deploy && docker compose up -d --build` e
   verificar que backend sobe e migrações aplicam.
2. Criar GitHub App + OAuth App, popular `.env`.
3. Seguir `deploy/easy-panel.README.md` para subir os 3 serviços.
4. Validar perguntas do brief uma a uma contra a UI da org.
5. (Opcional) Workflow GitHub Actions publicando imagens em GHCR — só
   quando o build-from-source no Easy Panel for confirmado funcionando.

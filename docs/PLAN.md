# Gitinho — Plano e Estado da Implementação

> Agente conversacional read-only para a organização **`splor-mg`** no GitHub
> (configurável via `ALLOWED_ORG`). Responde com precisão a perguntas em
> linguagem natural sobre repositórios, issues, PRs, commits, atividade de
> usuários, datapackages e gera planilhas (XLSX/CSV) sob demanda.

Última atualização: 2026-05-26

---

## 1. Objetivo

Construir um agente IA que conheça profundamente uma organização do GitHub
configurável e responda perguntas como:

- Qual o último issue criado pelo usuário X?
- Quantos PR/issues foram feitas pelo usuário Y este mês?
- Quantos datapackages possuímos? Quantos públicos e privados?
- Liste todos os repositórios com os campos A, B, C e gere uma planilha.
- Qual o último commit feito pelo usuário Z? E no repositório A?
- Quantos PRs estão abertos em toda a organização?
- Quais repositórios não recebem atualização há mais de N dias?
- Quais repositórios têm mais de 1 branch?
- Relatório completo de atividade por usuário (issues, commits, PRs,
  reviews, comentários, discussões, última interação).

**Requisitos não funcionais críticos:**

- **Precisão absoluta** — toda contagem vem da API com paginação completa
  ou de GraphQL agregado; o LLM nunca soma resultados parciais.
- **Memória de sessão** estilo ChatGPT (sidebar de threads, persistência,
  retomada de conversa).
- **Read-only por padrão.** GitHub App restrita a leitura; tools de
  escrita não estão registradas no servidor MCP.
- **Configurável para outras organizações.** Cada deploy = uma org.
- **Segurança forte** — ativos da org não podem ser destruídos nem
  expostos a usuários fora dela.

## 2. Stack Atual

Monorepo (pnpm workspace + uv workspace).

| Camada | Tecnologia | Onde |
|---|---|---|
| Chat / UI / Auth / persistência | Fork de `cgoinglove/better-chatbot` (Next.js 16, Vercel AI SDK, Better Auth, Drizzle ORM) | `apps/chat/` |
| Tools GitHub (read-only) | Servidor MCP Python (`gitinho-mcp`) — 22 tools | `apps/mcp/` |
| LLM | Azure AI Foundry via adapter OpenAI-compatible | env `OPENAI_COMPATIBLE_DATA` |
| DB | PostgreSQL 17 (schema do better-chatbot via Drizzle) | container `postgres` |
| File ingest | MinIO (S3-compatible) + MarkItDown no MCP | container `minio` + tool `convert_document` |
| Exports | LLM chama tool nativa `createTable` (better-chatbot) | UI renderiza tabela com download nativo |
| Deploy | Docker Compose → Easy Panel | `apps/chat/docker/compose.yml` |

A separação chat/MCP permite reusar as 22 tools fora do chat (CLI,
cron, CI) e plugar outros servidores MCP no mesmo chat (GitHub oficial,
Postgres, filesystem) — sem código nosso.

## 3. Estrutura do Repositório

```
gitinho/
├── apps/
│   ├── chat/              fork vendored do better-chatbot
│   │   ├── src/
│   │   │   ├── app/         App Router (Next.js)
│   │   │   ├── components/  React UI
│   │   │   ├── lib/
│   │   │   │   ├── ai/       Vercel AI SDK + prompts + agents Gitinho
│   │   │   │   ├── auth/     Better Auth + hook de allowlist por org
│   │   │   │   └── db/       Schema Drizzle
│   │   │   └── i18n/         Locales (PT-BR)
│   │   ├── scripts/
│   │   │   └── seed-gitinho-agents.ts   popula @Datapackages e @Atividade
│   │   ├── docker/
│   │   │   ├── Dockerfile
│   │   │   └── compose.yml   chat + postgres + minio + bootstrap
│   │   ├── drizzle.config.ts
│   │   └── package.json
│   └── mcp/                servidor MCP Python
│       ├── gitinho_mcp/
│       │   ├── __main__.py
│       │   ├── server.py
│       │   ├── config.py
│       │   ├── github/       cliente GitHub App + GraphQL
│       │   └── tools/        repos, issues, pulls, commits, users,
│       │                     discussions, activity, glossary, documents
│       ├── scripts/          smoke tests, MCP inspector helpers
│       └── pyproject.toml
├── docs/
│   ├── PLAN.md                       (este arquivo)
│   ├── ARCHITECTURE.md               diagramas e fluxos
│   ├── DEPLOY.md                     produção via Docker Compose / Easy Panel
│   ├── DECISIONS.md                  log de decisões estruturais
│   ├── SECURITY.md                   modelo de ameaças + controles
│   └── MIGRATION_BETTER_CHATBOT.md   histórico da migração (referência)
├── secrets/
│   └── gh-app.pem         chave privada da GitHub App (NÃO versionado)
├── pyproject.toml         uv workspace
├── pnpm-workspace.yaml    pnpm workspace
├── README.md
└── .env                    NÃO versionado (template em .env.example)
```

A versão pré-migração (FastAPI + React+Vite) está congelada na tag
`pre-migration-2026-05-25` e copiada para `../gitinho-legacy/` fora do
repo.

## 4. Catálogo de Tools MCP (`gitinho-mcp`)

22 tools read-only, todas auto-registradas em `apps/mcp/gitinho_mcp/tools/`:

| Módulo | Tool | Propósito |
|---|---|---|
| `repos.py` | `list_org_repos` | Lista repositórios da org |
| `repos.py` | `count_repos` | Total / públicos / privados / arquivados |
| `repos.py` | `repos_without_updates` | Repos sem push há N dias |
| `repos.py` | `repos_with_multiple_branches` | Repos com > 1 branch |
| `repos.py` | `datapackages_stats` | Estatística de repos com topic `datapackage` |
| `repos.py` | `find_datapackages` | **Canônico** — code search de `datapackage.json` na raiz |
| `repos.py` | `get_repo` | Detalhe de um repo específico |
| `users.py` | `list_org_members` | Lista membros da org |
| `users.py` | `count_user_contributions` | Contagem por tipo (issue/pr/commit/pr-review) |
| `issues.py` | `count_open_issues` | Conta issues abertas |
| `issues.py` | `last_issue_by_user` | Última issue de um login |
| `issues.py` | `search_issues` | Busca livre |
| `pulls.py` | `count_open_prs` | Conta PRs abertos |
| `pulls.py` | `list_prs_by_user` | PRs por autor (open/closed/merged/all) |
| `pulls.py` | `last_pr_by_user` | Último PR de um login |
| `commits.py` | `last_commit_in_repo` | Último commit em um repo |
| `commits.py` | `last_commit_by_user` | Último commit de um usuário |
| `discussions.py` | `discussions_overview` | Discussions por repo |
| `activity.py` | `user_activity_summary` | Resumo de atividade de um usuário |
| `activity.py` | `org_users_activity_report` | Relatório por usuário (org inteira) |
| `glossary.py` | `get_org_glossary` | Lê `<org>/.github/gitinho-context.md` (TTL 5 min) |
| `documents.py` | `convert_document` | Ingest de PDF/DOCX/PPTX/XLSX via MarkItDown |

**Exports**: a UI usa a tool nativa `createTable` do better-chatbot —
o agente busca os dados via tool MCP e chama `createTable` com
`title/columns/data`. A tabela renderizada já tem botões de download
XLSX/CSV. Não existem mais `export_*_xlsx` no MCP (essa lógica migrou
para o frontend).

## 5. Custom Agents

Dois agentes nomeados, populados via `pnpm --filter chat gitinho:seed-agents`
(arquivo `apps/chat/scripts/seed-gitinho-agents.ts`):

| Agente | Tools | Foco |
|---|---|---|
| `@Datapackages` | `find_datapackages`, `datapackages_stats`, `list_org_repos`, `get_repo`, `get_org_glossary`, `createTable` | Especialista em datapackages Frictionless |
| `@Atividade` | `user_activity_summary`, `org_users_activity_report`, `list_prs_by_user`, `last_commit_by_user`, `count_user_contributions`, `list_org_members`, `get_org_glossary`, `createTable` | Relatórios de atividade da org |

`@-mention` no chat input invoca o agente específico com prompt e tools
restritas. O agente default (sem @-mention) tem acesso a todas as tools.

## 6. Modelos LLM

Configurado via `OPENAI_COMPATIBLE_DATA` (JSON gerado pelo helper do
better-chatbot ou pelo `openai-compatible.config.ts`). Aponta para o
endpoint v1 Foundry:

```
https://aid-splor-default-resource.services.ai.azure.com/openai/v1
```

Deployments em uso:
- `gpt-4.1-301271` — orquestrador default
- `gpt-5.4-pro` — raciocínio analítico pesado (selecionável na UI)

Trocar de provider é uma operação de UI no better-chatbot — não requer
código.

## 7. Fluxo de uma Pergunta

```
Usuário digita no chat
  ↓
Better Auth: cookie de sessão → resolve usuário
  ↓
POST /api/chat (route do Next.js)
  ↓
streamText() do Vercel AI SDK
  ├── system prompt (4 camadas: base + user prefs + project + MCP customizations)
  ├── tools do MCP `gitinho` (registradas via stdio em FILE_BASED_MCP_CONFIG)
  └── tools nativas do better-chatbot (createTable, etc.)
  ↓
LLM decide tool: ex. count_open_prs()
  ↓
gitinho-mcp executa via GitHub App (GraphQL totalCount)
  ↓
Retorna {"count": 42}
  ↓
LLM formata resposta em markdown e streama tokens
  ↓
UI renderiza chat com chips de tool call e download de tabelas
```

## 8. Persistência

Schema Drizzle gerenciado pelo better-chatbot. Tabelas principais:

- `users`, `sessions`, `accounts`, `verifications` — Better Auth
- `threads`, `messages` — conversas
- `agents` — `@Datapackages`, `@Atividade` e os que o usuário criar
- `mcp_servers` — config dinâmica (no nosso caso, vem do
  `.mcp-config.json` por `FILE_BASED_MCP_CONFIG=true`)
- `workflows` — pipelines no-code (não usado em Fase 1)

Migrations rodam automaticamente no startup do container `chat` via
`db:migrate`.

## 9. Roadmap

### Fase 1 — Migração para better-chatbot ✅ concluída

| Fase | Entrega | Commit |
|---|---|---|
| 1 | Scaffolding monorepo + ingestão do better-chatbot | `9e16116` |
| 2 | Allowlist por org no login OAuth (hook Better Auth) | `9f07e60` |
| 3 | 19 tools read-only de GitHub no servidor MCP | `3fff1bb` |
| 4 | System prompt do Gitinho + tool de glossário | `5c26f67` |
| 5 | Instrução de export XLSX/CSV via `createTable` | `ce2108b` |
| 6 | Agentes nomeados `@Datapackages` e `@Atividade` | `3af426d` |
| 7 | Ingest de PDF/DOCX/PPTX/XLSX via MarkItDown | `99bc14c` |
| 8 | Hardening de deploy + sidecar MinIO + headers | `a2ad9a9` |

### Fase 2 — Tools de escrita (futura)

- Criar issue, comentar, abrir PR, fechar issue, atribuir.
- Cada tool WRITE exige confirmação humana via UI (modal com diff antes
  da chamada).
- GitHub App ganha permissões de escrita por escopo, controladas via
  feature flag.

### Fase 3 — Operacional avançado (ideias)

- Workflows agendados (digest semanal de atividade, health-check de
  datapackages, lista de PRs pendentes > N dias).
- Sync local em DuckDB para queries instantâneas em orgs grandes.
- Webhook listener para frescor em tempo real.
- Dashboards salvos (sem precisar de pergunta).

## 10. Critérios de Aceite (Fase 1)

- [x] Login OAuth funcional; usuário fora da `ALLOWED_ORG` é bloqueado.
- [x] Chat persistente com sidebar de threads.
- [x] Streaming de respostas com markdown rico (Mermaid, code blocks).
- [x] Todas as 10 perguntas-tipo do brief retornam números corretos.
- [x] Export para XLSX/CSV via `createTable` (tabela com download nativo).
- [x] Apenas tools read-only no MCP (nenhuma create_/update_/delete_).
- [x] Deploy via Docker Compose / Easy Panel documentado.
- [x] README + ARCHITECTURE + SECURITY + DEPLOY documentam tudo.
- [ ] Ingest de PDF/DOCX/PPTX/XLSX em produção validado com arquivos reais.
- [ ] Smoke test fim-a-fim em staging antes do cutover de DNS.

## 11. Riscos & Mitigações

| Risco | Mitigação |
|---|---|
| LLM inventar números | Tools determinísticas com `totalCount` GraphQL; nunca pedir ao LLM para somar. |
| Janela de contexto estoura em histórico longo | Better-chatbot já faz janelamento; sumarização pode ser ligada. |
| Rate-limit do GitHub | GitHub App: 15k req/h por instalação; GraphQL agregado economiza chamadas. |
| Prompt-injection via conteúdo de issue malicioso | Tools nunca recebem tokens; tools WRITE não estão carregadas; `OrgAllowlistError` bloqueia owners ≠ ALLOWED_ORG. |
| LLM tenta usar tool de escrita | Não existe tool WRITE no `gitinho-mcp`; `NOT_ALLOW_ADD_MCP_SERVERS=1` impede plugar outros servidores via UI. |
| Custo Azure Foundry | Default `gpt-4.1`; modelos pesados (`gpt-5.4-pro`) só sob demanda. |
| Confusão entre orgs | Uma instância = uma org. Para multi-org, replicar o trio de serviços com sufixo. |
| MinIO single-instance falha | Backup do volume `minio_data`; exports são regeneráveis na pior hipótese. |

## 12. Setup Local (resumo)

```bash
# 1. Variáveis
cp .env.example .env       # preencha conforme docs/DEPLOY.md §3

# 2. Dependências
pnpm install
uv sync --directory apps/mcp

# 3. Postgres
docker compose -f apps/chat/docker/compose.yml up -d postgres

# 4. Dev server (chat + MCP via stdio embutido)
pnpm chat:dev
```

Detalhes em [`README.md`](../README.md) e [`docs/DEPLOY.md`](./DEPLOY.md).

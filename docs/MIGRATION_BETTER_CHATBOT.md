# Migração do Gitinho para better-chatbot

> Plano de migração da Fase 1 do Gitinho (FastAPI + React custom) para a
> stack do projeto open-source [`cgoinglove/better-chatbot`](https://github.com/cgoinglove/better-chatbot).
>
> Status: **proposta** — aguardando aprovação antes de execução.
> Data do plano: 2026-05-24.

---

## 1. Resumo executivo (TL;DR)

**Recomendação:** adotar o `better-chatbot` como **plataforma de UI/chat/auth/persistência**
e transformar as 23 tools atuais do Gitinho em um **MCP server Python**
(`gitinho-mcp`) consumido pelo better-chatbot via stdio ou SSE.

**Por quê:**

- O better-chatbot já entrega "out of the box" praticamente tudo que
  ainda falta no Gitinho (workflows, agents nomeados, voz, file ingest,
  multi-provider, admin, threads, share, i18n) e em qualidade superior à
  que conseguiríamos construir em casa em prazo razoável.
- Nossas 23 tools — incluindo `find_datapackages`, `org_users_activity_report`,
  exports XLSX, etc. — sobrevivem 1:1 como um servidor MCP. Nenhum
  re-trabalho de regra de negócio.
- O modelo MCP nos abre a porta para conectar, no mesmo chat,
  **outros** servidores MCP (GitHub oficial, Postgres, filesystem,
  Playwright, etc.) sem código nosso.
- O backend Python continua sendo dono da autenticação `GitHub App`,
  do allowlist de org e da geração de XLSX — não precisamos jogar nada
  fora.

**Esforço estimado:** **4–7 semanas** com 1 dev focado. Caminho crítico
mínimo viável (migration "feature parity") em **3 semanas**.

**Riscos principais:**

- Next.js 16 é recente (jan/2026); better-chatbot está pausado até
  fev/2026 — upstream lento por algumas semanas.
- O modelo `per-org OAuth grant` que o usuário pediu **não existe
  nativamente** no GitHub OAuth Apps: vamos precisar manter o pattern
  atual (OAuth só para identidade + GitHub App para acesso a dados).
- Drizzle (better-chatbot) vs SQLAlchemy (Gitinho) — dados do `Phase 1`
  atual não migram automaticamente. Tratamos como **clean cutover**.

---

## 2. Análise de compatibilidade arquitetural

| Dimensão | Gitinho hoje | better-chatbot | Compatível? |
| --- | --- | --- | --- |
| Linguagem | Python (back) + React (front) | TypeScript ponta a ponta (Next.js 16) | ❌ — rewrite TS no front; back vira MCP server |
| Framework web | FastAPI | Next.js App Router | n/a — back vira MCP |
| ORM | SQLAlchemy 2 + Alembic | Drizzle ORM + Drizzle Kit | ❌ — schema novo |
| DB | Postgres 16 | Postgres (≥ 14) | ✅ — mesmo motor, schema novo |
| Cache | In-process TTL dict | Opcional Redis (multi-instância) | ✅ — Redis opcional |
| LLM provider | Azure OpenAI v1 via `AsyncOpenAI(base_url=...)` | Vercel AI SDK c/ `createOpenAICompatible` | ✅ — adapter pronto: [`azure-openai-compatible.ts`](https://github.com/cgoinglove/better-chatbot/blob/main/src/lib/ai/azure-openai-compatible.ts) |
| Streaming | SSE manual (`token / tool_call / tool_result / export / phase / done / error`) | Vercel AI SDK stream + UI Message Stream | ✅ — equivalente, formato AI SDK |
| Tool calling | Registry Python → OpenAI function-calling schema | MCP-first; tools internas via AI SDK | ✅ — nosso registry vira MCP server |
| Auth | GitHub OAuth (identidade) + GitHub App (dados) + session cookies (`itsdangerous`) | Better Auth (e-mail, GitHub, Google, Microsoft) | ⚠️ — adaptar: GitHub OAuth via Better Auth + check de org membership server-side |
| Persistência de chat | `users / sessions / chats / messages / tool_calls / audit_log / exports` | esquema próprio com `threads / messages / agents / workflows / mcp_servers / exports` | ❌ — schema novo, dados ficam no Gitinho antigo até cutover |
| Frontend de chat | React 18 + Vite + `react-markdown` + SSE custom | Next.js 16 + AI SDK UI primitives + Mermaid + voz | ✅ — feature set muito maior |
| Markdown | ✅ (`react-markdown` + `remark-gfm`) | ✅ + Mermaid + code blocks ricos | ✅ |
| Exports XLSX | `openpyxl` server-side, salva em `Export.payload` (LargeBinary) | Tem rota `(public)/export/[id]` e `api/export/` | ✅ — modelo similar; geração continua server-side |
| Glossário customizável | `<org>/.github/gitinho-context.md` carregado on-demand com TTL | "Project Instructions" + "MCP customizations" (4 camadas de prompt) | ✅ — mapeamento direto |
| Segurança / CSP | Middleware FastAPI com cabeçalhos restritos | Configurável no Next.js (`next.config.ts`) | ✅ — equivalente |
| Bind 127.0.0.1 | Easy Panel + Docker Compose | Docker Compose | ✅ — preservado no `docker-compose.yml` |
| Read-only / write tools | `ToolMode.READ/WRITE/ADMIN` enforce no registry | Sem enforcement nativo — fazemos no MCP server | ✅ — controlamos no servidor MCP |
| Org allowlist | `OrgAllowlistError` no `GitHubClient` | n/a — fazemos no servidor MCP + check no login | ✅ — preservado |

**Veredito:** sem bloqueadores arquiteturais. O caminho mais barato é
encarar isso como uma **substituição da camada de chat**, mantendo a
inteligência GitHub-específica como serviço MCP.

---

## 3. Inventário do Gitinho atual (o que precisa sobreviver)

### 3.1 Tools registradas (23)

| Tool | Arquivo | Propósito |
| --- | --- | --- |
| `list_org_repos` | `repos.py` | Lista repositórios da org |
| `count_repos` | `repos.py` | Total / públicos / privados / arquivados |
| `repos_without_updates` | `repos.py` | Repos sem push há N dias |
| `repos_with_multiple_branches` | `repos.py` | Repos com > 1 branch |
| `datapackages_stats` | `repos.py` | Estatística de repos com topic `datapackage` |
| `find_datapackages` | `repos.py` | **Canônico** — code search `datapackage.json` na raiz |
| `get_repo` | `repos.py` | Detalhe de um repo |
| `list_org_members` | `users.py` | Lista membros da org |
| `count_user_contributions` | `users.py` | Contagem de commits/issues/PRs/reviews |
| `count_open_issues` | `issues.py` | Conta issues abertas |
| `last_issue_by_user` | `issues.py` | Última issue de um login |
| `search_issues` | `issues.py` | Busca livre |
| `count_open_prs` | `pulls.py` | Conta PRs abertos |
| `list_prs_by_user` | `pulls.py` | PRs por autor (open/closed/merged/all) |
| `last_pr_by_user` | `pulls.py` | Último PR de um login |
| `last_commit_in_repo` | `commits.py` | Último commit em repo |
| `last_commit_by_user` | `commits.py` | Último commit de um usuário |
| `discussions_overview` | `discussions.py` | Discussions por repo |
| `user_activity_summary` | `activity.py` | Resumo de atividade de um usuário |
| `org_users_activity_report` | `activity.py` | Relatório por usuário (org inteira) |
| `export_repos_xlsx` | `exports.py` | XLSX de repos |
| `export_users_activity_xlsx` | `exports.py` | XLSX de atividade |
| `export_prs_by_user_xlsx` | `exports.py` | XLSX de PRs por autor |

### 3.2 Restrições e regras a preservar

1. **Read-only na Fase 1.** `ToolMode.READ` apenas — sem escrita.
2. **Allowlist de org.** Apenas `splor-mg` (configurável via env).
3. **Dois identificadores.** OAuth GitHub serve **só** para autenticar
   o usuário e verificar membership; o token é descartado. Dados são
   buscados server-side com **GitHub App** (App ID `3841439`,
   Installation `135227859`).
4. **Bind 127.0.0.1 apenas.** Easy Panel + reverse-proxy.
5. **Sem token leakage.** Headers de segurança restritivos (CSP estrita,
   `Referrer-Policy: strict-origin-when-cross-origin`, etc.).
6. **Glossário editável.** `<org>/.github/gitinho-context.md` carregado
   on-demand (cache TTL 5 min) — não vive no repo do Gitinho.
7. **PT-BR first.** System prompt em português; respostas em PT-BR.
8. **Audit log.** Todo evento (login, tool call) gravado em
   `audit_log` para compliance.
9. **Per-org OAuth grant** (preferência declarada pelo usuário). Atualmente
   parcialmente atendido — GitHub OAuth é por-conta, não por-org; o que
   nos protege é o **GitHub App** estar instalado **apenas** em
   `splor-mg`.

### 3.3 Schema atual

`users`, `sessions`, `chats`, `messages`, `tool_calls`, `audit_log`,
`exports`. Tudo via Alembic. **Nenhum dado de produção a migrar** (Fase
1 ainda não está em uso pleno).

---

## 4. O que o better-chatbot oferece (ganhos)

### 4.1 Já temos / equivalente

- Markdown rico (com Mermaid extra)
- SSE / streaming (com indicadores de "thinking" embutidos)
- Tool call UI (`tool-invocation/`, `tool-detail-popup`)
- Persistência de chats e mensagens
- Threads / histórico
- Exports
- OAuth com GitHub

### 4.2 Ganhos novos relevantes

| Recurso | O que destrava |
| --- | --- |
| **MCP first-class** | Plugar o GitHub MCP oficial, Postgres MCP, Filesystem MCP, etc. — sem código nosso |
| **Hot-reload de MCP servers** | Trocar config de tools sem rebuild ("You can add new MCP servers effortlessly through the UI — no need to restart the app") |
| **Custom Agents** | Criar agentes nomeados ("Gitinho-Datapackages", "Gitinho-PRs-Reviewer") com prompt próprio + ferramentas restritas |
| **@-mention de agents** | Chamar um agente específico mid-chat (`chat-mention-input.tsx`) |
| **Workflows** | Pipelines no-code (ex.: "todo domingo gerar XLSX de atividade") |
| **4 camadas de prompt** | Base + preferências do usuário + projeto + MCP customizations |
| **Voz** | `chat-bot-voice.tsx` + `lib/ai/speech/` — OpenAI Realtime API |
| **File ingest** | Subir PDF/docx no chat e o LLM ler (`lib/file-ingest/`) |
| **Image generation** | Tool nativa (`lib/ai/image/`) |
| **Multi-provider** | Trocar provider numa request (Google / OpenAI / Anthropic / xAI / Groq / Ollama local / Azure-compat) |
| **Better Auth** | Email + GitHub + Google + Microsoft com toggle de sign-up granular |
| **Admin panel** | UI pronta para gestão de usuários |
| **Bookmarks + share + archive** | Threads compartilháveis, arquiváveis, com favoritos |
| **i18n** | PT-BR como locale (já tem estrutura `messages/`) |
| **Mermaid** | Diagramas direto do markdown |
| **Temporary chats** | Sessões efêmeras (não persistidas) — útil para queries sensíveis |
| **Code runner sandbox** | `lib/code-runner/` — executar snippets sem instalação local |
| **E2E + unit tests** | Playwright + Vitest já configurados |
| **Redis multi-instância** | Sincronização de estado MCP entre múltiplas réplicas |
| **MIT license** | Liberdade total para fork e modificações |

---

## 5. Mapeamento funcional (Gitinho → better-chatbot)

| Funcionalidade Gitinho | Equivalente better-chatbot | Ação |
| --- | --- | --- |
| 23 tools read-only Python | MCP server stdio | Empacotar `app/tools/*.py` como `gitinho-mcp` |
| `GitHubClient` + `OrgAllowlistError` | Mantido dentro do `gitinho-mcp` | Mover `app/github/` para o servidor MCP |
| `app/agent/runner.py` (streaming + tools) | Vercel AI SDK + `streamText` no Next.js | Descartar — better-chatbot já faz |
| `app/agent/prompts.py` | `lib/ai/prompts.ts` + Project Instructions | Adaptar para 4 camadas |
| `app/agent/glossary.py` (cache TTL `<org>/.github/gitinho-context.md`) | Project Instructions (CRUD em DB) **ou** preservar como MCP tool `get_org_glossary` | Recomendado: tool MCP — preserva fonte canônica (GitHub) |
| `app/auth/oauth.py` (GitHub OAuth) | Better Auth com provider `github` | Configurar com mesmas credenciais (`Ov23lit3J2ceJ03kdZlO`) |
| `app/auth/allowlist.py` (org membership check) | Hook `signIn.before` do Better Auth | Reimplementar como middleware Better Auth |
| `app/api/chats.py` (CRUD de chat) | `app/api/thread/` + `(chat)/` no better-chatbot | Descartar — equivalente |
| `app/api/messages.py` | `app/api/chat/route.ts` | Descartar |
| `app/api/stream.py` (SSE custom) | AI SDK `streamText` | Descartar |
| `app/api/exports.py` (download) | `app/(public)/export/[id]/` | Reaproveitar; persistência fica no MCP server |
| `app/db/models.py` (Export, ToolCall, AuditLog) | Schema Drizzle novo | Recriar `tool_calls`, `audit_log`, `exports` |
| `frontend/src/components/ChatView.tsx` | `components/chat-bot.tsx` | Descartar |
| `frontend/src/components/LoginScreen.tsx` | `(auth)/sign-in` | Descartar |
| `frontend/src/components/Sidebar.tsx` | `components/layouts/` | Descartar |
| `styles.css` (animações: spinner, thinking-bounce, caret-blink) | Built-in | Descartar |
| XLSX export via `openpyxl` | Manter no MCP server | Servidor MCP retorna blob; rota Next.js entrega download |
| Audit log em DB | Schema novo no better-chatbot | Recriar tabela `audit_log` |

---

## 6. Decisão de abordagem — 3 opções

### Opção A — **Greenfield com MCP server Python (recomendado)**

Fork do `better-chatbot` → customizações de marca, provider Azure
OpenAI, allowlist de org, Better Auth. As 23 tools viram um MCP server
Python (`gitinho-mcp`) usando `fastmcp` ou `mcp` SDK oficial.

**Prós:**
- Aproveita 100% das features do better-chatbot.
- Zero re-trabalho de regra GitHub (tools Python ficam intactas).
- `gitinho-mcp` pode ser reusado fora do chat (CLI, CI, cron).
- Convida outros MCP servers (GitHub oficial, Postgres, FS).
- Update do upstream relativamente fácil (rebase do fork).

**Contras:**
- Duas linguagens / dois repos (ou monorepo) para manter.
- Curva inicial do MCP protocol.
- Não migra dados atuais (mas Fase 1 não tem usuários ativos).

### Opção B — **Híbrido: better-chatbot como front + FastAPI atual como back via MCP HTTP**

Igual à A, porém o `gitinho-mcp` é um **HTTP/SSE MCP server** dentro
do FastAPI atual, não um stdio.

**Prós:**
- Mantém deploy atual do FastAPI no Easy Panel.
- Backend pode falar com mais de um cliente (não só o chat).

**Contras:**
- HTTP MCP requer infra de auth/CORS própria (stdio é trivial).
- Mais latência (rede vs IPC).

### Opção C — **Strip-and-mount (descartado)**

Manter FastAPI; trocar **apenas** o frontend pelo build estático do
better-chatbot.

**Por que descartar:**
- Better-chatbot é Next.js, não SPA — não roda como build estático
  desacoplado do back.
- Perderia praticamente todos os ganhos (workflows, agents, file ingest
  dependem do back TS).

**Recomendação:** **Opção A** (stdio MCP). Migração incremental:
começamos com stdio (simples, sem rede) e podemos migrar para HTTP MCP
depois sem mudar tools.

---

## 7. Plano faseado (assumindo Opção A)

> Estimativas em **dias úteis** para 1 dev focado. "Pessoa-dias".

### Fase 0 — Decisão e scaffolding (1–2 dias)

- Confirmar Opção A com stakeholders.
- Criar fork `splor-mg/gitinho-chat` do `cgoinglove/better-chatbot`.
- Criar repo `splor-mg/gitinho-mcp` (servidor MCP Python).
- Decidir estratégia de monorepo vs multi-repo. **Sugestão:** monorepo
  pnpm workspace + uv workspace (`apps/chat`, `apps/mcp`, `packages/*`).
- Reservar nomes / vault de secrets no Easy Panel.

### Fase 1 — better-chatbot baseline local (2–3 dias)

- Clonar fork, rodar `pnpm i && pnpm docker-compose:up && pnpm dev`.
- Validar fluxo padrão com Azure OpenAI:
  - Configurar `OPENAI_COMPATIBLE_DATA` via UI helper ou
    `openai-compatible.config.ts` apontando para nosso endpoint
    `https://aid-splor-default-resource.services.ai.azure.com/openai/v1`.
  - Modelos: `gpt-4.1-301271`, `gpt-5.4-pro`.
- Desabilitar providers não usados (deixar campos vazios).
- Aplicar branding "Gitinho" (logo, favicon, título, cores
  `globals.css`).
- Locale default PT-BR em `i18n/`.

**Checkpoint:** Login local funciona com Better Auth (e-mail
temporariamente), chat conversa com Azure OpenAI.

### Fase 2 — Auth + org allowlist (3–5 dias)

- Desabilitar email sign-up (`DISABLE_EMAIL_SIGN_UP=1`) e
  `DISABLE_SIGN_UP=1`.
- Habilitar `github` provider no Better Auth com
  `GITHUB_CLIENT_ID=Ov23lit3J2ceJ03kdZlO` (reusar OAuth App existente).
- Reescrever `app/auth/allowlist.py` como hook Better Auth:
  - No callback `signIn.after`, chamar `GET https://api.github.com/user/orgs`
    com o token OAuth recebido.
  - Se `splor-mg` ∉ lista → invalidar sessão, retornar 403, logar em
    `audit_log`.
- Definir tabela `audit_log` no schema Drizzle do fork.
- Documentar variável `ALLOWED_ORG=splor-mg` (multi-org futuro:
  `ALLOWED_ORGS=splor-mg,outra-org`).

**Checkpoint:** Login GitHub funciona apenas para membros de `splor-mg`;
não-membros são bloqueados com mensagem clara.

### Fase 3 — Gitinho MCP server (5–7 dias)

- Criar `apps/mcp/` (Python 3.12, `uv`).
- Adotar `mcp` SDK oficial (`mcp[stdio,sse]`).
- Estrutura sugerida:

  ```
  apps/mcp/
    pyproject.toml
    gitinho_mcp/
      __init__.py
      server.py          # ponto de entrada MCP (stdio)
      context.py         # equivalente ao ToolContext atual
      github_client.py   # cópia adaptada de app/github/client.py
      github_app_auth.py # cópia adaptada de app/github/app_auth.py
      tools/
        repos.py         # cópia direta de app/tools/repos.py
        users.py
        issues.py
        pulls.py
        commits.py
        discussions.py
        activity.py
        exports.py
        glossary.py      # nova tool get_org_glossary
      config.py
  ```

- Adapter de registry: nosso `@registry.register(mode=ToolMode.READ)`
  vira `@mcp.tool()` do SDK MCP. Schema é inferido da assinatura.
- Verificar cada tool individualmente via MCP Inspector
  (`npx @modelcontextprotocol/inspector`).

**Checkpoint:** 23 tools respondem via MCP CLI standalone.

### Fase 4 — Plugar `gitinho-mcp` no better-chatbot (2–3 dias)

- Modo dev: `FILE_BASED_MCP_CONFIG=true` + `.mcp-config.json`:

  ```json
  {
    "gitinho": {
      "command": "uv",
      "args": ["run", "--directory", "../mcp", "python", "-m", "gitinho_mcp.server"]
    }
  }
  ```

- Modo prod: adicionar via UI ou DB.
- Configurar **MCP customizations** (per-tool/per-server instructions)
  com guidelines extraídas do `prompts.py` atual (princípios 1–8).
- Smoke test: perguntas que hoje funcionam no Gitinho (ex.: "quantos
  PRs abertos?", "quantos repos com datapackage.json?", "gere planilha
  de atividade").

**Checkpoint:** Feature parity com Fase 1 atual via better-chatbot.

### Fase 5 — Glossário e Project Instructions (1–2 dias)

Duas opções de implementação:

**5a.** (recomendada) **Tool MCP `get_org_glossary`** — preserva a
fonte canônica `splor-mg/.github/gitinho-context.md`. O system prompt
do agente instrui o LLM a chamar essa tool no início de conversas que
mencionem termos do domínio. Mantém cache TTL 5 min.

**5b.** **Project Instructions UI** — copia o conteúdo do glossário
para um Project no better-chatbot. Mais ergonômico mas duplica fonte
da verdade e exige que alguém atualize manualmente.

**Recomendação:** **5a + 5b combinados** — Project Instructions
referencia o arquivo (1 linha "Use `get_org_glossary` para definições
internas"), e a tool entrega o conteúdo on-demand.

### Fase 6 — XLSX exports (3–5 dias)

- Manter geração com `openpyxl` no `gitinho-mcp` (3 tools de export
  permanecem).
- Definir formato de payload MCP → frontend:
  - Tool retorna `{kind: "export_xlsx", filename, base64, rows}`.
- No fork better-chatbot: handler em `app/api/export/route.ts` recebe
  payload, persiste em `exports` (Drizzle), retorna `id`.
- Reaproveitar UI `(public)/export/[id]` para download.
- Migrar princípio 8 do prompt atual: "Exports: NUNCA escreva link de
  download" para o system prompt do agente Gitinho.

**Checkpoint:** Botão de download estilizado funciona; LLM não duplica
links em markdown.

### Fase 7 — Custom Agents (2–3 dias)

Criar 2–3 agentes nomeados:

| Agente | Prompt foco | Tools permitidas |
| --- | --- | --- |
| `@Gitinho` (default) | Generalista — princípios 1–8 atuais | Todas as 23 |
| `@Datapackages` | Especialista em datapackages frictionless | `find_datapackages`, `get_repo`, `get_org_glossary` |
| `@Atividade` | Especialista em atividade / relatórios | `org_users_activity_report`, `export_users_activity_xlsx`, `list_prs_by_user`, `export_prs_by_user_xlsx` |

Aproveitar `@-mention` no chat input.

### Fase 8 — Workflows (opcional, 3–5 dias)

Workflows pré-construídos:

- **Digest semanal:** todo domingo às 8h gerar XLSX de atividade e
  postar resumo em Markdown.
- **Health check de datapackages:** scan semanal de repos com
  `datapackage.json` para flag de inconsistências.
- **PR pendentes:** lista PRs abertos há > N dias.

Workflows ficam em UI; podem ser disparados manualmente ou agendados.

### Fase 9 — Hardening, deploy e cutover (2–3 dias)

- **CSP** equivalente à atual no `next.config.ts`.
- **Bind 127.0.0.1** no `docker-compose.yml` (já é prática do Easy
  Panel).
- **HTTPS** via reverse proxy do Easy Panel.
- **Logs estruturados** (manter `structlog` ou equivalente JS).
- **Audit log** ativo em todos os pontos sensíveis (login, MCP tool
  call, export download).
- **Backup do schema novo** automatizado.
- **Smoke test** de fluxo completo em staging.
- **Cutover plan:**
  1. Anunciar janela.
  2. Pôr Gitinho-velho em read-only / banner de migração.
  3. Apontar DNS para a stack nova.
  4. Manter Gitinho-velho ligado em URL alternativa por 30 dias para
     consulta de histórico antigo.

### Fase 10 — Limpeza (1 dia)

- Arquivar `frontend/` e `backend/app/api/*` (mover para `legacy/`).
- Manter `backend/app/tools/`, `backend/app/github/` como **fonte
  histórica** para o `gitinho-mcp` (já copiado).
- README atualizado.

---

## 8. Estrutura final proposta

```
splor-mg/gitinho/   (monorepo)
├── apps/
│   ├── chat/                  ← fork do better-chatbot
│   │   ├── src/...            (custom: brand, allowlist hook, agentes)
│   │   ├── .env
│   │   └── package.json
│   └── mcp/                   ← novo: Python MCP server
│       ├── gitinho_mcp/
│       │   ├── server.py
│       │   ├── tools/         ← cópia direta de backend/app/tools/
│       │   ├── github_client.py
│       │   └── ...
│       └── pyproject.toml
├── packages/
│   └── shared-types/          ← (opcional) tipos compartilhados
├── deploy/
│   ├── docker-compose.yml
│   └── easypanel.yml
├── docs/
│   ├── ARCHITECTURE.md        (atualizado)
│   ├── MIGRATION_BETTER_CHATBOT.md (este arquivo)
│   └── ...
└── legacy/
    ├── backend/               ← FastAPI antigo congelado
    └── frontend/              ← React+Vite antigo congelado
```

---

## 9. Riscos e mitigações

| Risco | Probabilidade | Impacto | Mitigação |
| --- | --- | --- | --- |
| Next.js 16 instável (lançado recentemente) | Média | Médio | Travar versão; PRs do upstream antes de bumpar |
| better-chatbot em pausa até fev/2026 (sem patches upstream) | Alta | Baixo | Vivemos com fork por 2–3 meses; aplicamos patches críticos manualmente |
| MCP SDK Python mudando interface | Média | Médio | Travar versão de `mcp`; testes E2E cobrindo todas as 23 tools |
| Per-org OAuth não nativo no GitHub | **Confirmado** | Médio | Manter dual-identity (OAuth → membership; GitHub App → dados). Documentar em SECURITY.md |
| Drizzle vs SQLAlchemy → sem migração automática | Baixa | Baixo | Fase 1 não tem dados de produção a preservar |
| Token leak via novo provider compatível OpenAI | Baixa | Alto | CSP estrita; revisão de código; nunca logar `Authorization` headers |
| Custo Azure ↑ por mais tools + workflows | Média | Médio | Quotas; preferir `gpt-4.1` para tarefas simples, `gpt-5.4-pro` só para multi-step |
| Better Auth secret rotation quebra sessões | Baixa | Médio | Documentar rotação; rolling sessions |
| Hot-reload de MCP server requer Redis em multi-instância | Baixa | Baixo | Single-instance no Easy Panel até precisar escalar |
| Dependência `openpyxl` no Python para XLSX (mantém Python no path) | n/a — desejada | n/a | Confirma escolha de MCP server Python |

---

## 10. Estimativa total

| Fase | Dias úteis |
| --- | --- |
| 0. Decisão + scaffolding | 1–2 |
| 1. Baseline local | 2–3 |
| 2. Auth + org allowlist | 3–5 |
| 3. Gitinho MCP server (23 tools) | 5–7 |
| 4. Plug no better-chatbot | 2–3 |
| 5. Glossário + Project Instructions | 1–2 |
| 6. XLSX exports | 3–5 |
| 7. Custom Agents | 2–3 |
| 8. Workflows (opcional) | 3–5 |
| 9. Hardening + deploy + cutover | 2–3 |
| 10. Limpeza | 1 |
| **Total mínimo (sem 8)** | **22–33 dias** (≈ 4½–6½ semanas) |
| **Total com workflows** | **25–38 dias** (≈ 5–7½ semanas) |

**Caminho crítico mínimo viável (MVP — feature parity sem ganhos):**
Fases 0–4 + 6 + 9 ≈ **15–22 dias** (3–4½ semanas).

---

## 11. Próximos passos imediatos (se aprovado)

1. **Confirmar Opção A** com stakeholders (1 reunião curta).
2. **Validação técnica de 1 dia:** rodar o better-chatbot localmente
   com Azure OpenAI ligado, só para garantir que o
   `azure-openai-compatible.ts` aceita nosso endpoint v1 Foundry.
3. **Criar fork** `splor-mg/gitinho-chat` (privado).
4. **Spike de 2 dias:** portar 1 tool (`count_repos`) como MCP server
   stdio e plugar no fork. Se isso funciona, todo o resto é
   incremental e previsível.
5. **Apresentar resultado do spike** antes de começar Fase 3 cheia.

---

## 12. Decisões em aberto (precisam input)

1. **Monorepo vs multi-repo?** Recomendação: monorepo
   (`pnpm + uv workspaces`).
2. **MCP transport: stdio (default) ou SSE/HTTP?** Recomendação:
   stdio (sem complexidade de rede); mudamos depois se precisar de
   multi-cliente.
3. **Migrar histórico de chats existentes?** Recomendação: não.
   Fase 1 atual ainda não tem uso real.
4. **Workflows agora ou depois?** Recomendação: agora não (MVP sem).
   Próxima iteração.
5. **Voz na Fase 1?** Recomendação: não — gating por feature flag,
   destrava em fase futura.
6. **Code-runner ligado?** Recomendação: **não** na Fase 1 — adiciona
   superfície de ataque. Considerar Fase 2.
7. **File ingest (PDF/docx)?** Recomendação: ligado, sem upload externo
   (storage local apenas).

---

## 13. Apêndice — referências externas

- Repositório upstream: <https://github.com/cgoinglove/better-chatbot>
- AGENTS.md (convenções de desenvolvimento)
- `docs/tips-guides/mcp-server-setup-and-tool-testing.md`
- `docs/tips-guides/adding-openAI-like-providers.md`
- `docs/tips-guides/system-prompts-and-customization.md`
- `docs/tips-guides/oauth.md`
- MCP spec oficial: <https://modelcontextprotocol.io/>
- Python MCP SDK: <https://github.com/modelcontextprotocol/python-sdk>
- Better Auth: <https://www.better-auth.com/>
- Drizzle ORM: <https://orm.drizzle.team/>

# Log de Decisões

> Decisões tomadas em sessões de planejamento. Cada entrada explica **o
> que** foi decidido, **por que**, e **alternativas consideradas**. Use
> este log para entender o histórico antes de mudar algo estrutural.

## 2026-05-26 — Migração para better-chatbot + MCP Python

O esqueleto FastAPI/React+Vite escrito em 2026-05-21 foi descartado em
favor de um monorepo:
- `apps/chat/` — fork vendored de `cgoinglove/better-chatbot` (Next.js 16,
  Vercel AI SDK, Better Auth, Drizzle ORM)
- `apps/mcp/` — servidor MCP Python `gitinho-mcp` (FastMCP) com 22 tools
  read-only

Versão pré-migração congelada na tag `pre-migration-2026-05-25` e copiada
para `../gitinho-legacy/` fora do repo. Plano completo da migração em
[`MIGRATION_BETTER_CHATBOT.md`](./MIGRATION_BETTER_CHATBOT.md).

### Por que better-chatbot

O FastAPI+React custom precisava reconstruir do zero: workflows, agents
nomeados, file ingest, voz, multi-provider, admin panel, share, i18n,
threads, archive. O better-chatbot já entrega tudo isso em qualidade
superior à que conseguiríamos em prazo razoável, sob licença MIT.

**Alternativas consideradas:**
- **Continuar FastAPI custom**: ~3+ meses para feature parity com
  better-chatbot. Não justifica.
- **Strip-and-mount** (better-chatbot só como build estático + FastAPI
  back): descartado — better-chatbot é Next.js full-stack, não SPA;
  perderia features que dependem do back TS.
- **Híbrido** (better-chatbot + FastAPI atual como MCP HTTP): mais
  latência e mais infra (CORS, auth dupla). Stdio MCP é mais simples.

### Por que MCP Python (não TypeScript)

As 22 tools sobreviveram 1:1 — apenas mudaram de registry Python custom
para `@mcp.tool()` do SDK MCP oficial. Zero rework de regra GitHub:
- `GitHubClient` + `OrgAllowlistError`
- Tools `find_datapackages`, `org_users_activity_report`, etc.
- Geração XLSX via `openpyxl` (no caso de `convert_document`, MarkItDown)

Manter Python deixou a base de domínio intacta e abriu a porta para
reusar `gitinho-mcp` fora do chat (CLI, cron, CI) ou plugar outros
servidores MCP (GitHub oficial, Postgres, filesystem) no mesmo chat.

### MCP via stdio (não SSE/HTTP)

`FILE_BASED_MCP_CONFIG=true` aponta o better-chatbot para
`.mcp-config.json`, que executa `uv run python -m gitinho_mcp` como
subprocesso no mesmo container.

**Por que stdio:**
- Sem rede, sem CORS, sem porta exposta.
- Sem auth entre chat e MCP (são o mesmo processo lógico).
- Latência mínima.

**Quando migrar para SSE/HTTP:** se quisermos múltiplos clientes (ex.:
CLI + chat) compartilhando o mesmo servidor. Por enquanto não é o caso.

### Exports: tool nativa `createTable` (não tool MCP custom)

A geração de XLSX/CSV foi movida do servidor MCP para o frontend. O
LLM agora busca os dados via tool MCP (ex.: `org_users_activity_report`)
e chama `createTable` (tool nativa do better-chatbot) com
`title/columns/data`. A tabela renderizada já tem botões nativos de
download XLSX/CSV.

**Por que:** elimina round-trip de payload binário pelo MCP, dá ao
usuário controle de coluna/ordenação na UI, e remove ~300 linhas de
código de geração XLSX do MCP.

### Allowlist por org no Better Auth (não em código próprio)

Hook `databaseHooks.account.create.before` em
`apps/chat/src/lib/auth/auth-instance.ts` chama
`assertGitHubOrgMembership(accessToken, ALLOWED_ORG)` antes de persistir
a conta. Logo após, `stripOAuthTokens` zera o token OAuth (identidade
fica, segredo some).

**Por que `/user/orgs` em vez de `/user/memberships/orgs/{org}`:**
`/user/orgs` lista apenas orgs que o usuário **explicitamente
autorizou o OAuth App a acessar** no fluxo de consentimento. Isso
implementa o "per-org grant" que o usuário pediu — não basta o usuário
ser membro de `splor-mg`, ele precisa ter dado consent explícito ao
Gitinho para aquela org.

### MinIO sidecar para file ingest (não Vercel Blob, não filesystem)

Decidido em 2026-05-26 (fase 7-8): adicionar `minio` como sidecar do
compose, com bucket `gitinho-uploads`. Driver `FILE_STORAGE_TYPE=s3`.
Porta apenas em `127.0.0.1`.

**Por que MinIO local em vez de Vercel Blob ou S3 real:**
- Easy Panel é self-hosted; não queremos dependência externa para uma
  feature opcional (file ingest).
- MinIO é S3-compatível — se um dia migrarmos para S3 real, é mudar
  endpoint e credenciais.
- Mantém payload sensível dentro da VM da org.

**Por que não filesystem:** better-chatbot espera driver S3 ou
vercel-blob. Implementar driver "local fs" seria patch invasivo no
upstream.

### Per-org OAuth grant (limitação confirmada)

Confirmado durante a migração: GitHub OAuth Apps **não suportam**
"grant por org" nativamente — uma OAuth App é por-conta. O que protege
o Gitinho:
1. GitHub App (que faz o acesso a dados) instalada apenas em `splor-mg`.
2. `/user/orgs` retorna só orgs com consent explícito do OAuth App
   pelo usuário.
3. `OrgAllowlistError` no cliente HTTP do MCP.

Para multi-org, cada deploy do Gitinho usa sua própria GitHub App.

---

## 2026-05-21 — Sessão inicial de planejamento e esqueleto da Fase 1

> ⚠️ A stack descrita abaixo foi **substituída** pela migração de
> 2026-05-26 (acima). Mantida como histórico — a maioria dos racionais
> (precisão GraphQL, allowlist em camadas, read-only enforcement,
> deploy Easy Panel como serviços individuais) **continuam aplicáveis**
> à stack atual, só mudaram de implementação.

### Stack: Python + FastAPI (substituindo Node.js)

A stack Node original (preservada em `legacy/`) foi descartada em favor de
Python 3.12 + FastAPI + SQLAlchemy 2 async + Postgres 16.

**Por que:**
- Ecossistema Python para agentes é mais maduro (OpenAI SDK, MCP Python
  SDK oficial, structlog).
- async-first do FastAPI casa com SSE para streaming de tokens.
- openpyxl + pandas dão controle preciso de tipos em Excel — o brief
  exige relatórios em planilha.
- Postgres (não SQLite) por causa de multi-usuário, FK estritas, JSONB
  para `tool_calls`, e auditoria.

**Alternativas descartadas:** continuar em Node (ecossistema mais raso
para agentes), Go (perda de velocidade de iteração), SQLite (multi-user
+ concurrent writes problemático).

### LLM: Azure AI Foundry com 3 deployments por papel

- Orquestrador: GPT-4.1 (ou GPT-5 se disponível)
- Raciocínio analítico pesado: o3
- Tarefas leves (títulos de chat, classificação): GPT-4.1-mini

**Por que:** O usuário tem assinatura corporativa Azure Foundry ampla
(praticamente todos os modelos). Priorizar **precisão sobre custo** foi
explicitamente solicitado. Roteamento por papel evita usar o3 onde 4.1
basta.

**Como aplicar:** env vars `AZURE_DEPLOYMENT_ORCHESTRATOR`,
`AZURE_DEPLOYMENT_ANALYTIC`, `AZURE_DEPLOYMENT_LIGHT` permitem trocar
modelos sem mudar código.

### Precisão: GraphQL agregado, nunca somar via LLM

Toda contagem (repos, PRs, issues, commits) usa `totalCount` do GraphQL
v4 ou `search/issues` com `total_count`. O LLM **nunca** soma resultados
parciais.

**Por que:** O brief exige "precisão absoluta — nunca aproximar". LLMs
erram aritmética e perdem itens em paginação. Delegando para a API,
a fonte de verdade é o GitHub.

**Como aplicar:** Cada tool customizada em `backend/app/tools/` é
implementada com queries determinísticas. O system prompt instrui o LLM
a **chamar a tool** em vez de calcular mentalmente.

### Autenticação: GitHub App + OAuth separados

- **GitHub App (read-only)**: agente faz todas as chamadas à API da org
  usando installation token (JWT RS256 → token de 1h).
- **GitHub OAuth**: só para identificar o humano que está logando. Token
  OAuth é descartado logo após checar membership na `ALLOWED_ORG`.

**Por que:** Separação de concerns. O token do agente **nunca** é o
token do usuário — se o usuário não tem permissão para algo, o agente
ainda tem (e vice-versa). Reduz blast radius: comprometer cookie de
sessão não dá acesso à API do GitHub.

### Org allowlist em 3 camadas

1. **Permissão no token**: GitHub App só está instalado na `ALLOWED_ORG`.
2. **Login**: usuário precisa ser membro da `ALLOWED_ORG`
   (`/user/memberships/orgs/{org}`).
3. **Defesa em profundidade no cliente HTTP**: `_check_owner` em
   `backend/app/github/client.py` levanta `OrgAllowlistError` se algum
   path tem owner ≠ `ALLOWED_ORG`.

**Por que:** Qualquer uma das camadas, sozinha, pode falhar (bug, config
errada, escopo do App ampliado por engano). As três juntas tornam
exfiltração entre orgs praticamente impossível.

### Read-only enforcement (Fase 1) preparado para Fase 2

- `ToolMode` enum em `backend/app/tools/_base.py`: `READ | WRITE | ADMIN`.
- Env `AGENT_ALLOW_WRITE=false` (default). `ToolRegistry.all(include_write=False)`
  filtra qualquer tool WRITE no carregamento.
- MCP client (`backend/app/mcp/client.py`) tem `_is_read_only` que rejeita
  tools com prefixos `create_/update_/delete_/merge_/close_/...`.
- Fase 2 ativará `AGENT_ALLOW_WRITE=true` + UI de confirmação humana com
  diff antes de cada chamada WRITE.

**Por que:** Brief exige "primeira fase pensando em escrita futura". A
arquitetura permite ligar escrita por env var, sem refactor estrutural,
mas mantendo confirmação humana obrigatória.

### Deploy: serviços individuais no Easy Panel (não docker-compose)

O usuário tem VM Azure com **Easy Panel** instalado, com projeto
chamado `applications`. Produção = adicionar **3 serviços** ao projeto:
- `gitinho-db` (Database → PostgreSQL 16, managed pelo Easy Panel)
- `gitinho-backend` (App, build from GitHub, porta interna 8000)
- `gitinho-frontend` (App, build from GitHub, porta interna 80, domínio
  público + HTTPS automático)

**Por que:** Easy Panel não é Docker Swarm nem Kubernetes — é um painel
onde você adiciona serviços individuais. Tentar empurrar um
`docker-compose.prod.yml` não bate com o modelo mental do produto e
deixaria o usuário sem usar features nativas (env vars seguras,
auto-deploy on push, backups, healthchecks, Let's Encrypt).

**Decisão derivada:** `deploy/docker-compose.prod.yml` foi removido. Só
existe `deploy/docker-compose.yml` para **dev local**. Produção mora em
`deploy/easy-panel.README.md`.

### Frontend Docker image: parametrizado por env var (BACKEND_HOST)

`frontend/nginx.conf.template` usa `${BACKEND_HOST}:${BACKEND_PORT}`,
renderizado por envsubst no startup (feature nativa do
`nginx:1.27-alpine`).

**Por que:** Em dev local (compose), o nome de serviço é `backend`. No
Easy Panel, é `gitinho-backend`. Sem parametrização, precisaríamos de
duas imagens diferentes. Com env vars (defaults `backend:8000`), **a
mesma imagem** funciona nos dois ambientes.

### Multi-org: trio de serviços por org, mesmo projeto Easy Panel

Para servir uma segunda org, **não** clonar a VM nem o projeto — apenas
adicionar `gitinho-<org2>-db`, `gitinho-<org2>-backend`,
`gitinho-<org2>-frontend` no mesmo projeto, com `ALLOWED_ORG=<org2>` e
GitHub App próprio.

**Por que:** Isolamento total de dados (DB físico separado +
`ALLOWED_ORG` separado), zero cruzamento, blast radius contido. Custo
incremental por org é pequeno (Postgres + 2 containers leves).

### Logs: verbosos por padrão, segredos sempre redacted

Postura permissiva para logs (verbose para debugging), MAS:
- `_redact_processor` em `backend/app/logging_setup.py` mascara tokens,
  segredos, `Bearer …`, padrões `gh_…` em **todos** os logs.
- Defesa em profundidade arquitetural (allowlist, token read-only, sem
  write tools registradas) continua aplicada **mesmo em modo permissivo
  de log**.

**Por que:** Usuário confia na própria org, prefere conveniência de
debugging, mas vazamento de token em log é incidente real (não é
discricionário).

### Memória de sessão estilo ChatGPT

- Sidebar com lista de chats, persistência em Postgres.
- Sumarização incremental de histórico longo (não tentar enfiar 10k
  mensagens no contexto).
- Título de chat gerado por LLM leve (GPT-4.1-mini) a partir da
  primeira mensagem.

**Por que:** UX explicitamente comparada a "ChatGPT/Grok/Gemini" no
brief. Persistência em DB é o que diferencia de uma sessão volátil.

# Log de Decisões

> Decisões tomadas em sessões de planejamento. Cada entrada explica **o
> que** foi decidido, **por que**, e **alternativas consideradas**. Use
> este log para entender o histórico antes de mudar algo estrutural.

## 2026-05-21 — Sessão inicial de planejamento e esqueleto da Fase 1

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

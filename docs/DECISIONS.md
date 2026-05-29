# Log de Decisões

> Decisões tomadas em sessões de planejamento. Cada entrada explica **o
> que** foi decidido, **por que**, e **alternativas consideradas**. Use
> este log para entender o histórico antes de mudar algo estrutural.

## 2026-05-29 — Navegação de repo + troca de modelo default (terceira iteração)

Mesmo com `describe_repo` na prod, o agente continuou patinando em
perguntas do tipo "me dê uma análise completa do dpm, inclusive sobre
seu funcionamento":

1. Chutou paths sem listar — `dpm/__init__.py`, `dpm/manager.py`,
   `manager.py`, `src/dpm.py` — todos 404. A estrutura real do dpm é
   `main.py` na raiz + `src/` (sem subdir `dpm/`).
2. Invocou `list_org_repos` (178 repos) na investigação de UM repo —
   desperdício gritante de contexto.
3. **Alucinou conteúdo do README**: disse haver "instruções para
   construir imagem Docker e rodar jupyter notebook" — o README real
   tem 777 B (título + badges, nenhuma instrução).

Duas decisões compostas:

### Decisão A — Tools de navegação

- **`list_repo_contents(repo, path)`** — nova tool. Lista entries
  reais de um path; `path=""` (default) lista a raiz. Resposta clara
  `{ok, entries: [{name, type, size, path}]}`, sem disfarçar como
  erro quando recebe um diretório.
- **`describe_repo` agora retorna `root_listing`** — top-level
  files/dirs do repo já vêm na primeira chamada. O LLM passa a ter
  o "mapa" do repo de cara, sem precisar de uma segunda viagem só
  pra descobrir que `dpm/` não existe e o módulo principal é
  `main.py` na raiz.

Total subiu de 25 para 26 tools.

### Decisão B — Trocar modelo default para Claude Sonnet 4.6

Anteriormente: GPT-4.1. Hipótese diagnóstica (confirmada com o
usuário): em loops de "explorar → ler → decidir próximo passo"
(estilo Claude Code), o GPT-4.1 fica para trás em três frentes
observáveis no transcript:

- Não corrige rumo após 404s — repete chutes em vez de listar.
- Invoca tools óbvia e custosamente erradas (`list_org_repos` para
  pergunta sobre 1 repo).
- Alucina conteúdo quando o input legítimo é curto.

Claude Sonnet 4.6 é dramaticamente melhor nas três. Opus 4.7 também,
mas com custo muito maior — mantemos disponível na UI sob demanda,
não como default. Implementação: `apps/chat/src/lib/ai/models.ts`
ganhou `sonnet-4.6` e `opus-4.7` em `staticModels.anthropic` e o
`fallbackModel` agora aponta pra Sonnet 4.6.

### Decisão C — Reescrita do system prompt

O `buildGitinhoBasePrompt` foi reestruturado:

- Princípio explícito (#7): **"Nunca chute caminhos de arquivo."**
  Recipe: `describe_repo` → `root_listing` → `list_repo_contents` →
  `get_file_content` em paths reais.
- Princípio explícito (#8): **"Não use `list_org_repos` para
  perguntas sobre 1 repo."** Cite a razão (custo de contexto) e a
  alternativa (`describe_repo`/`get_repo`/`list_repo_contents`).
- Princípio explícito (#9): **"Não invente conteúdo."** Hallucination
  é o pior erro possível.
- Princípio explícito (#12): **"`convert_document` é só para uploads
  do usuário."** Anti-padrão observado em prod (LLM chamou pra
  "buscar URL").

### Alternativas consideradas

- **Só trocar o modelo, sem mudar tools.** Subestima o problema:
  mesmo um modelo top precisa de tool de listagem pra navegar repo.
- **Adicionar `walk_repo` que faz BFS automático.** Descartado:
  rebenta janela de contexto em repos médios (>50 arquivos) e
  não dá pro LLM o controle de "olhar onde importa".
- **Forçar `describe_repo` no system prompt em vez de também ter
  `list_repo_contents` à parte.** Insuficiente — para queries de
  drill-down ("o que tem dentro de src/?") a listagem isolada é
  necessária.

## 2026-05-29 — Orquestrador `describe_repo` (segunda iteração)

Logo após adicionar `get_repo_readme` + `get_file_content` (entrada
abaixo), observamos em produção que o LLM **não invocava** as tools
novas para perguntas tipo "do que se trata o repo X?". Em vez disso
caía em `convert_document` (tool de ingest de upload — não fetcha
URL nem nada remoto), chutava ler o site mkdocs sem ter tool pra
isso, e respondia "não sei" mesmo com o README disponível.

Diagnóstico: dar três tools compostáveis (`get_repo` + `get_repo_readme`
+ `get_file_content`) coloca o ônus de orquestração no LLM, e ele
falha. Para o README do `dpm` (777 B = título + badges) uma chamada
sozinha é insuficiente — a descrição real está em `pyproject.toml`
e nas páginas mkdocs (`docs/index.md`).

Resposta: tool orquestradora `describe_repo(repo)` que numa única
chamada (paralelizada via `asyncio.gather`) busca:

- metadata (`get_repo`)
- README via `/readme`
- `docs/index.md`, `docs/README.md` — landing pages do MkDocs
- `mkdocs.yml` — site_name + nav, útil mesmo sem renderizar HTML
- `pyproject.toml`, `package.json`, `datapackage.json`,
  `requirements.txt` — manifests com descrição/dependências

Tolerante a falhas individuais: arquivo ausente vira `null` no dict,
nunca quebra a chamada. Docstring agressiva ("USE THIS for …", "Do
**not** call `convert_document` to fetch a URL") guia o LLM.

Total subiu de 24 para 25 tools.

### Por que não foi suficiente só atualizar a docstring

A docstring de `get_repo_readme` já dizia "use whenever a user asks
what a repo is about". Em produção o LLM ainda errou. Razões
prováveis:

1. **Espaço de decisão grande**. Com 24 tools, o LLM tem muitas
   opções erradas (`get_repo`, `search_issues`, `convert_document`,
   etc.) com nomes que parecem plausíveis.
2. **README sozinho é insuficiente para alguns repos**. Mesmo se o LLM
   chamasse `get_repo_readme`, o `dpm` daria 777 B inúteis.

Orquestrador resolve as duas: uma tool com nome explícito do uso
(`describe_repo`), e ela já busca em paralelo todos os arquivos que
juntos formam uma resposta substantiva.

### Alternativas consideradas

- **Só reescrever a docstring** de `get_repo_readme` mais agressiva.
  Descartado: não resolve o caso `dpm` onde README é insuficiente.
- **Tool `fetch_url`** para puxar a página renderizada do mkdocs.
  Descartado pela mesma razão da entrada abaixo (escapa do allowlist
  de org). E os arquivos-fonte (`docs/*.md`) já vêm pela API de
  contents da própria org.
- **Fetch dinâmico do `nav` do mkdocs.yml** para ler todas as páginas
  documentadas. Adiável: complexidade extra (parse YAML, recursão por
  N páginas) que ainda não se justifica — README + `docs/index.md` +
  manifests resolvem o caso de uso.

## 2026-05-29 — Tools de leitura de conteúdo de arquivo

Adicionadas duas tools ao `gitinho-mcp`:

- `get_repo_readme(repo, ref?)` — chama `GET /repos/{org}/{repo}/readme`.
- `get_file_content(repo, path, ref?)` — chama `GET /repos/{org}/{repo}/contents/{path}`.

Total subiu de 22 para 24 tools.

### Por que

Perguntas do tipo "sobre o que é o repo X?" caíam num beco sem saída:
as tools existentes (`get_repo`, `search_issues`) só viam metadata
(descrição, linguagem, datas, contagens). Quando a descrição vinha
vazia — comum nos repos antigos — o agente respondia que não sabia.
O conteúdo real (README, manifestos como `mkdocs.yml`,
`datapackage.json`, `pyproject.toml`) era invisível ao LLM.

A permissão `Contents: Read` da GitHub App já existia desde a Fase 1
(ver `SECURITY.md` §2.1) — só faltava expor o caminho na camada MCP.

### Decisões de design

- **Cap de 512 KB por arquivo**. O endpoint `/contents` do GitHub
  devolve até 1 MB inline (base64) e rejeita >100 MB; entre 1–100 MB
  exigiria cair na Git Data API (`/git/blobs`). Em vez de implementar
  os três caminhos, fixamos um teto bem abaixo de 1 MB para proteger a
  janela de contexto do LLM (512 KB ≈ 130k tokens, já cobre README e
  manifestos com folga). Acima disso, a tool retorna erro com
  `html_url` e o agente orienta o usuário a abrir no GitHub.
- **`ref` opcional**. Permite buscar conteúdo em branch/tag/SHA
  específico ("como era o README na tag `v1.0`?"). Custo zero —
  apenas repassa o query param.
- **UTF-8 obrigatório**. Binários (imagens, PDFs em repo) são
  rejeitados explicitamente. Para PDF/DOCX já existe `convert_document`
  (file ingest, não fetch remoto).
- **Erros como dado**, não exceção: `{"ok": false, "error": "..."}`.
  Segue o padrão de `convert_document`; o agente trata o "não achei" /
  "muito grande" como informação e adapta a resposta.

### Alternativas consideradas

- **Tool genérica `fetch_url`** para qualquer URL (incluindo páginas
  mkdocs renderizadas). Descartada nesta rodada: escapa do allowlist
  da org (`OrgAllowlistError` deixa de fazer sentido pra URLs
  arbitrárias), e o caso de uso central — "do que se trata este repo"
  — é resolvido com leitura do README direto da API. Fica anotado pra
  uma Fase 3 caso precise.
- **Stream Git Data API para arquivos > 1 MB**. Não compensa: nenhum
  uso atual passa de centenas de KB.

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

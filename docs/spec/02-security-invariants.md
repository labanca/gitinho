# 02 — Invariantes de segurança

O que NÃO pode regredir no rebuild. Cada item lista (a) o que ele garante, (b) onde está enforçado hoje, (c) como detectar regressão.

A maioria desses invariantes é redundante por design — defesa em profundidade. Se um deles cair, os outros seguram. Mas qualquer um deles sumindo é regressão e precisa de teste.

---

## I.1 — Read-only

**Garante**: O agente nunca cria/edita/comenta/deleta nada na org. Issues, PRs, comments, files, branches — só leitura.

**Enforçado em**:
- `apps/mcp/gitinho_mcp/tools/*.py` — só endpoints GET/GraphQL queries. Nenhum POST/PUT/PATCH/DELETE.
- `apps/mcp/gitinho_mcp/github/client.py:85` — `GitHubClient.get(...)`, `paginate(...)`, `graphql(...)`. Não há `post`/`put`/`patch`/`delete`.
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts` — só exporta `GET`; outros métodos retornam 405.

**Detecção de regressão**: `rg -n "ctx\.gh\.(post|put|patch|delete)" apps/mcp` deve retornar zero. Qualquer PR que adicione método mutador no client é alarme vermelho.

---

## I.2 — Org allowlist (`ALLOWED_ORG`)

**Garante**: A GitHub App tem acesso técnico a outras organizações em que possa estar instalada, mas o Gitinho só consulta `splor-mg`. Tentativa de leakage cross-org (via parâmetro `owner` na MCP ou `repo:other-org/x` em search) é bloqueada.

**Enforçado em**:
- `apps/mcp/gitinho_mcp/github/client.py:73-79` — `_check_owner()` levanta `OrgAllowlistError` se `owner != ALLOWED_ORG` e o caller não passou `owner=None`.
- `apps/mcp/gitinho_mcp/tools/code_search.py:13-50` — `_strip_scope_qualifiers()` remove qualquer `org:`, `user:`, `repo:` que o agente injete na query e re-anchora em `org:<ALLOWED_ORG>`.
- `apps/mcp/gitinho_mcp/tools/pulls.py` (mesmo helper) — `search_prs` e `list_prs_by_repo` aplicam a mesma defesa.
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts` — allowlist de path: aceita só `/repos/<ALLOWED_ORG>/...` e `/orgs/<ALLOWED_ORG>...`.

**Detecção de regressão**: tests unitários pra `_strip_scope_qualifiers` (já existem inline no commit `ef3ea3a`). Pra o proxy: chamar `GET /api/gh-proxy/repos/other-org/foo` autenticado e confirmar 403.

---

## I.3 — GitHub App, nunca PAT

**Garante**: Autenticação contra a GitHub API usa um GitHub App + installation token mintado on-demand. PATs de usuário não são lidos nem aceitos. O token tem TTL ~1h e é cacheado server-side com refresh 30s antes do exp.

**Enforçado em**:
- `apps/mcp/gitinho_mcp/github/app_auth.py` — JWT RS256 via PEM da App; troca por installation token na rota `/app/installations/{id}/access_tokens`.
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts:24-78` — mesma lógica replicada server-side (sem dep nova, usa `node:crypto`).

**Detecção de regressão**: nenhum dos dois (`client.py`, `route.ts`) pode importar nem ler `GH_TOKEN` ou `GITHUB_TOKEN`. Se aparecer, é fallback PAT velado.

---

## I.4 — Token nunca sai pro browser/LLM

**Garante**: O installation token vive só dentro da rede privada (container do MCP, server-side da rota Next). Nunca aparece em response body, em texto da resposta do agente, nem em headers que cheguem ao browser.

**Enforçado em**:
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts:14-19` — comentário de design + handler descarta `Authorization` header do caller antes de forwardar.
- Sistema prompt em `apps/chat/src/lib/ai/prompts.ts` (item 4) — "Nunca inclua tokens, segredos ou identificadores internos de API em suas respostas".
- MCP tools nunca retornam o token nos campos de resposta — verificável por `rg "token" apps/mcp/gitinho_mcp/tools/`.

**Detecção de regressão**: teste manual — abrir DevTools → Network → fazer pergunta que use a MCP → confirmar que nenhum response body contém substrings de token (`ghs_*`, `ghp_*`, `gho_*`).

---

## I.5 — CSP estrito (app principal) + relaxado escopado (Pyodide runner)

**Garante**: O HTML do app não pode executar script de terceiros, conectar a domains não-listados, ou embedar em iframe externo. O runner de Pyodide, que precisa relaxar várias coisas, vive numa rota separada (`/pyodide-runner`) com headers exclusivos — o app principal continua intacto.

**Enforçado em**:
- `apps/chat/next.config.ts:11-30` (`csp`) — `default-src 'self'`, `script-src` com `'wasm-unsafe-eval'` (necessário pro Shiki, ver commit `28043ea`), `connect-src 'self' https://api.github.com`, `frame-ancestors 'none'`.
- `apps/chat/next.config.ts:41-52` (`runnerCsp`) — escopo do `/pyodide-runner`. Permite `blob:` workers, WASM eval, `cdn.jsdelivr.net` (Pyodide CDN). `frame-ancestors 'self'` (mas não externo) garante que só o app principal embeda.
- `apps/chat/next.config.ts:98-113` — header rules com regex negative-lookahead pra não misturar os 2 CSPs.

**Detecção de regressão**: abrir `/test/pyodide` em produção e rodar o smoke (3 passos). Falha do passo 3 ("CSP bloqueia api.github.com direto") significa que o `connect-src` do runner foi relaxado por acidente.

---

## I.6 — Pyodide runs only inside same-origin iframe with cookie attached

**Garante**: O Pyodide do agente nunca tem credencial GitHub direta. Pra ler dados da org, faz `pyfetch("/api/gh-proxy/...")` — o iframe é same-origin, então o cookie de sessão do usuário acompanha, o proxy mint do token acontece server-side, e o token nunca aparece no contexto Python.

**Enforçado em**:
- `apps/chat/src/app/pyodide-runner/page.tsx` + `runner-client.tsx` — host do iframe.
- `apps/chat/src/lib/code-runner/call-worker.ts` — instancia o iframe com `src="/pyodide-runner"` (same-origin).
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts` — gate de session cookie obrigatório.
- Sistema prompt (`apps/chat/src/lib/ai/prompts.ts` seção "Análises com Python") proíbe explicitamente `api.github.com` direto ou `raw.githubusercontent.com` direto.

**Detecção de regressão**: teste smoke em `/test/pyodide` passo 3 deve continuar passando (CSP bloqueia fetch direto à `api.github.com`).

---

## I.7 — Allowlist de path no proxy (defense in depth)

**Garante**: Mesmo que session check e org check no MCP falhem, o proxy só forwarda paths que casam exatamente `/repos/<ALLOWED_ORG>/...` ou `/orgs/<ALLOWED_ORG>...`. Path traversal (`..`) é bloqueado mesmo encodado (`%2E%2E`, etc.).

**Enforçado em**:
- `apps/chat/src/app/api/gh-proxy/[...path]/route.ts` — `isAllowedPath()` com `decodeURIComponent` antes do `includes("..")`. 15 casos de teste cobertos no commit que introduziu (vide `git log`).

**Detecção de regressão**: rodar mentalmente cada caso: `repos/splor-mg/foo` ✓, `repos/Splor-MG/foo` ✓ (case-insensitive), `repos/other/x` ✗, `repos/splor-mg/foo/../../other/x` ✗, `repos/splor-mg/foo/%2E%2E/other` ✗, `orgs/splor-mg` ✓, `orgs/other` ✗.

---

## I.8 — Body content limitado pra evitar leak de blob grande na resposta do LLM

**Garante**: Bodies de PR, issue, README — qualquer texto que pode conter dados sensíveis (logs, dumps de erro, configs vazadas em commit) — são truncados pra um limite explícito antes de irem pra context do LLM.

**Enforçado em**:
- `apps/mcp/gitinho_mcp/tools/pulls.py:_truncate()` — limita body de PR a 4000 chars com marker visível.
- `get_pr` aplica em `body` (4000 chars) e em cada review body (1000 chars).
- Diff de PR (`include_files`) NÃO retorna o `patch` raw — só `additions/deletions/changes`. Se o agente precisar do diff, manda o usuário ao GitHub.

**Detecção de regressão**: revisar tools novas — qualquer campo `body`, `description`, `content` sem `_truncate()` é candidato a regressão.

---

## I.9 — Sem ações destrutivas no painel admin

**Garante**: O painel admin (`/admin/users`) permite gerenciar contas locais, mas operações irreversíveis (deletar usuário, mudar permissão) exigem confirmação UI e logging. Read-only por default; mutations explícitas só.

**Pendência atual**: este invariante existe na intenção mas a verificação no código ainda não foi formalizada. Marcar como gap.

---

## I.10 — Hardening headers em todas as rotas

**Garante**: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=()/microphone=()/geolocation=()`, HSTS quando HTTPS habilitado. Aplicados tanto pro app principal quanto pro runner.

**Enforçado em**:
- `apps/chat/next.config.ts:54-82` — `baseHardeningHeaders` mais `securityHeaders` (app) ou `runnerHeaders` (runner).

**Detecção de regressão**: `curl -I https://applications-gitinho-splor-mg.nhfnv0.easypanel.host/` deve mostrar todos esses headers.

---

## Checklist mínimo do rebuild

Antes de fazer merge de um rebuild, validar:

- [ ] Nenhum método mutador no GitHub client.
- [ ] `_check_owner` aplicado em TODA chamada que recebe `owner` de fora.
- [ ] Qualifier strip em TODA tool de busca/search (não só `search_code` e `search_prs`).
- [ ] Proxy `/api/gh-proxy` continua GET-only, com session check, allowlist e path-traversal block.
- [ ] CSP do app principal sem `'unsafe-eval'` (só `'wasm-unsafe-eval'` é OK).
- [ ] `runnerCsp` separado pra `/pyodide-runner`, sem relaxar `connect-src` pra `api.github.com`.
- [ ] PEM da App não está no repo, não está no Docker image, lido só de path em runtime.
- [ ] Bodies de texto livre (PR, issue, README) truncados antes de irem pro LLM.
- [ ] Smoke test em `/test/pyodide` passando os 3 passos em produção.

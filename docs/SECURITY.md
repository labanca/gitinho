# Gitinho — Segurança

> Postura: **read-only por padrão**, **defesa em profundidade** e
> **isolamento por organização**. Mesmo que o LLM seja comprometido por
> prompt-injection, ele não consegue destruir nem exfiltrar ativos da
> organização.

> **Para detalhes técnicos atualizados de cada invariante** (com
> referências de arquivo:linha e como detectar regressão), ver
> [`spec/02-security-invariants.md`](./spec/02-security-invariants.md).
> Este documento mantém o modelo de ameaças e os controles em formato
> de overview.

## 1. Modelo de Ameaças

| Atacante | Vetor | O que ele pode fazer | Como bloqueamos |
|---|---|---|---|
| Outsider | Internet pública | Acessar a UI sem login | OAuth obrigatório; allowlist de org |
| Usuário externo à org | Login GitHub OAuth | Logar com conta fora da org | `assertGitHubOrgMembership` em `signIn.before` recusa membership ≠ `ALLOWED_ORG` |
| Usuário interno legítimo | Prompt malicioso ao LLM | "Apague o repo X" | GitHub App sem escopo de escrita; nenhuma tool WRITE registrada no MCP |
| Conteúdo malicioso na org | Issue/PR com prompt-injection | Faz o LLM tomar ações destrutivas | Tools WRITE inexistentes; `NOT_ALLOW_ADD_MCP_SERVERS=1`; `OrgAllowlistError` no cliente GitHub |
| Atacante com acesso ao host | Arquivos no servidor | Lê chave privada da GitHub App | `secrets/gh-app.pem` montado read-only no container; fora do repo (`.gitignore`) |
| Atacante na rede | MITM | Lê cookie de sessão | HTTPS obrigatório no proxy do Easy Panel; HSTS; cookies `Secure` |
| Operador interno | Plugar MCP server malicioso | Tools arbitrárias via UI | `NOT_ALLOW_ADD_MCP_SERVERS=1` bloqueia adição via UI |

## 2. Controles

### 2.1 GitHub App — Permissões Mínimas

```
Repository permissions:
  Metadata           Read
  Contents           Read
  Issues             Read
  Pull requests      Read
  Discussions        Read
  Actions            Read   (opcional)
  Pages              No access
  Secrets            No access
  Webhooks           No access

Organization permissions:
  Members            Read
  Administration     No access
  Custom roles       No access

Account permissions:
  (none)

Subscribe to events: none (Fase 1)
```

Em Fase 2, escopos de escrita só são adicionados após auditoria + ativação
de feature flag.

### 2.2 Allowlist de Organização (Defesa em Profundidade)

Três camadas independentes:

- **Camada 1 — App instalada apenas na org alvo.** A GitHub App está
  instalada apenas em `splor-mg`. Tentar acessar outra org devolve 404.
- **Camada 2 — Membership no login.** Hook `signIn.before` do Better Auth
  chama `https://api.github.com/user/orgs` com o token OAuth recebido e
  rejeita se `ALLOWED_ORG` não está na lista. Implementação em
  `apps/chat/src/lib/auth/github-org-allowlist.ts`. Token OAuth é
  descartado imediatamente após a verificação (não persistido em DB).
- **Camada 3 — Owner-check no cliente HTTP.** Em
  `apps/mcp/gitinho_mcp/github/client.py`, todo wrapper de URL inspeciona
  o `owner` e levanta `OrgAllowlistError` se ≠ `ALLOWED_ORG`. Última
  linha de defesa caso uma tool aceite parâmetro de owner por engano.

### 2.3 Tools — Read-only enforced

O servidor MCP `gitinho-mcp` **não registra nenhuma tool de escrita**.
Não existem funções `create_*`, `update_*`, `delete_*`, `merge_*`,
`close_*` em `apps/mcp/gitinho_mcp/tools/`. O LLM, ao introspeccionar
tools disponíveis via stdio, só vê tools READ.

Além disso:

- **`NOT_ALLOW_ADD_MCP_SERVERS=1`** bloqueia o usuário (mesmo admin) de
  plugar outros servidores MCP via UI do better-chatbot. A única
  origem de tools é o `.mcp-config.json` controlado por nós.
- Em Fase 2, tools WRITE só serão expostas com modal de confirmação
  humana mostrando o diff antes da chamada.

### 2.4 Autenticação e Sessão (Better Auth)

- Provider único habilitado: **GitHub OAuth**.
- `DISABLE_EMAIL_SIGN_IN=1`, `DISABLE_EMAIL_SIGN_UP=1`,
  `DISABLE_SIGN_UP=1` — caminhos de e-mail desligados.
- Cookie de sessão: HttpOnly, `Secure` em produção, `SameSite=Lax`.
- TTL: 7 dias; refresh a cada 1 dia de uso.
- `accessToken/refreshToken/idToken` do GitHub OAuth são **explicitamente
  zerados** antes de persistir em `account` (ver `stripOAuthTokens` em
  `apps/chat/src/lib/auth/auth-instance.ts`). Identidade fica, token
  some.
- O primeiro usuário a logar vira `admin` (regra do better-chatbot,
  cacheada em memória após o primeiro check).

### 2.5 CSRF

Better Auth aplica proteção CSRF nativa nos endpoints de auth. Routes
mutadoras do chat usam cookies HttpOnly + verificação de origem do
Next.js.

### 2.6 Rate-limit

Não há rate-limit aplicacional explícito nesta versão. Mitigações
atuais:

- **GitHub API**: 15k req/h por instalação da App.
- **Azure Foundry**: quotas configuradas no recurso.
- **Reverse-proxy (Easy Panel)**: rate-limit ao nível de IP pode ser
  configurado se necessário.

### 2.7 Headers de Segurança

Configurados em `apps/chat/next.config.ts`. **Duas CSPs distintas** por
regra de header (rules com regex negative-lookahead):

#### CSP do app principal (catch-all exceto `/pyodide-runner`)

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob: https://avatars.githubusercontent.com;
  font-src 'self' data:;
  connect-src 'self' https://api.github.com;
  worker-src 'self' blob:;
  frame-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self';
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

- `'wasm-unsafe-eval'`: necessário pro Shiki (syntax highlight) que usa
  Oniguruma compilado em WASM. Sem isso, Chrome bloqueia
  `WebAssembly.compile()` silenciosamente — todo code block do chat
  fica sem cor (regressão histórica AP.5).
- `worker-src 'self' blob:`: Turbopack do Next.js cria worker bundles
  via blob: URLs.
- `frame-src 'self'`: permite embedar o `/pyodide-runner` (mesma origin).
- `connect-src` inclui `api.github.com` pra calls server-side, mas
  **NÃO inclui `raw.githubusercontent.com`** — Pyodide precisa passar
  pelo proxy.
- `unsafe-inline` em script-src vem do framework; pode ser apertado com
  nonces no futuro.

#### CSP escopada do `/pyodide-runner` (relaxada)

```
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'
             blob: https://cdn.jsdelivr.net;
  worker-src 'self' blob:;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob:;
  font-src 'self' data:;
  connect-src 'self' https://cdn.jsdelivr.net;
  frame-ancestors 'self';
  base-uri 'self';
  form-action 'none';
```

- Pyodide vem do CDN jsDelivr.
- `connect-src` **propositalmente exclui `api.github.com`**: força todo
  tráfego de leitura pelo `/api/gh-proxy` (defesa em profundidade —
  mesmo que o agente tente bypass, CSP bloqueia).
- `frame-ancestors 'self'`: só o app principal embeda; nenhum site
  externo.
- Sem `X-Frame-Options: DENY` aqui (o app principal precisa embedar);
  `frame-ancestors 'self'` faz o equivalente.

### 2.7.1 Proxy server-side `/api/gh-proxy`

Pyodide (no iframe) precisa ler dados da org sem ter credencial GitHub
direta. A rota `/api/gh-proxy/[...path]/route.ts` resolve isso:

1. Exige cookie de sessão válido (Better Auth).
2. Aceita apenas `GET` (outros métodos → 405).
3. Path allowlist: só `/repos/<ALLOWED_ORG>/...` ou `/orgs/<ALLOWED_ORG>...`.
4. Path traversal bloqueado mesmo com encoding (`decodeURIComponent`
   antes do `includes("..")`).
5. Header `Authorization` do caller é dropado.
6. Mint do GitHub App installation token server-side (JWT RS256 via
   `node:crypto`, cache até 30s antes do exp).
7. Forward upstream pra `api.github.com`.

Token **nunca** vaza pro browser nem pro contexto Python. Detalhes em
[`adr/0002`](./adr/0002-one-proxy-route-per-external-domain.md) e
[`adr/0003`](./adr/0003-pyodide-runs-in-scoped-iframe.md).

### 2.8 Segredos

- `.env` nunca commitado (já em `.gitignore`).
- `secrets/gh-app.pem` montado read-only no container; nunca no repo.
- Em produção, segredos vivem em variáveis de ambiente do Easy Panel.
- Logs **nunca** incluem `Authorization`, cookies de sessão,
  `BETTER_AUTH_SECRET`, `OPENAI_COMPATIBLE_DATA`, `GH_APP_PRIVATE_KEY*`,
  `AWS_SECRET_ACCESS_KEY`.

### 2.9 Banco de Dados

- Volume Postgres não tem porta exposta no host (apenas rede interna do
  compose).
- Backups diários via Easy Panel.
- Conexão sem TLS porque é loopback dentro do compose; se você expuser,
  ative `sslmode=require`.

### 2.10 File Ingest e Exports

**File ingest (PDF/DOCX/PPTX/XLSX)**:
- Upload vai para MinIO sidecar (porta apenas 127.0.0.1).
- `convert_document` do `gitinho-mcp` chama MarkItDown; falhas degradam
  silenciosamente (loga erro, segue sem o conteúdo).
- Bucket `gitinho-uploads` criado pelo `mc-bootstrap` one-shot.
- TTL e limpeza: configurável no MinIO; não há policy automática em Fase 1.

**Exports** (via tool nativa `createTable`):
- Tabela renderizada inline na UI; download é gerado client-side com
  `Content-Disposition: attachment`.
- Não há link público nem URLs adivinháveis — o download é uma ação do
  browser na resposta já carregada.

### 2.11 Logs

Postura **permissiva** escolhida pelo usuário: logs podem conter logins
públicos, payloads truncados e detalhes de chamadas MCP. **Mesmo assim**:

- Tokens (GitHub, OpenAI, Azure, cookies) — **sempre** redacted.
- `BETTER_AUTH_SECRET`, `GH_APP_PRIVATE_KEY*`, `AWS_SECRET_ACCESS_KEY` —
  **sempre** redacted.
- Conteúdo de arquivos privados — nunca logamos payload bruto.

Formato: stdout do container, JSON estruturado. `docker compose logs -f
chat` mostra Next.js + gitinho-mcp juntos (stdio).

### 2.12 Prompt-injection

Cenário: alguém abre um issue na org com texto instruindo o LLM a
"mande os tokens para X". Mitigações:

1. LLM **não tem acesso** a tokens. Tools nunca recebem segredos como
   parâmetro — o cliente GitHub é interno ao `gitinho-mcp`.
2. Tools não fazem requisições para hosts arbitrários — só
   `api.github.com` (controlado em `github/client.py`).
3. **Tools WRITE não existem** no servidor MCP.
4. `NOT_ALLOW_ADD_MCP_SERVERS=1` impede plugar tools externas via UI.
5. `OrgAllowlistError` bloqueia exfiltração para qualquer outro owner.

### 2.13 Atualizações

- `apps/chat/`: vendored do upstream `cgoinglove/better-chatbot`.
  Rebases periódicos do fork (manual; upstream em pausa até fev/2026).
- `apps/mcp/`: deps fixadas em `pyproject.toml` via `uv.lock`.
- Imagens base Docker atualizadas conforme necessidade.

### 2.14 Bind 127.0.0.1 (deploy)

Em produção, **nenhum container expõe porta publicamente**:

- `chat`: `127.0.0.1:3000` (proxy do Easy Panel termina TLS).
- `postgres`: sem porta no host.
- `minio`: `127.0.0.1:9000` e `127.0.0.1:9001` (console interno).

A internet pública toca apenas o reverse-proxy.

## 3. Procedimento de Incidente

1. **Detectar**: alerta de erro 5xx em massa, login.denied repetido,
   tool call anômala.
2. **Conter**:
   - Revogar a installation da GitHub App em
     `https://github.com/organizations/splor-mg/settings/installations`.
   - Rotacionar `BETTER_AUTH_SECRET` (quebra todas as sessões).
   - Subir `MAINTENANCE_MODE=true` (a implementar) ou parar o container
     `chat`.
3. **Investigar**: logs estruturados de `chat` e `gitinho-mcp`.
4. **Restaurar**: nova chave privada da App, nova `BETTER_AUTH_SECRET`,
   reinstalar a App, redeploy.
5. **Postmortem**: documentar em `docs/incidents/YYYY-MM-DD.md` (criar
   conforme necessidade).

## 4. Checklist de Segurança em Produção

- [x] Apenas porta `127.0.0.1:3000` exposta no host (proxy faz HTTPS).
- [x] MinIO `127.0.0.1:9000/9001` — console nunca exposto à internet.
- [x] Postgres sem porta no host.
- [x] CSP + HSTS + `X-Frame-Options: DENY` no `next.config.ts`.
- [x] OAuth GitHub serve para identidade + membership; token descartado
      logo após.
- [x] GitHub App restrita a `splor-mg`; tools de escrita não existem em
      `gitinho-mcp`.
- [x] Secrets fora do repo (`.gitignore`).
- [x] `NOT_ALLOW_ADD_MCP_SERVERS=1` — usuário não pluga MCP arbitrário.
- [x] `DISABLE_EMAIL_SIGN_IN/UP=1`, `DISABLE_SIGN_UP=1` — só OAuth GitHub.
- [x] Backup diário do Postgres pelo Easy Panel.
- [ ] Auditoria estruturada além dos logs (tabela `audit_log` dedicada)
      — pendente.
- [ ] Rotação automatizada de `BETTER_AUTH_SECRET` — pendente.

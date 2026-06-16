# ADR 0002 — One proxy route per external domain

**Status**: Accepted (2026-06)

## Context

O agente roda Python no browser via Pyodide (iframe escopado em `/pyodide-runner`), e precisa fazer chamadas read-only à API do GitHub sem ter credencial direta (CSP do iframe bloqueia `api.github.com` por design — defesa em profundidade).

A solução atual: `/api/gh-proxy/[...path]/route.ts` em Next.js, que:
1. Exige cookie de sessão válido (Better Auth).
2. Aceita apenas `GET` (outros métodos retornam 405).
3. Restringe path a `/repos/<ALLOWED_ORG>/...` ou `/orgs/<ALLOWED_ORG>...` (com defesa contra path traversal mesmo com encoding).
4. Drop do header `Authorization` do caller.
5. Mint do GitHub App installation token server-side (JWT RS256 via `node:crypto`, cache até 30s antes do exp).
6. Forward upstream pra `api.github.com`.

A questão: quando um segundo domínio externo (SEI, orçamento, qualquer outro) entrar, ele deve:
- (a) ser adicionado como path adicional do mesmo `/api/gh-proxy` (e renomear o lugar), OR
- (b) ganhar sua própria rota proxy server-side?

Esta ADR fixa a resposta antes do segundo domínio aparecer.

## Decision

**Cada domínio externo recebe sua própria rota de proxy server-side, sob um path namespace consistente: `/api/proxy/<domain>/[...path]/route.ts`.**

Hoje `/api/gh-proxy` é renomeado para `/api/proxy/github` numa pequena refatoração (sem urgência — quando houver folga). Futuros domínios seguem o padrão imediatamente: `/api/proxy/sei`, `/api/proxy/orcamento`, etc.

Cada rota tem **shape defensivo idêntico**:
- Session check.
- Method allowlist (GET-only por default; POST permitido apenas se o domínio justificar e a justificativa virar ADR própria).
- Path allowlist específica do domínio.
- Auth header do caller descartado.
- Credencial obtida server-side (App token, OAuth refresh, service account — específico por domínio).
- Forward.

Mas a **implementação é independente por domínio**. Não há um "proxy framework genérico" que cada domínio configura — é cópia-e-adaptação até o 3º domínio surgir e mostrar o que de fato é comum.

## Consequences

### Positivas

- **Blast radius claro**: um bug no proxy GitHub não compromete o SEI. Em incidente de segurança, o componente afetado é evidente pelo path da request.
- **Auditabilidade isolada**: revisão de segurança do proxy GitHub lê **um arquivo**. Sem flags, sem branching, sem "se domain==X então...".
- **Auth flows distintos não brigam**: GitHub usa JWT + installation token (~1h TTL, server-mint on demand). SEI provavelmente é OAuth com refresh ou service account com API key persistido. Forçar esses 2 modelos em código compartilhado seria abstração feia.
- **Path prefix `/api/proxy/<domain>`** torna óbvio em PR review qual domínio está sendo tocado. Em rate limiting de WAF/observability, filtrar por domínio fica trivial.
- **Telemetria por domínio** sai de graça (filtrar request path).
- **Métodos permitidos por domínio** podem divergir sem condicional: o do GitHub é GET-only; um futuro SEI poderia ser GET+POST se precisar abrir consultas server-side. Mas POST exige ADR própria (não acidental).

### Negativas

- **Código duplicado entre rotas até generalização ser justificada por uso real** (provavelmente a partir do 3º domínio). Helpers comuns (verificação de session, parse de `[...path]`, build de error response) viram copy-paste no início.
- **"Copy e adapta" torna o template suscetível a drift**: alguém pode esquecer de copiar a checagem de path traversal. Mitigação: enforcement por test (ver seção).
- **Adicionar domínio é "criar arquivo"**, não "registrar plugin". É bom (explícito) mas se o número de domínios crescer pra 5+, esse padrão começa a custar.

## Alternatives considered

### Alternativa 1 — Proxy genérico `/api/proxy/[domain]/[...path]/route.ts` com config por domínio

Uma única rota Next.js carrega config (`{allowedPaths, auth, allowedMethods}`) baseado no parâmetro `[domain]`.

**Rejeitado porque**:
- Força todos os domínios a caberem num modelo comum. GitHub e SEI provavelmente têm models de auth tão diferentes que o "config" vira código procedural com if/else (que é exatamente o que estamos tentando evitar).
- Um bug na implementação afeta todos os domínios ao mesmo tempo.
- Auditoria de segurança fica difícil: a defesa de cada domínio é spread entre código compartilhado + config — não dá pra ler "uma página" pra entender o que o proxy SEI permite.
- Performance hit: branching por domínio em cada request quente.

### Alternativa 2 — Manter `/api/gh-proxy` e adicionar `/api/sei-proxy` sem renomear

Cada domínio com prefix próprio (`gh-`, `sei-`, `orc-`) sem namespace comum.

**Rejeitado porque**:
- Inconsistência cresce silenciosamente. Em 6 meses, ninguém lembra por que um é `gh-proxy` e outro é `sei-`. Pode ser que algum desenvolvedor crie `proxy-orcamento` por achatar que é mais legível, e aí o padrão quebra de vez.
- Path namespace `/api/proxy/<domain>` torna o padrão **descobrível** — qualquer dev novo vê `proxy` no path e entende que ali é fronteira com domínio externo.

### Alternativa 3 — Tudo no MCP, sem proxy do chat

A MCP do GitHub poderia expor um endpoint próprio que o Pyodide chama (ao invés do chat ter sua própria rota de proxy).

**Rejeitado porque**:
- Quebra a defesa em profundidade. Hoje a defesa é: (a) MCP enforça allowlist no client HTTP, (b) chat proxy enforça allowlist no path. Se o Pyodide chamasse direto a MCP, perderíamos a segunda camada.
- Bagunça responsabilidades: MCP fala MCP protocol (stdio/JSON-RPC). Servir HTTP pro Pyodide é função diferente — concentrar tudo numa MCP cria componente híbrido.
- Better Auth session vive no chat, não na MCP. Replicar verificação de sessão no MCP é re-engenharia.

### Alternativa 4 — Não usar proxy; deixar Pyodide pegar credencial diretamente

Pyodide receberia algum tipo de token via mensagem do iframe pai e chamaria `api.github.com` direto.

**Rejeitado porque**:
- Token vaza pro browser. CSP foi escolhida exatamente pra **forçar** o tráfego pelo proxy server-side e nunca expor token. Esta alternativa viola a invariante I.4 do `docs/spec/02-security-invariants.md`.

## Enforcement

- Todo proxy route fica em `apps/chat/src/app/api/proxy/<domain>/[...path]/route.ts`. O path namespace `/api/proxy/` é reservado.
- **Lint regex** (a implementar quando 2ª rota aparecer): cada arquivo sob `apps/chat/src/app/api/proxy/*/[...path]/route.ts` DEVE conter as strings:
  - referência a `getCurrentUser` (ou equivalente do Better Auth) — session check.
  - um array literal ou `Set` chamado tipo `ALLOWED_METHODS` — method allowlist.
  - uma função tipo `isAllowedPath` ou `assertAllowed` — path check com `decodeURIComponent`.
- E2E test recomendado: pra cada rota, casos canônicos:
  - Sem session → 307 redirect a `/sign-in`.
  - Method não permitido → 405.
  - Path fora do allowlist → 403.
  - Path com `..` (cru e percent-encoded) → 403.
  - Authorization header do caller é stripado antes do forward.
- POST em qualquer proxy exige ADR própria (não é decisão de PR, é decisão de design).

## Implementation note

O rename `/api/gh-proxy` → `/api/proxy/github` é trabalho pequeno mas precisa atualizar:
- O arquivo `apps/chat/src/app/api/gh-proxy/[...path]/route.ts` → mover para `apps/chat/src/app/api/proxy/github/[...path]/route.ts`.
- Sistema prompt (`apps/chat/src/lib/ai/prompts.ts`) — referências a `/api/gh-proxy/` viram `/api/proxy/github/`.
- Smoke test em `apps/chat/src/app/test/pyodide/pyodide-smoke-test.tsx` — passo 2 referencia `/api/gh-proxy/orgs/<org>`.

Sem urgência. Pode ser feito no momento que o 2º domínio for adicionado (junto da criação da nova rota), pra ter sentido de oportunidade.

## References

- Current implementation: `apps/chat/src/app/api/gh-proxy/[...path]/route.ts`
- Path traversal defense origin: commit que introduziu o proxy (15 casos de teste mencionados no log)
- Related: [ADR 0001 — One MCP server per external domain](0001-one-mcp-per-external-domain.md)
- Security invariants: `docs/spec/02-security-invariants.md` — I.4 (token isolation), I.6 (Pyodide same-origin), I.7 (path allowlist)
- Anti-patterns: `docs/spec/03-anti-patterns.md` — AP.5 (CSP regression risk)

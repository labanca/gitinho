# ADR 0003 — Pyodide roda em iframe escopado, não no contexto do app principal

**Status**: Accepted (2026-06)

## Context

O agente precisa executar Python no browser do usuário pra análises ad-hoc (transformações sobre listas grandes, joins, gráficos). A escolha técnica foi Pyodide (CPython → WebAssembly).

Pyodide tem requisitos de runtime que conflitam com hardening do app principal:
- **`WebAssembly.compile()`** — bloqueado por CSP sem `'wasm-unsafe-eval'` (que o app principal só liberou recentemente, e só pra Shiki).
- **Workers via `blob:` URLs** — Pyodide usa worker thread pra evitar congelar a UI; bloqueado por CSP sem `worker-src blob:`.
- **CDN externa (`cdn.jsdelivr.net`)** — bundle do Pyodide vem do CDN; bloqueado por `connect-src 'self'`.
- **Dependência de Oniguruma WASM** — engine de regex em WASM, idem `wasm-unsafe-eval`.

Surge a escolha: relaxar o CSP do app principal pra acomodar Pyodide, ou isolar Pyodide num contexto separado?

## Decision

**Pyodide roda num iframe same-origin em `/pyodide-runner`, com CSP próprio (relaxado o suficiente pra Pyodide funcionar) separado do CSP do app principal (que continua estrito).**

Detalhes da implementação:
- Rota Next.js dedicada: `apps/chat/src/app/pyodide-runner/page.tsx` + `runner-client.tsx`.
- CSP escopado pra essa rota (`runnerCsp` em `next.config.ts`): inclui `'wasm-unsafe-eval'`, `worker-src 'self' blob:`, `connect-src 'self' https://cdn.jsdelivr.net`, mas **não** inclui `api.github.com` (defesa em profundidade — o Python só fala com o proxy server-side).
- Iframe same-origin: cookie de sessão acompanha; o Python pode chamar `/api/gh-proxy/...` sem auth adicional.
- `frame-ancestors 'self'`: só o app principal pode embedar; nenhum site externo.
- Headers do app principal e do runner aplicados via duas rules de Next.js com regex negative-lookahead, pra garantir que nenhum CSP "vaze" pro outro escopo.

## Consequences

### Positivas

- **App principal mantém CSP estrito** sem comprometer pra Pyodide. Único relaxamento adicional foi `'wasm-unsafe-eval'` (necessário pro Shiki — ver ADR futura sobre Shiki, ou commit `28043ea`).
- **Blast radius contido**: bug ou exploit dentro do Pyodide só vê DOM do iframe. Não acessa cookies de outros origens, não acessa `document.cookie` do parent diretamente.
- **CSP do runner pode ser auditado isolado**: o que o Python pode fazer está descrito em **uma única declaração** (`runnerCsp` em `next.config.ts`).
- **`connect-src` do runner não inclui `api.github.com`** — força todo tráfego de leitura pelo proxy server-side, mantendo a invariante I.4 (token isolation). Mesmo se o Python tentar `fetch("https://api.github.com/...")` direto, a CSP bloqueia.
- **Smoke test verificável**: `/test/pyodide` exercita boot + proxy + bloqueio de fetch direto. Falha do passo 3 do smoke = regressão detectada.

### Negativas

- **Setup mais complexo**: o iframe precisa de um protocolo postMessage entre parent (chat) e child (runner) pra enviar código e receber resultados. Hoje implementado em `apps/chat/src/lib/code-runner/call-worker.ts` (parent) + `runner-client.tsx` (child).
- **Latência de startup**: criar iframe + carregar Pyodide leva ~3-5s na primeira execução. Mitigado por cache (iframe e instância Pyodide são reusados ao longo da sessão).
- **Debug mais difícil**: stack traces de erros do Python ficam dentro do iframe; logs precisam ser explicitamente transferidos via postMessage.
- **CDN externa requerida**: depende de `cdn.jsdelivr.net` estar disponível. Mitigação possível futura: self-host do bundle Pyodide (entra como ADR própria se virar problema).

## Alternatives considered

### Alternativa 1 — Pyodide no contexto principal (relaxar o CSP do app)

Adicionar `'wasm-unsafe-eval'`, `worker-src blob:`, `connect-src cdn.jsdelivr.net` direto no CSP do app principal.

**Rejeitada porque**:
- Expande a superfície de ataque do app inteiro pra acomodar uma feature específica. CSP existe pra ser restritiva.
- Um bug futuro em qualquer parte do app principal que envolva eval de string ou compile dinâmico ganha o mesmo nível de permissão. Privilégio espalha.
- Audit fica difícil: "o app pode rodar WASM?" → "depende de qual rota; está em todo lugar".
- O scope vazaria pra páginas administrativas (`/admin`), de auth (`/sign-in`), etc., onde nada de Python deveria rodar.

### Alternativa 2 — Pyodide como Web Worker direto (sem iframe)

Spawnar Pyodide num `Worker` separado, no contexto do app principal.

**Rejeitada porque**:
- Worker **herda** o CSP da página que o criou. Pra criar Worker que use WASM, o CSP da página principal precisa permitir — voltamos à Alternativa 1.
- Não isola: o Worker compartilha origin, pode acessar IndexedDB, etc.

### Alternativa 3 — Pyodide num subdomínio (`pyodide.gitinho.splor-mg.gov.br`)

Subdomínio próprio dá isolamento de origin de verdade (não só de contexto).

**Rejeitada porque**:
- Custos operacionais: DNS, cert, deploy infra extra.
- Cookie de sessão **não atravessa** subdomínios diferentes por default — perderíamos a vantagem do same-origin (cookie automático).
- Pra um deploy single-server (Easy Panel hoje), montar subdomínio é trabalho desproporcional ao ganho.
- Iframe same-origin já dá 80% do isolamento (CSP separado, frame-ancestors restrito) com 10% do custo operacional.

### Alternativa 4 — Não ter execução Python (usar só tool calls)

Eliminar Pyodide e cobrir todas as análises via tools MCP novas.

**Rejeitada porque**:
- Análises ad-hoc são, por natureza, cardapio aberto. Cada pergunta nova exigiria uma tool nova ou um agent novo no backend.
- Pyodide cobre o "long tail" de pedidos com 1 ferramenta (executar Python sobre dados já fetchados). Trocar isso por dezenas de tools específicas é caminho infeliz.
- Casos como "agrupar resources por mediatype" ou "gerar histograma de PR sizes" são naturais em Python e ridiculamente caros de virar tool.

## Enforcement

- `next.config.ts` precisa **sempre** ter as duas regras de header (`/pyodide-runner` e catch-all com negative-lookahead). PR que remova uma das duas, ou misture as duas CSPs, é regressão.
- `connect-src` do runner não inclui `api.github.com` nem `raw.githubusercontent.com`. Adicionar **um** desses na `runnerCsp` requer ADR de superseding ou justificativa explícita no PR description.
- `frame-ancestors 'self'` em `runnerCsp` é obrigatório. Mudar pra `*` ou domínio externo = regressão.
- Smoke test em `/test/pyodide` é canônico — deploy que falhe nele não pode ser promovido.

## References

- Implementation: `apps/chat/src/app/pyodide-runner/`
- CSP definitions: `apps/chat/next.config.ts` (`csp` vs `runnerCsp`)
- Postmessage protocol parent↔runner: `apps/chat/src/lib/code-runner/call-worker.ts`
- Smoke test: `apps/chat/src/app/test/pyodide/pyodide-smoke-test.tsx`
- Security invariants: `docs/spec/02-security-invariants.md` — I.5 (CSP estrito vs runner), I.6 (Pyodide iframe), I.7 (path allowlist)
- Related: [ADR 0002 — One proxy route per external domain](0002-one-proxy-route-per-external-domain.md)
- Bug histórico: `docs/spec/03-anti-patterns.md` — AP.4, AP.5 (regressões de CSP/Shiki que evidenciaram a importância do scope)

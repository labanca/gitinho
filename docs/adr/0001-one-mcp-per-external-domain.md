# ADR 0001 — One MCP server per external domain

**Status**: Accepted (2026-06)

## Context

O Gitinho hoje consome **uma** MCP server (`apps/mcp/gitinho_mcp/`) que expõe 34 tools read-only pra dados da org `splor-mg` no GitHub. A intenção declarada é estender o agente pra outros domínios (orçamento SPLOR, processos SEI, etc.) ao longo do tempo — sem se comprometer com datas, mas como direção provável.

Surge a pergunta arquitetural: quando o segundo domínio aparecer, ele deve ser:
- (a) adicionado como mais um pacote de tools dentro da MCP existente, OU
- (b) shipado como uma MCP server independente, num processo separado?

Esta ADR fixa a resposta antes que o segundo domínio chegue, pra evitar que a decisão seja tomada na pressa quando ele chegar.

## Decision

**Cada domínio externo (definido como: um sistema/API/autoridade distinta que o agente precisa consultar) ganha sua própria MCP server, em processo separado.**

Hoje isso é `apps/mcp/gitinho_mcp/` para GitHub.
Amanhã, se SEI for adicionado, seria algo como `apps/sei-mcp/` rodando como processo independente.

O chat continua sendo o único consumidor — Better Chatbot já suporta nativamente múltiplas MCPs simultâneas, então adicionar uma nova é configuração, não código.

## Consequences

### Positivas

- **Isolamento de falha**: 401 no installation token do GitHub não derruba queries do SEI. Cada MCP cai sozinha.
- **Auth independente por domínio**: GitHub App (JWT + installation token), OAuth pessoal, service account, API key — cada MCP usa o modelo que faz sentido pra ela, sem unificação artificial.
- **Versionamento e deploy independentes**: bumpar a integração SEI não risca a GitHub.
- **Namespace de tool name limpo**: `gitinho_list_org_repos` vs `sei_list_processes`. Colisão de nome impossível.
- **Liberdade de linguagem**: gitinho MCP é Python (FastMCP). SEI MCP pode ser TS, Go, ou outro Python — quem escreve escolhe.
- **Docs de spec escalam por slice**: `docs/spec-github/` (atual `docs/spec/`), `docs/spec-sei/` futuro. Cada domínio tem seus próprios acceptance cases, security invariants, anti-padrões.
- **Boundary de auditoria fica claro**: numa revisão de segurança, "o que o agente pode fazer com GitHub?" é uma resposta lendo só `apps/mcp/gitinho_mcp/`. Não precisa varrer monorepo.

### Negativas

- **Footprint operacional cresce linearmente**: N domínios = N processos pra deployar, monitorar, atualizar dependências. Hoje 1 processo Python, 1 imagem Docker. Amanhã: N.
- **Cross-domain queries** ("PRs do labanca relacionados ao processo SEI X") exigem um *agent* no Better Chatbot que tenha acesso aos 2 MCPs no contexto. Funciona, mas o orçamento de tokens por turn cresce com o número de tool descriptions no system prompt. Pode forçar uso de seleção `@mention` ou subsetting dinâmico de tools.
- **Concerns compartilhadas** (logging consistente, rate limiting agregado, telemetria por usuário) precisam ser re-aplicadas em cada MCP, ou centralizadas num layer acima (proxy, gateway).
- **Helpers comuns** (e.g., decode de Bearer header, paginação genérica de REST) podem acabar duplicados entre MCPs com linguagens diferentes — duplicação aceitável até a 3ª MCP, aí compensa extrair.

## Alternatives considered

### Alternativa 1 — Mega-MCP única com submódulos por domínio

Uma única MCP `apps/mcp/` que internamente tem subpacotes `github/`, `sei/`, `orcamento/`. Roda como um processo só.

**Rejeitado porque**:
- Um bug ou exception não tratada em qualquer submodelo derruba TODOS os domínios.
- Força unificação do modelo de auth (ou criar um auth-manager interno complexo).
- Força linguagem única (Python hoje).
- Tempo de boot da MCP cresce com o número de domínios — todos importados sempre.

### Alternativa 2 — Plugin system dentro de uma MCP (load tools dinamicamente)

A MCP carrega dinamicamente "domain plugins" baseado em config. Cada plugin registra suas tools.

**Rejeitado porque**:
- Inventa uma camada de framework que o protocolo MCP **já resolve nativamente**: o jeito padrão de ter múltiplos providers de tools é... rodar múltiplas MCPs. Reimplementar isso dentro de uma MCP é trabalho sem retorno.
- Adiciona complexidade de runtime (carregamento dinâmico, ordering, dependency entre plugins).

### Alternativa 3 — Domain logic embutida no chat (sem MCP separada)

Tools do domínio ficam em `apps/chat/src/lib/ai/tools/` direto, sem MCP intermediária.

**Rejeitado porque**:
- Acopla domain logic à camada de UI/auth. Uma futura CLI agent, ou um batch job (e.g., "todo dia 1, gera relatório de PRs"), não consegue reusar.
- Tools em linguagem do chat (TS) — perde a opção de Python pra integrações que têm libs maduras em Python (e.g., `frictionless` lib).
- Mistura responsabilidades: o chat passa a ser "domain code + UI" em vez de só "render + orquestração".

## Enforcement

- PR que adicione tool não-GitHub em `apps/mcp/gitinho_mcp/` é rejeitado com referência a esta ADR.
- Tool name **deve** ser prefixado pelo domínio (`gitinho_*`, `sei_*`). O router de tools do chat (`apps/chat/src/lib/ai/mcp/mcp-tool-id.ts`) preserva esse prefix automaticamente; uma tool sem prefix de domínio é violação visível.
- Lint sugerido (a implementar quando 2ª MCP aparecer): `apps/<domain>-mcp/` é o único path permitido pra registrar tools naquele domínio.

## References

- MCP protocol: https://modelcontextprotocol.io
- Existing MCP: `apps/mcp/gitinho_mcp/server.py` + `apps/mcp/gitinho_mcp/tools/`
- Better Chatbot multi-MCP config: `apps/chat/src/lib/ai/mcp/`
- Related: [ADR 0002 — One proxy route per external domain](0002-one-proxy-route-per-external-domain.md)
- Spec: `docs/spec/02-security-invariants.md` — I.2 (org allowlist), I.3 (GitHub App)

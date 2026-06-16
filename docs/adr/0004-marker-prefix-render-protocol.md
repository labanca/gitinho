# ADR 0004 — Tool result auto-render via marker prefix protocol

**Status**: Accepted (2026-06)

## Context

Listagens grandes (583 recursos de datapackages, 200 PRs, 100 repos) precisam aparecer no chat como tabela interativa (busca, ordenação, export CSV/XLSX). O caminho ingênuo era o agente chamar uma tool MCP pra buscar os dados e depois chamar `createTable` (ou `pythonExecution` com `display_table`) pra renderizar.

Problema: ambos os caminhos forçam o LLM a **regenerar cada linha como tool arg** sequencialmente. A ~70 tokens/s, 583 linhas × ~150 chars = ~87K tokens = **~20 minutos** travado em "Generating Code…" (caso documentado em `docs/spec/03-anti-patterns.md` AP.2).

Surge a questão: como o front-end recebe dados ricos pra renderizar sem o LLM ter que reemitir esses dados como tokens?

Dois cenários distintos com o mesmo problema:
1. **Tool result MCP**: tool já tem os dados na resposta — só falta sinalizar pro UI renderizar de jeito específico.
2. **Stdout de Pyodide**: agente roda Python que produz uma tabela ou imagem — só falta o front-end interpretar a saída como render rico.

## Decision

**Adotar marker prefix protocol como canal único de comunicação "renderize isso de jeito X" entre produtor (MCP/Pyodide) e UI, sem passar pelo LLM.**

Dois sabores convivem por necessidade de canal:

### Sabor 1 — Campo `_chat_table` em tool result JSON (MCP)

A tool MCP inclui um campo `_chat_table` no dict de retorno:

```json
{
  "rows": [...583 items...],
  "_chat_table": {
    "title": "Recursos de datapackages",
    "description": "583 recursos em 58 repositórios",
    "data_field": "rows",
    "columns": [
      {"key": "repo", "label": "Repositório", "type": "string"},
      {"key": "resource_name", "label": "Recurso", "type": "string"}
    ]
  }
}
```

O UI (`apps/chat/src/components/message-parts.tsx`) detecta o campo, lê os dados de `result[data_field]`, e renderiza `<InteractiveTable>` inline.

### Sabor 2 — Marker em texto de stdout (Pyodide)

Quando Pyodide gera saída via `print()`, o front-end parsa stdout procurando markers no formato canônico:

```
[[gitinho:<render-type>]]<json-payload>[[/gitinho:<render-type>]]
```

Tipos atuais: `[[gitinho:table]]<payload>[[/gitinho:table]]` (helper `display_table` em `apps/chat/src/lib/code-runner/safe-python-run.ts`). Mesmo formato que matplotlib usa pra inline images (`data:image/png;base64,...`).

### Por que dois sabores e não um

- Tool result MCP é JSON estruturado — campo extra é natural e barato.
- Stdout do Pyodide é texto puro — não há campo extra; marker prefix é a única forma de comunicar metadata sem inventar segundo canal (postMessage paralelo, side-channel API).

Ambos sabores partilham o mesmo princípio: **payload de render é metadado opcional que o UI consome, e que o LLM ignora ou só usa como contexto pra escrever resumo curto**.

## Consequences

### Positivas

- **Tempo de resposta cai de minutos pra segundos**: 583 linhas via `_chat_table` aparecem em ~3-5s (latência da MCP); via `display_table` em ~33ms de processamento Python + render UI. LLM emite só a tool call e uma resposta curta de resumo.
- **Backward compatibility**: tool MCP sem `_chat_table` cai no render default (JsonView colapsado). Não quebra nada existente.
- **Decoupling produtor↔render**: tool não sabe nada de React; UI não sabe nada de Python. Comunicam por JSON via canal acordado.
- **Extensível por adição**: novos render types entram como marker types novos (`[[gitinho:network]]`, `[[gitinho:tree]]`, `[[gitinho:diff]]`) sem mudar o protocolo. Cada tipo entra com handler no UI e helper no Python/MCP.
- **Auditável**: o que renderiza no chat é determinado por (a) campo `_chat_table` numa tool result OU (b) marker no stdout. Lista finita, grep-able.
- **Sistema prompt enforça o contrato**: agente é instruído a NÃO chamar `createTable` por cima de result com `_chat_table` (commit `3c5c9d7` + item 11 do prompt). Reforça que o canal é responsável.

### Negativas

- **Marker no stdout pode ser confundido com texto regular**: se um usuário fizer `print("[[gitinho:table]]foo[[/gitinho:table]]")` por brincadeira, o UI tenta parsar e renderizar. Mitigação atual: JSON parse falha graciosamente; marker malformado vira texto plain. Risk residual: marker no resultado de uma string vinda de fora (e.g., um README de repo contendo o marker como exemplo). Não observado em produção até agora.
- **Acoplamento implícito de schema**: `data_field` aponta pra um campo no result; se a tool MCP renomear `rows` pra `items` sem atualizar `_chat_table.data_field`, a tabela some silenciosamente. Mitigação: helper compartilhado por família (e.g., `_PR_TABLE_COLUMNS` + `_pr_row` em `pulls.py`) reduz duplicação.
- **LLM ainda vê o JSON completo**: a tool result inclui as 583 linhas, mesmo que o UI renderize de outro canal. Custo de **input** tokens cresce com o dado (input tokens são baratos e instantâneos; output tokens — o gargalo original — são poupados). Trade-off aceito.
- **Front-end precisa conhecer a lista de tipos**: handler de cada `gitinho:<type>` mora no `message-parts.tsx` (pra MCP) e em `safe-python-run.ts` (pra Pyodide). Adicionar tipo novo = 2 lugares atualizados.

## Alternatives considered

### Alternativa 1 — Tipo de mensagem MCP customizado

Estender o protocolo MCP com `MessageType` próprio (`"chat:table"` etc.) que o chat backend parse.

**Rejeitada porque**:
- Quebra interoperabilidade com qualquer cliente MCP padrão (MCP Inspector, outros chatbots) que não conheça os tipos custom.
- Força versionamento do protocolo e migrations.
- AI SDK do Vercel não tem extensão fácil pra tipos de tool result custom.

### Alternativa 2 — JSX/React components inline na tool result

Tool MCP devolve JSX serializado que o front-end deserializa.

**Rejeitada porque**:
- Vetor de XSS gigante: tool result vem de processo externo (MCP server pode estar comprometido). JSX serializado = JS rendering arbitrário.
- Complexidade de serialização de tree React em JSON.
- Acopla tool MCP ao framework de UI (React). Trocar de framework = reescrever tools.

### Alternativa 3 — Side-channel API (POST do front-end após tool call)

Front-end recebe a tool call response, faz POST adicional pra um endpoint que retorna a render payload.

**Rejeitada porque**:
- Race condition com streaming: a parte do agente que segue pode chegar antes do POST de render terminar.
- Extra round-trip + extra endpoint server-side pra cada render.
- Estado dividido entre dois canais: difícil debuggar quando renders aparecem "atrasadas".

### Alternativa 4 — Tudo via `createTable` (estado original) com aceitação de latência

Manter `createTable` como caminho único; aceitar que listagens grandes vão demorar.

**Rejeitada porque**:
- 20 minutos de "Generating Code…" é experiência inaceitável (caso documentado AP.2).
- O modelo (LLM) é gargalo na geração de tokens; arquitetura que enfileira dados pelo modelo é estruturalmente errada.

### Alternativa 5 — Só `_chat_table` (sem marker no stdout)

Ignorar o cenário de Pyodide e cobrir só tool result MCP.

**Rejeitada porque**:
- Análises Python que produzem tabelas (e.g., agrupar por mediatype, contar por ano) precisariam ou voltar pra MCP (perde flexibilidade) ou cair no `createTable` (perde tempo).
- Marker no stdout custou ~30 linhas de código a mais e cobre o caso completo.

## Enforcement

- **Toda tool MCP que retorna lista** (dados uniformes em `rows`, `prs`, `repos`, etc.) **deve** ter `_chat_table` com `data_field` apontando pro campo de dados. Hoje 14 tools cobertas (commit `3c5c9d7`).
- Tool nova de listagem sem `_chat_table` é gap (entrar no `03-anti-patterns.md` AP.8 como exemplo).
- **Helpers compartilhados por família**: `_PR_TABLE_COLUMNS`, `_pr_row` em `pulls.py` (commit `ef3ea3a`). Ao adicionar 3ª tool de PR, reusar; criar coluna nova só se a tool tem campo novo.
- **Marker types vivem em catálogo único**: novos tipos entram em `safe-python-run.ts` (`OUTPUT_HANDLERS`) e no handler do `message-parts.tsx` no mesmo PR.
- Sistema prompt item 11 lista tools com auto-render. Lista desatualizada → manutenção atrasada.

## References

- `_chat_table` introdução: commit `3c5c9d7` (`feat(mcp,chat): _chat_table em 14 tools de listagem + search_code`)
- `display_table` (marker stdout): `apps/chat/src/lib/code-runner/safe-python-run.ts` — `OUTPUT_HANDLERS.basic`
- UI render hook MCP: `apps/chat/src/components/message-parts.tsx` (procura `_chat_table`)
- UI render hook stdout: `apps/chat/src/lib/code-runner/safe-python-run.ts` (regex parser)
- Helpers compartilhados PR: `apps/mcp/gitinho_mcp/tools/pulls.py` (`_pr_row`, `_PR_TABLE_COLUMNS`)
- Anti-padrão evitado: `docs/spec/03-anti-patterns.md` — AP.2 (hang por createTable), AP.8 (JSON crú sem `_chat_table`)
- Spec relacionada: `docs/spec/01-acceptance-cases.md` — invariante #2 (não chamar createTable por cima de `_chat_table`)

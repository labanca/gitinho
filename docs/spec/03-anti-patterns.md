# 03 — Anti-padrões observados

Catálogo das falhas reais que apareceram em produção, com causa raiz, exemplo concreto e regra de "não pode repetir". O rebuild precisa ter teste/lint pra cada um destes — sem isso, o erro volta em 2 meses.

Cada item: **(sintoma) → (causa raiz) → (onde aconteceu) → (regra)**.

---

## AP.1 — LLM emite tool-call XML como texto em vez de tool-call estruturado

**Sintoma**: A resposta do agente, num `part.text`, contém literalmente:
```xml
<function_calls>
<invoke name="list_prs_by_user">
<parameter name="login">gabrielbdornas</parameter>
</invoke>
</function_calls>
<function_result>{"total": 2, "prs": [...]}</function_result>
```
E **não há** nenhuma parte `tool-*` na mensagem. O conteúdo é exibido como markdown bruto pro usuário, e os dados que aparecem (PRs, números, URLs) podem ser totalmente inventados — nada bateu na MCP.

**Causa raiz**: O modelo (provavelmente Claude rodando em outro provider/adapter que não entende o formato XML do Anthropic) está gerando tool calls no formato XML nativo, mas o adapter do Vercel AI SDK não está parseando essas tags como tool calls — então elas viram texto puro.

**Onde aconteceu**: thread `7a5c4b19-f22d-48e1-bb1c-6f877191e7c4` (produção, 2026-06).

**Regra**:
- Se `part.text` contém `<function_calls>` ou `<invoke ` ou `<function_result>`, é bug — tem que ser parseado como tool call ou rejeitado.
- Validação no client side: detectar essas substrings no `part.text` de qualquer mensagem assistant e exibir erro claro pro usuário ("tool call malformed — resposta pode ser inventada").
- Validação no rebuild: testes E2E precisam afirmar que pra perguntas que requerem dados, há SEMPRE uma parte `tool-*` correspondente na mensagem.

---

## AP.2 — Tabela grande regerada como tool args, hang de minutos

**Sintoma**: Usuário pede listagem de 500+ itens (e.g., "todos os recursos dos datapackages"). Chat trava em "Generating Code..." por 5–20 minutos. Não há erro — só lentidão.

**Causa raiz**: Tool MCP devolveu N linhas. Agente decidiu renderizar com `createTable` (ou `pythonExecution` com Python literal contendo as linhas). O LLM tem que **gerar cada linha como token** no `code`/`data` arg, o que escala linearmente com N. A ~70 tokens/s, 583 rows × 150 chars/row = ~87K tokens = ~20 min.

**Onde aconteceu**: histórico em `d2fbfcc0`, `67952848`, `685a81be`, `03f16643` (várias tentativas).

**Regra**:
- Toda tool MCP que retorna lista expõe `_chat_table` (commit `3c5c9d7`).
- Sistema prompt proíbe `createTable` / `pythonExecution` por cima de result que já tem `_chat_table` (commit `3c5c9d7`).
- UI renderiza tabela direto do `_chat_table` sem passar pelo LLM (commit `3c5c9d7`).
- Teste de regressão: pergunta "liste todos os recursos" deve responder em < 10s.

---

## AP.3 — Agente pede credenciais que ele já tem

**Sintoma**: Pergunta natural "liste os datapackages" recebe resposta tipo:
> "⚠️ Não tenho acesso direto a sistemas externos. Por favor forneça: 1) URL da organização, 2) Token de API, 3) Acesso aos `datapackage.json` de cada repositório."

Mais um bloco de Python de exemplo usando `requests.get` com `token`.

**Causa raiz**: Agente esqueceu (ou nunca soube) que tem MCP tools com autenticação pronta. Provavelmente foi disparado em contexto sem o system prompt aplicado, ou o prompt não enfatizou que as tools estão sempre disponíveis.

**Onde aconteceu**: threads `d2fbfcc0`, `67952848` (produção, 2026-06).

**Regra**:
- O `buildGitinhoBasePrompt` é aplicado em **todo chat default**, sem precisar de `@agent` (já garantido). Ver `apps/chat/src/lib/ai/prompts.ts`.
- Item 13 do prompt ("Nunca prometa o que não pode entregar") tem espelho positivo: "use as tools listadas — elas já têm credencial".
- Anti-padrão proibido no prompt: dar receita de Python com `TOKEN = "seu-token"` como exemplo.

---

## AP.4 — `useState` inicial pré-computado escondendo conteúdo durante streaming

**Sintoma**: Code blocks (bash, python, yaml) aparecem com header da linguagem mas **corpo vazio** no chat. Copiar a mensagem traz o conteúdo correto — então é só problema de render.

**Causa raiz**: `PreBlock` em `apps/chat/src/components/pre-block.tsx` inicializava `useState` com um JSX literal capturando `children`/`code` da primeira render. Durante streaming, primeira render via `<code></code>` vazio. JSX inicial fica preso. Quando o conteúdo chega via streaming, `useLayoutEffect` chama Shiki. Se Shiki falha (caso real: `bash` com URL contendo `&`), `.ifOk(setComponent)` não dispara e o componente fica preso no JSX vazio inicial.

**Onde aconteceu**: thread `fa18c8b6` — reportado pelo usuário, resolvido commit `e79fb48`.

**Regra**:
- Nunca pré-computar JSX como argumento de `useState`. Estado inicial = `null`, fallback renderizado no JSX de retorno (re-avaliado a cada render).
- Tratamento explícito de falha: `safe().ifFail(() => setX(null))`.
- Regression test: bloco com URL contendo `&` no fence ` ```bash ` precisa mostrar o texto.

---

## AP.5 — Shiki falha silenciosa por CSP sem `wasm-unsafe-eval`

**Sintoma**: Syntax highlight não aparece em nenhum code block em produção. Texto é exibido (após fix do AP.4), mas tudo monocromático. Console limpo, sem erro visível.

**Causa raiz**: Shiki usa engine Oniguruma compilada para WebAssembly. CSP de produção tinha `script-src 'self' 'unsafe-inline'` mas faltava `'wasm-unsafe-eval'`. Chrome bloqueia `WebAssembly.compile()` silenciosamente — a promise rejeita, `safe()` engole o erro, fallback plain.

**Onde aconteceu**: descoberto na investigação do AP.4 (toda thread em produção até commit `28043ea`).

**Regra**:
- CSP de produção precisa de `'wasm-unsafe-eval'` enquanto Shiki ou qualquer dep WASM estiver no bundle.
- `ts-safe`'s `.ifFail()` deve ter handler explícito que pelo menos loga em dev (`console.error("[Highlight failed]", err)`) pra não esconder esse tipo de bug.
- Regression: smoke em `/test/pyodide` já cobre WASM no runner; precisa de smoke equivalente que confirme Shiki render no app principal.

---

## AP.6 — Agente chuta paths de arquivo em vez de listar primeiro

**Sintoma**: Pergunta "o que faz o repo X?" leva o agente a chamar `get_file_content(repo="X", path="src/main.py")`, `get_file_content(repo="X", path="src/cli.py")`, `get_file_content(repo="X", path="X/__init__.py")` — 3 chamadas em paralelo a paths chutados, várias delas 404, e o agente concluindo com base no que sobrou.

**Causa raiz**: Sem listing prévio, o agente assume convenções (Python = `src/main.py`, etc.) que não valem na org real. O resultado depende de qual chute deu sorte.

**Onde aconteceu**: thread `541481f0` — múltiplos turns do agente chamando `get_file_content` em paths chutados.

**Regra**:
- Sistema prompt (item 7) proíbe explicitamente: "Nunca chute caminhos de arquivo". Caminho correto: `describe_repo` já retorna `root_listing`; `list_repo_contents` pra explorar; `get_file_content` só em paths confirmados.
- Regression: questionar `describe_repo(repo="dpm")` deve devolver root_listing + README + manifests numa única call. Se está chamando 3 tools separadas, há regressão no prompt.

---

## AP.7 — `search_issues` com `repo:` recebe 422 por conflito de qualifier

**Sintoma**: Agente tenta `search_issues(query="is:pr is:open repo:splor-mg/dados-orcamentarios")` e GitHub responde 422. Agente diz: "não tenho ferramenta pra isso".

**Causa raiz**: O wrapper de `search_issues` força `org:splor-mg` na query, e quando o LLM adiciona `repo:splor-mg/X`, GitHub Search rejeita por ter os 2 qualifiers (`org:` e `repo:`) simultâneos.

**Onde aconteceu**: thread `41baf41c` — usuário ficou frustrado quando o agente disse não conseguir ver PRs dum repo específico.

**Regra**:
- A tool `list_prs_by_repo` (commit `ef3ea3a`) é a alternativa correta: aplica `repo:` sem `org:`.
- A tool `list_prs_awaiting_review` (commit `ef3ea3a`) cobre o caso reviewer-side.
- Regression: pergunta "PRs abertos no repo X" deve usar `list_prs_by_repo`, nunca `search_issues`.

---

## AP.8 — Tools de listagem retornando JSON crú no painel Response (sem `_chat_table`)

**Sintoma**: Pergunta retorna dados via MCP, mas em vez de `InteractiveTable` aparece o `JsonView` colapsado. Usuário tem que expandir, scrollar — e exportar pra Excel/CSV é impossível.

**Causa raiz**: A tool MCP retornou lista mas sem `_chat_table` hint. UI cai no render default (`JsonView`).

**Onde aconteceu**: estado pré-`3c5c9d7`. Hoje 14 tools cobertas; gap conhecido em algumas (e.g., `list_repo_contents`).

**Regra**:
- Toda tool MCP que retorna lista de objetos uniformes (`rows`, `prs`, `repos`, `members`, etc.) inclui `_chat_table` com `data_field` apontando pro campo de dados.
- Helper compartilhado: `_PR_TABLE_COLUMNS` (em `pulls.py`) — extrair padrão pra outras famílias de tool.
- Regression: cada `@mcp.tool()` que retorne lista deve ter teste verificando shape de `_chat_table` no result.

---

## AP.9 — Tool chamada repetidamente no mesmo turn por loop do agente

**Sintoma**: Mesma chamada de tool (e.g., `get_file_content`) aparece 3, 5, 8 vezes seguidas no mesmo turn, com inputs idênticos ou só ligeiramente diferentes. Resposta final pode estar fragmentada ou inconsistente.

**Causa raiz**: Modelo entrou em loop de retry (provavelmente um problema na resposta de algum step que não terminou). Visível pelas `partTypes: ["step-start","text","tool-X","step-start","text","tool-X",...]` repetidas.

**Onde aconteceu**: thread `541481f0` — 5 ocorrências de turns com 3 chamadas idênticas de `get_file_content`.

**Regra**:
- Backend de chat deve detectar > 2 chamadas idênticas (mesma tool, mesmos args) no mesmo turn e interromper com erro claro.
- Telemetria: contar tool calls por turn; alarme em > 5 calls/turn.

---

## AP.10 — Resposta cita PR/issue/commit com número/URL sem ter feito tool call

**Sintoma**: Agente menciona "PR #46 do coteg" com URL plausível, mas a inspeção do `parts` mostra **nenhuma parte `tool-*`** — é texto puro inventado pelo LLM.

**Causa raiz**: Mistura de AP.1 (tool-call XML não parseado) com habilidade do modelo de inventar URLs plausíveis a partir de padrões conhecidos. Sem tool call = sem dado real.

**Onde aconteceu**: thread `7a5c4b19` — todos os PRs citados no texto eram XML não parseado.

**Regra**:
- Lint regex no client: se texto da resposta contém `splor-mg/\S+/(pull|issues)/\d+` ou `#\d+`, exigir parte `tool-gitinho_*` correspondente na mesma mensagem.
- Pior caso: marcar resposta como "não validada — possivelmente alucinada" no UI.

---

## AP.11 — Fence ` ``` ` sem linguagem default vira "bash"

**Sintoma**: Markdown raw tem ` ``` ` (fence sem lang). UI mostra o bloco com header "bash" e tenta highlight como bash. Pra URLs ou texto, isso causa parse error no Shiki e renderiza estranho.

**Causa raiz**: Em `apps/chat/src/components/pre-block.tsx:122`:
```ts
const language = children.props.className?.split("-")?.[1] || "bash";
```
Default `"bash"` é arbitrário e contribui pro AP.4/AP.5.

**Onde aconteceu**: thread `fa18c8b6` — URL longa em fence sem lang virou "bash" e disparou os bugs cascateados.

**Regra**:
- Default mais seguro: `"text"` ou `"plaintext"`. Esses são lex'd como plain text por Shiki, sem chance de syntax error.
- Sistema prompt: instruir agente a SEMPRE especificar lang em fence (`text` quando não couber outra).

---

## AP.14 — `search_issues` com `repo:` + `sort:` → retorna 0 silenciosamente (pior que AP.7)

**Sintoma**: Usuário pergunta "qual última issue do repo X?". Agente chama `search_issues` com `query="repo:splor-mg/X is:issue sort:created-desc"`. Wrapper anexa `org:splor-mg`, fica:
```
(repo:splor-mg/X is:issue sort:created-desc) org:splor-mg
```
GitHub responde **`total: 0` SEM erro 422**. Agente conclui: "o repo X não tem issues". **Repo tem 16 issues abertas e várias fechadas** — agente mentiu.

**Causa raiz**: 3 problemas combinados.
1. **`repo:` + `org:` conflitam** — variante do AP.7 (que documentamos pra PRs). Em PRs dá 422; em issues GitHub aceita mas filtra zerando.
2. **`sort:created-desc` como qualifier dentro do `q`** — `sort:` NÃO é qualifier válido do GitHub Search. Ordenação é via parâmetro `sort=created&order=desc`, não embutida em `q`. Adicionar isso como qualifier provavelmente faz GitHub interpretar como nome de label/milestone e zera os resultados.
3. **Gap real de tool**: não existe `list_issues_by_repo` análoga a `list_prs_by_repo`. Sem alternativa específica, o agente cai em `search_issues` que é AP.7-style.

**Onde aconteceu**: thread em produção (jun/2026) — usuário perguntou pela última issue do repo `splor-mg/datamart`. Agente retornou "0 issues" enquanto o repo mostrava 16 abertas.

**Por que é pior que AP.7**:
- AP.7 dá 422 → agente vê erro → tenta outra coisa.
- AP.14 dá 200 + `total: 0` → agente acredita → resposta confiante errada. **Alucinação por construção (não por modelo)**.

**Regras**:
- **Criar `list_issues_by_repo(repo, state, label, since, until, max_results)`** análoga a `list_prs_by_repo`. Mesmo shape (`is:issue` forçado, `repo:<org>/<X>` pinado, strip de `org:`/`user:`/`repo:` do agente). Item de roadmap.
- **Criar `last_issue_by_repo(repo)`** análoga a `last_pr_by_user` mas por repo. 1 call, retorna o registro top.
- **Mitigação imediata** (sem nova tool): hardening do `search_issues` — se a query do agente já contém `repo:X/Y`, **NÃO** anexar `org:`. Detectar e suprimir. Custa ~5 linhas.
- **Mitigação imediata 2**: strip de qualifier `sort:` dentro do `q` — sort não tem efeito como qualifier; usar parâmetro `sort=` se o agente pedir ordering.
- Atualizar prompt: catálogo da família "issues" com critério de seleção, equivalente ao item 12.2 da família PR.

---

## AP.13 — Tool mode "none" + system prompt cita tools → alucinação silenciosa

**Sintoma**: O usuário pergunta algo que requer tool (ex.: "liste os resources de cada datapackage"). A resposta do agente vem com XML do tipo:
```
<function_calls>
<invoke name="list_datapackage_resources">
</invoke>
</function_calls>
<function_response>
{"resources":[{"repo":"armazem-mg",...]}, ..., "_chat_table":true}
</function_response>
```
literalmente no `part.text`. Dados parecem plausíveis mas são **inventados** — nomes de repos não existem na org, contagens erradas, `_chat_table` aparece como boolean (não como objeto). O sidebar continua mostrando "Tools N" (tools disponíveis) mas a mensagem assistant tem só `[step-start, text]`, sem parte `tool-*`.

**Causa raiz**: O Better Chatbot tem 3 modos de tool: `auto` (default), `manual`, `none`. O modo é selecionável via dropdown no input do chat E ciclável via shortcut (`auto → manual → none → auto`). Quando o estado em localStorage está em `"none"`, o backend bindar 0 tools ao modelo no `streamText`, mesmo tendo N tools registradas no MCP. O modelo recebe o system prompt que **menciona ferramentas por nome** (catálogo do item 11) mas **não pode chamá-las** — e cai num modo de "simular tool call em texto livre" usando o formato XML nativo do provider (Anthropic-style).

Confirmação nos logs em produção:
```
[better-chatbot] ℹ Chat API:  tool mode: none, mentions: 0
[better-chatbot] ℹ Chat API:  allowedMcpTools: 33, allowedAppDefaultToolkit: 2
[better-chatbot] ℹ Chat API:  binding tool count APP_DEFAULT: 0, MCP: 0, Workflow: 0
```
Threads com bug têm `tool mode: none` + `binding tool count MCP: 0`. Threads que funcionam têm `tool mode: auto` + `binding tool count MCP: N`.

**Onde aconteceu**: threads `7a5c4b19` e `f6c27824` (produção, jun/2026). Reportado pelo usuário com screenshot mostrando o XML cru renderizando como markdown na tela.

**Regra**:
- Banner persistente no `prompt-input.tsx` quando `toolChoice === "none"` — alerta visível "Ferramentas desativadas" com clique pra voltar pro auto. Não impede o modo (respeita upstream), mas torna a armadilha visível.
- Detector client-side em `message-parts.tsx`: regex `/<function_calls\b|<invoke\s+name=|<function_response\b/i` em `part.text` de assistant. Se acertar, mostra banner "Possível resposta alucinada" acima do markdown.
- Não confiar em "tools count > 0 no sidebar" como sinal de saúde — esse contador reflete tools registradas, não tools bindadas a este turn.
- Pra investigar incidente similar: log do container procurando `binding tool count` na linha do `Chat API`.

---

## AP.12 — Agente dizendo "não tenho ferramenta pra X" quando tem

**Sintoma**: Usuário pergunta algo coberto. Agente responde "infelizmente não tenho uma ferramenta disponível para isso" e redireciona pro GitHub.

**Causa raiz**: Prompt desatualizado (não menciona a tool nova) OU prompt menciona mas o LLM não associou a pergunta com o nome da tool.

**Onde aconteceu**: thread `41baf41c` — agente disse não conseguir listar PRs por repo, mas o gap real era `search_issues` retornar 422; após `list_prs_by_repo` (commit `ef3ea3a`) o caso está resolvido.

**Regra**:
- Toda tool nova precisa entrar na lista do item 11 do prompt no MESMO commit.
- Catálogo categorizado por intenção (ver item 12.2 do prompt — catálogo de PR) — não confiar que o LLM mapeia "PRs aguardando review" → `list_prs_awaiting_review` sem ajuda explícita.

---

## Checklist de prevenção (pra cada novo commit)

- [ ] Não adicionou método mutador no GitHub client.
- [ ] Tool nova com listagem tem `_chat_table`.
- [ ] Tool nova entrou no item 11 do prompt e no catálogo da família.
- [ ] Nenhum `useState(<JSX literal capturando props>)` em componente que recebe streaming content.
- [ ] Toda chamada `safe().map(asyncFn)` tem `.ifFail(handler)` explícito.
- [ ] Default de linguagem em code blocks não é `bash`.
- [ ] Não há `<function_calls>` ou `<function_result>` aparecendo em `part.text` de testes E2E.
- [ ] Bodies de texto livre passam por `_truncate()`.
- [ ] Banner de `toolChoice === "none"` no prompt-input segue visível e clicável.
- [ ] Detector AP.13 em `message-parts.tsx` segue cobrindo o regex de XML phantom tool call.

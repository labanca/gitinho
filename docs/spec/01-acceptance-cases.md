# 01 — Casos de aceitação canônicos

Casos reais extraídos do histórico de conversas em produção
(`applications-gitinho-splor-mg.nhfnv0.easypanel.host`). Cada caso descreve:

- **Pergunta**: o que o usuário disse, palavra por palavra (ou variantes equivalentes).
- **Tool calls esperados**: o caminho feliz e mínimo. Se houver mais de uma sequência aceitável, ambas são listadas.
- **Render esperado**: como o resultado deve aparecer pro usuário (tabela interativa, texto curto, etc.).
- **Anti-padrões observados**: o que o agente fez no histórico e NÃO pode repetir.

Use este documento como spec executável: qualquer rebuild precisa passar nesses casos. Quando aparecer uma pergunta nova que não cabe em nenhuma família, adicione um caso novo aqui ANTES de mexer em código.

---

## Família A — Inventário extensivo de uma capability

### A.1 — "Liste todos os recursos de todos os datapackages da organização"

**Pergunta exemplo**: "liste todos os recursos de todos os datapackages da organização" (variações: "lista de recursos dos datapackages", "tabela de resources").

**Tool calls esperados**: exatamente 1
- `list_datapackage_resources()` → devolve `{rows: [...583 itens...], _chat_table: {...}}`

**Render esperado**:
- `InteractiveTable` renderizada inline a partir do campo `_chat_table` (sem chamadas adicionais).
- Resposta de texto curta (1–3 frases): total de recursos, total de repositórios, observações relevantes (e.g., "0 erros de leitura").

**Anti-padrões observados em produção**:
- Chamar `pythonExecution` ou `createTable` por cima do resultado da MCP — força o LLM a regerar cada linha como tool arg, traveou em ~20 min.
- Re-emitir as linhas como texto/markdown table na resposta.
- Pedir credenciais ou nome da organização ao usuário ("forneça o token", "qual a URL?") quando a tool já está configurada — visto nas threads `d2fbfcc0` e `67952848`.

### A.2 — "Liste todos os datapackages"

**Pergunta exemplo**: "datapackages da org", "listagem de datapackages", "quais datapackages temos".

**Tool calls esperados**: exatamente 1
- `find_datapackages()` (critério canônico Frictionless — `datapackage.{json,yaml,yml}` no root).

**Render esperado**: tabela interativa via `_chat_table`. Resumo curto: total + público/privado + arquivados.

**Anti-padrões**:
- Usar `datapackages_stats(topic="datapackage")` em vez de `find_datapackages` quando o usuário não pediu filtro por topic — `topic` é flag opcional do GitHub, a maioria dos repos reais não tem.
- Compor manualmente via `list_org_repos` + N×`get_file_content`.

---

## Família B — Pull request

### B.1 — "Quais PRs foram criados pelo usuário X?"

**Pergunta exemplo**: "PRs criados pelo gabrielbdornas", "list PRs de @labanca".

**Tool calls esperados**: exatamente 1
- `list_prs_by_user(login="gabrielbdornas", state="all|open|closed|merged")`.

**Render esperado**: `InteractiveTable` via `_chat_table`. Resumo curto: total + estado dominante.

**Anti-padrões observados (thread `7a5c4b19`)**:
- **CRÍTICO** — o LLM produziu, no `part.text`, XML estilo Anthropic (`<function_calls><invoke name="list_prs_by_user">...</invoke></function_calls><function_result>{...}</function_result>`) sem nenhuma parte do tipo `tool-*` na mensagem. Isso é o sintoma do "tool call vazando como texto" reportado pelo usuário. A resposta inteira pode ser alucinada (PRs inventados); não há prova de que a MCP foi consultada.
- Caso de teste obrigatório: validar que toda resposta com lista de PRs tem uma parte `tool-gitinho_*` correspondente.

### B.2 — "Qual o último PR do usuário X?"

**Pergunta exemplo**: "último PR de gabrielbdornas", "qual o último pull request do labanca?".

**Tool calls esperados**: exatamente 1
- `last_pr_by_user(login="gabrielbdornas")`.

**Render esperado**: texto curto com título + número + repo + URL clicável. Não precisa de tabela (resultado único).

### B.3 — "Quais PRs estão esperando review do usuário X?"

**Pergunta exemplo**: "PRs aguardando review do gabrielbdornas", "o que preciso revisar?".

**Tool calls esperados**: exatamente 1
- `list_prs_awaiting_review(login="gabrielbdornas")` — usa `review-requested:<login>`.

**Render esperado**: tabela via `_chat_table` + resumo.

**Anti-padrões observados (thread `41baf41c`)**:
- Tentar `search_issues("review-requested:<login>")` — falha com 422 porque o wrapper força `org:` que conflita com `repo:`. Resolvido pela nova tool dedicada (commit `ef3ea3a`).
- Dizer "não tenho ferramenta para isso" quando o caso é coberto pela tool — sintoma de prompt desatualizado.

### B.4 — "Quais PRs estão abertos no repositório X?"

**Pergunta exemplo**: "PRs abertos no `dados-orcamentarios`", "lista os PRs do repo coteg".

**Tool calls esperados**: exatamente 1
- `list_prs_by_repo(repo="dados-orcamentarios", state="open")`.

**Render esperado**: tabela + resumo.

**Anti-padrões observados (thread `41baf41c`)**:
- Cair em `search_issues(query="repo:splor-mg/dados-orcamentarios is:pr is:open")` e receber 422 por causa de conflito `org:`+`repo:`. Resolvido por `list_prs_by_repo` (commit `ef3ea3a`).
- Responder "use o link do GitHub" quando a tool exata existe.

### B.5 — "Detalhe do PR #N do repo X"

**Pergunta exemplo**: "detalhes do PR 41 do dpetl", "me mostra o PR #46 do coteg".

**Tool calls esperados**:
- `get_pr(repo="dpetl", number=41)` (default — sem files/reviews).
- Se o usuário pedir "arquivos alterados", chamar de novo com `include_files=True`.
- Se o usuário pedir "reviews", `include_reviews=True`.

**Render esperado**: texto estruturado em tabela markdown com os campos chave (state, merged, author, base/head, labels, stats, URL).

**Anti-padrões**:
- Chamar `get_pr` com `include_files=True, include_reviews=True` por padrão "por garantia" — infla resposta sem motivo.
- Tentar derivar detalhe via `search_issues` + parsing de body.

---

## Família C — Descrição/análise de um repositório nomeado

### C.1 — "O que o repo X faz?" / "Análise do repo X"

**Pergunta exemplo**: "o que o repo dpm faz?", "qual o propósito do repositório coteg?", "análise do dados-pptx-cofin".

**Tool calls esperados**: exatamente 1
- `describe_repo(repo="dpm")` — combina metadata + README + manifests + root listing numa chamada.

**Render esperado**: texto narrativo (3–6 parágrafos) cobrindo propósito, tecnologias, manifestos presentes, status (ativo/arquivado).

**Anti-padrões observados (thread `541481f0`)**:
- Chamar `get_repo_readme` + `get_repo` em paralelo (2 calls) em vez de `describe_repo` (1 call).
- Quando o usuário pede "mais detalhes", chamar `get_file_content` em 3 paths chutados ("src/main.py", "src/cli.py", etc.) — visto repetidamente na thread `541481f0`, com várias chamadas redundantes. Em vez disso: `list_repo_contents` primeiro pra ver o que existe, AÍ `get_file_content` em paths reais.
- Não inventar conteúdo se README é curto. Dizer explicitamente "li o README de N chars, não consegui confirmar mais detalhes".

---

## Família D — Atividade de usuário em janela de tempo

### D.1 — "Commits do usuário X em [mês/janela]"

**Pergunta exemplo**: "commits do labanca em maio de 2026", "atividade do rayanecardoso na última semana".

**Tool calls esperados**: depende do que se quer
- Pro **número** (contagem): `count_user_contributions(login, type="commit", since, until)` — 1 call.
- Pra **lista** de commits específicos: hoje não há tool ideal — gap a marcar.
- Pra **panorama** (commits + issues + PRs + reviews): `user_activity_summary(login, since, until)` — 1 call.

**Render esperado**: número direto + breakdown (issues vs PRs vs reviews) se for summary. Citar a janela explicitamente (e.g., "1–31 maio 2026 UTC").

**Anti-padrões**:
- Chamar `list_prs_by_user` + `list_issue_comments_by_user` + `last_commit_by_user` separadamente quando `user_activity_summary` já entrega tudo.

---

## Família E — Busca de literal em código

### E.1 — "Encontre arquivos contendo a string X"

**Pergunta exemplo**: "procura `periodo=` no código", "onde aparece `api_url`?", "arquivos com `from frictionless`".

**Tool calls esperados**: exatamente 1
- `search_code(query="periodo=", extension=None, repo=None)`.

**Render esperado**: tabela via `_chat_table` (repo, path, name, url). Se `incomplete_results=true` no resultado, surfacar explicitamente: "o índice do GitHub pode estar desatualizado".

**Anti-padrões**:
- Chutar paths e iterar `get_file_content` (visto antes do `search_code` existir, thread `541481f0`).
- Não citar `incomplete_results=true` quando vem `true` — o usuário precisa saber que pode estar faltando.

---

## Família F — Configuração/URL externa (fora do escopo)

### F.1 — "Como construir a URL do SIGPLAN v4 para X?"

**Pergunta exemplo**: "qual a URL do SIGPLAN para 2023?", "como monto o endpoint v4 com período Y?".

**Tool calls esperados**: combinação curta
- `search_code(query="sigplan", extension="yaml|json")` ou `search_code(query="api_url")` pra achar os `datapackage.yaml` que documentam a estrutura.
- Talvez `get_file_content(repo="dados-sigplan-monitoramento", path="datapackage.yaml")` pra ler o padrão.

**Render esperado**:
- Tabela com os parâmetros (nome, valor, origem).
- Bloco de código com a URL completa em fence (lang `text` ou sem lang — NUNCA `bash` puro com URL, ver anti-padrão).
- Ressalva explícita sobre o que é inferência (e.g., "ppag vem do repo Y; se o ppag de 2023 for diferente, esta URL retorna dados errados").

**Anti-padrões observados (thread `fa18c8b6`)**:
- Emitir a URL em fence `bash` — desencadeou bug visual onde o bloco renderizava vazio até o fix do CSP `wasm-unsafe-eval` (commit `28043ea`) + o fix do PreBlock initial state (`e79fb48`). Hoje resolvido; mas o caso deve continuar testado.
- Não declarar incerteza quando parte do mapeamento depende de inferência cruzando 2 repos.

---

## Invariantes que valem pra todos os casos

1. **Toda resposta com dados de PR/repo/usuário tem uma parte `tool-gitinho_*` correspondente**. Se não tem, é alucinação. Caso de teste:
   ```
   for part in assistant.parts:
       if part.type == "text" and re.search(r"(splor-mg/\S+/pull/\d+|#\d+\s)", part.text):
           assert any(p.type.startswith("tool-gitinho_") for p in assistant.parts), "PR mencionado sem tool call"
   ```

2. **Quando uma tool MCP devolve `_chat_table`, o agente NÃO chama `createTable` nem `pythonExecution` por cima.** A tabela já está renderizada.

3. **Conteúdo da tool result NÃO aparece como texto no markdown.** Especificamente, `<function_calls>...</function_calls>` ou `{"total": ..., "prs": [...]}` no campo `text` é bug — sinal de que o adapter não parseou o tool call format do modelo.

4. **Nunca prometer ação não-disponível.** Se não há tool, dizer "não tenho ferramenta pra isso" — não dar receita de Python com token falso.

5. **Sempre citar a janela temporal quando aplicável.** "Em maio de 2026" precisa virar "01 a 31 de maio de 2026 UTC" na resposta.

6. **Read-only.** Nenhuma resposta deve sugerir abrir issue, fazer PR, comentar, etc. Apenas leitura.

---

## Como usar este documento

- **Rebuild**: antes de qualquer linha de código novo, garantir que o rebuild atende todos os casos aqui — adicionar testes automatizados que exercitem cada um (mockando ou batendo na MCP de staging).
- **Reportar bug**: se uma conversa real diverge de um caso aqui, abra um ticket citando o caso (`A.1`, `B.3`, etc.) — facilita triagem.
- **Adicionar caso novo**: quando aparecer uma família de pergunta não coberta, escreva o caso ANTES de mexer em código. Caso novo sem teste correspondente vira regressão dois meses depois.

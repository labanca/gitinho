# gitinho-mcp

Servidor [MCP](https://modelcontextprotocol.io) que expõe as ferramentas
read-only do Gitinho (consultas à org `splor-mg` no GitHub) para qualquer
cliente compatível — incluindo o frontend de chat em `apps/chat`.

## Como rodar (stdio)

```bash
uv run --directory apps/mcp python -m gitinho_mcp
```

## Como inspecionar interativamente

```bash
uv run --directory apps/mcp mcp dev gitinho_mcp/server.py
```

Abre o MCP Inspector no navegador para exercitar cada tool individualmente.

## Variáveis de ambiente

| Variável | Obrigatória | Default | Descrição |
| --- | --- | --- | --- |
| `ALLOWED_ORG` | sim | `splor-mg` | Organização autorizada |
| `GH_APP_ID` | sim | — | GitHub App ID |
| `GH_APP_INSTALLATION_ID` | sim | — | Installation ID na org |
| `GH_APP_PRIVATE_KEY_PATH` | sim | — | Caminho do `.pem` da App |
| `GLOSSARY_CACHE_TTL_S` | não | `300` | TTL do cache do glossário |

## Cobertura de tools de pull request

Em `gitinho_mcp/tools/pulls.py` (todas com `_chat_table` para auto-render no chat,
exceto `get_pr` que retorna detalhe único e `last_pr_by_user`):

- `count_open_prs(repo=None)` — contagem (GraphQL totalCount, exato).
- `list_prs_by_user(login, state, since, until, max_results)` — PRs **criados** por um usuário (autor), com filtros de estado e janela de criação.
- `last_pr_by_user(login)` — último PR criado por um usuário.
- `list_prs_by_repo(repo, state, base, head, author, label, since, until, max_results)` — todos os PRs de UM repo, com filtros (estado, branches base/head, autor, label, janela de criação).
- `list_prs_awaiting_review(login, repo=None, max_results)` — PRs **abertos onde `login` foi pedido como reviewer e ainda não revisou** (`review-requested:<login>`).
- `search_prs(query, state, label, base, head, repo, since, until, max_results)` — busca livre escopada a `is:pr`, com filtros opcionais. Defesa: qualquer `org:`/`user:`/`repo:` no `query` é stripado e o escopo é re-anchorado a `org:<ALLOWED_ORG>` (ou `repo:` quando informado).
- `get_pr(repo, number, include_files=False, include_reviews=False)` — detalhe completo de UM PR (title, body truncado em 4000 chars, state, merged, author, base/head, labels, requested_reviewers, stats). Opcionais opt-in: lista de arquivos alterados e lista de reviews submetidas.

Complementares (não-pulls.py mas tocam PR):

- `count_user_contributions(login, type="pr", since, until)` — contagem por usuário via `/search`.
- `list_pr_comments_by_user(login, since, until)` — comentários do usuário em PRs.
- `org_users_activity_report(since, until)` — inclui `prs_created` e `pr_reviews` por membro.

Gaps conhecidos remanescentes (não bloqueantes; planejar quando aparecer demanda):

- **Team-review requests** — `list_prs_awaiting_review` cobre só requests individuais (`review-requested:<login>`); não inclui PRs aguardando review de um time (`team-review-requested:<team>`).
- **PR review-line comments** — `list_pr_comments_by_user` lê só os comentários do timeline (`/issues/.../comments`), não os de linha de código (`/pulls/.../comments`).
- **Status check detail** — `get_pr` traz `mergeable_state` mas não a tabela detalhada de check runs (GitHub Checks API).

## Cobertura de tools de issues — gap conhecido

Hoje só existe `count_open_issues`, `last_issue_by_user`, `search_issues` e `list_issue_comments_by_user`. Faltam contrapartidas das tools de PR já feitas (commit `ef3ea3a`):

- **`list_issues_by_repo(repo, state, label, since, until, max_results)`** — análoga a `list_prs_by_repo`. Necessária pra responder "lista issues do repo X" sem cair em `search_issues` (caminho AP.14).
- **`last_issue_by_repo(repo)`** — análoga a `last_pr_by_user` mas por repo. Necessária pra "qual última issue do repo X?".
- **`get_issue(repo, number, include_comments=False)`** — análoga a `get_pr`. Detalhe de uma issue.
- **`search_issues` precisa de hardening**: detectar `repo:X/Y` na query do agente e NÃO anexar `org:Y` (provoca AP.14 — `total: 0` silencioso). Strip de `sort:` dentro de `q` (não é qualifier válido, zera resultados).

Esses gaps motivaram o anti-padrão AP.14 em [`docs/spec/03-anti-patterns.md`](../../docs/spec/03-anti-patterns.md) (jun/2026).

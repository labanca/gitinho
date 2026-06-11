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

## Pendências de cobertura de tools

### Pull requests — busca elaborada

Cobertura atual de PRs (em `gitinho_mcp/tools/pulls.py` + complementares):

- `count_open_prs(repo=None)` — contagem (GraphQL totalCount, exato).
- `list_prs_by_user(login, state, since, until, max_results)` — PRs **criados** por um usuário, com filtros de estado e janela de criação.
- `last_pr_by_user(login)` — último PR criado por um usuário.
- `count_user_contributions(login, type="pr", since, until)` — contagem por usuário (search-based).
- `list_pr_comments_by_user(login, since, until)` — comentários do usuário em PRs.
- `org_users_activity_report(since, until)` — inclui `prs_created` e `pr_reviews` por membro.

Não cobertos ainda (gaps conhecidos a planejar):

- **Busca livre em PRs** — análogo a `search_issues(query)` mas escopado a `is:pr`. Permite filtrar por título/body, label, milestone, etc.
- **Listar PRs por repositório** — todos os PRs de um repo X com filtros (estado, autor, base/head, label). Hoje só dá pra fatiar por autor.
- **Detalhes de um PR específico** — `get_pr(repo, number)` com files changed, commits, reviews, status checks.
- **Filtrar por reviewer / por label / por base branch** — `reviewer:<login>`, `label:<x>`, `base:<branch>`, `head:<branch>` no estilo do search da GitHub.
- **PRs aguardando review** — PRs abertos onde o usuário foi designado como reviewer mas ainda não revisou (`review-requested:<login>`).

Workaround temporário: o agente pode usar `search_code` pra buscar trechos em diffs/branches, ou `search_issues(query)` com qualquer query que inclua `is:pr` — porém isso depende dele construir o filtro à mão e perde a fail-safety do pin de `org:` que essas tools dedicadas teriam.

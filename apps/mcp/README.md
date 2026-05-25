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

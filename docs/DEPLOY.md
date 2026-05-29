# Gitinho — Deploy

Guia para subir o Gitinho em uma VM (Easy Panel ou Docker Compose
direto) com a postura de segurança da Fase 1: **read-only**,
**127.0.0.1-only**, **HTTPS via reverse-proxy**.

## 1. Arquitetura em produção

```
                     ┌────────────────────────────────┐
                     │   Easy Panel proxy (HTTPS)     │
                     │   gitinho.splor.mg → :3000     │
                     └───────────────┬────────────────┘
                                     │ 127.0.0.1
        ┌────────────────────────────┴────────────────────────────┐
        │  apps/chat (Next.js 16 + apps/mcp embarcado via stdio)  │
        │  PORT=3000                                              │
        └─────┬──────────────────┬────────────────────────────────┘
              │                  │
              ▼                  ▼
        ┌──────────┐       ┌──────────┐
        │ postgres │       │  minio   │  127.0.0.1:9000 / :9001
        └──────────┘       └──────────┘
```

Sem portas expostas publicamente — só o Easy Panel/reverse-proxy
toca a internet. O MCP Python roda dentro do mesmo container do chat
via stdio (`FILE_BASED_MCP_CONFIG=true` + `.mcp-config.json`).

## 2. Pré-requisitos

- Docker Engine ≥ 24 + Docker Compose ≥ 2.20.
- GitHub App instalada na org `splor-mg` com as permissões mínimas
  documentadas em [`SECURITY.md`](./SECURITY.md) §2.1.
- OAuth App do GitHub para login do usuário (mesma reusada da Fase
  anterior, ID `Ov23lit3J2ceJ03kdZlO`).
- Conta no Azure AI Foundry com chave OpenAI-compatível.

## 3. Variáveis de ambiente

Copie `.env.example` para `.env` na raiz e preencha:

| Bloco | Variável | Notas |
| --- | --- | --- |
| App | `ALLOWED_ORG` | `splor-mg` |
| Postgres | `POSTGRES_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | URL aponta para `postgres:5432` (rede interna do compose) |
| Better Auth | `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL` | gere com `openssl rand -base64 32`; URL pública (`https://gitinho.splor.mg`) |
| GitHub OAuth | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | login do usuário |
| GitHub App | `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PRIVATE_KEY_PATH` | path do `.pem` montado no container |
| Azure (GPT) | `OPENAI_COMPATIBLE_DATA` | JSON gerado pelo helper do better-chatbot — modelos GPT no Foundry |
| Azure (Claude) | `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` | passthrough Anthropic no Foundry: URL termina em `/anthropic/v1` (inclua o `/v1`); chave é a do deployment Foundry (não `sk-ant-…`). Default `fallbackModel` em `models.ts` aponta para `sonnet-4.6` deste canal |
| MCP | `FILE_BASED_MCP_CONFIG=true`, `NOT_ALLOW_ADD_MCP_SERVERS=1` | já default no compose |
| File ingest | `FILE_STORAGE_TYPE=s3`, `FILE_STORAGE_S3_*`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | MinIO sidecar |

> **Nunca** commitar `.env` ou `secrets/gh-app.pem` — ambos já estão
> em `.gitignore`.

## 4. Subindo via Docker Compose

```bash
# Na raiz do repo
cp .env.example .env
# Preencha as variáveis listadas em §3.

# Coloque a chave privada da GitHub App em ./secrets/gh-app.pem
mkdir -p secrets
mv ~/Downloads/gitinho.<data>.private-key.pem secrets/gh-app.pem
chmod 600 secrets/gh-app.pem

# Suba a stack
docker compose -f apps/chat/docker/compose.yml up -d --build

# Verifique
docker compose -f apps/chat/docker/compose.yml ps
```

Saída esperada: `chat`, `postgres`, `minio` em `healthy` e
`minio-bootstrap` em `Exited (0)` (criou o bucket).

### 4.1 Migrations Drizzle

Rodam automaticamente no startup do container `chat` (script
`db:migrate` antes do `start`). Para rodar manualmente:

```bash
docker compose -f apps/chat/docker/compose.yml exec chat \
  node apps/chat/server.js db:migrate
```

### 4.2 Seed dos agentes nomeados

Primeira vez, popular `@Datapackages` e `@Atividade`:

```bash
docker compose -f apps/chat/docker/compose.yml exec chat \
  node -e "require('./apps/chat/scripts/seed-gitinho-agents.ts')"
```

(Em dev local: `pnpm --filter chat gitinho:seed-agents`.)

## 5. Easy Panel

Equivalente, com 3 (ou 4, contando MinIO) "Services" no projeto:

| Service | Tipo | Notas |
| --- | --- | --- |
| `gitinho-postgres` | Postgres 17 | Apenas porta interna; backup diário ligado |
| `gitinho-minio` | Custom image `minio/minio:RELEASE.2025-04-22T22-12-26Z` | Comando `server /data --console-address ":9001"`; volume `minio_data`; portas só 127.0.0.1 |
| `gitinho-chat` | App build do `apps/chat/docker/Dockerfile` | Bind 127.0.0.1:3000; depende de postgres+minio |
| `gitinho-mc-bootstrap` | (one-shot) `minio/mc:RELEASE.2025-04-16T18-13-26Z` | Cria o bucket; pode ser executado uma vez via console |

Domain do Easy Panel aponta para `gitinho-chat:3000` com HTTPS
gerenciado.

## 6. Checklist de segurança (Fase 1)

- [x] Apenas porta `127.0.0.1:3000` exposta no host (proxy faz HTTPS).
- [x] MinIO `127.0.0.1:9000/9001` — console nunca exposto.
- [x] Postgres sem porta no host.
- [x] CSP estrita + HSTS + `X-Frame-Options: DENY` (Next.js
      `headers()`).
- [x] OAuth GitHub só serve para identidade + membership; token é
      descartado depois do callback.
- [x] GitHub App restrita a `splor-mg`; tools de escrita não
      registradas no `gitinho-mcp`.
- [x] Secrets fora do repo (`.gitignore`).
- [x] `NOT_ALLOW_ADD_MCP_SERVERS=1` — usuário não pode plugar MCP
      arbitrário pela UI.
- [x] `DISABLE_EMAIL_SIGN_IN=1`, `DISABLE_EMAIL_SIGN_UP=1`,
      `DISABLE_SIGN_UP=1` — só OAuth GitHub.

## 7. Operação

### 7.1 Logs

```bash
docker compose -f apps/chat/docker/compose.yml logs -f chat
```

Logs do Next.js e do `gitinho-mcp` saem juntos no stdout do mesmo
container (stdio).

### 7.2 Backup

- **Postgres:** `pg_dump` periódico do volume `postgres_data` (Easy
  Panel faz por padrão).
- **MinIO:** snapshot do volume `minio_data` é suficiente para a
  Fase 1 (exports XLSX são regeneráveis).

### 7.3 Rotação de chaves

- `BETTER_AUTH_SECRET` — quebra sessões ativas. Rotacionar em janela
  de manutenção.
- Chave privada da GitHub App (`secrets/gh-app.pem`) — gerar nova
  no GitHub, substituir o arquivo, reiniciar `chat`.

## 8. Troubleshooting

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| `gitinho` MCP não aparece nas tools | `.mcp-config.json` ausente ou `uv` não no PATH | Verifique `FILE_BASED_MCP_CONFIG=true` e `which uv` dentro do container |
| Upload de PDF/DOCX devolve "FILE_NOT_FOUND" | Bucket MinIO não criado | Rode `minio-bootstrap` ou crie via console |
| `convert_document failed` nos logs | MarkItDown não conseguiu parsear (arquivo corrompido) | Veja o `error` no log; o chat degrada silenciosamente |
| Login GitHub devolve 403 | Usuário não é membro de `splor-mg` | Conforme `audit_log` em `SECURITY.md` §2.2 |

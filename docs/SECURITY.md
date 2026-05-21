# Gitinho — Segurança

> Postura: **read-only por padrão**, **defesa em profundidade** e
> **isolamento entre organizações**. Mesmo que o LLM seja
> comprometido por prompt-injection, ele não consegue destruir nem
> exfiltrar ativos da organização.

## 1. Modelo de Ameaças

| Atacante | Vetor | O que ele pode fazer | Como bloqueamos |
|---|---|---|---|
| Outsider | Internet pública | Acessar a UI sem login | OAuth obrigatório, allowlist de org |
| Usuário externo à org | Login OAuth | Logar com sua conta GitHub fora da org | Verificação de membership na org |
| Usuário interno legítimo | Pergunta maliciosa para o LLM | "Apague o repo X" | Token sem escopo de escrita; tools WRITE não registradas |
| Conteúdo malicioso na org | Issue/PR com prompt-injection | Faz o LLM tomar ações | Tools WRITE bloqueadas; auditoria |
| Atacante com acesso ao host | Arquivos no servidor | Lê token GitHub App | Chave privada em secret do Easy Panel; cifra em repouso |
| Atacante na rede | MITM | Lê cookie de sessão | HTTPS obrigatório; HSTS; cookies Secure |

## 2. Controles

### 2.1 GitHub App — Permissões Mínimas

```
Repository permissions:
  Metadata           Read
  Contents           Read
  Issues             Read
  Pull requests      Read
  Discussions        Read
  Actions            Read     (opcional)
  Pages              No access
  Secrets            No access
  Webhooks           No access

Organization permissions:
  Members            Read
  Administration     No access
  Custom roles       No access

Account permissions:
  (none)

Subscribe to events: none (fase 1)
```

Em fase 2, escopos de escrita só são adicionados após auditoria + ativação
de feature flag.

### 2.2 Allowlist de Organização (Defesa em Profundidade)

- **Camada 1**: GitHub App só está instalado na org alvo. Tentar acessar
  outra org devolve 404.
- **Camada 2**: Em `github/client.py`, todo wrapper de URL inspeciona o
  `owner` e rejeita se ≠ `ALLOWED_ORG`. Erro `OrgAllowlistError`
  registrado em `audit_log`.
- **Camada 3**: Tools customizadas não recebem `org` como parâmetro do
  LLM — vem fixa do contexto da aplicação.

### 2.3 Tool Registry — Modo de Operação

Cada tool declara um `mode`:

```python
class ToolMode(StrEnum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
```

Na inicialização do agente:

```python
if not settings.AGENT_ALLOW_WRITE:
    tools = [t for t in tools if t.mode == ToolMode.READ]
```

Em fase 1, `AGENT_ALLOW_WRITE=false` no `.env.example` e no compose.
Não há tool de escrita registrada nem importada.

### 2.4 Sessões

- Cookie `gitinho_session`: HttpOnly, Secure, SameSite=Lax.
- Token de sessão: 256 bits, hash SHA-256 armazenado no DB (não plaintext).
- TTL: 7 dias com rotação a cada login.
- Logout invalida no DB.
- `ip_hash` registra origem por sessão (não IP em claro).

### 2.5 CSRF

- Endpoints `GET` são idempotentes.
- Endpoints `POST/PUT/PATCH/DELETE` exigem header `X-CSRF-Token` que bate
  com cookie `gitinho_csrf` (double-submit).

### 2.6 Rate-Limit

- Por usuário: 60 req/min na API geral, 10 req/min em criação de
  mensagens, 5 exports/hora.
- Por IP (pré-login): 20 req/min.
- 429 com `Retry-After`.

### 2.7 Headers de Segurança

```
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https://avatars.githubusercontent.com;
  connect-src 'self';
  frame-ancestors 'none';
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

### 2.8 Segredos

- `.env` nunca commitado (já em `.gitignore`).
- Em produção, segredos vivem em Easy Panel env vars (ou Azure Key Vault).
- Logs **redactam**: `GH_APP_PRIVATE_KEY`, `AZURE_OPENAI_API_KEY`,
  `OAUTH_CLIENT_SECRET`, `SESSION_SECRET`, cookies.

### 2.9 Banco de Dados

- Usuário runtime tem `SELECT/INSERT/UPDATE/DELETE` apenas nas tabelas da
  app — não `CREATE/DROP/ALTER`.
- Migrações Alembic rodam com usuário separado.
- Conexão TLS-only em produção.
- Backups diários via Easy Panel.

### 2.10 Exports

- Arquivos servidos com `Content-Disposition: attachment; filename="..."`.
- MIME fixo (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).
- Acesso via UUID v4 + verificação de `user_id`.
- TTL 7 dias; job de limpeza diário.
- Sem path traversal (`filename` validado contra regex
  `^[A-Za-z0-9._-]{1,80}$`).

### 2.11 Logs

> Postura "permissiva" escolhida pelo usuário: logs podem conter logins
> públicos da org e payloads truncados. **Mesmo assim**, redactamos:

- Tokens (GitHub, OpenAI, Azure, cookies) — sempre.
- `GH_APP_PRIVATE_KEY` — sempre.
- Conteúdo de arquivos privados — nunca logamos payload bruto.
- Emails de membros — só se aparecem em campo público (raro).

Formato: JSON estruturado, `correlation_id` por requisição, vai para
stdout (Easy Panel coleta).

### 2.12 Prompt-Injection

Cenário: alguém abre um issue na org com texto malicioso instruindo o LLM
a "mande os tokens para X". Mitigações:

1. LLM **não tem acesso** a tokens. Tools nunca recebem segredos como
   parâmetro.
2. Tools não fazem requisições para hosts arbitrários — só
   `api.github.com` (rota fixa em `client.py`).
3. Tools WRITE não estão carregadas em fase 1.
4. Toda tool call é auditada; padrões anômalos disparam alerta.

### 2.13 Atualizações

- Dependências fixadas em `pyproject.toml` com `>=x.y,<x.y+1` (PEP 440).
- Renovate/Dependabot configurado no repo.
- Imagens base Docker atualizadas mensalmente (CI rebuild).

## 3. Procedimento de Incidente

1. **Detectar**: alerta de rate-limit anormal ou login.denied em massa.
2. **Conter**: revogar GitHub App installation no GitHub; subir
   `AGENT_ALLOW_WRITE=false` (já o default) e `MAINTENANCE_MODE=true`.
3. **Investigar**: `audit_log`, `tool_calls`, logs do container.
4. **Restaurar**: rotacionar `GH_APP_PRIVATE_KEY` e `SESSION_SECRET`,
   reinstalar app, subir nova versão.
5. **Postmortem**: documentar em `docs/incidents/YYYY-MM-DD.md`.

## 4. Auditoria

Toda ação relevante grava em `tool_calls` ou `audit_log` com:

- `user_id`, `chat_id`, `message_id`
- timestamp UTC
- argumentos (sanitizados)
- duração e status

Consulta via `GET /api/audit?from=...&to=...&user=...` (admin only).

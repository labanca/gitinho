# Deploy no Easy Panel (VM Azure)

> Você já tem uma VM na Azure com **Easy Panel** instalado e um projeto
> onde adiciona seus serviços. Estas instruções partem desse cenário —
> você **não** precisa criar projeto novo nem instalar nada na VM.

## Visão geral

Você vai adicionar **3 serviços** ao seu projeto existente no Easy Panel:

| # | Serviço | Tipo no Easy Panel | Imagem / Source |
|---|---|---|---|
| 1 | `gitinho-db` | **Database → PostgreSQL 16** | imagem managed pelo Easy Panel |
| 2 | `gitinho-backend` | **App** | Build from GitHub (`backend/Dockerfile`) ou imagem GHCR |
| 3 | `gitinho-frontend` | **App** | Build from GitHub (`frontend/Dockerfile`) ou imagem GHCR |

Os três serviços ficam isolados na rede interna do seu projeto. O
Easy Panel cuida de:
- DNS interno (o backend acessa o DB pelo nome `gitinho-db`)
- Certificado HTTPS automático (Let's Encrypt) para o frontend
- Reinício e healthchecks
- Logs centralizados
- Variáveis de ambiente por serviço (UI segura, não vão para o git)

> **Multi-org:** se um dia você quiser servir uma segunda organização,
> basta repetir os passos abaixo adicionando outros 3 serviços com
> sufixo (`gitinho-<org2>-db`, `gitinho-<org2>-backend`, etc.) ao mesmo
> projeto. Os dados ficam totalmente isolados porque cada backend só
> conhece seu próprio DB e sua própria `ALLOWED_ORG`.

## Pré-requisitos (fora do Easy Panel)

1. **GitHub App** criada e instalada na organização alvo, com as
   permissões read-only listadas em `../docs/SECURITY.md` §2.1. Você
   precisa de:
   - `GH_APP_ID` (App ID)
   - `GH_APP_INSTALLATION_ID` (Installation ID — aparece após instalar
     o App na org)
   - Chave privada `.pem` (download único após criar o App)
2. **GitHub OAuth App** (para login dos usuários humanos):
   - Crie em `https://github.com/organizations/<ORG>/settings/applications`
     (ou em settings pessoais) → New OAuth App.
   - **Homepage URL**: `https://gitinho.<seu-dominio>`
   - **Authorization callback URL**:
     `https://gitinho.<seu-dominio>/auth/github/callback`
   - Anote `Client ID` e gere `Client Secret`.
3. **Azure AI Foundry**: endpoint, chave de API, e os nomes dos
   **deployments** (não dos modelos) para orquestrador, analítico e leve.
4. Um **subdomínio** apontado para o IP da sua VM. Ex.: registre um
   `A record` `gitinho.seu-dominio.com → IP-da-VM` no seu DNS.

## Passo 1 — Serviço PostgreSQL (`gitinho-db`)

No seu projeto do Easy Panel:

1. **+ Service → Database → PostgreSQL** (versão 16).
2. Service name: `gitinho-db`.
3. Deixe o Easy Panel gerar usuário/senha — anote ambos.
4. Salve. Não exponha porta para a internet — uso interno apenas.

**Resultado:** dentro do projeto, o host do DB é `gitinho-db` na porta
`5432`. Você usará isto na `DATABASE_URL` do backend.

## Passo 2 — Serviço backend (`gitinho-backend`)

1. **+ Service → App**.
2. Service name: `gitinho-backend`.
3. **Source** — duas opções:
   - **(A) Build from GitHub** (recomendado para começar):
     - Conecte sua conta GitHub no Easy Panel se ainda não tiver.
     - Repository: `<você>/gitinho` (este repo).
     - Branch: `main`.
     - **Build path / context**: `backend`
     - **Dockerfile path**: `backend/Dockerfile`
   - **(B) Image** (recomendado para produção estável):
     - Configure CI (ex.: GitHub Actions) para publicar
       `ghcr.io/<você>/gitinho-backend:<tag>` e aponte aqui.
4. **Port (internal)**: `8000`.
5. **Domains**: ainda **não** publique externamente o backend (o
   frontend faz proxy para ele pela rede interna). Mantenha sem domínio
   público.
6. **Environment**: cole as variáveis abaixo. Substitua tudo que estiver
   entre `<…>`:

   ```env
   APP_ENV=production
   APP_BASE_URL=https://gitinho.<seu-dominio>
   SESSION_SECRET=<gere com: python -c "import secrets; print(secrets.token_urlsafe(48))">

   ALLOWED_ORG=splor-mg

   OAUTH_CLIENT_ID=<do GitHub OAuth App>
   OAUTH_CLIENT_SECRET=<do GitHub OAuth App>
   OAUTH_REDIRECT_URI=https://gitinho.<seu-dominio>/auth/github/callback

   GH_APP_ID=<do GitHub App>
   GH_APP_INSTALLATION_ID=<da instalação na org>
   # Cole o PEM inteiro como string (preserve as quebras de linha; o
   # Easy Panel mantém quebras em campos multilinha):
   GH_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----
   ...conteúdo...
   -----END RSA PRIVATE KEY-----

   AZURE_OPENAI_ENDPOINT=https://<seu-recurso>.openai.azure.com
   AZURE_OPENAI_API_KEY=<...>
   AZURE_OPENAI_API_VERSION=2024-10-21
   AZURE_DEPLOYMENT_ORCHESTRATOR=<nome do deployment do GPT-4.1 / GPT-5>
   AZURE_DEPLOYMENT_ANALYTIC=<nome do deployment do o3>
   AZURE_DEPLOYMENT_LIGHT=<nome do deployment do GPT-4.1-mini>

   # DATABASE_URL: host é o nome do serviço Postgres do Passo 1.
   # Substitua user/pwd/db pelo que o Easy Panel gerou.
   DATABASE_URL=postgresql+asyncpg://<user>:<pwd>@gitinho-db:5432/<dbname>

   AGENT_ALLOW_WRITE=false
   LOG_LEVEL=INFO
   LOG_FORMAT=json
   ```

7. **Health check**: `GET /healthz`.
8. **Resources** (sugestão inicial): 1 vCPU, 1 GB RAM, 2 GB disco.
   Ajuste depois conforme uso.
9. **Deploy**.

**Resultado:** o backend sobe, roda as migrações do Postgres
automaticamente (via `alembic upgrade head` no entrypoint), e fica
acessível dentro do projeto como `http://gitinho-backend:8000`.

## Passo 3 — Serviço frontend (`gitinho-frontend`)

1. **+ Service → App**.
2. Service name: `gitinho-frontend`.
3. **Source**:
   - **(A) Build from GitHub**:
     - Repository: este repo.
     - Branch: `main`.
     - **Build path / context**: `frontend`
     - **Dockerfile path**: `frontend/Dockerfile`
   - **(B) Image**: `ghcr.io/<você>/gitinho-frontend:<tag>`.
4. **Port (internal)**: `80`.
5. **Domains**:
   - Adicione `gitinho.<seu-dominio>`.
   - Marque **HTTPS automático** (Let's Encrypt — Easy Panel cuida).
6. **Environment** (o nginx do frontend descobre o backend via env):

   ```env
   BACKEND_HOST=gitinho-backend
   BACKEND_PORT=8000
   ```

7. **Deploy**.

> O `frontend/nginx.conf.template` usa `${BACKEND_HOST}` e
> `${BACKEND_PORT}`. A imagem `nginx:alpine` renderiza o template no
> startup via `envsubst`. Em dev local (compose) o default é `backend`;
> no Easy Panel, sobrescreva para `gitinho-backend`.

## Passo 4 — Smoke test

1. Acesse `https://gitinho.<seu-dominio>`.
2. Você deve ver a tela de login. Clique em **Entrar com GitHub**.
3. Autorize o OAuth App.
4. Se você for membro da org alvo, entra no app; senão, vê a mensagem
   "Você precisa ser membro da organização X".
5. Inicie uma conversa e pergunte: **"Quantos repositórios temos?"**.
   Deve responder com o número real obtido via GraphQL.
6. Tente perguntas do brief para validar precisão (último commit,
   PRs abertos, repos sem update há N dias, exportar planilha).

## Atualizações

Se você usou **Build from GitHub**:
- Easy Panel oferece **Auto Deploy on push** — ative para o branch
  `main`. Cada push faz rebuild automático.

Se você usou **Image**:
- Configure GitHub Actions para push de imagem ao GHCR (ver
  `.github/workflows/` se/quando você criar).
- No Easy Panel, ative **Watchtower** ou puxe a nova tag manualmente.

## Backups

No serviço `gitinho-db`:
- Easy Panel → aba **Backups** → habilite backup diário.
- Defina retenção (sugestão: 14 dias).
- Restauração testada antes de depender disso para produção.

## Rollback rápido

- **Backend ou frontend quebrado:** Easy Panel → aba **Deploys** →
  clique no deploy anterior → **Redeploy**.
- **Vazamento suspeito:** revogue a GitHub App em
  `https://github.com/organizations/<ORG>/settings/installations` e
  rotacione `SESSION_SECRET` no serviço backend (Easy Panel reinicia
  automaticamente). Isso desloga todo mundo.

## Custos esperados (Azure VM)

Backend + frontend + Postgres rodando na mesma VM consomem pouco:
- Idle: ~300 MB RAM total
- Durante streaming de resposta: pico de ~500 MB
- Disco: ~500 MB para o app + DB cresce com o histórico de chats

Sua VM atual deve aguentar tranquilamente junto com seus outros apps.

## Multi-org no mesmo projeto

Se um dia você atender outra org, **não** clone a VM nem o projeto.
Apenas adicione 3 novos serviços no **mesmo projeto** do Easy Panel:
- `gitinho-<org2>-db`
- `gitinho-<org2>-backend` (com `ALLOWED_ORG=<org2>` e GitHub App da
  org2)
- `gitinho-<org2>-frontend` (com domínio `gitinho-<org2>.<seu-dominio>`)

Cada instância vê só os dados da sua própria org — isolamento por DB
físico + por `ALLOWED_ORG`.

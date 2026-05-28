# =================================================================
# Stage 1 — builder do Next.js
# =================================================================
FROM node:23-alpine AS builder
ARG DOCKER_BUILD="1"
WORKDIR /app

# O contexto de build do compose é a raiz do monorepo, então copiamos
# o repo inteiro e o pnpm cuida do workspace (apps/chat).
COPY . .

RUN corepack enable pnpm
RUN pnpm install --frozen-lockfile

ENV NEXT_STANDALONE_OUTPUT="true"

RUN pnpm --filter chat build

# =================================================================
# Stage 2 — runtime: Node + Python + uv + apps/mcp embarcado
# =================================================================
FROM node:23-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Python + uv para o servidor MCP `gitinho-mcp` (stdio).
RUN apk add --no-cache python3 py3-pip ca-certificates curl \
  && python3 -m venv /opt/uv-venv \
  && /opt/uv-venv/bin/pip install --no-cache-dir uv \
  && ln -s /opt/uv-venv/bin/uv /usr/local/bin/uv \
  && ln -s /opt/uv-venv/bin/uvx /usr/local/bin/uvx

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

# Standalone output do Next.js.
COPY --from=builder /app/apps/chat/public ./apps/chat/public
COPY --from=builder --chown=nextjs:nodejs /app/apps/chat/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/chat/.next/static ./apps/chat/.next/static

# Migrations Drizzle.
COPY --from=builder /app/apps/chat/src/lib/db/migrations ./apps/chat/src/lib/db/migrations

# Servidor MCP Python: copiamos o source e deixamos o `uv run`
# resolver o ambiente no primeiro boot (cache no volume do container).
COPY --from=builder --chown=nextjs:nodejs /app/apps/mcp ./apps/mcp
COPY --from=builder --chown=nextjs:nodejs /app/uv.lock /app/pyproject.toml ./

# Config MCP file-based esperada pelo chat.
COPY --from=builder --chown=nextjs:nodejs /app/apps/chat/.mcp-config.json.example ./apps/chat/.mcp-config.json

# Pré-aquece o ambiente Python para que o primeiro request não
# pague a penalidade de sync.
RUN uv sync --directory /app/apps/mcp --no-dev \
  && chown -R nextjs:nodejs /app/apps/mcp/.venv /root/.cache 2>/dev/null || true

USER nextjs

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
ENV FILE_BASED_MCP_CONFIG=true
# Next.js standalone runs from /app, so the default config-path lookup
# (`process.cwd()/.mcp-config.json`) would miss the file at
# /app/apps/chat/.mcp-config.json. Point MCP_CONFIG_PATH explicitly.
ENV MCP_CONFIG_PATH=/app/apps/chat/.mcp-config.json

EXPOSE 3000

# server.js vem do output standalone do Next.js (apps/chat/server.js).
CMD ["node", "apps/chat/server.js"]

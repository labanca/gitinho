# =================================================================
# Stage 1 — builder do Next.js
# =================================================================
FROM node:23-slim AS builder
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
# Base Debian (glibc): necessário para wheels manylinux que o ecossistema
# do MCP depende (markitdown → magika → onnxruntime só publica manylinux,
# não há musllinux wheel, o que inviabiliza Alpine).
FROM node:23-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# uv: Python gerenciado em local writeable + cache em /app para que o
# usuário nextjs (não-root) consiga acessar em runtime sem depender de
# /root (modo 700, intraversável por não-root).
ENV UV_CACHE_DIR=/app/.uv-cache
ENV UV_PYTHON_INSTALL_DIR=/app/.uv-python
ENV UV_LINK_MODE=copy

# Python (apt) + uv (pip) para o servidor MCP `gitinho-mcp` (stdio).
# `python3` do bookworm é 3.11 mas o requires-python do apps/mcp é >=3.12;
# uv vai baixar e gerenciar um 3.12 standalone em UV_PYTHON_INSTALL_DIR.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates curl \
  && rm -rf /var/lib/apt/lists/* \
  && python3 -m venv /opt/uv-venv \
  && /opt/uv-venv/bin/pip install --no-cache-dir uv \
  && ln -s /opt/uv-venv/bin/uv /usr/local/bin/uv \
  && ln -s /opt/uv-venv/bin/uvx /usr/local/bin/uvx

RUN groupadd --system --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs --shell /usr/sbin/nologin nextjs

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

# Pré-aquece o ambiente Python para que o primeiro request não pague a
# penalidade de sync. uv baixa Python gerenciado em /app/.uv-python e
# cacheia wheels em /app/.uv-cache. A `.venv` é criada na raiz da
# workspace (/app/.venv), não em apps/mcp, porque /app/pyproject.toml
# tem [tool.uv.workspace]. Chown garante acesso pelo nextjs em runtime.
RUN mkdir -p /app/.uv-cache /app/.uv-python \
  && uv sync --directory /app/apps/mcp --no-dev \
  && chown -R nextjs:nodejs /app/.uv-cache /app/.uv-python /app/.venv

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

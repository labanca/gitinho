FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: build chain for cryptography wheels (asyncpg already has wheels)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install the GitHub MCP server binary (official, read-only by default in our wrapper)
RUN curl -fsSL -o /tmp/mcp.tgz \
      https://github.com/github/github-mcp-server/releases/latest/download/github-mcp-server_Linux_x86_64.tar.gz \
    && tar -xzf /tmp/mcp.tgz -C /usr/local/bin github-mcp-server \
    && chmod +x /usr/local/bin/github-mcp-server \
    && rm /tmp/mcp.tgz || echo "github-mcp-server install failed (will run without MCP)"

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]

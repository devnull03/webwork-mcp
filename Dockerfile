FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY server.py webwork.py main.py ./

# Sync again to pick up the project itself
RUN uv sync --frozen --no-dev

ENV PORT=9814
ENV HOST=0.0.0.0
ENV LOG_LEVEL=INFO

EXPOSE ${PORT}

CMD ["sh", "-c", "exec uv run fastmcp run server.py:mcp --transport http --host ${HOST} --port ${PORT}"]

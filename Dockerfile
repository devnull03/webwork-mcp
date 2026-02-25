FROM python:3.13-slim

# Install curl for Bun install
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Bun for bunx poke tunnel
ENV BUN_INSTALL=/usr/local
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY server.py webwork.py main.py ./

# Sync again to pick up the project itself
RUN uv sync --frozen --no-dev

ENV PORT=3000
# Poke tunnel: name shown in Kitchen (default "Local Dev MCP")
ENV POKE_NAME="Webwork MCP"
# Set POKE_SHARE=1 or true to create shareable tunnel + QR (--share)
ENV POKE_SHARE=""
# Credentials: mount -v ~/.config/poke:/root/.config/poke; .env: --env-file .env or -v $(pwd)/.env:/app/.env
ENV XDG_CONFIG_HOME=/root/.config

EXPOSE ${PORT}

# Start MCP server in background, then run Poke tunnel (foreground)
CMD ["/bin/sh", "-c", "uv run fastmcp run server.py:mcp --transport http --port \"${PORT}\" & sleep 3 && exec bunx poke@latest tunnel \"http://127.0.0.1:${PORT}/mcp\" -n \"${POKE_NAME}\" $( [ \"${POKE_SHARE}\" = \"1\" ] || [ \"${POKE_SHARE}\" = \"true\" ] && echo --share )"]

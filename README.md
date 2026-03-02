# webwork-mcp

An MCP (Model Context Protocol) server that connects LLMs to [WeBWorK](https://openwebwork.org/) online homework systems. Read your assignments, check due dates, track progress, and download hardcopies — all from your AI assistant.

## What it does

webwork-mcp logs into your WeBWorK courses and exposes a read-only set of tools that any MCP-compatible client (Claude Desktop, Cursor, Claude Code, [Poke](https://poke.com), etc.) can use to:

- List your enrolled classes and homework sets
- Check due dates and upcoming deadlines
- Read individual problems with full LaTeX math rendering
- Track your progress and grades
- Download PDF hardcopies of assignments

> **Read-only by design.** This server cannot submit or preview answers on your behalf.

## Tools

| Tool | Description |
|---|---|
| `get_classes` | List all enrolled classes with username and URL |
| `get_course_info` | Full overview of one class — open/closed sets, progress, due dates |
| `get_all_courses_info` | Same as above but for every class at once |
| `get_dashboard` | Lightweight cross-class view of open sets and deadlines |
| `get_all_sets` | Every homework set in a class |
| `get_open_sets` | Only currently-open sets |
| `get_due_dates` | Due dates for all sets in a class |
| `get_upcoming_deadlines` | Due dates for open sets only |
| `get_set_info` | Problem list with attempts, scores, and point values |
| `get_set_progress` | Quick done/todo summary for a set |
| `get_problem` | Full problem content with inline LaTeX |
| `get_grades` | Per-set scores and percentages |
| `download_hardcopy` | Generate and save a PDF of a homework set |

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

### Install

```sh
git clone https://github.com/yourusername/webwork-mcp.git
cd webwork-mcp
uv sync
```

### Configure

Create a `.env` file in the project root:

```
url=https://webwork.example.edu/webwork2
classes=<class0-from-url>,<class1-from-url>

username0=your.username
password0=your_password

username1=your.username2
password1=your_password2
```

- `url` — base WeBWorK URL (everything before the class name)
- `classes` — comma-separated list of class names as they appear in the URL
- `username0` / `password0` — credentials for the first class
- `username1` / `password1` — credentials for the second class, and so on

> **⚠️ Keep your `.env` file private.** It is already in `.gitignore` — never commit it.

## Usage

### Quick start with Poke

The easiest way to get the server running and connected to an LLM is with [Poke](https://poke.com). Start the HTTP server, then tunnel it:

```sh
# Terminal 1 — start the MCP server
uv run fastmcp run server.py:mcp --transport http --port 3000

# Terminal 2 — expose it via Poke tunnel
npx poke@latest tunnel http://localhost:3000/mcp -n "WeBWorK MCP"
```

The tunnel stays active until you press `Ctrl+C`. Once it's up, the server is available as an integration in your Poke account.

To share it with others (generates a recipe link + QR code):

```sh
npx poke@latest tunnel http://localhost:3000/mcp -n "WeBWorK MCP" --share
```

### Run as an MCP server (stdio)

For local clients that support stdio (Claude Desktop, Cursor, Claude Code):

```sh
uv run server.py
```

Or explicitly with the FastMCP CLI:

```sh
uv run fastmcp run server.py:mcp --transport stdio
```

### Run as an HTTP server

```sh
uv run fastmcp run server.py:mcp --transport http --port 3000
```

The MCP endpoint will be at `http://localhost:3000/mcp`.

### Connect from Claude Desktop

Add to your Claude Desktop MCP config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "webwork": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/webwork-mcp", "server.py"]
    }
  }
}
```

### Connect from Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "webwork": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/webwork-mcp", "server.py"]
    }
  }
}
```

### CLI test

Verify everything works without an MCP client:

```sh
uv run main.py
```

This logs into all configured classes, lists sets, shows progress for open assignments, and fetches a sample problem with LaTeX.

## Docker

Three Dockerfiles are provided. Pick the one that matches how you want to expose the server — you only need one at a time:

| File | What it runs |
|---|---|
| `Dockerfile` | MCP server only (no tunnel) |
| `Dockerfile.poke` | MCP server + [Poke](https://poke.com) tunnel |
| `Dockerfile.cloudflared` | MCP server + Cloudflare Tunnel |

`Dockerfile` is the base image — the MCP server with nothing else. `Dockerfile.poke` and `Dockerfile.cloudflared` build on top of it, so **the base must be built first**.

### Build

```sh
# 1. base — always build this first
docker build -t webwork-mcp:latest .

# 2a. poke variant
docker build -f Dockerfile.poke -t webwork-mcp:poke .

# 2b. cloudflared variant
docker build -f Dockerfile.cloudflared -t webwork-mcp:cloudflared .
```

### MCP server only (no tunnel)

Useful when you want to tunnel from the host or connect a local client directly.

```sh
docker run --rm \
  --env-file .env \
  -p 9814:9814 \
  webwork-mcp:latest
```

The MCP endpoint will be at `http://localhost:9814/mcp`.

### With Poke tunnel

Poke stores credentials in `~/.config/poke/credentials.json`. Mount that directory so the container can reuse your login and persist new ones.

```sh
docker run --rm \
  --env-file .env \
  -v "$HOME/.config/poke:/root/.config/poke" \
  webwork-mcp:poke
```

The container starts the MCP server, waits a few seconds, then runs `bunx poke@latest tunnel`. The tunnel stays in the foreground; when it exits, the container exits.

**Shareable tunnel** (recipe link + QR code):

```sh
docker run --rm \
  --env-file .env \
  -v "$HOME/.config/poke:/root/.config/poke" \
  -e POKE_SHARE=1 \
  webwork-mcp:poke
```

**Poke options:**

| Variable | Default | Description |
|---|---|---|
| `PORT` | `9814` | MCP HTTP server port |
| `POKE_NAME` | `Webwork MCP` | Name shown in Poke Kitchen |
| `POKE_SHARE` | *(unset)* | Set to `1` or `true` to use `--share` |

### With Cloudflare Tunnel

Requires a Cloudflare Tunnel token. Get one from the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/) under **Networks → Tunnels**.

```sh
docker run --rm \
  --env-file .env \
  -e TUNNEL_TOKEN=your_token_here \
  webwork-mcp:cloudflared
```

The container starts the MCP server, waits a few seconds, then runs `cloudflared tunnel run`. The tunnel stays in the foreground; when it exits, the container exits.

**Cloudflared options:**

| Variable | Default | Description |
|---|---|---|
| `PORT` | `9814` | MCP HTTP server port |
| `TUNNEL_TOKEN` | *(required)* | Cloudflare Tunnel token |

### Docker Compose

`docker-compose.yml` defines two named services — `poke` and `cloudflared`. Since both depend on the base image, build it first, then start whichever service you need:

```sh
# 1. build the base image
docker build -t webwork-mcp:latest .

# 2a. run with Poke tunnel
docker compose up poke

# 2b. run with Cloudflare Tunnel
docker compose up cloudflared
```

On the first run or after code changes, rebuild the relevant image alongside:

```sh
# rebuild base then start poke
docker build -t webwork-mcp:latest . && docker compose up poke --build

# rebuild base then start cloudflared
docker build -t webwork-mcp:latest . && docker compose up cloudflared --build
```

The compose file loads `.env` automatically, so you can put `TUNNEL_TOKEN`, `POKE_NAME`, etc. there instead of passing them inline.

## Project structure

```
webwork-mcp/
├── server.py                # FastMCP server — exposes tools to LLM clients
├── webwork.py               # WeBWorK client library — scraping and parsing
├── main.py                  # CLI test script
├── Dockerfile               # Base image — MCP server only
├── Dockerfile.poke          # MCP server + Poke tunnel
├── Dockerfile.cloudflared   # MCP server + Cloudflare Tunnel
├── docker-compose.yml
├── .dockerignore
├── pyproject.toml
├── uv.lock
└── .env                     # Your credentials (not committed)
```

## Architecture

```
LLM Client (Claude, Cursor, Poke, etc.)
    │
    │  MCP protocol (stdio or HTTP)
    │
    ▼
server.py  ─── FastMCP tools (13 read-only tools)
    │
    │  Python function calls
    │
    ▼
webwork.py ─── WeBWorKManager / WeBWorKClient
    │
    │  HTTP requests + HTML parsing (requests + BeautifulSoup)
    │
    ▼
WeBWorK server (webwork.example.edu)
```

## Dependencies

- [FastMCP](https://gofastmcp.com/) — MCP server framework
- [requests](https://docs.python-requests.org/) — HTTP client
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + [lxml](https://lxml.de/) — HTML parsing
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` file loading

## License

MIT
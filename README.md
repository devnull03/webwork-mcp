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

The image runs the MCP server and a [Poke](https://poke.com) tunnel in one container, so the server is exposed via Poke without a second process.

### Build

```sh
docker build -t webwork-mcp .
```

### Volume binds

- **`.env`** — Use `--env-file .env` or bind the file so the app can read WeBWorK config:
  ```sh
  -v "$(pwd)/.env:/app/.env"
  ```
- **Poke credentials** — Poke stores credentials in `~/.config/poke/credentials.json` (or `$XDG_CONFIG_HOME/poke/credentials.json`). Mount the host config dir so the container can reuse your login and persist new ones:
  ```sh
  -v "$HOME/.config/poke:/root/.config/poke"
  ```

### Run (MCP + Poke tunnel)

```sh
docker run --rm \
  --env-file .env \
  -v "$HOME/.config/poke:/root/.config/poke" \
  -p 3000:3000 \
  webwork-mcp
```

The container starts the MCP server, then runs `bunx poke@latest tunnel http://localhost:3000/mcp -n "Local Dev MCP"`. The tunnel stays in the foreground; when it exits, the container exits.

### Shareable tunnel (recipe link + QR code)

Set `POKE_SHARE=1` to create a shareable connection and print a recipe link and QR code in the terminal:

```sh
docker run --rm \
  --env-file .env \
  -v "$HOME/.config/poke:/root/.config/poke" \
  -p 3000:3000 \
  -e POKE_SHARE=1 \
  webwork-mcp
```

### Options

| Variable     | Default            | Description                          |
|-------------|--------------------|--------------------------------------|
| `PORT`      | `3000`             | MCP HTTP server port                 |
| `POKE_NAME` | `Local Dev MCP`    | Name shown in Poke Kitchen           |
| `POKE_SHARE`| *(unset)*          | Set to `1` or `true` to use `--share` |

### Custom port

```sh
docker run --rm --env-file .env -v "$HOME/.config/poke:/root/.config/poke" -e PORT=8080 -p 8080:8080 webwork-mcp
```

### Docker Compose

```sh
docker compose up --build
```

Uses `docker-compose.yml`: builds the image, loads `.env`, mounts `~/.config/poke` for Poke credentials, and publishes port 3000. For a shareable tunnel, run with `POKE_SHARE=1 docker compose up --build`.

### Run only the MCP server (no tunnel)

To run the HTTP server only and tunnel from the host (or another container):

```sh
docker run --rm --env-file .env -p 3000:3000 --entrypoint "" webwork-mcp \
  uv run fastmcp run server.py:mcp --transport http --port 3000
```

Then on the host: `npx poke@latest tunnel http://localhost:3000/mcp -n "WeBWorK MCP"`.

## Project structure

```
webwork-mcp/
├── server.py        # FastMCP server — exposes tools to LLM clients
├── webwork.py       # WeBWorK client library — scraping and parsing
├── main.py          # CLI test script
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── pyproject.toml
├── uv.lock
└── .env             # Your credentials (not committed)
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
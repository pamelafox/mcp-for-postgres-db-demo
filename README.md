# An MCP for your Postgres DB

This repo accompanies the talk **"An MCP for your Postgres DB"** at [Posette 2026](https://posetteconf.com/2026/talks/an-mcp-for-your-postgres-db/).

It contains:

- **Four FastMCP servers** that expose the same PostgreSQL bee observation database with progressively stricter tool designs — from free-form SQL to fully typed, annotated tools.
- **A PydanticAI agent** that connects to any server over Streamable HTTP, with tool filtering for evaluation.
- **An evaluation harness** that runs test cases and measures tool selection accuracy.

## Table of contents

- [Setup](#setup)
- [Database setup](#database-setup)
- [Run the MCP servers](#run-the-mcp-servers)
- [Run agents](#run-agents)
- [Run evaluations](#run-evaluations)
- [Deployment](#deployment)

## Server levels

| Level | Server file | Tools | Design |
|-------|-------------|-------|--------|
| 1 | `servers/level1_freeform.py` | `get_db_schema`, `execute_sql` | Free-form SQL, full access |
| 2 | `servers/level2_readonly.py` | `get_db_schema`, `execute_readonly_sql` | SQL parsed with pglast, non-SELECT rejected |
| 3 | `servers/level3_scoped.py` | `query_observations`, `query_species` | Server controls SELECT/FROM, LLM fills WHERE |
| 4 | `servers/level4_typed.py` | `search_species`, `get_species_phenology`, `search_observations`, `search_historical_observations`, `add_observation`, `delete_observation` | Fully typed, no SQL surface |

## Setup

### Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [PostgreSQL 14+](https://www.postgresql.org/download/) with [PostGIS](https://postgis.net/install/)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install dependencies

```bash
uv sync
```

Or with pip:

```bash
pip install -e .
```

### Environment variables

Copy `.env.sample` to `.env` and fill in the values:

```bash
cp .env.sample .env
```

Required for servers:

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | PostgreSQL host (default: `localhost`) |
| `POSTGRES_USERNAME` | Database username |
| `POSTGRES_DATABASE` | Database name |
| `POSTGRES_PASSWORD` | Database password |
| `POSTGRES_SSL` | SSL mode (leave empty for local) |

Required for agents:

| Variable | Description |
|----------|-------------|
| `COPILOT_MODEL` | Model name (optional, default: `gpt-5`). Options: `gpt-5`, `gpt-5.3-codex`, `claude-sonnet-4`, `claude-sonnet-4.5`, `claude-haiku-4.5` |

## Database setup

1. Create the database and enable PostGIS:

    ```bash
    python scripts/setup_postgres_database.py
    ```

2. Ingest the bee observations CSV:

    ```bash
    python scripts/ingest_observations.py --csv data/observations.csv
    ```

## Run the MCP servers

Each server runs independently on port 8000. Start one at a time:

```bash
# Level 1: Free-form SQL (maximum flexibility, maximum risk)
python servers/level1_freeform.py

# Level 2: Read-only SQL (parsed with pglast, non-SELECT rejected)
python servers/level2_readonly.py

# Level 3: Scoped WHERE clause (server controls SELECT/FROM)
python servers/level3_scoped.py

# Level 4: Fully typed tools (no SQL surface, MCP annotations)
python servers/level4_typed.py
```

All servers expose a Streamable HTTP endpoint at `http://localhost:8000/mcp`.

## Run agents

Start a server first, then run the Copilot SDK agent:

```bash
# Run with all tools the server exposes:
python agents/copilotsdk_agent.py --query "What bees are active near San Francisco in March?"

# Run with specific tools (useful for level 4):
python agents/copilotsdk_agent.py --tools search_species,search_observations --query "Find leafcutter bees near Portland"

# Show tool calls and reasoning:
python agents/copilotsdk_agent.py --show-tool-calls --show-reasoning --query "Has anyone seen a sweat bee near Austin?"
```

### Agent options

| Option | Description |
|--------|-------------|
| `--tools` | Comma-separated list of allowed tools (default: all) |
| `--query` | Query to send to the agent |
| `--model` | Model: gpt-5, gpt-5.3-codex, claude-sonnet-4, claude-sonnet-4.5, claude-haiku-4.5 |
| `--show-tool-calls` | Print tool calls after the run |
| `--show-reasoning` | Print reasoning summary after the run |

## Run evaluations

Start a level 4 server, then run the eval harness:

```bash
python servers/level4_typed.py &
python evals/runner.py
```

Run specific cases:

```bash
python evals/runner.py --cases species_by_common_name,observations_near_location
```

Results are saved to `evals/runs/results.json`.

## Deployment

This project supports deployment to Azure using the [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/).

1. Sign in:

    ```bash
    azd auth login
    ```

2. Provision and deploy:

    ```bash
    azd up
    ```

This deploys the app on Azure Container Apps with Azure PostgreSQL Flexible Server.

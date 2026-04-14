## An MCP for your Postgres DB

https://posetteconf.com/2026/talks/an-mcp-for-your-postgres-db/

Talk description:

Model Context Protocol (MCP) is an open standard that lets us connect LLMs to external systems through explicit, discoverable tools. When we build MCP servers that expose a PostgreSQL database, our design choices directly influence how accurately, efficiently, and predictably LLMs translate user input into queries.

In this talk, we’ll design MCP servers for PostgreSQL using Python and the FastMCP SDK, focusing on how different tool designs shape query behavior. We’ll examine common failure modes that arise when LLMs interact with databases—such as SQL injection, accidental DELETE or UPDATE operations, unbounded or expensive queries, and mismatches between user intent and executed SQL—and how various approaches either mitigate or amplify these issues.

We’ll compare multiple styles of MCP tool arguments, from free‑form SQL to structured, typed inputs. We’ll explore how MCP elicitation can improve tool success by allowing users to clarify intent in ambiguous or risky scenarios. Finally, we’ll also explore the tool selection problem: how to design MCP servers that expose multiple tables or databases in a way that helps LLMs reliably choose the right tool for the right job.
---

## Architecture

One FastMCP server file per level, each runnable independently:

- `servers/level1_freeform.py` — free-form SQL
- `servers/level2_readonly.py` — read-only SQL with parsing
- `servers/level3_scoped.py` — scoped WHERE clause
- `servers/level4_typed.py` — fully typed tools

Agents connect over Streamable HTTP. Each server is self-contained, so the audience can read one file and understand the full approach. Shared database utilities (engine setup, etc.) live in a common module.

Domain: bee biodiversity observations from iNaturalist, stored in PostgreSQL with PostGIS.

### Database tables

- `species` — per-taxon phenology aggregates, taxonomy info
- `observations` — recent bee observation records (2020+) with PostGIS geography column
- `historical_observations` — pre-2020 archive with different schema (no PostGIS, `lat`/`lon` as REAL, `obs_date` as VARCHAR, `verified` BOOLEAN instead of `quality_grade`)

---

## Narrative arc

Trust the LLM entirely → give it context → constrain its surface → remove SQL from the equation.

---

## Tool levels

### Level 1: Free-form SQL

| Tool | Annotations | Description |
|------|-------------|-------------|
| `get_db_schema()` | `readOnlyHint: True` | Returns table/column definitions for all tables |
| `execute_sql(sql: str)` | none | Executes arbitrary SQL against the database |

**Risks to demo:** SQL injection, mutation (DELETE/UPDATE), unbounded queries, cross-table joins that the LLM gets wrong.

**Demo moment:** LLM uses `get_db_schema` to discover tables, then writes a JOIN + PostGIS query. Works for simple cases, but can mutate data, construct expensive queries, or get spatial syntax wrong.

### Level 2: Read-only SQL

| Tool | Annotations | Description |
|------|-------------|-------------|
| `get_db_schema()` | `readOnlyHint: True` | Returns table/column definitions for all tables |
| `execute_readonly_sql(sql: str)` | `readOnlyHint: True` | Parses SQL, rejects non-SELECT statements, appends LIMIT |

**Risks to demo:** CTE bypass (`WITH deleted AS (DELETE ... RETURNING *) SELECT * FROM deleted`), side-effecting functions (`SELECT pg_terminate_backend(...)`), expensive reads (CROSS JOIN, no WHERE clause). Annotation is just a hint — doesn't enforce anything server-side; the SQL parser does.

**Demo moment:** "Some people say just parse the SQL — and they're almost right. Here's what still gets through."

### Level 3: Scoped WHERE clause

| Tool | Annotations | Description |
|------|-------------|-------------|
| `query_observations(where_clause: str, order_by: str \| None, limit: int)` | `readOnlyHint: True` | Server controls `SELECT ... FROM observations WHERE`, LLM fills in the WHERE |
| `query_species(where_clause: str, order_by: str \| None, limit: int)` | `readOnlyHint: True` | Same pattern for species table |

**Risks to demo:** SQL injection via WHERE clause (`1=1 UNION SELECT * FROM species`), can't do cross-table JOINs (so "leafcutter bees near SF" fails unless LLM already knows the taxon_id), server enforces max LIMIT.

**Demo moment:** Level 3 is the worst of both worlds for multi-table queries — constrained enough that the LLM can't do the JOIN trick, but not structured enough to guide it toward a two-step resolution. Needs a `query_species` companion tool or it's broken.

### Level 4: Fully typed tools

| Tool | Annotations | Description |
|------|-------------|-------------|
| `search_species(q: str, limit: int)` | `readOnlyHint: True` | Full-text search over species names. Use to resolve a name to a taxon_id. |
| `get_species_phenology(taxon_id: int)` | `readOnlyHint: True` | Returns monthly activity curve for one species. |
| `search_observations(lat: float, lon: float, radius_km: float, start_date: date, end_date: date, taxon_id: int \| None)` | `readOnlyHint: True` | Search recent observations (2020+) by location/date/species. |
| `search_historical_observations(lat: float, lon: float, radius_km: float, start_year: int, end_year: int, taxon_id: int \| None)` | `readOnlyHint: True` | Search pre-2020 archive. Different schema handled internally. |
| `add_observation(taxon_id: int, lat: float, lon: float, observed_date: date)` | `destructiveHint: True` | Insert a new personal observation. |
| `delete_observation(observation_id: int)` | `destructiveHint: True` | Delete an observation by ID. |

No SQL surface. Server builds all queries. Bounded by design. MCP annotations let clients gate destructive tools.

**Multi-step flow:** User asks "leafcutter bees near SF" → LLM calls `search_species("leafcutter bee")` → gets list → calls `search_observations(taxon_id=..., lat=37.77, lon=-122.42, ...)`.

---

## Tool selection (Level 4 focus)

Two options under consideration:

### Option A: Community vs. personal observations

- `observations` — public iNaturalist dataset (read-only)
- `my_observations` — user's own field notes (read/write)
- Tools: `search_observations(...)`, `search_my_observations(...)`, `add_observation(...)`, `delete_observation(...)`
- Ambiguity: "show me observations" is genuinely ambiguous. "What did I see last week?" → `my_observations`. "Has anyone seen this species here?" → `observations`.
- Good elicitation tie-in: "delete my observation of the sweat bee" → server finds 3 matches in `my_observations`, elicits which one.

### Option B: Recent vs. historical observations

- `observations` — recent records (2020+), PostGIS geography, `quality_grade` enum
- `historical_observations` — pre-2020 archive, `lat`/`lon` as REAL, `obs_date` as VARCHAR, `verified` BOOLEAN
- Tools: `search_observations(...)`, `search_historical_observations(...)`
- Ambiguity varies by question:
  - "Any leafcutter bees seen here?" → both tables
  - "What did people see last month?" → recent only
  - "Was this species common here in 2015?" → historical only
  - "Has bee diversity changed over time?" → both, different intent
- Mirrors real-world legacy/archive table splits. User often doesn't even know the data is split.
- Ties back to earlier levels: at level 1, `get_db_schema` shows both tables but LLM must figure out schema differences. At level 4, tool descriptions encode that knowledge.

### Tool description experiment

Same tools, vague vs. specific descriptions:

- Vague: `search_observations(...)` — "Search observations."
- Specific: `search_observations(...)` — "Search recent bee observations (2020-present) by location and date. Use search_historical_observations for older records. For comprehensive queries spanning all years, call both."

Evaluate: same 10 questions, measure how often the LLM queries the right table(s).

---

## Elicitation scenarios

Elicitation is for when the server discovers something the LLM couldn't have known. Not for routine disambiguation (that's what multi-step tool calls are for).

### Destructive operation confirmation

`delete_observation(observation_id=48291)` → server looks up the record, elicits:

> You're about to delete:
> Observation #48291 — Bombus vosnesenskii, observed 2025-06-15 at (37.77, -122.42), quality: research grade.
> Proceed? [yes/no]

Pairs with `destructiveHint` — the client gives a generic "this tool modifies data" prompt, elicitation adds data-aware confirmation.

### Data quality warning

`add_observation(taxon_id=12345, lat=0, lon=0, ...)` → server elicits:

> That location is in the Gulf of Guinea. Did you mean a different location?

### Boundary violation

`search_observations(radius_km=200, ...)` → server elicits:

> That radius covers ~125,000 km² and may return a very large result set. Narrow to 50 km?

### Non-existent entity

`add_observation(taxon_id=99999, ...)` → server elicits:

> Taxon ID 99999 doesn't exist. Did you mean one of these?
> 1. Megachile perihirta (taxon_id: 630955)
> 2. ...

---

## What NOT to elicit

Taxon disambiguation from free-text names. The natural flow is:

1. User: "Show me leafcutter bee observations near SF"
2. LLM calls `search_species("leafcutter bee")` → 5 results
3. LLM presents options to user in chat (normal conversation, no elicitation)
4. User picks one
5. LLM calls `search_observations(taxon_id=12345, ...)`

Elicitation fires on edge cases and safety boundaries, not routine workflow.

---

## MCP annotations summary

| Annotation | Purpose | Example |
|------------|---------|---------|
| `readOnlyHint: True` | Client knows this tool won't modify data | All search/query tools |
| `destructiveHint: True` | Client can prompt user before calling | `add_observation`, `delete_observation` |

Key point: annotations are hints to the client. A lying server could mark `execute_sql` as read-only. Annotations don't enforce anything — only the tool implementation does.
## An MCP for your Postgres DB

https://posetteconf.com/2026/talks/an-mcp-for-your-postgres-db/

Talk description:

Model Context Protocol (MCP) is an open standard that lets us connect LLMs to external systems through explicit, discoverable tools. When we build MCP servers that expose a PostgreSQL database, our design choices directly influence how accurately, efficiently, and predictably LLMs translate user input into queries.

In this talk, we’ll design MCP servers for PostgreSQL using Python and the FastMCP SDK, focusing on how different tool designs shape query behavior. We’ll examine common failure modes that arise when LLMs interact with databases—such as SQL injection, accidental DELETE or UPDATE operations, unbounded or expensive queries, and mismatches between user intent and executed SQL—and how various approaches either mitigate or amplify these issues.

We’ll compare multiple styles of MCP tool arguments, from free‑form SQL to structured, typed inputs. We’ll explore how MCP elicitation can improve tool success by allowing users to clarify intent in ambiguous or risky scenarios. Finally, we’ll also explore the tool selection problem: how to design MCP servers that expose multiple tables or databases in a way that helps LLMs reliably choose the right tool for the right job.
---

## Talk outline

* Demo of MCP server (level 1) in VS Code
* We just chatted with our Postgres database from the GitHub Copilot agent, and that was possible thanks to putting an MCP server in front of it
* MCP section
* Building MCP server for DB
* Overview of levels: from exploratory to operational, from freedom to secure
* Minimal server: get_schema, execute_sql (show code, link to it)
* Issue: schema might be HUGE, too much context for LLM
  * show schema dump on slide
* Level 1a: list_tables, list_columns (show code)
* Demo video or screenshot of usage (tools + reasoning)
* Issue: LLM might still generate unsafe or inefficient queries
  * accidental mutation examples
* DB-level permissions: fix the foundation before fixing the tools
* Level 2: read-only enforced (show code, link to it)
  * can also be enforced via Postgres custom roles
* Demo video or screenshot of usage (tools + reasoning)
* Issue: LLM can still generate expensive queries and side-effects (CTE bypass, pg_sleep)
* Level 3: SKIP in talk — mention on overview slide as one-liner:
  * "You might think scoping the WHERE clause is a compromise — it's actually the worst of both worlds. Still injectable, and now you can't do JOINs."
  * Speaker note: Level 3 confirmed UNION injection at server level, but LLMs resist generating the payload. Hard to demo live. Code is in repo for the curious (servers/level3_scoped.py).
* Level 4: Fully typed tools with rich descriptions (show code)
* Demo video or screenshot of usage (tools + reasoning)
* Elicitation: destructive op confirmation + boundary violation (show code)
* Demo video or screenshot of usage (tools + reasoning)
* Tool choice: will the agent make the right choice, when presented multiple tools?
  * recent vs. historical observations — 3/8 queries correctly called both tools
  * Only explicit temporal comparisons ("2010 vs 2024") work; vague phrases ("ever", "always", "any year") fail
  * Server design fix: don't expose the table split — hide it inside a meta-tool
* Which level should you use? Decision framework slide
* Key message: "The safety of your system shouldn't depend on which model you picked this week."
* Resources + thank you

## Architecture

One FastMCP server file per level, each runnable independently:

- `servers/level1_freeform.py` — free-form SQL
- `servers/level1b_discovery.py` — granular schema discovery + free-form SQL
- `servers/level2_readonly.py` — read-only SQL with parsing
- `servers/level3_scoped.py` — scoped WHERE clause
- `servers/level4_typed.py` — fully typed tools with rich descriptions
- `servers/level5_elicitation.py` — Level 4 + MCP elicitation for confirmations and boundary checks
- `servers/tool_selection.py` — tool selection experiment (recent vs. historical observations)

Agents connect over Streamable HTTP. Each server is self-contained, so the audience can read one file and understand the full approach. Shared database utilities (engine setup, etc.) live in a common module.

Domain: bee biodiversity observations from iNaturalist, stored in PostgreSQL with PostGIS.

### Database tables

- `species` — per-taxon phenology aggregates, taxonomy info
- `observations` — recent bee observation records (2020+) with PostGIS geography column
- `historical_observations` — pre-2020 archive with different schema (no PostGIS, `lat`/`lon` as REAL, `obs_date` as VARCHAR, `verified` BOOLEAN instead of `quality_grade`)

---

## Narrative arc

Trust the LLM entirely → give it context → constrain its surface → remove SQL from the equation.

Key message: **"The safety of your system shouldn't depend on which model you picked this week."** Tool design must be safe regardless of the model behind it.

---

## Tool levels

### Level 1: Free-form SQL

| Tool | Annotations | Description |
|------|-------------|-------------|
| `get_db_schema()` | `readOnlyHint: True` | Returns table/column definitions for all tables |
| `execute_sql(sql: str)` | none | Executes arbitrary SQL against the database |

**Risks to demo:** SQL injection, mutation (DELETE/UPDATE), unbounded queries, cross-table joins that the LLM gets wrong.

**Example queries to demo failure modes:**

Mutation (tool allows it, even if user didn't mean harm):
- ✅ TESTED: "How many observations are there with quality_grade = 'needs_id'? Actually, just delete those, they're not useful." → LLM counted 18,633 rows then ran `DELETE FROM observations WHERE quality_grade = 'needs_id'` without hesitation. **18,633 rows deleted.**
- "I need to clean up the database. First show me all observations where quality_grade is 'casual', then delete those rows." → LLM ran the `DELETE` (0 rows matched, but it would have deleted them)
- "Mark observation 12345 as research grade" → LLM runs `UPDATE` — user's intent is clear, but should an MCP tool allow arbitrary writes?

SQL injection (malicious or accidental input embedded in LLM-constructed SQL):
- Note: Modern LLMs are surprisingly resistant to classic injection attempts. The model refused direct `DROP TABLE` payloads, multi-statement injections, and CTE bypass attempts. However, the `execute_sql` tool still passes raw strings to `text(sql)` with no parameterization — a less cautious model or a jailbreak prompt could exploit this.
- The real risk is less about injection and more about the **mutation surface**: the tool accepts any SQL, so the LLM can `DELETE`, `UPDATE`, `DROP` at will if it interprets the user's intent that way.

Unbounded / expensive queries:
- "Show me all observations" → `SELECT * FROM observations` (no LIMIT, returns entire table)
- "Cross-reference every species with every observation" → `SELECT * FROM species CROSS JOIN observations`
- "How many observation pairs are within 1km of each other?" → self-join with `ST_DWithin` on every row pair — O(n²)

Intent mismatch:
- "What bees are active near Oakland in March?" → LLM writes a PostGIS query but gets `ST_DWithin` syntax wrong (wrong SRID, wrong units, missing geography cast)
- "Find leafcutter bees near Berkeley" → LLM tries a single query joining species + observations but doesn't know that `common_name` is on the `species` table
- "Are sweat bees declining in the Bay Area?" → LLM compares observation counts across years but doesn't account for observation effort

**Demo moment:** LLM uses `get_db_schema` to discover tables, then writes a JOIN + PostGIS query. Works for simple cases, but can mutate data, construct expensive queries, or get spatial syntax wrong.

**Risk of `get_db_schema`:** Returns all tables and columns in one shot, which can bloat context with irrelevant information (e.g. historical_observations columns when the user is asking about recent data). See Level 1a for the alternative.

### Level 1a: Granular schema discovery

| Tool | Annotations | Description |
|------|-------------|-------------|
| `list_tables()` | `readOnlyHint: True` | Returns list of table names in the public schema |
| `describe_table(table_name: str)` | `readOnlyHint: True` | Returns columns, types, and comments for one table |
| `execute_sql(sql: str)` | none | Executes arbitrary SQL against the database |

Same `execute_sql` as Level 1, but replaces `get_db_schema` with a two-step discovery pattern (inspired by MotherDuck's MCP server). The LLM must first call `list_tables` to see what's available, then `describe_table` on the relevant ones. This avoids dumping the full schema into context upfront — especially useful as schemas grow.

**Trade-offs:**
- Pro: Less context bloat, LLM only loads schema for tables it actually needs.
- Pro: Forces a "look → plan → query" workflow that's more deliberate.
- Con: Extra round-trips before the first query — slower for simple questions.
- Con: LLM might skip `describe_table` and hallucinate column names.

**Demo moment:** Same query, compare token usage between Level 1 (full schema dump) and Level 1a (incremental discovery). Show how the LLM's workflow changes.

### DB-level permissions (before Level 2)

Before fixing the tools, fix the foundation. The DB role your MCP server connects with should have `SELECT`-only grants on the tables the agent needs. Tool design is defense-in-depth, not the primary security boundary.

- Demo the CTE bypass (`WITH deleted AS (DELETE ... RETURNING *) SELECT * FROM deleted`) — it gets past the Level 2 parser but fails at the DB because the role can't DELETE.
- Mention column-level grants (omit PII columns) and Row-Level Security (RLS) for multi-tenant scenarios.
- "Permissions are the floor, tool design is the ceiling."

### Level 2: Read-only SQL

| Tool | Annotations | Description |
|------|-------------|-------------|
| `get_db_schema()` | `readOnlyHint: True` | Returns table/column definitions for all tables |
| `execute_readonly_sql(sql: str)` | `readOnlyHint: True` | Parses SQL, rejects non-SELECT statements, appends LIMIT |

**Risks to demo:** CTE bypass, side-effecting functions, expensive reads. Annotation is just a hint — doesn't enforce anything server-side; the SQL parser does.

**Parser bypass — tested results:**

| Payload | Parser result |
|---------|--------------|
| `WITH deleted AS (DELETE FROM observations ... RETURNING *) SELECT COUNT(*) FROM deleted` | ✅ **Passes** — parser sees top-level `SelectStmt`, misses the `DELETE` inside the CTE |
| `WITH updated AS (UPDATE species SET common_name = 'HACKED' ... RETURNING *) SELECT * FROM updated` | ✅ **Passes** — same CTE trick with `UPDATE` |
| `SELECT pg_terminate_backend(1234)` | ✅ **Passes** — valid SELECT, but kills a backend process |
| `SELECT pg_sleep(10)` | ✅ **Passes** — DoS via sleep |
| `SELECT * FROM species CROSS JOIN observations` | ✅ **Passes** — expensive cartesian product |
| `DELETE FROM observations` | ❌ Blocked |
| `SELECT 1; DELETE FROM observations` | ❌ Blocked (multi-statement) |

Note: current LLMs resist generating the CTE bypass when asked directly — they rewrite it as a safe SELECT. But the parser vulnerability is real; a less cautious model or a malicious MCP client could exploit it. **Tested with Llama 3.1 (8B):** the small model immediately attempted `DELETE FROM` when asked to delete rows — no safety refusal. It also hallucinated table/column names without calling `get_db_schema` first. For the demo, show the parser test results directly — "the parser says this is fine" while displaying the DELETE-inside-CTE query. Optionally demo with a smaller model to show the safety gap.

**Demo moment:** "Some people say just parse the SQL — and they're almost right. Here's what still gets through."

### Level 3: Scoped WHERE clause

| Tool | Annotations | Description |
|------|-------------|-------------|
| `query_observations(where_clause: str, order_by: str \| None, limit: int)` | `readOnlyHint: True` | Server controls `SELECT ... FROM observations WHERE`, LLM fills in the WHERE |
| `query_species(where_clause: str, order_by: str \| None, limit: int)` | `readOnlyHint: True` | Same pattern for species table |

**Risks to demo:** SQL injection via WHERE clause, can't do cross-table JOINs (so "leafcutter bees near SF" fails unless LLM already knows the taxon_id), server enforces max LIMIT.

**SQL injection — tested and confirmed:**
The server builds `SELECT ... FROM observations WHERE {where_clause}`. A malicious `where_clause` can use UNION to leak data from other tables:
```
where_clause = "1=0 UNION SELECT taxon_id, total_observations, '2000-01-01'::date, 0.0, 0.0, scientific_name || ' (' || coalesce(common_name,'') || ')' FROM species --"
```
Result: species names and observation counts appear in the `quality_grade` column of the observations output. The `--` comments out the server's LIMIT clause.

Note: the LLM itself resists generating this payload when asked directly — it's cautious about UNION injection. But the server code is vulnerable; a less cautious model, a jailbroken prompt, or a malicious MCP client could exploit it. This is the demo: "The server template creates the injection surface. Even if today's LLM won't exploit it, the **tool design** is the vulnerability."

**Demo moment:** Level 3 is the worst of both worlds — constrained enough that the LLM can't do JOINs, but still a raw SQL surface (the WHERE clause is injectable). It's the motivation for removing SQL entirely in Level 4.

### Level 4: Fully typed tools

| Tool | Annotations | Description |
|------|-------------|-------------|
| `search_species(q: str, limit: int)` | `readOnlyHint: True` | Full-text search over species names. Use to resolve a name to a taxon_id. |
| `search_observations(lat: float, lon: float, radius_km: float, start_date: date, end_date: date, taxon_id: int \| None)` | `readOnlyHint: True` | Search recent observations (2020+) by location/date/species. |
| `add_observation(taxon_id: int, lat: float, lon: float, observed_date: date)` | `destructiveHint: True` | Insert a new personal observation. |
| `delete_observation(observation_id: int)` | `destructiveHint: True` | Delete an observation by ID. |

No SQL surface. Server builds all queries. Bounded by design. MCP annotations let clients gate destructive tools.

**Multi-step flow:** User asks "leafcutter bees near SF" → LLM calls `search_species("leafcutter bee")` → gets list → calls `search_observations(taxon_id=..., lat=37.77, lon=-122.42, ...)`.

---

## Tool selection experiment

How do tool descriptions affect routing when the LLM needs to choose between tools that query **different tables** — recent observations (2020+) vs. historical observations (pre-2020)?

### Setup

Single server (`servers/tool_selection.py`) with 3 tools, run with `--descriptions=minimal` or `--descriptions=rich`:

**Minimal descriptions:**
- `search_species(q)` — "Search species."
- `search_observations(...)` — "Search observations."
- `search_historical_observations(...)` — "Search historical observations."

**Rich descriptions:**
- `search_species(q)` — "Search bee species by scientific or common name. Use to resolve a name to a taxon_id before calling search_observations or search_historical_observations."
- `search_observations(...)` — "Search recent bee observations (2020-present). Use search_historical_observations for records before 2020. For comprehensive queries spanning all years, call both tools."
- `search_historical_observations(...)` — "Search historical bee observations (before 2020). Use search_observations for records from 2020 onward. For comprehensive queries spanning all years, call both tools."

### Test queries and results (gpt-4.1)

| Query | Expected | Minimal | Rich |
|-------|----------|---------|------|
| "What bees were seen near Oakland last month?" | recent only | ✅ `search_observations` | ✅ `search_observations` |
| "Were there any bee observations near Berkeley in 2015?" | historical only | ✅ `search_historical_observations` | ✅ `search_historical_observations` |
| "Has bee diversity changed near Oakland over the years?" | **both** | ❌ historical only | ❌ historical only |
| "Any leafcutter bees ever seen near San Francisco?" | **both** | ❌ recent only | ❌ recent only |
| "Is there a bee called Osmia lignaria?" | species only | ✅ `search_species` | ✅ `search_species` |

**Key finding:** Both variants performed identically on single-tool routing. The LLM correctly routed unambiguous time-range queries (Q1, Q2) regardless of description quality — the tool name `search_historical_observations` was enough. But **neither variant called both tools** for queries that span all time periods (Q3, Q4).

**Expanded test — queries that should call both tools (with `allow_multiple_tool_calls=True`, rich descriptions):**

| Query | Result | Called both? |
|-------|--------|-------------|
| "Any leafcutter bees ever seen near SF?" | recent only | ❌ |
| "How common are honey bees near Oakland? Include all years." | recent only | ❌ |
| "Show me every bumble bee observation near Berkeley, past and present." | both | ✅ |
| "Compare sweat bee sightings in 2010 vs 2024 near Oakland." | both | ✅ |
| "What is the full history of bee observations near SF?" | historical only | ❌ |
| "Have Western Honey Bees always been common near the Bay Area?" | historical only | ❌ |
| "Were there more bee species observed near Oakland in 2015 or 2024?" | both | ✅ |
| "Find all records of Osmia lignaria near Berkeley, any year." | recent only | ❌ |

**3 out of 8 correct.** The LLM only calls both tables when the query has **explicit temporal comparison** ("past and present", "2010 vs 2024", "2015 or 2024"). Vague time-spanning language ("ever", "always", "include all years", "full history", "any year") consistently fails — the LLM picks one table and stops.

**This is an MCP server design problem, not an agent problem.** The data split across two tables is invisible to the user. Descriptions saying "call both tools" don't work. The fix is a server design change:
- **Option A:** Add a `search_all_observations` meta-tool that queries both tables internally and merges results. The user never needs to know the data is split.
- **Option B:** Return a hint in the tool result: "Note: this only covers 2020+. For older records, also call search_historical_observations."
- **Option C:** Don't split the data — keep everything in one table/tool. The split creates a routing problem that descriptions can't solve.

---

## Elicitation scenarios (pick 2 for the talk)

Implemented in `servers/level5_elicitation.py` (Level 4 tools + elicitation).

Elicitation is for when the server discovers something the LLM couldn't have known. Not for routine disambiguation (that's what multi-step tool calls are for).

### Demo 1: Destructive operation confirmation

`delete_observation(observation_id=319809831)` → server looks up the record, elicits:

> You're about to delete:
> Observation #319809831 — Apis mellifera (Western Honey Bee), observed 2025-10-09 at (37.791, -122.436), quality: research.
> Proceed? [yes/no]

Pairs with `destructiveHint` — the client gives a generic "this tool modifies data" prompt, elicitation adds data-aware confirmation.

### Demo 2: Boundary violation

`search_observations(radius_km=200, ...)` → server elicits:

> That radius covers ~125,000 km² and may return a very large result set. Narrow to 50 km?

### Additional scenarios (mention briefly, link to repo)

- **Data quality warning:** `add_observation(lat=0, lon=0)` → "That location is in the Gulf of Guinea."
- **Non-existent entity:** `add_observation(taxon_id=99999)` → "Taxon ID 99999 doesn't exist. Did you mean...?"

### What NOT to elicit

Taxon disambiguation from free-text names — that's normal multi-step tool flow (search_species → user picks → search_observations), not elicitation.

Note: Elicitation support is inconsistent across clients (per MotherDuck's findings). Frame these as aspirational — `destructiveHint` annotations are the more portable safety layer.

---

## MCP annotations summary

| Annotation | Purpose | Example |
|------------|---------|---------|
| `readOnlyHint: True` | Client knows this tool won't modify data | All search/query tools |
| `destructiveHint: True` | Client can prompt user before calling | `add_observation`, `delete_observation` |

Key point: annotations are hints to the client. A lying server could mark `execute_sql` as read-only. Annotations don't enforce anything — only the tool implementation does.

---

## Lessons from MotherDuck's MCP server (weave into relevant levels, not a separate section)

Ref: MotherDuck's Posette talk on context engineering with MCP servers.

These should be integrated into the levels where they apply, not presented as a standalone section:

- **Control schema tool output** → weave into Level 1/1a: trim `information_schema.columns` to just column names, types, comments. Avoid bloating context.
- **Enriched error messages** → weave into Level 4: return descriptive errors, not raw Postgres tracebacks. RetryableToolErrors nudge the LLM to re-check schema.
- **Tool names matter** → weave into tool selection experiment: self-documenting names like `search_historical_observations` give routing hints before the LLM reads descriptions.
- **Client fragmentation limits elicitation** → already noted in elicitation section.
- **Observability gap in evals** → mention during eval results: MCP only exposes tool inputs, not the agent's reasoning.
- **Remove unused tools** → mention during tool selection: too many tools can degrade selection accuracy.

---

## TODO

- ~~**Historical observations data:**~~ ✅ Done. 6,627 pre-2020 observations populated from existing CSV.
- **Elicitation:** ✅ Implemented in `servers/level5_elicitation.py`. Three scenarios: delete confirmation, large-radius warning, suspicious-coordinates warning.
- **Closing slide:** Add a "which level should you use?" decision framework (e.g. Level 2 for internal/exploratory, Level 4 for production, DB permissions always).
- **Time budget (25 min):** Cut aggressively. Rough allocation:
  - Intro + MCP overview: 3 min
  - Demo Level 1 + failures: 4 min
  - Level 1a + DB permissions: 3 min
  - Level 2 + parser bypass: 3 min
  - Level 3 (brief): 2 min
  - Level 4 + elicitation: 5 min
  - Tool selection: 3 min
  - Decision framework + close: 2 min

---

## Related resources

- [MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox) — Google's open-source MCP server for databases, with built-in connection pooling, authentication, and tool construction from SQL templates
- [Designing SQL Tools for AI Agents](https://www.arcade.dev/blog/sql-tools-ai-agents-security) — Arcade's taxonomy of Exploratory vs Operational SQL tools. Their progression (exploratory → hybrid → operational) maps directly to our levels 1–4. Key takeaways:
  - **DB-level enforcement matters more than tool-level constraints.** Least-privilege roles, column-level grants, and Row-Level Security (RLS) are the real security boundary. Worth mentioning when presenting level 2 — parsing SQL is defense-in-depth, not a substitute for DB permissions.
  - **Prepared statements for operational tools.** Level 4's parameterized queries are the right pattern; levels 1–2 let the LLM construct raw SQL, which is inherently riskier.
  - **RetryableToolErrors.** When the LLM hallucinates a column name, return a descriptive error that nudges it to re-check the schema. Relevant to enriched error messages (MotherDuck lesson).
  - **Schema hints save tokens and improve accuracy.** Annotating which tables to prefer, what units data is in, etc. — aligns with our tool description experiment in level 4.


  ## Demo plan



Here's a demo plan for each section. For each, I'll list what server to run, what to show, and suggested queries:

---

### Demo 1: Free-form SQL (after title slide)
**Server:** `uv run servers/level1_freeform.py`
**Client:** VS Code with GitHub Copilot agent (or your agent framework)

**Show:**
1. **Happy path:** "What bees are active near Oakland in March?" — shows `get_db_schema` → `execute_sql` with a JOIN + PostGIS query working
  Assets:
  level1b_both_calls.png
  level1b_execute_sql.png
  level1b_select.mov

2. **Mutation:** "How many observations have quality_grade = 'needs_id'? Actually, delete those." — shows the 18k row deletion. (Opus will not do it, but Gemini 2.5 will!)
  Assets:
  level1b_delete_gemini_done.png
  level1b_delete_opus_confirm.png
  level1b_delete.mov

**Reset after:** `PGPASSWORD=postgres psql -h localhost -U admin -d bees -c "TRUNCATE observations;" && uv run scripts/ingest_observations.py --csv data/observations.csv` to restore data


---

### Demo 2: Schema bloat (optional screenshot)
**No live demo needed** — the slide already shows the full schema dump. But if you want, show the `get_db_schema` tool result in the Copilot chat to emphasize how much context it dumps.

level1b_get_db_schema.png

---

### Demo 3: Progressive discovery (optional)
**Server:** `uv run servers/level1b_discovery.py`
**Show:** Same query as Demo 1 — notice the agent calls `list_tables` → `describe_table("observations")` → `describe_table("species")` → `execute_sql`. More round-trips but less context.

level1b_select.mov
level1b_list_tables.png
level1b_describe_table_obs.png
level1b_describe_table_species.png

---

### Demo 4: Read-only SQL
**Server:** `uv run servers/level2_readonly.py`

**Show:**
1. **Happy path:** "What bees were seen near Berkeley last year?" — works fine

level2_select.png
level2_select.mov

2. **Blocked:** "Delete all observations where quality_grade is needs_id" — parser rejects it, show the ToolError

level2_delete_refusal.mov - smarter models realize they cant even do it
level2_delete_toolerror.mov - older models still try it, get tool error
level2_delete_toolerror.png

3. **Optional:** Show the timeout by asking for something expensive: How many pairs of bee observations were made within 1km of each other?

level2_join_timeout.png
level2_join_timeout_gridbucket.png
level2_join_timeout_randomsamples.png
level2_join_timeout.mov

---

### Demo 5: Fully typed tools
**Server:** `uv run servers/level4_typed.py`

**Show:**
1. **Multi-step chaining:** "Find leafcutter bees near Berkeley" — agent calls `search_species` → `search_observations(taxon_id=...)`. Show the tool calls panel.

  level4_typed_search_species.png
  level4_typed_search_obs.png

2. **Typed parameters:** Point out that the agent can't construct arbitrary SQL — it can only pass lat/lon/dates/taxon_id

  level4_typed_count_failure.mov
  level4_typed_count_failure.png
---

### Demo 6: Elicitation
**Server:** `uv run servers/level5_elicitation.py`

**Show:**
1. **Delete confirmation:** "Delete observation 319809831" — server looks up the record and elicits with details
   level5_delete_confirm.png
   level5_delete_confirm.mov

2. **Boundary violation:** "Show me all bee observations within 200km of San Francisco" — server elicits to narrow the radius

   level5_radius_confirm.png
   level5_radius_confirm.mov

---

### Demo 7: Tool selection (optional, could be slides only)
**Server:** `uv run servers/tool_selection.py`

**Show:** "Has bee diversity changed near Oakland over the years?" — agent only calls one tool instead of both. Then "Compare 2010 vs 2024" — agent calls both.

---

### Recording tips:
- **Kill port 8000 between demos:** `fuser -k 8000/tcp` before starting each server
- **Pre-warm:** Run one query before recording to avoid cold-start delays
- **Show tool calls:** Use `--show-tool-calls` flag or the VS Code tool calls panel
- **Terminal split:** Server log on one side, agent output on the other
- **Keep queries short:** Each demo should be 30-60 seconds max

Want me to create a script that automates the server switching between demos?
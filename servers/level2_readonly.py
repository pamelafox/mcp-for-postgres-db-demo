"""Level 2: Read-only SQL MCP server.

Exposes get_db_schema() and execute_readonly_sql(sql).
Parses SQL to reject non-SELECT statements and appends a LIMIT.
Demonstrates the "just parse the SQL" approach and its cracks.
"""

import logging

import pglast
from fastmcp import FastMCP
from sqlalchemy import text

from servers.db import create_engine, get_db_schema_text

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("bees_mcp.level2")
logger.setLevel(logging.INFO)

MAX_LIMIT = 100

mcp = FastMCP("Bees DB - Read-only SQL")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


def _validate_readonly_sql(sql: str) -> str:
    """Parse SQL and reject anything that isn't a plain SELECT. Returns the (possibly rewritten) SQL."""
    try:
        stmts = pglast.parse_sql(sql)
    except pglast.parser.ParseError as e:
        raise ValueError(f"SQL parse error: {e}")

    if len(stmts) != 1:
        raise ValueError("Only single statements are allowed")

    stmt = stmts[0].stmt
    if not hasattr(stmt, "targetList"):
        raise ValueError("Only SELECT statements are allowed")

    stmt_type = type(stmt).__name__
    if stmt_type != "SelectStmt":
        raise ValueError(f"Only SELECT statements are allowed, got {stmt_type}")

    sql_upper = sql.strip().rstrip(";").upper()
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip().rstrip(";") + f" LIMIT {MAX_LIMIT}"

    return sql


@mcp.tool(annotations={"readOnlyHint": True})
async def get_db_schema() -> str:
    """Return the database schema (tables, columns, types) for all public tables.

    Use this to discover available tables and columns before writing SQL queries.
    """
    engine = await _get_engine()
    return await get_db_schema_text(engine)


@mcp.tool(annotations={"readOnlyHint": True})
async def execute_readonly_sql(sql: str) -> str:
    """Execute a read-only SQL query against the database and return results.

    Only SELECT statements are allowed. Non-SELECT statements will be rejected.
    A LIMIT clause is automatically appended if not present (max 100 rows).
    """
    try:
        validated_sql = _validate_readonly_sql(sql)
    except ValueError as e:
        return f"Error: {e}"

    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(validated_sql))
        rows = result.fetchall()
        columns = list(result.keys())
        lines = [" | ".join(columns)]
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        return "\n".join(lines)


if __name__ == "__main__":
    logger.info("Starting Level 2 (read-only SQL) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)

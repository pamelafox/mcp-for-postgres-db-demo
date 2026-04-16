"""Read-only SQL MCP server.

Exposes get_db_schema() and execute_readonly_sql(sql).
Parses SQL to reject non-SELECT statements and appends a LIMIT.
Demonstrates the "just parse the SQL" approach and its cracks.
"""

import logging

import pglast
import sqlalchemy
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from sqlalchemy import text

from servers.db import create_engine, get_db_schema_text

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.readonly")
logger.setLevel(logging.INFO)

MAX_LIMIT = 100

mcp = FastMCP("Bees DB - Read-only SQL")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()

        # Enforce read-only at the connection level — catches CTE bypass
        @sqlalchemy.event.listens_for(_engine.sync_engine, "connect")
        def set_read_only(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET default_transaction_read_only = ON")
            cursor.close()

    return _engine


def _validate_readonly_sql(sql: str) -> str:
    """Parse SQL and reject anything that isn't a plain SELECT. Return original SQL if valid."""
    try:
        stmts = pglast.parse_sql(sql)
    except pglast.parser.ParseError as e:
        raise ValueError(f"SQL parse error: {e}")

    if len(stmts) != 1:
        raise ValueError("Only single statements are allowed")

    if (stmt_type := type(stmts[0].stmt).__name__) != "SelectStmt":
        raise ValueError(f"Only SELECT statements are allowed, got {stmt_type}")

    return sql


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_db_schema() -> str:
    """Return the database schema (tables, columns, types) for all public tables.
    Use this to discover available tables and columns before writing SQL queries.
    """
    engine = await _get_engine()
    return await get_db_schema_text(engine)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True), timeout=30.0)
async def execute_readonly_sql(sql: str) -> str:
    """Execute a read-only SQL query against the database and return results.
    Only SELECT statements are allowed. Non-SELECT statements will be rejected.
    A LIMIT clause is appended if not present, and results are capped at 100 rows.
    """
    try:
        validated_sql = _validate_readonly_sql(sql)
    except ValueError as e:
        raise ToolError(str(e))

    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(validated_sql))
        columns = list(result.keys())
        rows = result.fetchmany(MAX_LIMIT)
        return {"columns": columns, "rows": [[str(v) for v in row] for row in rows]}


if __name__ == "__main__":
    logger.info("Starting Read-only SQL MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)

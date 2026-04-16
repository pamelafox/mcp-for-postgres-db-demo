"""Level 1: Free-form SQL MCP server.

Exposes get_db_schema() and execute_sql(sql) — maximum flexibility, maximum risk.
The LLM can read schema, then execute any SQL it constructs.
"""

import logging

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import text

from servers.db import create_engine, get_db_schema_text

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.level1")
logger.setLevel(logging.INFO)

mcp = FastMCP("Bees DB - Free-form SQL")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_db_schema() -> str:
    """Return the database schema (tables, columns, types) for all public tables.

    Use this to discover available tables and columns before writing SQL queries.
    """
    engine = await _get_engine()
    return await get_db_schema_text(engine)


@mcp.tool()
async def execute_sql(sql: str) -> str:
    """Execute a SQL query against the database and return results.

    You can run any SQL statement including SELECT, INSERT, UPDATE, DELETE.
    Results are returned as text rows.
    """
    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        if result.returns_rows:
            columns = list(result.keys())
            rows = result.fetchmany(100)
            return {"columns": columns, "rows": [[str(v) for v in row] for row in rows]}
        await conn.commit()
        return f"Statement executed. Rows affected: {result.rowcount}"


if __name__ == "__main__":
    logger.info("Starting Level 1 (free-form SQL) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
